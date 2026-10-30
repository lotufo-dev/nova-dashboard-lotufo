"""Nota fiscal como ato de operacao (spec §3 passo 3, §7.1): o PDF lido avanca a medicao, o RM confirma.

Uma nota = uma linha em `notas_fiscais` (origem pdf ou rm; ver migracao 021). A nota da Lotufo (CNPJ de
entidade com coligada no RM) e' lida, conferida contra a saida do espelho vigente e ALOCADA a' medicao;
`nota_emitida` fecha quando toda saida esperada tem nota. Nota de consorciada e FRC sao so' documentos.
Nada aqui muda estado para tras.
"""
import datetime
import json

from app import arquivos, auditoria, db, espelho, frc, leitura_nfse, leitura_pdf, medicoes, tempo

EMISSOR_LOTUFO = "lotufo"
CAMPOS_CONFERIDOS = ("valor", "iss", "inss", "irrf", "ibs", "cbs", "liquido")   # liquido por ultimo: tolera os tributos
DIAS_AUSENTE_RM = 5
MOTIVO_CANCELADA_RM = "NF cancelada no RM"


# ------------------------------------------------------------------ esperadas

def _espelho_vigente(conn, medicao_id) -> dict | None:
    r = conn.execute("""SELECT e.id, e.saidas FROM espelhos e JOIN espelho_medicoes em ON em.espelho_id=e.id
                        WHERE em.medicao_id=? AND e.situacao='vigente' ORDER BY e.versao DESC LIMIT 1""",
                     (medicao_id,)).fetchone()
    return {"id": r["id"], "saidas": json.loads(r["saidas"])} if r else None


def _alocadas(conn, medicao_id) -> list[dict]:
    return [dict(r) for r in conn.execute("""
        SELECT n.*, a.id AS alocacao_id FROM nf_alocacoes a JOIN notas_fiscais n ON n.id=a.nota_id
        WHERE a.medicao_id=? AND a.desfeita_em IS NULL ORDER BY n.emissao, n.id""", (medicao_id,))]


def _casar_saidas(saidas: list[dict], alocadas: list[dict]) -> list[dict]:
    """Cada saida esperada recebe a nota alocada que lhe corresponde: valor exato primeiro, depois
    municipio + natureza; uma nota atende uma saida so'. Sobra fica sem nota."""
    livres = list(alocadas)
    out = []
    for s in saidas:
        nota = next((n for n in livres if n["valor_centavos"] == s["valor"]), None)
        if nota is None:
            nota = next((n for n in livres if n.get("municipio") and s.get("municipio")
                         and n["municipio"].lower() == s["municipio"].lower()
                         and (n.get("natureza_lida") in (None, s["natureza"]))), None)
        if nota is not None:
            livres.remove(nota)
        out.append({**s, "nota_id": nota["id"] if nota else None})
    return out


def esperadas(conn, medicao_id: int) -> list[dict]:
    """Saidas Lotufo do espelho vigente, da natureza da medicao, cada uma com a nota que a atende.

    Leve de proposito (o casador do RM chama por medicao candidata): so' o tipo da medicao, o espelho
    vigente e as alocacoes -- nada de medicoes.detalhe (que carrega mensagens e documentos)."""
    m = conn.execute("SELECT tipo FROM medicoes WHERE id=?", (medicao_id,)).fetchone()
    esp = _espelho_vigente(conn, medicao_id)
    if m is None or esp is None:
        return []
    natureza = next(k for k, v in espelho.TIPO_POR_NATUREZA.items() if v == m["tipo"])
    saidas = [{"chave": s["chave"], "natureza": s["natureza"], "emissor": s["emissor"], "municipio": s["municipio"],
               "rotulo": s.get("rotulo") or espelho.ROTULO_NATUREZA.get(s["natureza"], s["natureza"]),
               **{c: s[c] for c in ("valor", "iss", "inss", "irrf", "ibs", "cbs", "liquido")}}
              for s in esp["saidas"] if s["natureza"] == natureza and s["emissor"] == EMISSOR_LOTUFO]
    return _casar_saidas(saidas, _alocadas(conn, medicao_id))


