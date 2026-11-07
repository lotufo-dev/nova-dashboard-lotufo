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


MIN_JUSTIFICATIVA_SEM_BOLETIM = 10


def _existentes(conn, contrato_id, numero) -> dict[str, dict]:
    """As medicoes deste numero (uma por tipo), com o que decide o valor travado e a trava do boletim (#284)."""
    return {m["tipo"]: dict(m) for m in conn.execute(
        "SELECT id, tipo, estado, competencia, valor_protocolado_centavos, valor_protocolado_origem, "
        "valor_atestado_centavos, planilha_enviada_em FROM medicoes WHERE contrato_id=? AND numero=?",
        (contrato_id, numero))}


def _travados(conn, existentes: dict[str, dict]) -> dict[str, tuple[int, str]]:
    """Issue #284: {tipo: (centavos, fonte)} das medicoes que o espelho ainda alcanca (antes do espelho ou nele):
    o aprovado, senao o pedido; `fonte` e' "boletim", "atestado" ou "pedido". A protocolada nao entra: o espelho
    dela nao se gera mais."""
    out = {}
    for tipo, m in existentes.items():
        if m["estado"] in (*medicoes.ESTADOS_ANTES_DO_ESPELHO, *medicoes.ESTADOS_ESPELHO):
            v = medicoes.valor_travado(m)
            if v is not None:
                # a fonte diz de onde veio o aprovado: do boletim (com o PDF) ou do atestado digitado, que tambem
                # vale (decisao do Leo de 03/11/2026)
                fonte = v[1] if v[1] != "aprovado" else ("boletim" if medicoes.tem_boletim(conn, m["id"]) else "atestado")
                out[tipo] = (v[0], fonte)
    return out


def _sem_boletim(conn, existentes: dict[str, dict], tipos) -> list[dict]:
    """Medicoes geradas agora que ja' existiam antes do espelho e nao tem o boletim do orgao (decisao do Leo de
    03/11/2026): so' seguem com justificativa. Gerar de novo um espelho ja' gerado nao pede nada."""
    return [m for t, m in sorted(existentes.items())
            if t in tipos and m["estado"] in medicoes.ESTADOS_SEM_BOLETIM and not medicoes.tem_boletim(conn, m["id"])]


def _vigentes(conn, contrato_id, numero) -> list[tuple]:
    """(id, versao, envio_id, tipo) de cada medicao nos espelhos vigentes do numero."""
    return [tuple(r) for r in conn.execute(
        "SELECT e.id, e.versao, e.envio_id, m.tipo FROM espelhos e JOIN espelho_medicoes em ON em.espelho_id=e.id "
        "JOIN medicoes m ON m.id=em.medicao_id WHERE e.contrato_id=? AND e.numero=? AND e.situacao='vigente' "
        "ORDER BY e.id, m.tipo", (contrato_id, numero))]


def _retrato(existentes: dict[str, dict], vigentes: list[tuple], tipos, travados) -> tuple:
    """O que a geracao confere de novo sob o lock (gate Sol, #284), so' dos tipos gerados agora: cada medicao com o
    estado exato, os valores e o travado, e os espelhos vigentes que tem alguma delas, com o envio. O envio (ou
    reenvio) da v1 terminado durante a montagem do .docx muda o retrato, e a v2 nao substitui a v1 enviada sem
    ninguem ver; o reenvio do espelho de outra medicao (a execucao, na geracao so' do projeto) nao recusa."""
    tipos = sorted(set(tipos))
    return ([tuple(sorted(existentes[t].items())) if t in existentes else None for t in tipos],
            [travados.get(t) for t in tipos],
            sorted({(i, v, envio) for i, v, envio, t in vigentes if t in tipos}))


def _regra_crua(conn, contrato_id) -> tuple | None:
    """A linha da regra do espelho como esta' no banco (situacao, regra, modelos, sha256): capturada no inicio da
    geracao e conferida sob o lock (gate Sol, #284), e o sha gravado no espelho e' o capturado."""
    r = conn.execute("SELECT situacao, regra, modelos, sha256 FROM espelho_regras WHERE contrato_id=?",
                     (contrato_id,)).fetchone()
    return tuple(r) if r else None


def _opcionais(conn, existentes: dict[str, dict]) -> set[str]:
    return ({m["tipo"] for m in _sem_boletim(conn, existentes, set(existentes))}
            | {t for t, m in existentes.items() if m["estado"] in medicoes.ESTADOS_ESPELHO})


