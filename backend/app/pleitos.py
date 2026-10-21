"""Pleitos: oficio de reajuste, pedido de prorrogacao de prazo e comunicacao de conclusao (bloco 7; spec
2026-09-21 §5.2, §7.2 a §7.4).

Mesmo caminho do protocolo (bloco 5), com um documento so': carta gerada -> anexos arrastados -> baixar ->
assinar no DocuSign -> arrastar o assinado (mesma conferencia) -> previa -> enviar. O instrumento que
atende o pleito (apostilamento, aditivo de prazo) e' calculado em `reajuste` e `prazos`, nao gravado aqui.
Pleito enviado antes do sistema entra pelo cadastro (`pleitos_anteriores`, origem 'cadastro').
"""
import datetime
import json
import re
from html import escape

from app import (arquivos, assinatura, auditoria, carta, correio, db, dinheiro, envio_reserva, espelhos,
                 leitura_planilha_reajuste, medicoes, oficios, pdfs, prazos, reajuste, tempo)
from app import html_email

TIPOS = ("reajuste", "prazo", "conclusao")
# Pecas que o orgao pode pedir no pleito de reajuste, alem das da IN (cadastro: `pecas_pleito_reajuste`; issue #50,
# apostilamento do reajuste anual da Prefeitura de Cuiaba). Mesmos valores do CHECK da migracao 037.
PECAS_ORGAO = ("falencia", "contrato_social", "documento_representante", "balanco")
TIPOS_ANEXO = ("planilha_calculo", "cronograma", "outro") + PECAS_ORGAO
# IN 001/2024 art. 21 §1º: o pleito de reajuste leva memoria de calculo e cronograma; o de prazo, o cronograma.
EXIGIDOS = {"reajuste": ("planilha_calculo", "cronograma"), "prazo": ("cronograma",), "conclusao": ()}
ROTULO = {"reajuste": "Pleito de reajuste", "prazo": "Pedido de prorrogação", "conclusao": "Comunicação de conclusão"}
ROTULO_ANEXO = {"planilha_calculo": "Memória de cálculo do reajuste", "cronograma": "Cronograma físico-financeiro",
                "outro": "Outro anexo", "falencia": "Certidão de falência", "contrato_social": "Contrato social",
                "documento_representante": "Documento do representante legal", "balanco": "Balanço patrimonial"}
TIPO_ENVIO = {"reajuste": "pleito_reajuste", "prazo": "carta_prazo", "conclusao": "conclusao"}
CHAVE_TEXTOS = {"reajuste": "pleito_reajuste", "prazo": "prazo", "conclusao": "conclusao"}
MIN_JUSTIFICATIVA = 10
_CHUVA = re.compile(r"\bchuv", re.IGNORECASE)
_MESES = carta.MESES


class RascunhoAberto(ValueError):
    """Ja' ha' pleito do sistema, nem enviado nem descartado, do mesmo contrato, tipo e ciclo (a API devolve 409)."""


def _linha(conn, pleito_id: int) -> dict:
    r = conn.execute("SELECT * FROM pleitos WHERE id=?", (pleito_id,)).fetchone()
    if r is None:
        raise ValueError(f"Pleito {pleito_id} não encontrado")
    return dict(r)


def _contrato(conn, contrato_id: int) -> dict:
    c = conn.execute("SELECT * FROM contratos WHERE id=?", (contrato_id,)).fetchone()
    if c is None:
        raise ValueError(f"Contrato {contrato_id} não encontrado")
    return dict(c)


def _orgao(conn, c: dict) -> tuple[str, dict, dict]:
    if not c.get("orgao_id"):
        raise ValueError("Contrato sem órgão no cadastro: não há para quem mandar o ofício")
    o = conn.execute("SELECT * FROM orgaos WHERE id=?", (c["orgao_id"],)).fetchone()
    return o["familia"], json.loads(o["regras"] or "{}"), dict(o)


def _obra(c: dict) -> str:
    return c.get("nome_curto") or c.get("numero_instrumento") or ""


def _br(iso: str | None) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso else ""


