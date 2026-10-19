"""Espelho de NF como ato de operacao (spec §3 passos 1-2, §4): a medicao nasce aqui.

Uma linha em `espelhos` por (contrato, numero, versao) cobre as medicoes geradas juntas (espelho_medicoes; o
Projeto tem numeracao propria, #208). Gerar de novo = versao nova (a anterior das mesmas medicoes vira `substituido`);
nada e' sobrescrito. Arquivos .docx gravados pelo sha256 em <dados>/espelhos. O envio ao
faturamento sai pela conta de quem clica (correio.py) e liga o envio as medicoes.
"""
import datetime
import html
import json
import re

from app import arquivos, auditoria, contratos, correio, db, envio_reserva, espelho, espelho_docx, medicoes, tempo
from app import html_email


def regra_do_contrato(conn, contrato_id: int) -> dict | None:
    r = conn.execute("SELECT situacao, regra, modelos FROM espelho_regras WHERE contrato_id=?",
                     (contrato_id,)).fetchone()
    if r is None:
        return None
    return {"situacao": r["situacao"], "regra": json.loads(r["regra"]), "modelos": json.loads(r["modelos"])}


def _exigir_ativa(conn, contrato_id) -> dict:
    r = regra_do_contrato(conn, contrato_id)
    if r is None or r["situacao"] != "ativa":
        raise ValueError("Esta obra ainda não gera espelho pelo sistema (fluxo antigo): regra ausente ou em prova")
    return r


def nome_emissor(chave: str) -> str:
    """Nome curto da emissora no arquivo: a chave do cadastro com inicial maiuscula (Lotufo, Rivoli, Guaxe)."""
    return chave.capitalize()


