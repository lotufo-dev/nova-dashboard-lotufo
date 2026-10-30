"""Documentos de protocolo (spec 2026-09-21 §9, bloco 4).

Duas gavetas. CERTIDAO tem validade e e' da empresa: tabela `certidoes`, historico append-only de
`certidoes.py`, que continua sendo a unica fonte de "o que valia na data". REGULARIDADE MENSAL e'
por competencia e por empresa: tabela `regularidades`, o PDF que o DP monta (folha, SEFIP/eSocial,
INSS), anexado uma vez e usado em todos os protocolos do mes.

O que e' EXIGIDO vem do cadastro: lista do orgao por natureza (medicao/projeto ou reajuste),
excecao do contrato, e em obra de consorcio as certidoes do consorcio e de cada consorciada.
"""
import datetime
import io
import json
import re
import sqlite3
import zipfile
from pathlib import Path

from app import (arquivos, auditoria, certidoes, contratos, db, entidades, feriados, garantias, leitura_certidao,
                 leitura_pdf, tempo)

TIPOS = leitura_certidao.TIPOS
TIPOS_ZIP = ("federal", "fgts", "trabalhista", "estadual", "municipal")    # D7 (09/10/2026): falencia fora
REGULARIDADE = "regularidade"
ROTULO = {"federal": "federal", "fgts": "FGTS", "trabalhista": "trabalhista", "estadual": "estadual",
          "municipal": "municipal", "falencia": "falência"}
VALIDADE_CURTA_DIAS = 31          # FGTS e municipal: ~30 dias de validade
LIMIAR_CURTA, LIMIAR_LONGA = 7, 15
DIA_REGULARIDADE = 10
# A-19 e gate Sol S5 (10/10/2026): teto da validade por tipo. Vem dos prazos REAIS das 54 certidoes de producao (lidas
# do PDF) em 10/10/2026 -- federal e CNDT 180, estadual sempre 59, municipal 30 a 90, FGTS 29, falencia 42-43 (dias
# uteis) -- com folga de poucos dias por tipo. Vale para a digitada e para a lida (S6, OCR que troca o ano).
VALIDADE_MAXIMA_DIAS = {"federal": 185, "trabalhista": 185, "estadual": 65, "municipal": 95, "fgts": 35, "falencia": 60}
_COMPETENCIA = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")  # A-14 (10/10/2026): \d casa digito arabe-indico


def _d(iso: str) -> datetime.date:
    return datetime.date.fromisoformat(iso)


def _br(iso: str) -> str:
    return _d(iso).strftime("%d/%m/%Y")


def _mes_br(mes: str) -> str:
    return f"{mes[5:7]}/{mes[:4]}"


def _nome(e: dict) -> str:
    return e.get("nome_curto") or e["nome"]


def limiar(cert: dict) -> int:
    """7 dias para a certidao de ate 31 dias de validade (FGTS, municipal), 15 para as demais."""
    total = (_d(cert["validade"]) - _d(cert["emissao"])).days
    return LIMIAR_CURTA if total <= VALIDADE_CURTA_DIAS else LIMIAR_LONGA


def tipo_por_chave(conn: sqlite3.Connection, chave: str) -> dict:
    r = conn.execute("SELECT * FROM certidao_tipos WHERE chave=?", (chave,)).fetchone()
    if r is None:
        raise ValueError(f"Tipo de certidão sem cadastro: {chave}")
    return dict(r)


# --- exigencia --------------------------------------------------------------------------------