def faltam(conn, medicao_id: int) -> int:
    esp = esperadas(conn, medicao_id)
    if esp:
        return sum(1 for e in esp if e["nota_id"] is None)
    return 0 if _alocadas(conn, medicao_id) else 1


def _coligada_lotufo(conn) -> int | None:
    """Coligada do RM da Lotufo: pela chave do cadastro, ou pelo papel (a entidade 1 semeada pela migracao
    012 vem sem chave ate' o `cadastro aplicar`)."""
    r = conn.execute("SELECT coligada_rm FROM entidades WHERE chave=? OR papel='lotufo' "
                     "ORDER BY (chave=?) DESC, id LIMIT 1", (EMISSOR_LOTUFO, EMISSOR_LOTUFO)).fetchone()
    return r["coligada_rm"] if r else None


def coligada_esperada(conn, medicao_id: int) -> int | None:
    """De qual coligada do RM vem a nota que esta medicao espera: a do EMISSOR da saida esperada (Lotufo,
    coligada 1, quando ha' espelho -- mesmo em obra de consorcio, onde a entidade do contrato e' o consorcio),
    ou a da entidade do contrato (medicao sem espelho)."""
    if esperadas(conn, medicao_id):
        return _coligada_lotufo(conn)
    else:
        r = conn.execute("""SELECT e.coligada_rm FROM medicoes m JOIN contratos c ON c.id=m.contrato_id
                            JOIN entidades e ON e.id=COALESCE(c.entidade_id, 1) WHERE m.id=?""", (medicao_id,)).fetchone()
    return r["coligada_rm"] if r else None


# ------------------------------------------------------------------ conferencia

# Nome do campo na tela (aviso no Inicio e em Avisos), o mesmo de CAMPO em Notas.tsx.
NOME_CAMPO = {"valor": "valor", "iss": "ISS", "inss": "INSS", "irrf": "IRRF", "ibs": "IBS", "cbs": "CBS",
              "liquido": "líquido", "municipio": "município", "tomador": "tomador"}


def _descontam_liquido(saida: dict) -> tuple:
    """Tributos que o espelho descontou do liquido desta saida: INSS e IRRF sempre; o ISS so' com
    `deduz_liquido` (espelho.py), o que a propria saida mostra (liquido = valor - INSS - IRRF - ISS)."""
    sem_iss = saida["valor"] - (saida.get("inss") or 0) - (saida.get("irrf") or 0)
    iss_desconta = saida.get("iss") is not None and saida.get("liquido") == sem_iss - saida["iss"]
    return ("inss", "irrf", "iss") if iss_desconta else ("inss", "irrf")


def conferir(saida: dict, nota: dict, cnpj_orgao: str | None, campos: tuple = CAMPOS_CONFERIDOS) -> list[dict]:
    """Diferencas entre a saida do espelho e a nota lida, cada uma com `grau`: `arredondamento` (ate' 1
    centavo num tributo: o portal arredonda onde a regra trunca) ou `divergente` (valor bruto, municipio,
    tomador, ou tributo acima de 1 centavo). IBS/CBS so' quando a regra os declara (None = nao confere).
    Nota digitada a mao (sem leitura) confere so' o valor: `campos=("valor",)`.
    O liquido (revisao da PR #97) pega o que valor e tributos nao pegam (ISS nao retido, retencao federal
    que o espelho nao modela); e' arredondamento so' quando bate EXATAMENTE com o efeito, com sinal, dos
    arredondamentos de INSS, IRRF e do ISS quando ele desconta o liquido (gate Sol S4)."""
    difs = []
    for c in campos:
        esperado = saida.get(c)
        lido = nota.get(f"{c}_centavos") if c != "valor" else nota.get("valor_centavos")
        if esperado is None or lido == esperado:
            continue
        if c == "liquido":
            efeito = sum(d["nota"] - d["espelho"] for d in difs
                         if d["campo"] in _descontam_liquido(saida) and d["grau"] == "arredondamento")
            grau = "arredondamento" if lido is not None and lido == esperado - efeito else "divergente"
        else:
            grau = ("arredondamento" if c != "valor" and lido is not None and abs(lido - esperado) <= 1 else "divergente")
        difs.append({"campo": c, "espelho": esperado, "nota": lido, "grau": grau})
    if saida.get("municipio") and nota.get("municipio") and saida["municipio"].lower() != nota["municipio"].lower():
        difs.append({"campo": "municipio", "espelho": saida["municipio"], "nota": nota["municipio"], "grau": "divergente"})
    if cnpj_orgao and nota.get("tomador_cnpj") and nota["tomador_cnpj"] != cnpj_orgao:
        difs.append({"campo": "tomador", "espelho": cnpj_orgao, "nota": nota["tomador_cnpj"], "grau": "divergente"})
    return difs