def validar_periodo(competencia: str, inicio: str | None, fim: str | None) -> tuple[str, str] | None:
    """Periodo informado (ISO) ou None = mes civil da competencia. Os dois ou nenhum; inicio <= fim; ate'
    um ano; e o periodo tem de tocar o mes da competencia (Coxipo 3a 12a: 06 e 07/2026, competencia 07)."""
    if not inicio and not fim:
        return None
    if not (inicio and fim):
        raise ValueError("período: informe início e fim, ou nenhum dos dois (mês inteiro)")
    try:
        # fromisoformat tambem aceita '20260801' e '2026-W31-6': o contrato da API e' AAAA-MM-DD
        if not all(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", d) for d in (inicio, fim)):  # A-14: so' 0-9
            raise ValueError
        ini, f = datetime.date.fromisoformat(inicio), datetime.date.fromisoformat(fim)
    except ValueError:
        raise ValueError("período: data inválida") from None
    if ini > f:
        raise ValueError("período: o início é depois do fim")
    if (f - ini).days > 366:
        raise ValueError("período: mais de um ano")
    mes_ini, mes_fim = espelho.periodo_do_mes(competencia)
    if f.isoformat() < mes_ini or ini.isoformat() > mes_fim:
        raise ValueError("período: não inclui nenhum dia do mês da competência")
    if (ini.isoformat(), f.isoformat()) == (mes_ini, mes_fim):
        return None
    return ini.isoformat(), f.isoformat()


def _obra(c: dict) -> str:
    return c["nome_curto"] or c["objeto"]


def _mes_br(competencia: str) -> str:
    return f"{competencia[5:7]}/{competencia[:4]}"


def _conferir_inicio(c: dict, competencia: str) -> None:
    """A-20 (testes de quebra 10/10/2026): competencia 2020-01 no MT-401 (execucao desde 2023-03) montava o
    espelho sem aviso. Antes do inicio da execucao (ou da vigencia, se a execucao esta' vazia) nao ha' medicao."""
    inicio = c["execucao_inicio"] or c["vigencia_inicio"]
    if not inicio:  # gate Sol S2: sem data nenhuma a conferencia acima nao vale nada
        raise ValueError("Contrato sem data de início cadastrada: complete o cadastro antes de gerar espelho")
    if competencia < inicio[:7]:
        raise ValueError(f"Competência {_mes_br(competencia)} é anterior ao início do contrato ({_mes_br(inicio)})")


def _calcular(conn, contrato_id, numero, competencia, entradas) -> tuple[dict, dict, list[dict], dict[str, int]]:
    r = _exigir_ativa(conn, contrato_id)
    regra = r["regra"]
    chaves = {e["chave"] for e in regra["entradas"]}
    estranhas = set(entradas) - chaves
    if estranhas:
        raise ValueError(f"entrada desconhecida para esta obra: {sorted(estranhas)}")
    saidas = espelho.calcular(regra, entradas, competencia)
    if not saidas:
        raise ValueError("nenhuma nota a emitir: todos os valores estão zerados")
    c = contratos.vigente(conn, contrato_id)
    _conferir_inicio(c, competencia)
    por_chave = {s["chave"]: s for s in regra["saidas"]}
    for s in saidas:
        s["nome_arquivo"] = espelho.nome_arquivo(regra, por_chave[s["chave"]], _obra(c), numero, competencia,
                                                 nome_emissor(s["emissor"]))
    return r, c, saidas, espelho.valor_por_natureza(regra, entradas)


def _medicoes_existentes(conn, contrato_id, numero, tipos) -> dict[str, dict]:
    if not tipos:
        return {}
    marcas = ",".join("?" * len(tipos))
    return {m["tipo"]: dict(m) for m in conn.execute(
        f"SELECT id, tipo, estado FROM medicoes WHERE contrato_id=? AND numero=? AND tipo IN ({marcas})",
        (contrato_id, numero, *tipos))}


def _medicoes_por_espelho(conn, contrato_id, numero) -> dict[int, list[dict]]:
    """{espelho_id: [{tipo, estado}]} dos espelhos VIGENTES deste numero, numa consulta so'."""
    por_espelho: dict[int, list[dict]] = {}
    for r in conn.execute(
            "SELECT e.id, m.tipo, m.estado FROM espelhos e JOIN espelho_medicoes em ON em.espelho_id=e.id "
            "JOIN medicoes m ON m.id=em.medicao_id WHERE e.contrato_id=? AND e.numero=? AND e.situacao='vigente'",
            (contrato_id, numero)):
        por_espelho.setdefault(r["id"], []).append({"tipo": r["tipo"], "estado": r["estado"]})
    return por_espelho


def _espelhos_anteriores(conn, contrato_id, numero, tipos) -> list[int]:
    """Espelhos vigentes que a geracao destes tipos substitui (#208). Decide pelas medicoes ligadas
    (espelho_medicoes), nao so' pelo numero: a 3a de Projeto e a 3a de execucao sao medicoes diferentes.
    - todas as medicoes do espelho estao sendo geradas: substitui;
    - sobra medicao ja' protocolada (fora de ESTADOS_ESPELHO): o espelho fica vigente para ela, intocado, e o
      novo cobre so' as geradas (o protocolado e' congelado);
    - sobra medicao ainda em espelho: recusa, para nao deixa-la sem espelho vigente (gere junto)."""
    tipos = set(tipos)
    ids = []
    for eid, meds in sorted(_medicoes_por_espelho(conn, contrato_id, numero).items()):
        if not any(m["tipo"] in tipos for m in meds):
            continue
        resto = [m for m in meds if m["tipo"] not in tipos]
        if not resto:
            ids.append(eid)
            continue
        abertas = sorted(m["tipo"] for m in resto if m["estado"] in medicoes.ESTADOS_ESPELHO)
        if abertas:
            nomes = " e ".join(medicoes.nome_medicao(numero, t) for t in abertas)
            verbo = "estão" if len(abertas) > 1 else "está"
            ainda = "ainda não foram protocoladas" if len(abertas) > 1 else "ainda não foi protocolada"
            raise ValueError(f"{nomes} {verbo} no mesmo espelho e {ainda}: gere junto para fazer uma versão nova")
    return ids


def _recusar_envio_reservado(conn, contrato_id, numero, tipos) -> None:
    """Espelho vigente destas medicoes com envio ao faturamento reservado nao se substitui (#210): o e-mail que
    esta' saindo leva os arquivos dele, e a medicao seria marcada enviada com o valor velho. Vale tambem para o
    misto que ficaria superado (fica vigente, mas a medicao gerada passaria a valer pela versao nova)."""
    marcas = ",".join("?" * len(tipos))
    r = conn.execute(
        "SELECT e.versao, e.envio_reservado_em, e.envio_reservado_por FROM espelhos e "
        "JOIN espelho_medicoes em ON em.espelho_id=e.id JOIN medicoes m ON m.id=em.medicao_id "
        "WHERE e.contrato_id=? AND e.numero=? AND e.situacao='vigente' AND e.envio_reservado_em IS NOT NULL "
        f"AND m.tipo IN ({marcas}) ORDER BY e.versao LIMIT 1", (contrato_id, numero, *tipos)).fetchone()
    if r is None:
        return
    em = envio_reserva.reservado(conn, r["envio_reservado_em"], r["envio_reservado_por"])
    raise ValueError(f"A versão {r['versao']} deste espelho está sendo enviada ao faturamento (iniciado às "
                     f"{em.reservado_em[11:16]} por {em.reservado_por_nome}): aguarde o envio terminar para gerar "
                     "uma versão nova. Se o envio foi interrompido, confira a caixa de Enviados do Outlook e libere "
                     "o envio.")


def previa(conn, contrato_id: int, numero: int, competencia: str, entradas: dict[str, int],
           periodo: tuple[str, str] | None = None) -> dict:
    _, _, saidas, por_tipo = _calcular(conn, contrato_id, numero, competencia, entradas)
    _espelhos_anteriores(conn, contrato_id, numero, list(por_tipo))
    existentes = _medicoes_existentes(conn, contrato_id, numero, list(por_tipo))
    avisos, meds = [], []
    for tipo, valor in por_tipo.items():
        ex = existentes.get(tipo)
        if ex and ex["estado"] not in medicoes.ESTADOS_ESPELHO:
            raise ValueError(f"{medicoes.nome_medicao(numero, tipo)} já está {medicoes.rotulo_estado(ex['estado'])}: "
                             "não pode gerar espelho de novo")
        if ex:
            avisos.append(f"{medicoes.nome_medicao(numero, tipo)} já tem espelho: será gerada uma versão nova")
        # A-20: so' aviso -- pode ser medicao atrasada de verdade. A propria medicao (gerar de novo) nao conta.
        ultima = conn.execute(
            "SELECT numero, competencia FROM medicoes WHERE contrato_id=? AND tipo=? AND numero<>? "
            "AND estado NOT IN ('cancelada','desistida') ORDER BY competencia DESC, numero DESC LIMIT 1",
            (contrato_id, tipo, numero)).fetchone()
        if ultima and competencia < ultima["competencia"]:
            avisos.append(f"Competência {_mes_br(competencia)} é anterior à da última medição "
                          f"(nº {ultima['numero']}, {_mes_br(ultima['competencia'])}): confira")
        meds.append({"tipo": tipo, "valor_centavos": valor, "existente": ex["estado"] if ex else None})
    return {"saidas": saidas, "medicoes": meds, "avisos": avisos, "periodo": espelho.periodo(competencia, periodo)}


def gerar(conn, usuario: dict, contrato_id: int, numero: int, competencia: str,
          entradas: dict[str, int], motivo: str | None = None, periodo: tuple[str, str] | None = None) -> int:
    r, c, saidas, por_tipo = _calcular(conn, contrato_id, numero, competencia, entradas)
    modelos = {k: arquivos.caminho_seguro(m["arquivo"]).read_bytes() for k, m in r["modelos"].items()}
    # so' calculo antes da transacao: preencher os modelos nao toca banco nem disco
    gerados = [(s, espelho_docx.preencher(modelos[s["chave"]], espelho.formatar_controles(
                   s, numero, competencia, r["regra"].get("texto"), periodo)))
               for s in saidas]
    regra_sha = conn.execute("SELECT sha256 FROM espelho_regras WHERE contrato_id=?", (contrato_id,)).fetchone()[0]
    with db.mutacao(conn):
        # A versao anterior e' a vigente das MESMAS medicoes (#208; a medicao e' unica por
        # contrato+numero+tipo): trocar a competencia e' correcao, nao espelho novo -- substitui, nao duplica.
        anteriores = _espelhos_anteriores(conn, contrato_id, numero, list(por_tipo))
        _recusar_envio_reservado(conn, contrato_id, numero, list(por_tipo))   # sob o mesmo lock da reserva (#210)
        ids = {tipo: medicoes.criar_para_espelho(conn, usuario["id"], contrato_id, numero, tipo, competencia, valor)
               for tipo, valor in por_tipo.items()}
        # UNIQUE (contrato_id, numero, versao) da 020: a versao segue a sequencia do numero, de todos os tipos
        versao = 1 + (conn.execute("SELECT COALESCE(MAX(versao), 0) FROM espelhos WHERE contrato_id=? AND numero=?",
                                   (contrato_id, numero)).fetchone()[0])
        for aid in anteriores:
            conn.execute("UPDATE espelhos SET situacao='substituido', substituido_em=datetime('now'), motivo=? "
                         "WHERE id=?", (motivo, aid))
        cur = conn.execute(
            "INSERT INTO espelhos (contrato_id, numero, competencia, versao, situacao, entradas, saidas, "
            "regra_sha256, criado_por, periodo_inicio, periodo_fim) VALUES (?,?,?,?,'vigente',?,?,?,?,?,?)",
            (contrato_id, numero, competencia, versao, json.dumps(entradas),
             json.dumps(saidas, ensure_ascii=False), regra_sha, usuario["id"], *(periodo or (None, None))))
        eid = cur.lastrowid
        for mid in sorted(set(ids.values())):
            conn.execute("INSERT INTO espelho_medicoes (espelho_id, medicao_id) VALUES (?,?)", (eid, mid))
        resumo = []
        for s, docx in gerados:
            caminho, sha = arquivos.gravar_bytes("espelhos", docx, "docx")
            mid = ids[espelho.TIPO_POR_NATUREZA[s["natureza"]]]
            conn.execute(
                "INSERT INTO medicao_documentos (medicao_id, fonte, tipo_doc, nome, item_id, arquivo, sha256, "
                "tamanho, espelho_id, saida, consorciada, municipio) "
                "VALUES (?,'sistema','espelho',?,?,?,?,?,?,?,?,?)",
                (mid, s["nome_arquivo"], f"{eid}:{sha}", caminho, sha, len(docx), eid, s["chave"],
                 nome_emissor(s["emissor"]), s["municipio"]))
            resumo.append({"nome": s["nome_arquivo"], "sha256": sha})
        auditoria.registrar(conn, usuario["id"], "espelho.gerar", "espelho", eid, None,
                            {"contrato_id": contrato_id, "numero": numero, "competencia": competencia,
                             "versao": versao, "entradas": entradas, "periodo": periodo,
                             "substitui": anteriores[0] if anteriores else None, "substituidos": anteriores,
                             "motivo": motivo,
                             "arquivos": resumo})
    return eid


def _arquivos(conn, espelho_id) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT id AS documento_id, medicao_id, saida, nome, tamanho, sha256 FROM medicao_documentos "
        "WHERE espelho_id=? ORDER BY id", (espelho_id,))]