def exigidos(conn: sqlite3.Connection, contrato_id: int, natureza: str) -> dict:
    """{'entidades': [ids], 'tipos': [linhas de certidao_tipos], 'regularidade': entidade | None}.

    Precedencia: excecao do contrato > lista do orgao > (contrato SEM orgao) tipos
    `aplicavel_por_padrao`, o comportamento de antes do cadastro versionado, que os contratos da tela
    antiga e os testes ainda usam. Projeto segue a lista da medicao.

    A regularidade mensal e' da Lotufo, salvo quando a entidade do contrato tem folha propria
    (`regularidade_propria`, o Complexo Leblon): ai' e' a dela.
    """
    c = conn.execute("SELECT * FROM contratos WHERE id=?", (contrato_id,)).fetchone()
    if c is None:
        raise ValueError(f"Contrato {contrato_id} não encontrado")
    chave = "reajuste" if natureza == "reajuste" else "medicao"
    lista = None
    if c["documentos"]:
        lista = json.loads(c["documentos"]).get(chave)
    if lista is None and c["orgao_id"] is not None:
        o = conn.execute("SELECT regras FROM orgaos WHERE id=?", (c["orgao_id"],)).fetchone()
        lista = json.loads(o["regras"]).get(f"documentos_{chave}") if o else None
    if lista is None:
        tipos = [dict(r) for r in conn.execute(
            "SELECT * FROM certidao_tipos WHERE aplicavel_por_padrao=1 ORDER BY id")]
        lista = []
    else:
        tipos = [tipo_por_chave(conn, k) for k in lista if k in TIPOS]
    ent = contratos.entidade_de(c)
    ents = [ent] + [r[0] for r in conn.execute(
        "SELECT consorciada_id FROM entidade_consorciadas WHERE consorcio_id=? ORDER BY consorciada_id", (ent,))]
    propria = conn.execute("SELECT regularidade_propria FROM entidades WHERE id=?", (ent,)).fetchone()
    if propria and propria[0]:
        dona = ent
    else:
        lotufo = conn.execute("SELECT id FROM entidades WHERE papel='lotufo' ORDER BY id LIMIT 1").fetchone()
        dona = lotufo[0] if lotufo else None
    return {"entidades": ents, "tipos": tipos, "regularidade": dona if REGULARIDADE in lista else None}


def _exigidos_ativos(conn) -> tuple[dict[int, dict[int, dict]], dict[int, int], set[int], dict[int, list[int]]]:
    """Uniao das exigencias dos contratos ATIVOS, nas duas naturezas.
    -> ({entidade: {tipo_id: tipo}}, {entidade: primeiro contrato}, {entidades com regularidade exigida},
        {entidade: todos os contratos que a exigem})"""
    cert: dict[int, dict[int, dict]] = {}
    contrato_de: dict[int, int] = {}
    regs: set[int] = set()
    obras_de: dict[int, list[int]] = {}

    def exige(e: int, cid: int):
        contrato_de.setdefault(e, cid)
        if cid not in obras_de.setdefault(e, []):
            obras_de[e].append(cid)

    for r in conn.execute("SELECT id FROM contratos WHERE estado='ativo' ORDER BY id").fetchall():
        for natureza in ("execucao", "reajuste"):
            ex = exigidos(conn, r["id"], natureza)
            if ex["tipos"]:
                for e in ex["entidades"]:
                    exige(e, r["id"])
                    cert.setdefault(e, {}).update({t["id"]: t for t in ex["tipos"]})
            # A regularidade vale por si: orgao que so' a exige tambem gera aviso (gate Sol, achado 5).
            if ex["regularidade"]:
                regs.add(ex["regularidade"])
                exige(ex["regularidade"], r["id"])
    return cert, contrato_de, regs, obras_de


# --- situacao ---------------------------------------------------------------------------------

def situacao(conn: sqlite3.Connection, entidade_id: int, tipo: dict, hoje: datetime.date) -> dict:
    v = certidoes.vigente(conn, entidade_id, tipo["id"], na_data=hoje.isoformat())
    if v:
        dias = (_d(v["validade"]) - hoje).days
        return {"situacao": "vencendo" if dias <= limiar(v) else "ok", "dias": dias, "certidao": v}
    if certidoes.nao_se_aplica_vigora(conn, entidade_id, tipo["id"]):
        return {"situacao": "nao_se_aplica", "dias": None, "certidao": None}
    ultima = certidoes.ultima_emissao(conn, entidade_id, tipo["id"], hoje.isoformat())
    return {"situacao": "vencida" if ultima else "faltando", "dias": None, "certidao": ultima}


# --- regularidade mensal ----------------------------------------------------------------------

def _mes_menos(mes: str, n: int) -> str:
    a, m = int(mes[:4]), int(mes[5:7])
    total = a * 12 + (m - 1) - n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def competencia_esperada(hoje: datetime.date) -> str:
    """Competencia da regularidade que o protocolo de HOJE leva.

    Medido nos protocolos de 2026: 22/06 levou 04/2026 e 16/09 levou 07/2026 (mes menos 2); 03/08
    levou 05/2026 (mes menos 3): antes do dia 10 o DP ainda nao fechou a do mes menos 2.
    """
    return _mes_menos(hoje.isoformat()[:7], 2 if hoje.day >= DIA_REGULARIDADE else 3)