def _recusar_planilha_sendo_enviada(conn, numero: int, existentes: dict[str, dict], tipos) -> None:
    """A planilha/carta com o e-mail ao orgao saindo (ou preso) nao ganha espelho: o envio poe a medicao em
    `planilha_enviada` com o pedido que ele leva."""
    for t in sorted(tipos):
        m = existentes.get(t)
        if m is None or m["estado"] not in ("planilha_gerada", "planilha_enviada"):
            continue
        r = conn.execute("SELECT envio_reservado_em, envio_reservado_por FROM medicao_planilha_envios "
                         "WHERE medicao_id=? AND envio_id IS NULL AND envio_reservado_em IS NOT NULL LIMIT 1",
                         (m["id"],)).fetchone()
        if r is not None:
            em = envio_reserva.reservado(conn, r["envio_reservado_em"], r["envio_reservado_por"])
            raise ValueError(f"A planilha/carta da {medicoes.nome_medicao(numero, t)} "
                             f"está sendo enviada ao órgão (iniciado às {em.reservado_em[11:16]} por "
                             f"{em.reservado_por_nome}): aguarde o envio terminar para gerar o espelho")


def _regra_capturada(crua: tuple | None) -> dict:
    """A regra de `_regra_crua` (situacao, regra, modelos, sha256) como `regra_do_contrato` a devolve, ativa."""
    if crua is None or crua[0] != "ativa":
        raise ValueError("Esta obra ainda não gera espelho pelo sistema (fluxo antigo): regra ausente ou em prova")
    return {"situacao": crua[0], "regra": json.loads(crua[1]), "modelos": json.loads(crua[2])}


def _conferir_planilhas(conn, numero: int, existentes: dict[str, dict], tipos, competencia: str) -> None:
    """Issue #289, para cada medicao gerada agora: a planilha/carta so' recebe espelho enviada, sem revisao pendente
    e na competencia dela (medicoes.conferir_espelho_da_planilha). Vem antes da trava do boletim: sem o envio ao
    orgao, o boletim nem existe."""
    for t in sorted(tipos):
        m = existentes.get(t)
        if m is not None and m["estado"] in (*medicoes.ESTADOS_ANTES_DO_ESPELHO, *medicoes.ESTADOS_ESPELHO):
            medicoes.conferir_espelho_da_planilha(conn, m, numero, t, competencia)