def divergente(conferencia: list[dict]) -> bool:
    return any(d.get("grau") == "divergente" for d in conferencia)


def _cnpj_do_orgao(conn, contrato_id) -> str | None:
    r = conn.execute("SELECT o.cnpj FROM contratos c LEFT JOIN orgaos o ON o.id=c.orgao_id WHERE c.id=?",
                     (contrato_id,)).fetchone()
    return r["cnpj"] if r and r["cnpj"] else None


def _entidade_por_cnpj(conn, cnpj) -> dict | None:
    if not cnpj:
        return None
    r = conn.execute("SELECT * FROM entidades WHERE cnpj=?", (cnpj,)).fetchone()
    return dict(r) if r else None


# ------------------------------------------------------------------ gravacao

def _gravar_documento(conn, usuario, medicao_id, caminho: str, sha: str, tamanho: int, nome: str, tipo_doc: str,
                      lida: dict | None, frc_id: int | None = None) -> tuple[int, bool]:
    """Linha em medicao_documentos para um PDF JA' gravado em disco (o arquivo e' escrito ANTES do envelope,
    como api_espelhos.anexar_documento: falha de negocio desfaz o banco e deixa em disco so' um arquivo
    nomeado pelo hash, inofensivo)."""
    # A leitura inteira fica no documento (migracao 032): a FRC soma as notas das consorciadas, que nunca
    # viram `notas_fiscais`.
    leitura = json.dumps(lida, ensure_ascii=False) if tipo_doc == "nfs" and lida else None
    ok = bool(lida and lida.get("ok"))
    consorciada = None
    if ok:
        ent = _entidade_por_cnpj(conn, lida["prestador_cnpj"])
        consorciada = (ent["nome"] if ent and ent["papel"] == "consorciada" else None)
    ja = conn.execute("SELECT id, leitura, frc_id FROM medicao_documentos WHERE medicao_id=? AND item_id=?",
                      (medicao_id, sha)).fetchone()
    if ja:
        # Revisor adversarial na PR #179: a assinada arrastada de novo, ja' conferida pelo texto contra a FRC vigente
        # (frc.para_assinar), passa a valer por ela (anexo sem vinculo, de antes da migracao 038, ou de uma versao
        # que o texto mostra ser igual a' vigente).
        if frc_id and ja["frc_id"] != frc_id:
            conn.execute("UPDATE medicao_documentos SET frc_id=? WHERE id=?", (frc_id, ja["id"]))
            auditoria.registrar(conn, usuario["id"], "medicao.documento", "medicao", medicao_id,
                                {"documento_id": ja["id"], "frc_id": ja["frc_id"]},
                                {"documento_id": ja["id"], "frc_id": frc_id})
        # Arrastar de novo o mesmo PDF rele a nota quando a leitura guardada falhou (leiaute que o leitor
        # passou a reconhecer depois, como a nota nova da Guaxe em 09/10/2026); leitura boa nao e' trocada.
        anterior_ok = bool(ja["leitura"] and json.loads(ja["leitura"]).get("ok"))
        if leitura and (ja["leitura"] is None or (ok and not anterior_ok)):
            conn.execute("UPDATE medicao_documentos SET leitura=?, numero_nf=COALESCE(?, numero_nf), "
                         "consorciada=COALESCE(?, consorciada), municipio=COALESCE(?, municipio) WHERE id=?",
                         (leitura, str(lida["numero"]) if ok else None, consorciada,
                          lida.get("municipio") if ok else None, ja["id"]))
        return ja["id"], True
    cur = conn.execute(
        "INSERT INTO medicao_documentos (medicao_id, fonte, tipo_doc, nome, numero_nf, consorciada, municipio, "
        "item_id, arquivo, sha256, tamanho, leitura, frc_id) VALUES (?,'operacao',?,?,?,?,?,?,?,?,?,?,?)",
        (medicao_id, tipo_doc, nome[-200:], str(lida["numero"]) if ok else None, consorciada,
         lida.get("municipio") if ok else None, sha, caminho, sha, tamanho, leitura, frc_id))
    auditoria.registrar(conn, usuario["id"], "medicao.documento", "medicao", medicao_id, None,
                        {"documento_id": cur.lastrowid, "tipo_doc": tipo_doc, "nome": nome[-200:], "sha256": sha,
                         "tamanho": tamanho, "leitura": (lida or {}).get("leiaute"), "ok": ok,
                         **({"frc_id": frc_id} if frc_id else {})})
    return cur.lastrowid, False