def detalhe(conn, espelho_id: int) -> dict | None:
    r = conn.execute("SELECT * FROM espelhos WHERE id=?", (espelho_id,)).fetchone()
    if r is None:
        return None
    d = dict(r)
    d["entradas"], d["saidas"] = json.loads(d["entradas"]), json.loads(d["saidas"])
    # `superado` (#208): espelho misto que ficou vigente para a medicao protocolada, mas outra das medicoes dele
    # ja' tem espelho vigente mais novo -- para essa medicao ele nao vale (nem na tela, nem no envio).
    d["medicoes"] = [{**dict(m), "superado": bool(m["superado"])} for m in conn.execute(
        "SELECT m.id, m.tipo, m.estado, m.valor_protocolado_centavos, "
        "(? = 'vigente' AND EXISTS (SELECT 1 FROM espelho_medicoes em2 JOIN espelhos e2 ON e2.id=em2.espelho_id "
        " WHERE em2.medicao_id=m.id AND e2.situacao='vigente' AND e2.versao > ?)) AS superado "
        "FROM espelho_medicoes em JOIN medicoes m ON m.id=em.medicao_id WHERE em.espelho_id=? ORDER BY m.tipo",
        (d["situacao"], d["versao"], espelho_id))]
    d["arquivos"] = _arquivos(conn, espelho_id)
    d["criado_por_nome"] = (conn.execute("SELECT nome FROM usuarios WHERE id=?", (d["criado_por"],)).fetchone()
                            or [None])[0]
    d["envio"] = None
    if d["envio_id"]:
        e = conn.execute("SELECT id, remetente, para, copia, assunto, enviado_em FROM envios WHERE id=?",
                         (d["envio_id"],)).fetchone()
        d["envio"] = {**dict(e), "para": json.loads(e["para"]), "copia": json.loads(e["copia"])}
    return d