def _calcular(conn, contrato_id, numero, competencia, entradas, regra_crua: tuple | None = None):
    """Devolve (regra, contrato, saidas, valor por tipo, entradas usadas, medicoes existentes,
    (travados, opcionais)). Com `regra_crua` (a captura de `gerar`), a conta usa ESSA regra e nao a relida do banco
    (gate Sol, #284: duas aplicacoes do cadastro no meio voltariam a regra a' captura e o espelho sairia com o sha
    de uma e o calculo de outra)."""
    r = _exigir_ativa(conn, contrato_id) if regra_crua is None else _regra_capturada(regra_crua)
    regra = r["regra"]
    chaves = {e["chave"] for e in regra["entradas"]}
    estranhas = set(entradas) - chaves
    if estranhas:
        raise ValueError(f"entrada desconhecida para esta obra: {sorted(estranhas)}")
    existentes = _existentes(conn, contrato_id, numero)
    travados = _travados(conn, existentes)
    # issue #284: o valor que a medicao ja' tem (aprovado, senao pedido) vem preenchido e nao muda. So' entra
    # sozinha a que espera o espelho (boletim recebido); a ainda sem boletim e a que ja' tem espelho (revisor: o
    # espelho so' de reajuste nao pode puxar a execucao ja' enviada) entram se a pessoa as puser (nada digitado = fora)
    opcionais = _opcionais(conn, existentes)
    entradas = espelho.entradas_pela_medicao(regra, entradas, travados, opcionais)
    saidas = espelho.calcular(regra, entradas, competencia)
    if not saidas:
        raise ValueError("nenhuma nota a emitir: todos os valores estão zerados")
    c = contratos.vigente(conn, contrato_id)
    _conferir_inicio(c, competencia)
    por_chave = {s["chave"]: s for s in regra["saidas"]}
    for s in saidas:
        s["nome_arquivo"] = espelho.nome_arquivo(regra, por_chave[s["chave"]], _obra(c), numero, competencia,
                                                 nome_emissor(s["emissor"]))
    return r, c, saidas, espelho.valor_por_natureza(regra, entradas), entradas, existentes, (travados, opcionais)


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
    """A previa nao recusa a falta do boletim: mostra (`sem_boletim` em cada medicao) para a tela pedir a
    justificativa; quem recusa e' `gerar`. `travados` e `entradas` dizem o valor que veio da medicao (#284)."""
    _, _, saidas, por_tipo, entradas, existentes, (travados, opcionais) = _calcular(conn, contrato_id, numero,
                                                                                   competencia, entradas)
    _espelhos_anteriores(conn, contrato_id, numero, list(por_tipo))
    sem_todos = {m["tipo"] for m in _sem_boletim(conn, existentes, set(existentes))}
    sem = sem_todos & set(por_tipo)
    avisos, meds = [], []
    for tipo, valor in por_tipo.items():
        ex = existentes.get(tipo)
        if ex and ex["estado"] not in (*medicoes.ESTADOS_ANTES_DO_ESPELHO, *medicoes.ESTADOS_ESPELHO):
            raise ValueError(f"{medicoes.nome_medicao(numero, tipo)} já está {medicoes.rotulo_estado(ex['estado'])}: "
                             "não pode gerar espelho de novo")
        # Issue #289: a planilha/carta so' recebe espelho enviada, sem revisao pendente e na competencia dela; o valor e'
        # o travado (aprovado, senao pedido) desde a #284
        if ex and ex["estado"] in (*medicoes.ESTADOS_ANTES_DO_ESPELHO, *medicoes.ESTADOS_ESPELHO):
            medicoes.conferir_espelho_da_planilha(conn, ex, numero, tipo, competencia)
        if ex and ex["estado"] in medicoes.ESTADOS_ESPELHO:
            avisos.append(f"{medicoes.nome_medicao(numero, tipo)} já tem espelho: será gerada uma versão nova")
        # A-20: so' aviso -- pode ser medicao atrasada de verdade. A propria medicao (gerar de novo) nao conta.
        ultima = conn.execute(
            "SELECT numero, competencia FROM medicoes WHERE contrato_id=? AND tipo=? AND numero<>? "
            "AND estado NOT IN ('cancelada','desistida') ORDER BY competencia DESC, numero DESC LIMIT 1",
            (contrato_id, tipo, numero)).fetchone()
        if ultima and competencia < ultima["competencia"]:
            avisos.append(f"Competência {_mes_br(competencia)} é anterior à da última medição "
                          f"(nº {ultima['numero']}, {_mes_br(ultima['competencia'])}): confira")
        meds.append({"tipo": tipo, "valor_centavos": valor, "existente": ex["estado"] if ex else None,
                     "sem_boletim": tipo in sem})
    return {"saidas": saidas, "medicoes": meds, "avisos": avisos, "periodo": espelho.periodo(competencia, periodo),
            "entradas": entradas,
            # todos os valores que vem das medicoes deste numero, tambem os da medicao que ficou fora (`opcional`:
            # so' entra digitada; `sem_boletim`: entra com a justificativa)
            "travados": [{"tipo": t, "valor_centavos": v, "fonte": f, "opcional": t in opcionais,
                          "sem_boletim": t in sem_todos} for t, (v, f) in sorted(travados.items())]}


def _conferir_boletim(conn, numero: int, existentes: dict[str, dict], tipos, justificativa: str | None) -> list[dict]:
    """A trava do boletim (#284): a medicao sem boletim so' segue com a justificativa. Devolve as que seguem sem."""
    sem = _sem_boletim(conn, existentes, tipos)
    if not sem:
        return []
    if not (justificativa or "").strip():
        nomes = " e ".join(medicoes.nome_medicao(numero, m["tipo"]) for m in sem)
        raise ValueError(f"{nomes} ainda sem o boletim do órgão: registre o boletim ou informe a justificativa para "
                         "seguir sem boletim")
    if len(justificativa.strip()) < MIN_JUSTIFICATIVA_SEM_BOLETIM:
        raise ValueError(f"Seguir sem boletim exige justificativa (ao menos {MIN_JUSTIFICATIVA_SEM_BOLETIM} "
                         "caracteres)")
    return sem