def competencia_do_pdf(pdf: bytes) -> str | None:
    """Competencia ("AAAA-MM") impressa no cabecalho da folha analitica do DP: "... 4.001.001 08/2026 Per:0"
    (o extrator cola o codigo da empresa na data: "4.001.00108/2026 Per:0"). None quando nao acha.

    09/10/2026: a regularidade do Consorcio Integra de 08/2026 entrou como 07/2026 porque o botao do envio
    mandava o mes SUGERIDO (antes do dia 10, mes menos 3). O que vale e' o que o PDF diz."""
    try:
        texto = leitura_pdf.primeira_pagina_com_limite(pdf) or ""
    except (leitura_pdf.TextoInadequado, ValueError):
        return None
    m = (re.search(r"\d\.\d{3}\.\d{3}\s*(0[1-9]|1[0-2])/(20\d{2})\s*Per:", texto)
         or re.search(r"(0[1-9]|1[0-2])/(20\d{2})\s*Per:\s*\d", texto))
    return f"{m.group(2)}-{m.group(1)}" if m else None


def conferir_regularidade(conn, entidade_id: int, competencia: str) -> None:
    """Guardas baratas da regularidade; a rota as chama ANTES de gravar o PDF (gate Sol, achado 6)."""
    if not _COMPETENCIA.match(competencia or ""):
        raise ValueError(f"Competência inválida: {competencia!r} (use AAAA-MM)")
    if competencia > tempo.hoje_local().isoformat()[:7]:
        raise ValueError(f"A competência {_mes_br(competencia)} ainda não aconteceu")
    e = entidades.detalhe(conn, entidade_id)
    if e is None:
        raise ValueError(f"Entidade {entidade_id} não encontrada")
    if not e["ativo"]:
        raise ValueError(f"Entidade '{_nome(e)}' está desativada e não aceita novos documentos")


def registrar_regularidade(conn, usuario_id: int, entidade_id: int, competencia: str, arquivo: str,
                           sha256: str, tamanho: int, nome_original: str | None) -> int:
    with db.mutacao(conn):
        conferir_regularidade(conn, entidade_id, competencia)
        if conn.execute("SELECT 1 FROM regularidades WHERE entidade_id=? AND competencia=? AND sha256=?",
                        (entidade_id, competencia, sha256)).fetchone():
            raise ValueError("Este arquivo já está anexado para essa competência")
        cur = conn.execute(
            "INSERT INTO regularidades (entidade_id, competencia, arquivo, sha256, tamanho, nome_original, usuario_id) "
            "VALUES (?,?,?,?,?,?,?)", (entidade_id, competencia, arquivo, sha256, tamanho, nome_original, usuario_id))
        rid = cur.lastrowid
        auditoria.registrar(conn, usuario_id, "regularidade.registrar", "regularidade", rid, None,
                            {"entidade_id": entidade_id, "competencia": competencia, "arquivo": arquivo,
                             "sha256": sha256, "tamanho": tamanho, "nome_original": nome_original})
    return rid


def regularidade_vigente(conn, entidade_id: int) -> dict | None:
    r = conn.execute("SELECT * FROM regularidades WHERE entidade_id=? ORDER BY competencia DESC, id DESC LIMIT 1",
                     (entidade_id,)).fetchone()
    return dict(r) if r else None


def situacao_regularidade(conn, entidade_id: int, hoje: datetime.date) -> dict:
    v = regularidade_vigente(conn, entidade_id)
    esperada = competencia_esperada(hoje)
    s = "ok" if v and v["competencia"] >= esperada else ("atrasada" if v else "faltando")
    return {"situacao": s, "competencia": v["competencia"] if v else None, "esperada": esperada, "regularidade": v}


# --- gravar certidao --------------------------------------------------------------------------

OBS_OCR = "lida por OCR"