def _upsert_nota_pdf(conn, coligada: int, lida: dict, documento_id: int, leitura: str | None) -> int:
    """Linha da nota vinda do PDF. Se o RM ja' a trouxe (mesma coligada e numero; emissao ou valor iguais),
    preenche a linha do RM e confirma; senao cria com idmov NULL, aguardando o RM. A emissao lida do PDF
    e' a data do portal e nao e' sobrescrita pelo RM."""
    campos = {"documento_id": documento_id, "prestador_cnpj": lida.get("prestador_cnpj"),
              "tomador_cnpj": lida.get("tomador_cnpj"), "competencia": lida.get("competencia"),
              "municipio": lida.get("municipio"), "natureza_lida": lida.get("natureza"),
              "numero_medicao_lido": lida.get("numero_medicao"), "valor_pdf_centavos": lida["valor_centavos"],
              **{f"{c}_centavos": lida.get(f"{c}_centavos") for c in ("iss", "inss", "irrf", "ibs", "cbs", "liquido")},
              "leitura": leitura}
    rm_rows = conn.execute("""SELECT * FROM notas_fiscais WHERE coligada=? AND numero_int=? AND idmov IS NOT NULL
                              AND situacao='ativa' AND (emissao=? OR valor_centavos=?) ORDER BY id""",
                           (coligada, lida["numero"], lida["emissao"], lida["valor_centavos"])).fetchall()
    if len(rm_rows) == 1:
        r = rm_rows[0]
        conf = "confirmada" if r["valor_centavos"] == lida["valor_centavos"] else "divergente"
        sets = ", ".join(f"{k}=?" for k in campos)
        conn.execute(f"UPDATE notas_fiscais SET {sets}, confirmacao=?, confirmada_em=datetime('now') WHERE id=?",
                     (*campos.values(), conf, r["id"]))
        auditoria.registrar(conn, None, "nota.confirmacao", "nota_fiscal", r["id"], None,
                            {"origem": "pdf depois do RM", "confirmacao": conf, "valor_rm": r["valor_centavos"],
                             "valor_pdf": lida["valor_centavos"]})
        return r["id"]
    ja = conn.execute("SELECT id FROM notas_fiscais WHERE coligada=? AND numero_int=? AND idmov IS NULL",
                      (coligada, lida["numero"])).fetchone()
    if ja:
        return ja["id"]
    cols = ", ".join(campos)
    cur = conn.execute(
        f"INSERT INTO notas_fiscais (coligada, numero, numero_int, emissao, valor_centavos, origem, confirmacao, {cols}) "
        f"VALUES (?,?,?,?,?,'pdf','aguardando_rm',{','.join('?' * len(campos))})",
        (coligada, str(lida["numero"]), lida["numero"], lida["emissao"], lida["valor_centavos"], *campos.values()))
    return cur.lastrowid