def gerar(conn, usuario: dict, contrato_id: int, numero: int, competencia: str,
          entradas: dict[str, int], motivo: str | None = None, periodo: tuple[str, str] | None = None,
          justificativa_sem_boletim: str | None = None) -> int:
    # #284 (gate Sol): a regra e os espelhos vigentes capturados ANTES da conta; sob o lock, o retrato dos tipos
    # gerados e a regra sao conferidos de novo, e o sha gravado e' o desta captura (nao o relido depois do .docx)
    regra0, vigentes0 = _regra_crua(conn, contrato_id), _vigentes(conn, contrato_id, numero)
    r, c, saidas, por_tipo, entradas, existentes, (travados, _) = _calcular(conn, contrato_id, numero, competencia,
                                                                           entradas, regra0)
    retrato = _retrato(existentes, vigentes0, por_tipo, travados)
    _recusar_planilha_sendo_enviada(conn, numero, existentes, por_tipo)   # o e-mail ao orgao saindo explica mais
    _conferir_planilhas(conn, numero, existentes, por_tipo, competencia)               # #289: antes do boletim
    _conferir_boletim(conn, numero, existentes, por_tipo, justificativa_sem_boletim)   # recusa antes de montar
    modelos = {k: arquivos.caminho_seguro(m["arquivo"]).read_bytes() for k, m in r["modelos"].items()}
    # so' calculo antes da transacao: preencher os modelos nao toca banco nem disco
    gerados = [(s, espelho_docx.preencher(modelos[s["chave"]], espelho.formatar_controles(
                   s, numero, competencia, r["regra"].get("texto"), periodo)))
               for s in saidas]
    regra_sha = regra0[3] if regra0 else None       # regra que surgiu no meio: a conferencia abaixo recusa
    with db.mutacao(conn):
        # A versao anterior e' a vigente das MESMAS medicoes (#208; a medicao e' unica por
        # contrato+numero+tipo): trocar a competencia e' correcao, nao espelho novo -- substitui, nao duplica.
        anteriores = _espelhos_anteriores(conn, contrato_id, numero, list(por_tipo))
        _recusar_envio_reservado(conn, contrato_id, numero, list(por_tipo))   # sob o mesmo lock da reserva (#210)
        if _regra_crua(conn, contrato_id) != regra0:
            raise ValueError("A regra do espelho desta obra mudou enquanto o espelho era gerado: gere de novo")
        # #284, sob o lock: boletim, revisao, envio ou cancelamento entre a conta e a gravacao mudam o valor que o
        # espelho tem de usar ou o espelho que ele substitui
        agora = _existentes(conn, contrato_id, numero)
        if _retrato(agora, _vigentes(conn, contrato_id, numero), por_tipo, _travados(conn, agora)) != retrato:
            raise ValueError("A medição mudou enquanto o espelho era gerado: confira os valores e gere de novo")
        _recusar_planilha_sendo_enviada(conn, numero, agora, por_tipo)
        _conferir_planilhas(conn, numero, agora, por_tipo, competencia)
        sem_boletim = _conferir_boletim(conn, numero, agora, por_tipo, justificativa_sem_boletim)
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
        # issue #359: o valor de cada medicao neste espelho, para o aviso de aprovado mudado depois dele
        for tipo, mid in sorted(ids.items(), key=lambda x: x[1]):
            conn.execute("INSERT INTO espelho_medicoes (espelho_id, medicao_id, valor_centavos) VALUES (?,?,?)",
                         (eid, mid, por_tipo[tipo]))
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
                             "arquivos": resumo,
                             **({"sem_boletim": {"justificativa": justificativa_sem_boletim.strip(),
                                                 "medicoes": [m["id"] for m in sem_boletim]}} if sem_boletim else {})})
        for m in sem_boletim:
            auditoria.registrar(conn, usuario["id"], "medicao.sem_boletim", "medicao", m["id"], {"estado": m["estado"]},
                                {"justificativa": justificativa_sem_boletim.strip(), "espelho_id": eid})
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


# --- issue #359: o aprovado mudou depois do espelho ----------------------------------------------------------

# Decisao do Leo de 03/11/2026: o boletim novo com outro valor pode ser glosa, correcao ou reemissao do orgao; o aviso
# so' diz que o aprovado mudou, nunca que e' glosa. Situacoes de `desatualizadas`, com o texto do aviso:
APROVADO_MUDOU = "aprovado_mudou"           # espelho gerado ou enviado: gerar de novo
NOTA_EMITIDA = "nota_emitida"               # nota emitida: o espelho nao se gera mais (revisor, PR #474)
NAO_CONFERIDO = "nao_conferido"             # espelho antigo sem valor de referencia nenhum (gate Sol, PR #474)
TEXTO_AVISO = {APROVADO_MUDOU: "o aprovado mudou depois do espelho, gere o espelho de novo",
               NOTA_EMITIDA: "o aprovado mudou depois do espelho e a nota já foi emitida",
               NAO_CONFERIDO: "não foi possível conferir o valor do espelho antigo, gere o espelho de novo"}
# uma situacao por medicao; no par (ou no espelho com mais de uma), a que pede o ato vem primeiro
PRIORIDADE = {APROVADO_MUDOU: 0, NAO_CONFERIDO: 1, NOTA_EMITIDA: 2}
# a nota emitida segue avisando (a nota da v1 lancada pelo RM leva a medicao a `nota_emitida` com o aviso na tela);
# do protocolo em diante o aviso sai
ESTADOS_DO_AVISO = (*medicoes.ESTADOS_ESPELHO, "nota_emitida")