def texto_para_leitura(pdf: bytes, texto: str) -> tuple[str, bool]:
    """(texto, veio_do_ocr). PDF sem texto passa pelo OCR local; se o OCR nao esta instalado ou
    falha, volta o texto vazio e a leitura recusa com `sem-texto` (campos digitados, como antes)."""
    if not leitura_certidao.sem_texto(texto):
        return texto, False
    ocr = leitura_pdf.texto_por_ocr_com_limite(pdf)
    if ocr is None or leitura_certidao.sem_texto(ocr):
        return texto, False
    return ocr, True


def ler(conn, texto: str) -> dict:
    """Leitura + empresa do cadastro (pelo CNPJ) + tipo cadastrado. Recusa com motivo estavel."""
    cads = {e["cnpj"]: e for e in entidades.listar(conn)}
    lido = leitura_certidao.ler(texto, frozenset(cads))
    e = cads.get(lido["cnpj"])
    if e is None:
        c = lido["cnpj"]
        raise leitura_certidao.Recusa(
            "empresa-desconhecida",
            f"O CNPJ {c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]} do documento não é de nenhuma empresa do cadastro.")
    # Gate Sol S6 (10/10/2026): OCR que le 2027 onde era 2026 instalaria uma vigente errada. Datas fora do prazo
    # normal do tipo (ou emissao futura) nao gravam como automatica: viram digitacao, ja' preenchida com o lido.
    if problema_nas_datas(lido["tipo"], lido["emissao"], lido["validade"]):
        raise leitura_certidao.Recusa(
            "datas-implausiveis",
            f"As datas lidas (emissão {_br(lido['emissao'])}, validade {_br(lido['validade'])}) não batem com o prazo "
            "normal desta certidão: confira no documento e digite",
            lidos={"entidade_id": e["id"], "tipo": lido["tipo"], "emissao": lido["emissao"],
                   "validade": lido["validade"], "natureza": lido["natureza"]})
    t = tipo_por_chave(conn, lido["tipo"])
    return {**lido, "entidade_id": e["id"], "entidade": _nome(e), "tipo_id": t["id"], "tipo_nome": t["nome"]}


def problema_nas_datas(tipo_chave: str, emissao: str, validade: str) -> str | None:
    """Emissao futura ou validade acima do teto do tipo (A-19, S5): a frase para a pessoa, ou None."""
    if _d(emissao) > tempo.hoje_local():
        return "A data de emissão não pode ser futura: confira as datas no documento"
    dias, teto = (_d(validade) - _d(emissao)).days, VALIDADE_MAXIMA_DIAS[tipo_chave]
    if dias > teto:
        return (f"Validade de {dias} dias passa do máximo de {teto} para certidão {ROTULO[tipo_chave]}: "
                "confira as datas no documento")
    return None


def dados_manuais(conn, entidade_id: int, tipo_chave: str, emissao: str, validade: str | None,
                  natureza: str | None, numero: str | None, cnpjs_do_texto: list[str] = ()) -> dict:
    """Campos digitados. `cnpjs_do_texto`: os CNPJs validos do PDF, quando ele tem texto -- a empresa
    digitada precisa ser uma delas (a CND da Guaxe nao vai para a Lotufo)."""
    if tipo_chave not in TIPOS:
        raise ValueError(f"Tipo inválido: {tipo_chave!r}")
    if natureza not in leitura_certidao.NATUREZAS:
        raise ValueError("Informe se a certidão é negativa ou positiva com efeito de negativa "
                         "(certidão positiva não serve para protocolo)")
    e = entidades.detalhe(conn, entidade_id)
    if e is None:
        raise ValueError(f"Entidade {entidade_id} não encontrada")
    if not e["ativo"]:
        raise ValueError(f"Entidade '{_nome(e)}' está desativada e não aceita novas certidões")
    if cnpjs_do_texto and e["cnpj"] not in cnpjs_do_texto:
        raise ValueError(f"O CNPJ de {_nome(e)} não aparece no documento — confira se o arquivo é dessa empresa")
    emissao = _d(emissao).isoformat()
    if not validade and tipo_chave == "falencia":
        validade = feriados.somar_dias_uteis(_d(emissao), leitura_certidao.DIAS_UTEIS_FALENCIA).isoformat()
    if not validade:
        raise ValueError("Informe a validade")
    # A-19: a pagina em branco digitada com validade em 2099 virava a vigente e escondia a real.
    problema = problema_nas_datas(tipo_chave, emissao, validade)
    if problema:
        raise ValueError(problema)
    t = tipo_por_chave(conn, tipo_chave)
    return {"entidade_id": entidade_id, "entidade": _nome(e), "tipo": tipo_chave, "tipo_id": t["id"],
            "tipo_nome": t["nome"], "emissao": emissao, "validade": _d(validade).isoformat(),
            "natureza": natureza, "numero": (numero or "").strip() or None}