def _vincular(conn, usuario, m: dict, nota_id: int, lida: dict) -> list[dict]:
    """Aloca (se ainda nao), confere contra a saida que a nota ATENDE (a mesma que `esperadas` lhe atribui:
    valor exato, senao municipio + natureza) ou contra o valor da medicao, grava a conferencia, fecha se completa.
    A saida e' procurada DEPOIS de alocar, pelo `nota_id`: e' a unica fonte de verdade do casamento nota x saida."""
    from app import sincronizacao_rm   # import local: sincronizacao_rm importa notas
    ja = conn.execute("SELECT medicao_id FROM nf_alocacoes WHERE nota_id=? AND desfeita_em IS NULL", (nota_id,)).fetchone()
    if ja is None:
        sincronizacao_rm.alocar(conn, usuario["id"], nota_id, m["id"], "manual", None, "pdf")
    elif ja["medicao_id"] != m["id"]:
        raise ValueError(f"A nota {lida['numero']} já está vinculada a outra medição")
    esp = esperadas(conn, m["id"])
    saida = next((e for e in esp if e["nota_id"] == nota_id), None)
    if saida is not None:
        campos = CAMPOS_CONFERIDOS if lida.get("leiaute") else ("valor",)     # manual: so' o valor
        difs = conferir(saida, lida, _cnpj_do_orgao(conn, m["contrato_id"]), campos)
    elif esp:
        # ha' espelho, mas nenhuma saida esperada casa com esta nota (valor e municipio estranhos): a nota
        # fica vinculada e a divergencia e' o proprio valor contra a menor saida sem nota
        livres = [e for e in esp if e["nota_id"] is None] or esp
        difs = [{"campo": "valor", "espelho": livres[0]["valor"], "nota": lida["valor_centavos"], "grau": "divergente"}]
    else:
        v = m["valor_atestado_centavos"] if m["valor_atestado_centavos"] is not None else m["valor_protocolado_centavos"]
        difs = ([] if v is None or v == lida["valor_centavos"]
                else [{"campo": "valor", "espelho": v, "nota": lida["valor_centavos"], "grau": "divergente"}])
    conn.execute("UPDATE notas_fiscais SET conferencia=? WHERE id=?", (json.dumps(difs), nota_id))
    if difs:
        auditoria.registrar(conn, usuario["id"], "nota.conferencia", "medicao", m["id"], None,
                            {"nota_id": nota_id, "numero": lida["numero"], "diferencas": difs,
                             "divergente": divergente(difs)})
    fechar_se_completa(conn, usuario["id"], m["id"])
    return difs


def fechar_se_completa(conn, usuario_id, medicao_id: int) -> bool:
    """`nota_emitida` quando a medicao nasceu do espelho e nao falta nota. Data = maior emissao das notas."""
    m = conn.execute("SELECT estado FROM medicoes WHERE id=?", (medicao_id,)).fetchone()
    if m is None or m["estado"] not in medicoes.ESTADOS_ESPELHO or faltam(conn, medicao_id) > 0:
        return False
    datas = [n["emissao"] for n in _alocadas(conn, medicao_id) if n["emissao"]]
    medicoes.mudar_estado(conn, usuario_id, medicao_id, "nota_emitida", None, max(datas) if datas else None)
    return True


# ------------------------------------------------------------------ atos da operacao