def listar(conn, contrato_id: int) -> list[dict]:
    # versao antes da competencia (#208): no mesmo numero a versao cresce a cada geracao, entao o mais novo vem
    # primeiro mesmo quando a versao nova tem competencia anterior
    ids = [r[0] for r in conn.execute("SELECT id FROM espelhos WHERE contrato_id=? "
                                      "ORDER BY numero DESC, versao DESC", (contrato_id,))]
    return [detalhe(conn, i) for i in ids]


# --- envio ao faturamento (spec §5.2) --------------------------------------------------------

def _geral(conn) -> dict:
    r = conn.execute("SELECT valor FROM cadastro_geral WHERE chave='faturamento'").fetchone()
    if r is None:
        raise ValueError("cadastro geral sem `faturamento`: rode `cadastro aplicar` com geral.yaml")
    return json.loads(r["valor"])


def rotulo_medicao(numero: int, saidas: list[dict]) -> str:
    """'10ª Medição', '10ª Medição e Reajuste', '14ª Medição e Projeto', '3ª Medição, Projeto e Reajuste'."""
    nat = {s["natureza"] for s in saidas}
    partes = [n for n, presente in (("Medição", "medicao" in nat), ("Projeto", "projeto" in nat),
                                    ("Reajuste", "reajuste" in nat)) if presente]
    texto = partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " e " + partes[-1]
    return f"{numero}ª {texto}"