def ja_cadastrada(conn, dados: dict) -> bool:
    """A mesma certidao (empresa, tipo, emissao, validade) ja' esta' gravada e vigente?"""
    return conn.execute("SELECT 1 FROM certidoes WHERE entidade_id=? AND tipo_id=? AND emissao=? AND validade=? "
                        "AND estado='vigente'", (dados["entidade_id"], dados["tipo_id"], dados["emissao"],
                                                 dados["validade"])).fetchone() is not None


def gravar_certidao(conn, usuario_id: int, dados: dict, arquivo: str, sha256: str,
                    nome_original: str | None, leitura: str, ocr: bool = False) -> int:
    with db.mutacao(conn):      # BEGIN IMMEDIATE: a conferencia e o INSERT nao se intercalam com outro escritor
        if ja_cadastrada(conn, dados):
            raise ValueError(f"Esta certidão já está cadastrada (válida até {_br(dados['validade'])})")
        return certidoes.registrar(conn, usuario_id, dados["entidade_id"], dados["tipo_id"], dados["emissao"],
                                   dados["validade"], arquivo, sha256, "upload", dados.get("numero"),
                                   natureza=dados["natureza"], leitura=leitura, nome_original=nome_original,
                                   observacao=OBS_OCR if ocr else None)


# --- painel, avisos, ZIP ----------------------------------------------------------------------

def _regularidades_anexadas(conn, entidade_id: int, limite: int = 12) -> list[dict]:
    """As ultimas regularidades anexadas da entidade (a mais recente primeiro): competencia e dia do anexo."""
    return [{"id": r["id"], "competencia": r["competencia"], "anexada_em": tempo.para_local(datetime.datetime.fromisoformat(r["criado_em"])).date().isoformat()}
            for r in conn.execute("SELECT id, competencia, criado_em FROM regularidades WHERE entidade_id=? "
                                  "ORDER BY competencia DESC, id DESC LIMIT ?", (entidade_id, limite))]


def painel(conn, hoje: datetime.date | None = None) -> dict:
    hoje = hoje or tempo.hoje_local()
    cert, _, regs, obras_de = _exigidos_ativos(conn)
    nomes = {r["id"]: r["nome_curto"] or r["numero_instrumento"]
             for r in conn.execute("SELECT id, nome_curto, numero_instrumento FROM contratos")}
    tipos = [tipo_por_chave(conn, k) for k in TIPOS]
    com_docs = {r[0] for r in conn.execute(
        "SELECT entidade_id FROM certidoes UNION SELECT entidade_id FROM regularidades")}
    ordem = {"lotufo": 0, "consorcio": 1, "consorciada": 2}
    # a empresa contratada de toda obra ativa entra (a garantia dela mora na pagina da empresa, #161)
    contratadas = {contratos.entidade_de(r) for r in conn.execute("SELECT entidade_id FROM contratos WHERE estado='ativo'")}
    ents = sorted((e for e in entidades.listar(conn)
                   if e["id"] in cert or e["id"] in regs or e["id"] in com_docs or e["id"] in contratadas),
                  key=lambda e: (ordem.get(e["papel"], 9), _nome(e)))
    # Redesenho de Documentos (#161): quem compoe cada consorcio (so' leitura), para a pagina da empresa.
    consorciadas: dict[int, list[int]] = {}
    consorcios: dict[int, list[int]] = {}
    for r in conn.execute("SELECT consorcio_id, consorciada_id FROM entidade_consorciadas ORDER BY consorciada_id"):
        consorciadas.setdefault(r[0], []).append(r[1])
        consorcios.setdefault(r[1], []).append(r[0])
    empresas = []
    for e in ents:
        linhas = []
        for t in tipos:
            s = situacao(conn, e["id"], t, hoje)
            linhas.append({"tipo_id": t["id"], "chave": t["chave"], "tipo": t["nome"], "link_emissao": t["link_emissao"],
                           "exigida": t["id"] in cert.get(e["id"], {}), **s})
        tem_reg = e["id"] in regs or regularidade_vigente(conn, e["id"]) is not None
        # A7 (mapa de 2026-09-28): as obras ativas que exigem a empresa, para saber de quem e' a certidao.
        obras = sorted(({"contrato_id": cid, "obra": nomes[cid]} for cid in obras_de.get(e["id"], [])),
                       key=lambda o: o["obra"])
        empresas.append({"entidade_id": e["id"], "entidade": _nome(e), "cnpj": e["cnpj"], "papel": e["papel"],
                         "certidoes": linhas, "regularidade_exigida": e["id"] in regs,
                         "regularidade": situacao_regularidade(conn, e["id"], hoje) if tem_reg else None,
                         "obras": obras, "consorciadas": consorciadas.get(e["id"], []),
                         "consorcios": consorcios.get(e["id"], []),
                         "regularidades_anexadas": _regularidades_anexadas(conn, e["id"])})
    # Issue #65: garantia (com validade) por contrato ativo, junto das certidoes.
    obras = [{"contrato_id": r["id"], "obra": nomes[r["id"]], "entidade_id": contratos.entidade_de(r),
              "garantia": garantias.garantia(conn, r["id"], hoje)}
             for r in conn.execute("SELECT id, entidade_id FROM contratos WHERE estado='ativo' ORDER BY nome_curto, id")]
    return {"hoje": hoje.isoformat(), "empresas": empresas, "contratos": obras}