def anexar_pdf(conn, usuario: dict, medicao_id: int, pdf: bytes, nome: str, tipo_doc: str = "nfs") -> dict:
    """Arrasta a nota (ou a FRC) na medicao: grava o documento, le a nota, vincula e confere."""
    if tipo_doc not in ("nfs", "fatura"):
        raise ValueError("tipo_doc: use nfs (nota) ou fatura (FRC)")
    lida = (leitura_nfse.ler(leitura_pdf.texto_de_pdf_com_limite(pdf)) if tipo_doc == "nfs"
            else {"ok": False, "motivo": "fatura", "leiaute": None})
    # issue #169: a assinada fica ligada a' FRC vigente que ela assina (conferida pelo texto do PDF); sem FRC gerada,
    # desatualizada ou PDF de outra versao, recusa. As recusas baratas e a leitura do texto ficam aqui, fora da
    # transacao; a conferencia, dentro (rodada 3 da PR #179).
    assinada = frc.ler_assinada(pdf) if tipo_doc == "fatura" and frc.precisa_ler(conn, medicao_id) else None
    caminho, sha = arquivos.gravar_bytes("notas", pdf, "pdf")      # disco ANTES do envelope (ver _gravar_documento)
    with db.mutacao(conn):
        m = medicoes.detalhe(conn, medicao_id)
        if m is None:
            raise ValueError("Medição não encontrada")
        if m["estado"] in ("cancelada", "desistida"):
            raise ValueError(f"Medição {m['estado']} não recebe nota")
        # rodada 3 da PR #179: sob o BEGIN IMMEDIATE, sem janela entre a conferencia e o INSERT
        frc_id = frc.para_assinar(conn, medicao_id, assinada) if tipo_doc == "fatura" else None
        documento_id, repetido = _gravar_documento(conn, usuario, medicao_id, caminho, sha, len(pdf), nome, tipo_doc, lida,
                                                   frc_id)
        nota_id, difs = None, []
        ent = _entidade_por_cnpj(conn, lida.get("prestador_cnpj")) if lida.get("ok") else None
        if ent and ent["coligada_rm"] is not None:
            nota_id = _upsert_nota_pdf(conn, ent["coligada_rm"], lida, documento_id, lida["leiaute"])
            difs = _vincular(conn, usuario, m, nota_id, lida)
        estado = medicoes.detalhe(conn, medicao_id)["estado"]
    # Obra de consorcio com FRC pela dashboard: a ultima nota esperada que chega gera a FRC sozinha.
    gerada = frc.gerar_se_completa(conn, usuario, medicao_id) if tipo_doc == "nfs" else None
    return {"documento_id": documento_id, "repetido": repetido, "leitura": lida, "nota_id": nota_id,
            "conferencia": difs, "faltam": faltam(conn, medicao_id), "estado": estado,
            "frc_gerada": gerada["numero"] if gerada else None}


def registrar_manual(conn, usuario: dict, medicao_id: int, documento_id: int, numero: int, emissao: str,
                     valor_centavos: int) -> dict:
    """PDF sem texto ou leiaute desconhecido: a pessoa digita numero, data e valor (spec §7.1)."""
    if numero <= 0 or valor_centavos <= 0:
        raise ValueError("Número e valor da nota têm que ser positivos")
    datetime.date.fromisoformat(emissao)
    lida = {"ok": True, "leiaute": None, "numero": numero, "emissao": emissao, "competencia": emissao[:7],
            "valor_centavos": valor_centavos, "prestador_cnpj": None, "tomador_cnpj": None, "municipio": None,
            "natureza": None, "numero_medicao": None}
    with db.mutacao(conn):
        m = medicoes.detalhe(conn, medicao_id)
        doc = conn.execute("SELECT id FROM medicao_documentos WHERE id=? AND medicao_id=? AND tipo_doc='nfs'",
                           (documento_id, medicao_id)).fetchone()
        if m is None or doc is None:
            raise ValueError("Documento não encontrado nesta medição")
        if m["estado"] in ("cancelada", "desistida"):
            raise ValueError(f"Medição {m['estado']} não recebe nota")
        coligada = _coligada_lotufo(conn)
        if coligada is None:
            raise ValueError("Entidade Lotufo sem coligada do RM no cadastro")
        nota_id = _upsert_nota_pdf(conn, coligada, lida, documento_id, "manual")
        conn.execute("UPDATE medicao_documentos SET numero_nf=? WHERE id=?", (str(numero), documento_id))
        auditoria.registrar(conn, usuario["id"], "nota.manual", "medicao", medicao_id, None,
                            {"nota_id": nota_id, "documento_id": documento_id, "numero": numero, "emissao": emissao,
                             "valor_centavos": valor_centavos})
        difs = _vincular(conn, usuario, m, nota_id, lida)
    return {"nota_id": nota_id, "conferencia": difs, "faltam": faltam(conn, medicao_id),
            "estado": medicoes.detalhe(conn, medicao_id)["estado"]}