def desatualizadas(conn, medicao_id: int | None = None) -> list[dict]:
    """Medicoes com espelho gerado, enviado ou nota emitida cujo aprovado vigente difere do valor delas no espelho
    vigente mais novo (`situacao` APROVADO_MUDOU, ou NOTA_EMITIDA na nota emitida, onde o espelho nao se gera mais).

    O valor do espelho vem de `espelho_medicoes.valor_centavos` (065). No espelho de antes da coluna: das entradas
    gravadas pela regra da obra, se ela ainda e' a do espelho (mesmo sha256); senao, do que o espelho travou ao ser
    gerado (#284): o aprovado que valia entao (ultimo atesto ate' o espelho), senao o pedido. Sem nenhum dos dois nao
    ha' como comparar: NAO_CONFERIDO (na nota emitida, o texto da nota emitida, que nao pede o espelho).

    Uma consulta so' (rodada 2 da PR #474): as versoes vigentes por medicao numa CTE, pelo indice de
    `espelho_medicoes (medicao_id, espelho_id)` da 065, e o nome da obra junto. Devolve {id, contrato_id, obra, numero,
    tipo, estado, espelho_id, situacao, aprovado_centavos, espelho_centavos}."""
    marcas = ",".join("?" * len(ESTADOS_DO_AVISO))
    linhas = conn.execute(
        "WITH alvo AS (SELECT id FROM medicoes "
        f"  WHERE estado IN ({marcas}) AND valor_atestado_centavos IS NOT NULL AND (? IS NULL OR id=?)), "
        "vig AS (SELECT em.medicao_id, MAX(e.versao) AS versao FROM alvo JOIN espelho_medicoes em ON em.medicao_id=alvo.id "
        "  JOIN espelhos e ON e.id=em.espelho_id WHERE e.situacao='vigente' GROUP BY em.medicao_id) "
        "SELECT m.id, m.contrato_id, COALESCE(c.nome_curto, c.numero_instrumento) AS obra, m.numero, m.tipo, m.estado, "
        "m.valor_atestado_centavos AS aprovado, m.valor_protocolado_centavos AS pedido, e.id AS espelho_id, "
        "em.valor_centavos, e.entradas, e.regra_sha256, "
        "CASE WHEN em.valor_centavos IS NULL THEN (SELECT a.valor_centavos FROM medicao_atestos a "
        "  WHERE a.medicao_id=m.id AND a.criado_em <= e.criado_em ORDER BY a.id DESC LIMIT 1) END AS aprovado_no_espelho "
        "FROM vig JOIN medicoes m ON m.id=vig.medicao_id JOIN contratos c ON c.id=m.contrato_id "
        # a versao e' unica por (contrato, numero) (UNIQUE da 020) e a medicao, por (contrato, numero, tipo)
        "JOIN espelhos e ON e.contrato_id=m.contrato_id AND e.numero=m.numero AND e.versao=vig.versao "
        "JOIN espelho_medicoes em ON em.espelho_id=e.id AND em.medicao_id=m.id ORDER BY m.id",
        (*ESTADOS_DO_AVISO, medicao_id, medicao_id)).fetchall()
    regras: dict[int, tuple | None] = {}
    out = []
    for r in linhas:
        valor = r["valor_centavos"]
        if valor is None:
            if r["contrato_id"] not in regras:
                regras[r["contrato_id"]] = _regra_crua(conn, r["contrato_id"])
            crua = regras[r["contrato_id"]]
            if crua is not None and crua[3] == r["regra_sha256"]:
                valor = espelho.valor_por_natureza(json.loads(crua[1]), json.loads(r["entradas"])).get(r["tipo"])
            if valor is None:
                # o que o espelho travou ao ser gerado (#284): o aprovado de entao, senao o pedido
                valor = r["aprovado_no_espelho"] if r["aprovado_no_espelho"] is not None else r["pedido"]
        if valor is None:
            situacao = NOTA_EMITIDA if r["estado"] == "nota_emitida" else NAO_CONFERIDO
        elif r["aprovado"] != valor:
            situacao = NOTA_EMITIDA if r["estado"] == "nota_emitida" else APROVADO_MUDOU
        else:
            continue
        out.append({"id": r["id"], "contrato_id": r["contrato_id"], "obra": r["obra"], "numero": r["numero"],
                    "tipo": r["tipo"], "estado": r["estado"], "espelho_id": r["espelho_id"], "situacao": situacao,
                    "aprovado_centavos": r["aprovado"], "espelho_centavos": valor})
    return out


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