def avisos(conn, hoje: datetime.date | None = None) -> list[dict]:
    """Spec §11: 'Documentos da empresa' (uma linha por empresa) e 'Regularidade do mes' (dia 10)."""
    hoje = hoje or tempo.hoje_local()
    cert, contrato_de, regs, _ = _exigidos_ativos(conn)
    out = []
    for eid in sorted(cert):
        e = entidades.detalhe(conn, eid)
        if e is None or not e["ativo"]:
            continue
        partes, grave, validades = [], False, []
        for t in sorted(cert[eid].values(), key=lambda t: TIPOS.index(t["chave"]) if t["chave"] in TIPOS else 99):
            s = situacao(conn, eid, t, hoje)
            rot = ROTULO.get(t["chave"], t["nome"])
            if s["situacao"] == "vencida":
                partes.append(f"{rot} vencida em {_br(s['certidao']['validade'])}")
                grave = True
                validades.append(s["certidao"]["validade"])
            elif s["situacao"] == "faltando":
                partes.append(f"{rot} sem certidão")
                grave = True
            elif s["situacao"] == "vencendo":
                partes.append(f"{rot} vence hoje" if s["dias"] == 0 else
                              f"{rot} vence em {s['dias']} dia{'s' if s['dias'] > 1 else ''}")
                validades.append(s["certidao"]["validade"])
        if partes:
            # D10 (Leonardo, 2026-09-26): certidao vencida ou faltando e' CRITICO, no aviso e na tela
            # (a matriz de Documentos e o checklist ja' a mostram em vermelho, como pendencia que trava).
            # `data` (A8): a validade mais antiga entre as que venceram ou vencem (a que pesa primeiro).
            # A11 (mapa de 2026-09-28): o nome da empresa, para a tela de Avisos agrupar e rotular por ela
            out.append({"tipo": "documentos_empresa", "nivel": "critico" if grave else "atencao",
                        "entidade_id": eid, "entidade": _nome(e), "contrato_id": contrato_de[eid],
                        "mensagem": f"{_nome(e)}: {'; '.join(partes)}",
                        "data": min(validades)[:10] if validades else None})
    if hoje.day >= DIA_REGULARIDADE:
        for eid in sorted(regs):
            s = situacao_regularidade(conn, eid, hoje)
            if s["situacao"] == "ok":
                continue
            e = entidades.detalhe(conn, eid)
            ultima = f"; a última é de {_mes_br(s['competencia'])}" if s["competencia"] else ""
            # `data` (A8): o dia do mes a partir do qual a regularidade e' cobrada (o aviso nasce nele).
            out.append({"tipo": "regularidade_mes", "nivel": "acao", "entidade_id": eid, "entidade": _nome(e),
                        "contrato_id": contrato_de[eid],
                        "mensagem": f"{_nome(e)}: regularidade de {_mes_br(s['esperada'])} não anexada{ultima}",
                        "data": hoje.replace(day=DIA_REGULARIDADE).isoformat()})
    return out