def declarar_completa(conn, usuario: dict, medicao_id: int, justificativa: str) -> None:
    if not (justificativa or "").strip():
        raise ValueError("Declarar as notas completas exige justificativa")
    with db.mutacao(conn):
        m = medicoes.detalhe(conn, medicao_id)
        if m is None:
            raise ValueError("Medição não encontrada")
        if m["estado"] not in medicoes.ESTADOS_ESPELHO:
            raise ValueError(f"Medição em {m['estado']}: só espelho gerado ou enviado declara notas completas")
        alocadas = _alocadas(conn, medicao_id)
        if not alocadas:
            raise ValueError("Nenhuma nota vinculada: anexe ao menos uma nota (ou protocole sem nota, com justificativa)")
        datas = [n["emissao"] for n in alocadas if n["emissao"]]
        medicoes.mudar_estado(conn, usuario["id"], medicao_id, "nota_emitida",
                              f"notas declaradas completas: {justificativa.strip()}", max(datas) if datas else None)


def justificar(conn, usuario: dict, nota_id: int, texto: str) -> None:
    if not (texto or "").strip():
        raise ValueError("Justificativa vazia")
    with db.mutacao(conn):
        cur = conn.execute("UPDATE notas_fiscais SET justificativa=? WHERE id=?", (texto.strip(), nota_id))
        if cur.rowcount != 1:
            raise ValueError("Nota não encontrada")
        auditoria.registrar(conn, usuario["id"], "nota.justificar", "nota_fiscal", nota_id, None,
                            {"justificativa": texto.strip()})


# ------------------------------------------------------------------ avisos

def avisos(conn, hoje: datetime.date | None = None) -> list[dict]:
    """Tres avisos (spec §11 e revisao adversarial): nota divergente do espelho (grau `divergente`, sem
    justificativa), nota protocolada ausente do RM ha' 5 dias, e nota cancelada no RM em medicao ainda aberta."""
    hoje = hoje or tempo.hoje_local()
    out = []
    for r in conn.execute("""
        SELECT n.id AS nota_id, n.numero_int AS numero, n.conferencia, a.medicao_id, m.contrato_id
        FROM notas_fiscais n JOIN nf_alocacoes a ON a.nota_id=n.id AND a.desfeita_em IS NULL
        JOIN medicoes m ON m.id=a.medicao_id
        WHERE n.conferencia IS NOT NULL AND n.conferencia <> '[]' AND (n.justificativa IS NULL OR n.justificativa='')
          AND m.estado NOT IN ('cancelada','desistida','recebida')"""):
        difs = json.loads(r["conferencia"])
        if not divergente(difs):
            continue
        out.append({"tipo": "nota_divergente", "nota_id": r["nota_id"], "numero": r["numero"], "medicao_id": r["medicao_id"],
                    "contrato_id": r["contrato_id"], "dias": None,
                    "mensagem": f"nota {r['numero']} diverge do espelho: "
                                + ", ".join(NOME_CAMPO.get(d["campo"], d["campo"]) for d in difs
                                            if d.get("grau") == "divergente")})
    for r in conn.execute("""
        SELECT n.id AS nota_id, n.numero_int AS numero, a.medicao_id, m.contrato_id,
               (SELECT MAX(p.data) FROM medicao_protocolos p WHERE p.medicao_id=m.id AND p.etapa='nota') AS protocolado_em
        FROM notas_fiscais n JOIN nf_alocacoes a ON a.nota_id=n.id AND a.desfeita_em IS NULL
        JOIN medicoes m ON m.id=a.medicao_id
        WHERE n.confirmacao='aguardando_rm' AND m.estado='protocolada'"""):
        if not r["protocolado_em"]:
            continue
        dias = (hoje - datetime.date.fromisoformat(r["protocolado_em"])).days
        if dias >= DIAS_AUSENTE_RM:
            out.append({"tipo": "nota_ausente_rm", "nota_id": r["nota_id"], "numero": r["numero"],
                        "medicao_id": r["medicao_id"], "contrato_id": r["contrato_id"], "dias": dias,
                        "mensagem": f"nota {r['numero']} protocolada há {dias} dias e ainda não apareceu no RM"})
    for r in conn.execute("""
        SELECT DISTINCT a.medicao_id, m.contrato_id, n.numero_int AS numero, n.id AS nota_id
        FROM nf_alocacoes a JOIN notas_fiscais n ON n.id=a.nota_id JOIN medicoes m ON m.id=a.medicao_id
        WHERE a.desfeita_em IS NOT NULL AND a.motivo_desfazer=?
          AND m.estado NOT IN ('cancelada','desistida','recebida')
          AND NOT EXISTS (SELECT 1 FROM nf_alocacoes b WHERE b.medicao_id=m.id AND b.desfeita_em IS NULL
                          AND b.criado_em >= a.desfeita_em)""", (MOTIVO_CANCELADA_RM,)):
        out.append({"tipo": "nota_cancelada_rm", "nota_id": r["nota_id"], "numero": r["numero"], "medicao_id": r["medicao_id"],
                    "contrato_id": r["contrato_id"], "dias": None,
                    "mensagem": f"nota {r['numero']} foi cancelada no RM e nenhuma nota nova foi vinculada"})
    return out