def saudacao() -> str:
    return "Bom dia." if tempo.para_local(tempo.agora_utc()).hour < 12 else "Boa tarde."


def _recusar_superado(conn, d: dict) -> None:
    """Espelho misto com uma medicao que ja' tem espelho mais novo (#208) nao se envia: mandaria ao faturamento
    o valor velho dela. A versao mais nova e' a que vale para essa medicao."""
    for m in d["medicoes"]:
        if m["superado"]:
            v = conn.execute("SELECT MAX(e.versao) FROM espelhos e JOIN espelho_medicoes em ON em.espelho_id=e.id "
                             "WHERE em.medicao_id=? AND e.situacao='vigente'", (m["id"],)).fetchone()[0]
            raise ValueError(f"{medicoes.nome_medicao(d['numero'], m['tipo'])} tem espelho mais novo "
                             f"(versão {v}): envie aquela versão")


def previa_envio(conn, espelho_id: int, remetente: str | None = None) -> dict:
    d = detalhe(conn, espelho_id)
    if d is None:
        raise ValueError("espelho não encontrado")
    if d["situacao"] != "vigente":
        raise ValueError("esta versão do espelho foi substituída; envie a versão vigente")
    _recusar_superado(conn, d)
    g = _geral(conn)
    c = contratos.vigente(conn, d["contrato_id"])
    emissores = {s["emissor"] for s in d["saidas"]}
    extras = []
    for e in conn.execute("SELECT chave, emails_faturamento FROM entidades "
                          "WHERE papel='consorciada' AND chave IS NOT NULL"):
        if e["chave"] in emissores and e["emails_faturamento"]:
            extras += json.loads(e["emails_faturamento"])
    para = list(dict.fromkeys(g["para"] + extras))
    # o e-mail de login e a conta do Outlook podem ser diferentes; nenhum dos dois vai em copia de si mesmo
    fora = {(remetente or "").lower()} | correio.contas_do_usuario(conn, remetente or "")
    copia = [e for e in g["copia"] if e not in para and e.lower() not in fora]
    assunto = g["assunto"].format(medicao=rotulo_medicao(d["numero"], d["saidas"]),
                                  competencia=f"{d['competencia'][5:7]}/{d['competencia'][:4]}",
                                  obra=_obra(c), instrumento=c["numero_instrumento"])
    corpo = g["corpo"].replace("{saudacao}", saudacao())
    anexos = [{"nome": a["nome"], "tamanho": a["tamanho"]} for a in d["arquivos"]]
    total = sum(a["tamanho"] for a in anexos)
    avisos = []
    if total > correio.MAX_TOTAL:
        avisos.append(f"anexos somam {total // 1024 // 1024} MB; o limite do e-mail é "
                      f"{correio.MAX_TOTAL // 1024 // 1024} MB")
    # so' o envio que cobre uma destas medicoes (#208): o da 3a de execucao nao e' substituido pelo da 3a de Projeto
    mids = [m["id"] for m in d["medicoes"]]
    ja = conn.execute(
        "SELECT MAX(e.versao) FROM espelhos e JOIN espelho_medicoes em ON em.espelho_id=e.id "
        f"WHERE e.envio_id IS NOT NULL AND em.medicao_id IN ({','.join('?' * len(mids))})",
        mids).fetchone()[0] if mids else None
    if ja is not None:
        avisos.append(f"a versão {ja} deste espelho já foi enviada ao faturamento; este envio substitui")
    return {"para": para, "copia": copia, "assunto": assunto, "corpo": corpo,
            "anexos": anexos, "total": total, "limite": correio.MAX_TOTAL, "avisos": avisos}