def zip_vigentes(conn, entidade_id: int, na_data: str) -> tuple[str, bytes]:
    e = entidades.detalhe(conn, entidade_id)
    if e is None:
        raise ValueError(f"Entidade {entidade_id} não encontrada")
    nome = re.sub(r'[\\/:*?"<>|]', "-", _nome(e))
    buf, n = io.BytesIO(), 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for chave in TIPOS_ZIP:
            v = certidoes.vigente(conn, entidade_id, tipo_por_chave(conn, chave)["id"], na_data=na_data)
            if v is None or not v["arquivo"].startswith("certidoes/"):
                continue
            caminho = arquivos.caminho_seguro(v["arquivo"])
            if not caminho.is_file():       # gate Sol, achado 11: erro de dominio, nao 500
                raise ValueError(f"O PDF da certidão {ROTULO[chave]} de {_nome(e)} não está na pasta de dados "
                                 f"— anexe de novo")
            z.write(caminho, f"{nome} - {chave.upper()} - {v['validade']}.pdf")
            n += 1
    if n == 0:
        raise ValueError(f"{_nome(e)} não tem nenhuma certidão vigente em {_br(na_data)}")
    return f"Certidoes - {nome} - {na_data}.zip", buf.getvalue()


# --- carga inicial (decisao 13) ---------------------------------------------------------------

class _Ensaio(Exception):
    """Sinal interno: desfaz a transacao do ensaio."""


def importar_pasta(conn, usuario_id: int, pasta: Path, ensaio: bool, hoje: datetime.date | None = None) -> dict:
    hoje_iso = (hoje or tempo.hoje_local()).isoformat()
    rel = {"ensaio": ensaio, "gravadas": [], "repetidas": [], "vencidas": [], "positivas": [], "sem_leitura": []}
    candidatos = []
    for p in sorted(Path(pasta).rglob("*.pdf")):
        nome = str(p.relative_to(pasta))
        if p.stat().st_size > arquivos.TETO_BYTES:       # mesmo teto do upload
            rel["sem_leitura"].append({"arquivo": nome, "motivo": f"maior que {arquivos.TETO_MB} MB"})
            continue
        dados = p.read_bytes()
        try:
            texto = leitura_pdf.texto_de_pdf_com_limite(dados)
        except Exception as e:        # PDF que nao abre ou estoura teto: fila humana
            rel["sem_leitura"].append({"arquivo": nome, "motivo": type(e).__name__})
            continue
        texto, ocr = texto_para_leitura(dados, texto)
        try:
            lido = ler(conn, texto)
        except leitura_certidao.Recusa as e:
            (rel["positivas"] if e.motivo == "positiva" else rel["sem_leitura"]).append(
                {"arquivo": nome, "motivo": e.motivo, **({"ocr": True} if ocr else {})})
            continue
        if lido["validade"] < hoje_iso:
            rel["vencidas"].append({"arquivo": nome, "validade": lido["validade"]})
            continue
        candidatos.append((nome, dados, lido, ocr))
    if not ensaio:     # arquivo em disco ANTES do banco: orfao por hash e' inofensivo, linha sem arquivo nao
        for _, dados, _, _ in candidatos:
            arquivos.gravar_bytes("certidoes", dados, "pdf")
    try:
        with db.mutacao(conn):
            for nome, dados, lido, ocr in candidatos:
                sha = arquivos.sha_de(dados)
                try:
                    cid = gravar_certidao(conn, usuario_id, lido, f"certidoes/{sha}.pdf", sha, Path(nome).name,
                                          "automatica", ocr=ocr)
                except ValueError:
                    rel["repetidas"].append({"arquivo": nome})
                    continue
                rel["gravadas"].append({"arquivo": nome, "id": cid, "entidade": lido["entidade"],
                                        "tipo": lido["tipo"], "validade": lido["validade"],
                                        **({"ocr": True} if ocr else {})})
            if ensaio:
                raise _Ensaio
    except _Ensaio:
        pass
    return rel