# ------------------------------------------------------------------ bloco 6: aba Notas da obra

def _situacao(n: dict) -> str:
    difs = json.loads(n["conferencia"] or "[]")
    if divergente(difs):
        return "justificada" if (n.get("justificativa") or "").strip() else "divergente"
    return {"aguardando_rm": "aguardando_rm", "divergente": "divergente_rm"}.get(n.get("confirmacao"), "conferida")


def _divergencias(n: dict) -> list[dict]:
    """So' os campos que divergem do espelho (G3-11), com o esperado (espelho) e o lido (nota); o
    arredondamento de 1 centavo num tributo nao entra."""
    return [{"campo": d["campo"], "esperado": d["espelho"], "lido": d["nota"]}
            for d in json.loads(n["conferencia"] or "[]") if d.get("grau") == "divergente"]


def do_contrato(conn, contrato_id: int) -> list[dict]:
    """Uma linha por medicao do contrato: as saidas esperadas do espelho com a nota que atende cada uma,
    as notas alocadas (com a situacao da conferencia) e os documentos de nota anexados."""
    out = []
    for m in conn.execute("SELECT * FROM medicoes WHERE contrato_id=? AND estado NOT IN ('cancelada','desistida') "
                          "ORDER BY numero DESC, tipo", (contrato_id,)):
        notas = {n["id"]: {"id": n["id"], "numero": n["numero_int"], "emissao": n["emissao"],
                           "valor_centavos": n["valor_centavos"], "situacao": _situacao(n),
                           "divergencias": _divergencias(n)}
                 for n in _alocadas(conn, m["id"])}
        docs = [dict(r) for r in conn.execute(
            "SELECT id, tipo_doc, nome, numero_nf FROM medicao_documentos WHERE medicao_id=? "
            "AND tipo_doc IN ('nfs','nf','fatura') ORDER BY id", (m["id"],))]
        out.append({"medicao_id": m["id"], "titulo": medicoes.titulo(m), "competencia": m["competencia"],
                    "estado": m["estado"], "valor_centavos": m["valor_protocolado_centavos"],
                    "saidas": [{"chave": s["chave"], "municipio": s["municipio"], "valor_centavos": s["valor"],
                                "nota": notas.get(s["nota_id"])} for s in esperadas(conn, m["id"])],
                    "notas": list(notas.values()), "documentos": docs})
    return out