def _html(texto: str) -> str:
    if html_email.eh_html(texto):           # corpo formatado no editor (issue #191): so' a lista fechada passa
        return html_email.sanitizar(texto)
    return "".join(f"<p>{html.escape(linha) or '&nbsp;'}</p>" for linha in texto.strip().splitlines())


def enviar(conn, usuario: dict, espelho_id: int, para: list[str], copia: list[str], assunto: str,
           corpo: str, cco: list[str] | None = None, reenviar: bool = False) -> int:
    d = detalhe(conn, espelho_id)
    if d is None or d["situacao"] != "vigente":
        raise ValueError("esta versão do espelho foi substituída; envie a versão vigente")
    _recusar_superado(conn, d)
    if not para:
        raise ValueError("informe ao menos um destinatário")
    # Antes de mandar o e-mail (que nao se desfaz): medicao encerrada nesse meio-tempo nao
    # recebe espelho. Protocolada continua podendo (o estado so' anda para a frente).
    fechadas = [m for m in d["medicoes"] if m["estado"] in ("cancelada", "desistida")]
    if fechadas:
        raise ValueError(f"{medicoes.nome_medicao(d['numero'], fechadas[0]['tipo'])} está "
                         f"{medicoes.rotulo_estado(fechadas[0]['estado'])}: "
                         "o espelho não pode ser enviado")
    # Reenviar a versao vigente continua permitido ("este envio substitui"), mas so' confirmado (S8, 10/10/2026):
    # um clique repetido depois de o primeiro terminar le o envio_id novo, passa pela reserva e manda o segundo
    # e-mail ao faturamento sem ninguem decidir. Leitura so', antes de reservar.
    if d["envio_id"] is not None and not reenviar:
        e = conn.execute("SELECT e.enviado_em, u.nome FROM envios e LEFT JOIN usuarios u ON u.id=e.usuario_id "
                         "WHERE e.id=?", (d["envio_id"],)).fetchone()
        em = tempo.para_local(datetime.datetime.fromisoformat(e["enviado_em"]))
        nome = e["nome"] or "outro usuário"
        raise envio_reserva.EnvioEmAndamento(
            f"Esta versão do espelho já foi enviada ao faturamento (às {em:%H:%M} por {nome}). Para mandar de novo, "
            "confirme o reenvio.", "ESPELHO_JA_ENVIADO", em.isoformat(), nome)
    # Reserva atomica antes do e-mail (A-01, 10/10/2026): barra o envio SIMULTANEO, ou o que leu antes de outro
    # terminar.
    envio_reserva.reservar(conn, "espelhos", espelho_id, usuario["id"], d["envio_id"])
    try:
        anexos = []
        for a in d["arquivos"]:
            rel = conn.execute("SELECT arquivo FROM medicao_documentos WHERE id=?",
                               (a["documento_id"],)).fetchone()[0]
            anexos.append((a["nome"], arquivos.caminho_seguro(rel).read_bytes()))
        if sum(len(b) for _, b in anexos) > correio.MAX_TOTAL:
            raise ValueError("anexos acima do limite do e-mail; divida o envio")
        # Envia e SO' ENTAO registra (correio.enviar_e_registrar): falha de envio nao muda nada.
        envio_id = correio.enviar_e_registrar(conn, usuario, "espelho", para, copia, assunto, _html(corpo), anexos,
                                              cco=cco)
    except correio.EnvioNaoRegistrado:
        raise                                       # o e-mail saiu: a reserva fica e segura a repeticao
    except Exception:
        envio_reserva.liberar_com_retentativa(conn, "espelhos", espelho_id)    # nada saiu: destrava e sobe o erro
        raise
    with correio.depois_do_envio(assunto, para, envio_id), db.mutacao(conn):
        envio_reserva.liberar(conn, "espelhos", espelho_id)
        for m in d["medicoes"]:
            conn.execute("INSERT OR IGNORE INTO envio_medicoes (envio_id, medicao_id) VALUES (?,?)",
                         (envio_id, m["id"]))
            medicoes.marcar_espelho_enviado(conn, usuario["id"], m["id"])
        conn.execute("UPDATE espelhos SET envio_id=? WHERE id=?", (envio_id, espelho_id))
        auditoria.registrar(conn, usuario["id"], "espelho.enviar", "espelho", espelho_id, None,
                            {"envio_id": envio_id, "medicoes": [m["id"] for m in d["medicoes"]]})
    return envio_id