def _editavel(p: dict) -> None:
    if p["situacao"] in ("enviado", "descartado"):
        raise ValueError(f"Pleito {p['situacao']}: não pode ser alterado")


def _anexos_de(conn, pleito_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM pleito_anexos WHERE pleito_id=? AND removido_em IS NULL ORDER BY id", (pleito_id,))]


def _bytes(rel: str) -> bytes:
    return arquivos.caminho_seguro(rel).read_bytes()


def _exigidos(conn, p: dict) -> tuple[str, ...]:
    """Anexos que o pleito cobra: os da IN e, no reajuste, as pecas que o orgao declara no cadastro."""
    if p["tipo"] != "reajuste":
        return EXIGIDOS[p["tipo"]]
    # sem _orgao(): pleito do cadastro pode ser de contrato sem orgao, e o detalhe nao pode quebrar por isso
    o = conn.execute("SELECT o.regras FROM contratos c JOIN orgaos o ON o.id=c.orgao_id WHERE c.id=?",
                     (p["contrato_id"],)).fetchone()
    regras = json.loads(o["regras"] or "{}") if o else {}
    return EXIGIDOS["reajuste"] + tuple(t for t in (regras.get("pecas_pleito_reajuste") or []) if t in PECAS_ORGAO)


def _medicao_final(conn, contrato_id: int) -> dict | None:
    r = conn.execute("SELECT * FROM medicoes WHERE contrato_id=? AND final=1 ORDER BY final_em DESC, id DESC LIMIT 1",
                     (contrato_id,)).fetchone()
    return dict(r) if r else None


# --- criar e anexos --------------------------------------------------------------------------------

def criar(conn, usuario_id: int, contrato_id: int, tipo: str, numero_oficio: str, data_base_mes: str | None = None,
          dias: int | None = None, justificativa: str | None = None, hoje: datetime.date | None = None) -> int:
    hoje = hoje or tempo.hoje_local()
    if tipo not in TIPOS:
        raise ValueError(f"Tipo de pleito inválido: {tipo!r}")
    c = _contrato(conn, contrato_id)
    _orgao(conn, c)
    sigla = conn.execute("SELECT sigla_oficio FROM entidades WHERE id=?",
                         (c["entidade_id"],)).fetchone()["sigla_oficio"] if c.get("entidade_id") else "LT"
    canon = oficios.canonico(numero_oficio or "", sigla, hoje.year)
    ciclo = None
    justificativa = (justificativa or "").strip() or None
    if tipo == "reajuste":
        ciclos = {k["data_base_mes"]: k for k in reajuste.ciclos(conn, contrato_id, hoje)}
        if data_base_mes is None and len(ciclos) == 1:
            data_base_mes = next(iter(ciclos))
        if data_base_mes not in ciclos:
            raise ValueError(f"Data-base {data_base_mes!r} não é do contrato (ou o contrato não tem reajuste)")
        ciclo = ciclos[data_base_mes]["ciclo"]
        dias = None
    elif tipo == "prazo":
        if not isinstance(dias, int) or dias <= 0:
            raise ValueError("Informe quantos dias de prorrogação pedir")
        if not justificativa:
            raise ValueError("Informe a justificativa do pedido de prazo")
        data_base_mes = None
    else:
        if not c.get("encerramento_iniciado_em"):
            raise ValueError("Comunicação de conclusão só para contrato em encerramento (marque a medição final)")
        data_base_mes, dias = None, None
    with db.mutacao(conn):
        # dentro do BEGIN IMMEDIATE: dois cliques simultaneos nao abrem dois oficios do mesmo ciclo (issue #9)
        aberto = conn.execute("SELECT numero_oficio FROM pleitos WHERE contrato_id=? AND tipo=? AND origem='sistema' "
                              "AND data_base_mes IS ? AND ciclo IS ? AND situacao NOT IN ('enviado','descartado') "
                              "LIMIT 1", (contrato_id, tipo, data_base_mes, ciclo)).fetchone()
        if aberto:
            onde = "para este ciclo" if ciclo else "deste tipo"
            raise RascunhoAberto(f"Já há um pleito em aberto {onde} ({ROTULO[tipo].lower()} "
                                 f"{aberto['numero_oficio'] or 'sem número'}): continue nele ou descarte-o antes "
                                 "de criar outro")
        pid = conn.execute("INSERT INTO pleitos (contrato_id, tipo, data_base_mes, ciclo, dias, justificativa, "
                           "numero_oficio, usuario_id) VALUES (?,?,?,?,?,?,?,?)",
                           (contrato_id, tipo, data_base_mes, ciclo, dias, justificativa, canon, usuario_id)).lastrowid
        auditoria.registrar(conn, usuario_id, "pleito.criar", "pleito", pid, None,
                            {"tipo": tipo, "numero_oficio": canon, "data_base_mes": data_base_mes, "ciclo": ciclo,
                             "dias": dias})
    return pid


def adicionar_anexo(conn, usuario_id: int, pleito_id: int, tipo: str, nome: str, dados: bytes, ext: str) -> int:
    if tipo not in TIPOS_ANEXO:
        raise ValueError(f"Tipo de anexo inválido: {tipo!r}")
    if ext not in ("pdf", "xlsx"):
        raise ValueError("O anexo é um PDF ou uma planilha .xlsx")
    p = _linha(conn, pleito_id)
    _editavel(p)
    rel, sha = arquivos.gravar_bytes("pleitos", dados, ext)
    with db.mutacao(conn):
        aid = conn.execute("INSERT INTO pleito_anexos (pleito_id, tipo, nome, arquivo, sha256, tamanho, ext) "
                           "VALUES (?,?,?,?,?,?,?)", (pleito_id, tipo, nome, rel, sha, len(dados), ext)).lastrowid
        auditoria.registrar(conn, usuario_id, "pleito.anexo", "pleito", pleito_id, None,
                            {"anexo_id": aid, "tipo": tipo, "nome": nome, "sha256": sha})
    return aid


def remover_anexo(conn, usuario_id: int, pleito_id: int, anexo_id: int) -> None:
    p = _linha(conn, pleito_id)
    _editavel(p)
    with db.mutacao(conn):
        n = conn.execute("UPDATE pleito_anexos SET removido_em=datetime('now') "
                         "WHERE id=? AND pleito_id=? AND removido_em IS NULL", (anexo_id, pleito_id)).rowcount
        if n != 1:
            raise ValueError("Anexo não encontrado")
        auditoria.registrar(conn, usuario_id, "pleito.anexo_removido", "pleito", pleito_id, None, {"anexo_id": anexo_id})


# --- previsao de reajuste (issue #272; spec 2026-10-20 §2.2) -----------------------------------------

ORIGENS_PREVISAO = ("pleito", "manual")      # o apostilamento entra pelo cadastro, nunca por aqui
MAX_COMPETENCIAS = leitura_planilha_reajuste.MAX_COMPETENCIAS
_COMPETENCIA = re.compile(r"[0-9]{4}-(0[1-9]|1[0-2])")


def gravar_previsao(conn, usuario_id: int, pleito_id: int, origem: str, linhas: list[dict]) -> int:
    """Grava a previsao conferida do pleito: uma linha de `reajuste_previsoes` por competencia (evento; aceitar de
    novo grava outra leva e a leitura escolhe a mais recente). `origem` 'pleito' quando veio da planilha lida e
    conferida sem mudar; 'manual' quando a pessoa digitou (planilha fora do modelo). Devolve quantas gravou.

    Como nada se apaga, duas guardas mantem a leitura (`reajuste.previsoes_vigentes`) igual ao que a pessoa viu:
    a leva nova do mesmo pleito traz todas as competencias das anteriores (senao a que saiu continuaria valendo), e
    a digitada nao vem depois da lida (a do pleito e' mais forte e a digitada nunca valeria)."""
    if origem not in ORIGENS_PREVISAO:
        raise ValueError("Origem da previsão inválida")
    p = _linha(conn, pleito_id)
    if p["tipo"] != "reajuste":
        raise ValueError("Previsão de reajuste só no pleito de reajuste")
    if p["situacao"] in ("descartado", "enviado"):
        raise ValueError(f"Pleito {p['situacao']}: a previsão não pode ser gravada (correção é pleito novo)")
    if not p["data_base_mes"] or not p["ciclo"]:
        raise ValueError("Pleito sem data-base e ciclo: a previsão não tem a que se ligar")
    if not linhas:
        raise ValueError("Informe ao menos uma competência com o valor previsto")
    if len(linhas) > MAX_COMPETENCIAS:
        raise ValueError(f"No máximo {MAX_COMPETENCIAS} competências por previsão")
    vistas: set[str] = set()
    for x in linhas:
        comp, valor = x.get("competencia"), x.get("valor_centavos")
        if not isinstance(comp, str) or not _COMPETENCIA.fullmatch(comp):
            raise ValueError("Competência inválida: use mês e ano")
        if comp in vistas:
            raise ValueError(f"A competência {comp[5:]}/{comp[:4]} aparece duas vezes")
        vistas.add(comp)
        # bool e' int no Python: True nao e' um centavo
        if not isinstance(valor, int) or isinstance(valor, bool) or abs(valor) > dinheiro.TETO_CENTAVOS:
            raise ValueError(f"Valor previsto inválido em {comp[5:]}/{comp[:4]}")
    ordenadas = sorted(linhas, key=lambda x: x["competencia"])
    with db.mutacao(conn):
        # dentro do BEGIN IMMEDIATE: a leva anterior lida aqui e' a que vale na hora de gravar
        anteriores = conn.execute("SELECT competencia, origem FROM reajuste_previsoes WHERE pleito_id=?",
                                  (pleito_id,)).fetchall()
        if origem == "manual" and any(r["origem"] == "pleito" for r in anteriores):
            raise ValueError("Este pleito já tem a previsão lida da planilha; para corrigir, anexe a planilha "
                             "corrigida")
        faltam = sorted({r["competencia"] for r in anteriores} - vistas)
        if faltam:
            lista = ", ".join(f"{c[5:]}/{c[:4]}" for c in faltam)
            raise ValueError(f"A previsão nova não traz {lista}, que a anterior deste pleito tinha; inclua a "
                             "competência ou reemita o pleito")
        for x in ordenadas:
            conn.execute("INSERT INTO reajuste_previsoes (contrato_id, data_base_mes, ciclo, competencia, "
                         "valor_previsto_centavos, origem, pleito_id, usuario_id) VALUES (?,?,?,?,?,?,?,?)",
                         (p["contrato_id"], p["data_base_mes"], p["ciclo"], x["competencia"], x["valor_centavos"],
                          origem, pleito_id, usuario_id))
        auditoria.registrar(conn, usuario_id, "pleito.previsao", "pleito", pleito_id, None,
                            {"origem": origem, "data_base_mes": p["data_base_mes"], "ciclo": p["ciclo"],
                             "competencias": {x["competencia"]: x["valor_centavos"] for x in ordenadas}})
    return len(ordenadas)


# --- carta -----------------------------------------------------------------------------------------

def _textos(conn, p: dict) -> dict:
    t = carta.config(conn).get(CHAVE_TEXTOS[p["tipo"]])
    if not t:
        raise ValueError(f"Textos de {CHAVE_TEXTOS[p['tipo']]} não carregados: rode `cadastro aplicar`")
    return t


def _campos(conn, p: dict, c: dict, hoje: datetime.date) -> dict:
    em = carta.emitente(conn, c["entidade_id"]) if c.get("entidade_id") else {}
    campos = {"razao_social": em.get("razao_social", ""), "cnpj": em.get("cnpj", ""), "oficio": p["numero_oficio"] or "",
              "obra": _obra(c), "instrumento": c.get("numero_instrumento") or "",
              "objeto": carta.objeto_na_frase(carta.objeto_do_contrato(c)),
              "municipio": c.get("municipio") or "Cuiabá",
              "saudacao": espelhos.saudacao()}
    if p["tipo"] == "reajuste" and p["data_base_mes"]:
        b = conn.execute("SELECT indice FROM contrato_datas_base WHERE contrato_id=? AND mes=?",
                         (c["id"], p["data_base_mes"])).fetchone()
        aniv = reajuste.aniversario(p["data_base_mes"], p["ciclo"])
        mes = _MESES[aniv.month - 1].upper()
        campos |= {"data_base": f"{p['data_base_mes'][5:7]}/{p['data_base_mes'][:4]}",
                   "data_base_extenso": f"{mes}/{p['data_base_mes'][:4]}",      # "MARÇO/2023", como no CT-122
                   "indice": (b["indice"] if b else None) or "índice do contrato",
                   "mes_aniversario": mes, "aniversario": aniv.strftime("%d/%m/%Y")}
    elif p["tipo"] == "prazo":
        fim = prazos.situacao(conn, c["id"], hoje)["execucao_fim"]
        novo = (datetime.date.fromisoformat(fim) + datetime.timedelta(days=p["dias"])).isoformat() if fim else None
        campos |= {"historico": prazos.historico_texto(conn, c["id"]), "justificativa": p["justificativa"] or "",
                   "dias": str(p["dias"]), "fim_execucao": _br(fim), "novo_fim_execucao": _br(novo)}
    elif p["tipo"] == "conclusao":
        m = _medicao_final(conn, c["id"])
        campos |= {"medicao_final": medicoes.titulo(m) if m else "medição final",
                   "data_final": _br(m["final_em"]) if m and m.get("final_em") else ""}
    return campos


def _texto(conn, p: dict, c: dict, chave: str) -> str:
    """Texto do tipo; `<chave>_<familia>` vence o comum (o pleito de reajuste da SINFRA cita a IN 001/2024)."""
    textos = _textos(conn, p)
    return textos.get(f"{chave}_{_orgao(conn, c)[0]}") or textos[chave]


def corpo_padrao(conn, pleito_id: int, hoje: datetime.date | None = None) -> str:
    hoje = hoje or tempo.hoje_local()
    p = _linha(conn, pleito_id)
    c = _contrato(conn, p["contrato_id"])
    return carta.preencher(_texto(conn, p, c, "carta_corpo"), _campos(conn, p, c, hoje)).strip()


def _carta(conn, p: dict, corpo: str, hoje: datetime.date) -> carta.Carta:
    c = _contrato(conn, p["contrato_id"])
    familia, regras, o = _orgao(conn, c)
    cfg = carta.config(conn)
    campos = _campos(conn, p, c, hoje)
    f = carta.fiscal_vigente(conn, c["id"], hoje.isoformat())
    ac = []
    if f:
        ac.append(f"A/C: {f['nome'] or f['email']}")
        ac += [x for x in (f.get("cargo"), f.get("portaria")) if x]
    vocativo = {"Senhor": "Prezado Senhor,", "Senhora": "Prezada Senhora,"}.get((f or {}).get("tratamento"),
                                                                              "Prezados Senhores,")
    objeto = carta.objeto_do_contrato(c)
    ref =f"Ref.: Contrato n.º {campos['instrumento']}" + (f" – {objeto}" if objeto else "")
    fam = (cfg.get("familias") or {}).get(familia) or {}
    local = carta.preencher(fam.get("local") or "Cuiabá/MT", campos)
    return carta.Carta(numero=oficios.na_carta(p["numero_oficio"]), local_data=f"{local}, {carta.data_extenso(hoje)}.",
                       destinatario=regras.get("carta_destinatario") or [o["nome"]], ac=ac, referencia=ref,
                       assunto=carta.preencher(_texto(conn, p, c, "carta_assunto"), campos), vocativo=vocativo,
                       corpo=corpo, assinatura=fam.get("assinatura") or cfg.get("signatario") or [],
                       emitente=carta.emitente(conn, c["entidade_id"]) if c.get("entidade_id") else {})


def nome_documento(conn, p: dict) -> str:
    c = _contrato(conn, p["contrato_id"])
    return f"{p['numero_oficio']} - {_obra(c)} - {ROTULO[p['tipo']]}.pdf"


def montar(conn, usuario_id: int, pleito_id: int, corpo: str | None = None, hoje: datetime.date | None = None) -> dict:
    hoje = hoje or tempo.hoje_local()
    p = _linha(conn, pleito_id)
    _editavel(p)
    corpo = (corpo or "").strip() or p["corpo_carta"] or corpo_padrao(conn, pleito_id, hoje)
    pdf = carta.gerar(_carta(conn, p, corpo, hoje))           # PDF gerado pelo sistema: um documento so'
    n = pdfs.paginas(pdf)
    rel, sha = arquivos.gravar_bytes("pleitos", pdf, "pdf")
    with db.mutacao(conn):
        conn.execute("UPDATE pleitos SET corpo_carta=?, montado_arquivo=?, montado_sha256=?, montado_paginas=?, "
                     "assinado_arquivo=NULL, assinado_sha256=NULL, conferencia=NULL, situacao='montado' WHERE id=?",
                     (corpo, rel, sha, n, pleito_id))
        auditoria.registrar(conn, usuario_id, "pleito.montar", "pleito", pleito_id, None,
                            {"sha256": sha, "paginas": n, "tamanho": len(pdf)})
    return {"arquivo": rel, "sha256": sha, "paginas": n, "tamanho": len(pdf), "nome": nome_documento(conn, p)}


def receber_assinado(conn, usuario_id: int, pleito_id: int, pdf: bytes) -> dict:
    p = _linha(conn, pleito_id)
    _editavel(p)
    if not p["montado_arquivo"]:
        raise ValueError("Monte a carta antes de anexar o assinado")
    conf = assinatura.conferir_pdfs(_bytes(p["montado_arquivo"]), pdf)
    rel, sha = arquivos.gravar_bytes("pleitos", pdf, "pdf")
    with db.mutacao(conn):
        conn.execute("UPDATE pleitos SET assinado_arquivo=?, assinado_sha256=?, conferencia=?, situacao='assinado' "
                     "WHERE id=?", (rel, sha, json.dumps(conf), pleito_id))
        auditoria.registrar(conn, usuario_id, "pleito.assinado", "pleito", pleito_id, None,
                            {"sha256": sha, "conferencia": conf})
    return detalhe(conn, pleito_id)


# --- pendencias, detalhe e lista -------------------------------------------------------------------

def pendencias(conn, p: dict, hoje: datetime.date) -> list[dict]:
    if p["origem"] == "cadastro":
        return []
    out = []
    presentes = {a["tipo"] for a in _anexos_de(conn, p["id"])}
    for t in _exigidos(conn, p):
        if t not in presentes:
            out.append({"codigo": "anexo", "mensagem": f"{ROTULO_ANEXO[t]}: não anexado"})
    if p["tipo"] == "prazo" and _CHUVA.search(p["justificativa"] or "") and not conn.execute(
            "SELECT 1 FROM instrumentos WHERE contrato_id=? AND tipo='paralisacao' LIMIT 1", (p["contrato_id"],)).fetchone():
        out.append({"codigo": "chuva", "mensagem": "O contrato veda alegar só chuva; cite a ordem de paralisação do órgão"})
    if p["situacao"] == "rascunho":
        out.append({"codigo": "nao_montado", "mensagem": "Carta ainda não montada"})
    elif not p["assinado_arquivo"]:
        out.append({"codigo": "nao_assinado", "mensagem": "Carta ainda não assinada"})
    else:
        for a in (json.loads(p["conferencia"] or "{}").get("avisos") or []):
            out.append({"codigo": "conferencia", "mensagem": a["mensagem"]})
    repetido = oficios.usos(conn, p["numero_oficio"], ignorar=("pleito", p["id"])) if p["numero_oficio"] else []
    if repetido:
        out.append({"codigo": "oficio_repetido", "mensagem": f"Ofício {p['numero_oficio']} já usado em {', '.join(repetido)}"})
    return out


def detalhe(conn, pleito_id: int, hoje: datetime.date | None = None) -> dict:
    hoje = hoje or tempo.hoje_local()
    p = _linha(conn, pleito_id)
    return {**p, "rotulo": ROTULO[p["tipo"]], "anexos": _anexos_de(conn, pleito_id),
            "exigidos": [{"tipo": t, "rotulo": ROTULO_ANEXO[t]} for t in _exigidos(conn, p)],
            "conferencia": json.loads(p["conferencia"] or "null"), "pendencias": pendencias(conn, p, hoje),
            "nome_documento": nome_documento(conn, p) if p["montado_arquivo"] else None}


def listar(conn, contrato_id: int, tipos: tuple[str, ...] | None = None) -> list[dict]:
    sql, args = "SELECT id FROM pleitos WHERE contrato_id=? AND situacao<>'descartado'", [contrato_id]
    if tipos:
        sql += f" AND tipo IN ({','.join('?' * len(tipos))})"
        args += list(tipos)
    return [detalhe(conn, r[0]) for r in conn.execute(sql + " ORDER BY COALESCE(enviado_em, criado_em) DESC, id DESC",
                                                       args)]


# --- previa e envio --------------------------------------------------------------------------------

def _destinatarios(conn, regras: dict, c: dict, hoje: datetime.date) -> tuple[list, list]:
    para = [str(x).lower() for x in (regras.get("protocolo_para") or [])]
    f = carta.fiscal_vigente(conn, c["id"], hoje.isoformat())
    if f and f["email"] and f["email"] not in para:
        para.append(f["email"])
    para += [x for x in json.loads(c.get("destinatarios_extras") or "[]") if x not in para]
    copia = [str(x).lower() for x in (regras.get("protocolo_copia") or [])]
    copia = list(dict.fromkeys(copia + json.loads(c.get("copia_extras") or "[]")))     # a da obra (14/10/2026)
    return para, [x for x in copia if x not in para]


def _anexos_envio(conn, p: dict) -> list[tuple[str, bytes]]:
    out = []
    if p["assinado_arquivo"] or p["montado_arquivo"]:
        out.append((nome_documento(conn, p), _bytes(p["assinado_arquivo"] or p["montado_arquivo"])))
    out += [(a["nome"], _bytes(a["arquivo"])) for a in _anexos_de(conn, p["id"])]
    return out


def previa_envio(conn, pleito_id: int, remetente: str | None = None, hoje: datetime.date | None = None) -> dict:
    hoje = hoje or tempo.hoje_local()
    p = _linha(conn, pleito_id)
    c = _contrato(conn, p["contrato_id"])
    _, regras, _ = _orgao(conn, c)
    textos, campos = _textos(conn, p), _campos(conn, p, c, hoje)
    para, copia = _destinatarios(conn, regras, c, hoje)
    if remetente:       # o e-mail de login e a conta do Outlook (podem ser diferentes), como no protocolo
        fora = {remetente.lower()} | correio.contas_do_usuario(conn, remetente)
        copia = [x for x in copia if x.lower() not in fora]
    anexos = _anexos_envio(conn, p)
    total = sum(len(b) for _, b in anexos)
    pend = pendencias(conn, p, hoje)
    if total > correio.MAX_TOTAL:
        pend.append({"codigo": "tamanho", "mensagem": f"Anexos somam {total // (1024 * 1024)} MB, acima do limite "
                                                      f"do e-mail ({correio.MAX_TOTAL // (1024 * 1024)} MB)"})
    return {"para": para, "copia": copia, "assunto": carta.preencher(textos.get("email_assunto", ""), campos),
            "corpo": carta.preencher(textos.get("email_corpo", ""), campos).strip(),
            "anexos": [{"nome": n, "tamanho": len(b)} for n, b in anexos], "total": total,
            "limite": correio.MAX_TOTAL, "pendencias": pend}


def _html(corpo: str) -> str:
    if html_email.eh_html(corpo):           # corpo formatado no editor (issue #191): so' a lista fechada passa
        return html_email.sanitizar(corpo)
    return "".join(f"<p>{escape(par).replace(chr(10), '<br>')}</p>" for par in corpo.strip().split("\n\n"))


def enviar(conn, usuario: dict, pleito_id: int, para: list[str], copia: list[str], assunto: str, corpo: str,
           justificativa: str | None = None, hoje: datetime.date | None = None, cco: list[str] | None = None) -> int:
    hoje = hoje or tempo.hoje_local()
    p = _linha(conn, pleito_id)
    # Tudo o que recusa vem ANTES do e-mail (que nao se desfaz).
    if p["situacao"] in ("enviado", "descartado"):
        raise ValueError(f"Pleito já {p['situacao']}")
    if not p["montado_arquivo"]:
        raise ValueError("Monte a carta antes de enviar")
    pv = previa_envio(conn, pleito_id, hoje=hoje)
    para = [x.strip() for x in para if x.strip()]
    if not para:
        raise ValueError("Informe ao menos um destinatário")
    if pv["total"] > correio.MAX_TOTAL:
        raise ValueError("Anexos acima do limite do e-mail")
    justificativa = (justificativa or "").strip() or None
    if pv["pendencias"] and len(justificativa or "") < MIN_JUSTIFICATIVA:
        raise ValueError(f"{len(pv['pendencias'])} pendência(s) na prévia: informe a justificativa "
                         f"(ao menos {MIN_JUSTIFICATIVA} caracteres) para enviar assim")
    # Reserva atomica antes do e-mail (10/10/2026): dois cliques simultaneos nao mandam duas cartas ao orgao.
    envio_reserva.reservar(conn, "pleitos", pleito_id, usuario["id"], p["envio_id"])
    # descartado entre a leitura acima e a reserva (outra aba): nada sai (com a reserva, `descartar` ja' recusa)
    if _linha(conn, pleito_id)["situacao"] == "descartado":
        envio_reserva.liberar_com_retentativa(conn, "pleitos", pleito_id)
        raise ValueError("Pleito descartado enquanto se preparava o envio: nada foi enviado")
    try:
        envio_id = correio.enviar_e_registrar(conn, usuario, TIPO_ENVIO[p["tipo"]], para,
                                              [x.strip() for x in copia if x.strip()], assunto, _html(corpo),
                                              _anexos_envio(conn, p), cco=cco)
    except correio.EnvioNaoRegistrado:
        raise                                       # o e-mail saiu: a reserva fica e segura a repeticao
    except Exception:
        envio_reserva.liberar_com_retentativa(conn, "pleitos", pleito_id)      # nada saiu: destrava e sobe o erro
        raise
    # O e-mail ja' saiu: o registro abaixo nao recusa nada.
    with correio.depois_do_envio(assunto, para, envio_id), db.mutacao(conn):
        envio_reserva.liberar(conn, "pleitos", pleito_id)
        conn.execute("UPDATE pleitos SET situacao='enviado', enviado_em=?, envio_id=?, envio_justificativa=? WHERE id=?",
                     (hoje.isoformat(), envio_id, justificativa, pleito_id))
        auditoria.registrar(conn, usuario["id"], "pleito.enviar", "pleito", pleito_id, None,
                            {"envio_id": envio_id, "pendencias": pv["pendencias"], "justificativa": justificativa})
    return envio_id


def descartar(conn, usuario_id: int, pleito_id: int, motivo: str) -> None:
    p = _linha(conn, pleito_id)
    if p["situacao"] == "enviado":
        raise ValueError("Pleito enviado não se descarta")
    if not (motivo or "").strip():
        raise ValueError("Informe o motivo")
    with db.mutacao(conn):
        # envio reservado = e-mail saindo, ou que saiu sem registro: descartar liberaria outro oficio do ciclo
        if not conn.execute("UPDATE pleitos SET situacao='descartado' WHERE id=? AND situacao<>'enviado' "
                            "AND envio_reservado_em IS NULL", (pleito_id,)).rowcount:
            agora = _linha(conn, pleito_id)
            if agora["situacao"] == "enviado":
                raise ValueError("Pleito enviado não se descarta")
            # a mesma recusa do envio (409 ENVIO_RESERVADO): a tela oferece ali mesmo a liberacao
            raise envio_reserva.reservado(conn, agora["envio_reservado_em"], agora["envio_reservado_por"])
        auditoria.registrar(conn, usuario_id, "pleito.descartar", "pleito", pleito_id,
                            {"situacao": p["situacao"]}, {"situacao": "descartado", "motivo": motivo.strip()})
