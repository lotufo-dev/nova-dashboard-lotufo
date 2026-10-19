"""Notas a enviar ao contratante (plano 2026-10-09; mapeamento 2026-10-08 §3, §5, §6a).

Nota emitida -> envio da nota ao orgao (pelo sistema, sobre `protocolo` etapa `nota`/`unico`, ou registrado
como feito por fora) -> aguardando pagamento (= `protocolada`). Um ENVIO e' um e-mail: na SINFRA e na Pref. VG
medicao e reajuste da mesma competencia vao juntos (D9); na MTPAR e na SES, um por medicao.
"""
import datetime
import json
import logging
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime

from app import arquivos, auditoria, certidoes, db, documentos, frc, medicoes, notas, oficios, protocolo, tempo

log = logging.getLogger(__name__)

SUB_SINFRA = {"sinfra-sagpm": "SAGPM", "sinfra-suef1": "SUEF I", "sinfra-suef2": "SUEF II", "sinfra-supu": "SUPU",
              "sinfra-sacid": "SACID"}
AVISO_DIAS = 15                    # D8: certidao a menos de 15 dias = aviso
NATUREZA = {"execucao": "medição", "reajuste": "reajuste", "projeto": "projeto"}
TETO_EML = 25 * 1024 * 1024
# A-11 (testes de quebra 10/10/2026): um PNG renomeado para .eml virou evidencia e protocolou. Sinais de que nao e' e-mail.
BINARIOS = (b"%PDF-", b"\x89PNG", b"PK\x03\x04", b"\xff\xd8\xff")
NAO_E_EML = ("O arquivo não é um e-mail salvo (.eml): na caixa de Enviados do Outlook, arraste o e-mail para uma "
             "pasta do computador e anexe o arquivo .eml gerado")
_PIOR = {"ok": 0, "aviso": 1, "falta": 2, "vencida": 3}
# Issue #188 (opcao A, decisao de 15/10/2026): execucao e reajuste do mesmo numero e competencia sao as duas metades
# de um envio onde o orgao junta. A espera fica na tela e no envio; o estado de cada medicao nao muda.
OUTRO = {"execucao": "reajuste", "reajuste": "execucao"}
COMPLETAS = ("nota_emitida", "protocolada", "nf_emitida", "recebida")
LIBERACAO = "notas.envio_sem_a_outra_metade"


def _grupo(familia: str, o: dict) -> str:
    return {"sinfra": "SINFRA", "mtpar": "MTPAR", "ses": "SES-MT"}.get(familia) or \
        {"pref-vg": "Pref. VG", "pref-cuiaba": "Pref. Cuiabá"}.get(o["chave"], o["nome"])


def _etapa(familia: str) -> str:
    return "nota" if familia == "sinfra" else "unico"


def _br(iso: str, fmt: str = "%d/%m/%Y") -> str:
    return datetime.date.fromisoformat(iso[:10]).strftime(fmt)


def _ativos(conn, etapa: str, medicao_id: int) -> list[dict]:
    """Protocolos de envio da nota ainda nao enviados nem descartados que contem a medicao."""
    return [dict(r) for r in conn.execute(
        "SELECT p.* FROM protocolo_medicoes pm JOIN protocolos p ON p.id=pm.protocolo_id WHERE pm.medicao_id=? "
        "AND p.etapa=? AND p.situacao NOT IN ('descartado','enviado') ORDER BY p.id DESC", (medicao_id, etapa))]


def _descricao(ms: list[dict]) -> str:
    if len(ms) == 2 and {m["tipo"] for m in ms} == {"execucao", "reajuste"} and len({m["numero"] for m in ms}) == 1:
        return f"{ms[0]['numero']}ª medição + reajuste"
    return " + ".join(medicoes.titulo(m).replace("Medição", "medição") for m in ms)


# --- medicao e reajuste: a outra metade (issue #188) -----------------------------------------------

def _outras_metades(conn, m) -> list[dict]:
    """Mesmo contrato, numero e competencia, o outro tipo do par execucao x reajuste (projeto e' outra serie)."""
    if m["tipo"] not in OUTRO:
        return []
    return [dict(r) for r in conn.execute(
        "SELECT * FROM medicoes WHERE contrato_id=? AND numero=? AND competencia=? AND tipo=? ORDER BY id",
        (m["contrato_id"], m["numero"], m["competencia"], OUTRO[m["tipo"]]))]


def _junta(conn, c: dict) -> tuple[bool, str | None]:
    """(o orgao junta medicao e reajuste no mesmo e-mail, o nome curto do orgao)."""
    if not c.get("orgao_id"):
        return False, None
    familia, regras, o = protocolo._orgao(conn, c)
    return protocolo.junta_naturezas(regras, o, protocolo._etapa(familia, _etapa(familia))), _grupo(familia, o)


def liberacao(conn, medicao_id: int) -> dict | None:
    """A saida de emergencia registrada na auditoria (quem, quando, por que), ou None."""
    r = conn.execute("SELECT a.depois, a.criado_em, u.nome FROM audit_log a LEFT JOIN usuarios u ON u.id=a.usuario_id "
                     "WHERE a.entidade='medicao' AND a.entidade_id=? AND a.acao=? ORDER BY a.id DESC LIMIT 1",
                     (str(medicao_id), LIBERACAO)).fetchone()
    if r is None:
        return None
    depois = json.loads(r["depois"] or "{}")
    return {"justificativa": depois.get("justificativa"), "em": r["criado_em"], "por": r["nome"]}


def espera(conn, m, c: dict | None = None) -> dict | None:
    """Onde o orgao junta (SINFRA, Pref. VG): a outra metade ainda sem as notas segura o envio desta. Cancelada,
    desistida ou ja' enviada nao segura; a saida de emergencia (`liberar_sem_a_outra`) solta."""
    outras = [x for x in _outras_metades(conn, m) if x["estado"] in protocolo.SEM_NOTA]
    if not outras:
        return None
    junta, _ = _junta(conn, c or protocolo._contrato(conn, m["contrato_id"]))
    if not junta or liberacao(conn, m["id"]):
        return None
    x = outras[0]
    return {"medicao_id": x["id"], "titulo": medicoes.titulo(x), "tipo": x["tipo"],
            "texto": "esperando as notas do reajuste" if x["tipo"] == "reajuste" else "esperando as notas da medição"}


def recusar_se_espera(conn, m, c: dict | None = None) -> None:
    c = c or protocolo._contrato(conn, m["contrato_id"])
    e = espera(conn, m, c)
    if e:
        sem = "Enviar a medição sem o reajuste…" if m["tipo"] == "execucao" else "Enviar o reajuste sem a medição…"
        raise ValueError(f"{medicoes.titulo(m)} está {e['texto']}: na {_junta(conn, c)[1]} a medição e o reajuste vão "
                         f"no mesmo e-mail. Anexe as notas do {e['titulo']} ou use “{sem}” na página da medição")


def par(conn, medicao_id: int) -> dict:
    """Pagina da medicao: as duas metades (execucao primeiro), com as notas esperadas, o que falta, a espera e a
    liberacao de cada uma. Sem a outra metade (ou com uma das duas encerrada por excecao), `metades` vem vazia."""
    m = conn.execute("SELECT * FROM medicoes WHERE id=?", (medicao_id,)).fetchone()
    if m is None:
        raise ValueError("Medição não encontrada")
    m = dict(m)
    c = protocolo._contrato(conn, m["contrato_id"])
    junta, orgao = _junta(conn, c)
    outras = [x for x in _outras_metades(conn, m) if x["estado"] not in ("cancelada", "desistida")]
    if m["estado"] in ("cancelada", "desistida") or not outras:
        return {"junta": junta, "orgao": orgao, "metades": []}
    metades = []
    for x in sorted([m, outras[0]], key=lambda y: y["tipo"] != "execucao"):
        metades.append({"medicao_id": x["id"], "tipo": x["tipo"], "titulo": medicoes.titulo(x), "estado": x["estado"],
                        "esperadas": notas.esperadas(conn, x["id"]), "faltam": notas.faltam(conn, x["id"]),
                        "completa": x["estado"] in COMPLETAS,
                        "espera": espera(conn, x, c) if x["estado"] == "nota_emitida" else None,
                        "liberacao": liberacao(conn, x["id"])})
    return {"junta": junta, "orgao": orgao, "metades": metades}


def liberar_sem_a_outra(conn, usuario_id: int, medicao_id: int, justificativa: str) -> None:
    """Saida de emergencia: a metade pronta segue sozinha e a outra vai depois, num envio proprio. Justificativa
    obrigatoria, gravada na auditoria (e dali na linha do tempo)."""
    j = (justificativa or "").strip()
    if len(j) < protocolo.MIN_JUSTIFICATIVA:
        raise ValueError(f"Informe a justificativa (ao menos {protocolo.MIN_JUSTIFICATIVA} caracteres)")
    with db.mutacao(conn):           # confere e grava sob o lock: dois cliques nao registram duas liberacoes
        m = conn.execute("SELECT * FROM medicoes WHERE id=?", (medicao_id,)).fetchone()
        if m is None:
            raise ValueError("Medição não encontrada")
        if m["estado"] != "nota_emitida":
            raise ValueError(f"{medicoes.titulo(m)} não está com a nota emitida (está "
                             f"{medicoes.ROTULO_ESTADO.get(m['estado'], m['estado'])})")
        e = espera(conn, m)
        if e is None:
            raise ValueError(f"{medicoes.titulo(m)} não está esperando a outra metade: o envio já está liberado")
        auditoria.registrar(conn, usuario_id, LIBERACAO, "medicao", m["id"], None,
                            {"justificativa": j, "outra_medicao_id": e["medicao_id"]})


# --- itens do envio --------------------------------------------------------------------------------

def _itens(conn, c: dict, familia: str, ms: list[dict], hoje: datetime.date) -> tuple[list[dict], list[dict], list[str]]:
    """(itens, notas, avisos curtos). Estados: ok | aviso (<15 dias) | falta (justifica) | vencida (bloqueia)."""
    e = protocolo._etapa(familia, _etapa(familia))
    ids = [m["id"] for m in ms]
    docs = [dict(r) for r in conn.execute(
        f"SELECT id, medicao_id, tipo_doc, nome, numero_nf, municipio, consorciada FROM medicao_documentos "
        f"WHERE medicao_id IN ({','.join('?' * len(ids))}) AND tipo_doc IN ('nfs','nf','fatura') "
        f"AND arquivo IS NOT NULL ORDER BY tipo_doc='fatura', id", ids)]
    tipo_de = {m["id"]: m["tipo"] for m in ms}
    nfs = [d for d in docs if d["tipo_doc"] != "fatura"]
    notas = [{"numero": d["numero_nf"], "natureza": tipo_de[d["medicao_id"]], "municipio": d["municipio"],
              "arquivo": d["nome"], "consorciada": d["consorciada"], "medicao_id": d["medicao_id"],
              "valor_centavos": None} for d in nfs]
    itens, curtos = [], []
    sem_nota = [m for m in ms if not any(d["medicao_id"] == m["id"] for d in nfs)]
    por_natureza = {}
    for d in nfs:
        por_natureza.setdefault(NATUREZA[tipo_de[d["medicao_id"]]], []).append(d["numero_nf"] or d["nome"])
    detalhe = " · ".join(f"NFS {', '.join(v)} ({k})" for k, v in por_natureza.items())
    if sem_nota:
        detalhe = "; ".join(x for x in (detalhe, "Falta a nota: " + ", ".join(medicoes.titulo(m) for m in sem_nota))
                            if x)
        curtos.append("Falta a nota fiscal")
    itens.append({"chave": "notas", "rotulo": f"Notas fiscais ({len(nfs)})" if len(nfs) != 1 else "Nota fiscal (1)",
                  "detalhe": detalhe, "estado": "falta" if sem_nota else "ok"})
    if c.get("entidade_id"):
        faltas = protocolo.faltas_consorcio(conn, c, ms)
        consorciadas = conn.execute("SELECT 1 FROM entidade_consorciadas WHERE consorcio_id=?",
                                    (c["entidade_id"],)).fetchone()
        if consorciadas:
            # FRC (2026-10-09): a dashboard gera a FRC sem assinatura na etapa 3; o que vai ao orgao e' a ASSINADA,
            # anexada aqui como documento `fatura` (uma por medicao). Arrastar e soltar no proprio item.
            for m in ms:
                # issue #169: so' conta a assinada ligada a' FRC vigente e nao desatualizada (frc.assinada)
                a = frc.assinada(conn, m["id"])
                d = a["documento"]
                # issue #148: a FRC gerada (sem assinatura) vigente, para a etapa 4 oferecer baixa-la; desatualizada
                # (as notas mudaram depois dela) nao se oferece: assinaria valores velhos
                g = None if d else a["frc"]
                if a["recusa"]:         # nao se justifica: o envio fica bloqueado (protocolo.frc_recusadas)
                    curtos.append("FRC fora do cadastro" if a["recusa"] == frc.SEM_CADASTRO
                                  else "Sem espelho para a FRC" if a["recusa"] == frc.SEM_ESPELHO
                                  else "FRC assinada não é a da FRC vigente")
                detalhe = (f"Assinada anexada · {d['nome']}" if d else a["recusa"] if a["recusa"]
                           else "Falta a assinada: as notas mudaram depois da FRC gerada; gere de novo na etapa 3 "
                                "(Nota fiscal), assine no DocuSign e anexe aqui" if g and g["desatualizada"]
                           else "Falta a assinada: baixe a FRC gerada, assine no DocuSign e anexe aqui" if g
                           else "Falta a FRC assinada: gere na etapa 3 (Nota fiscal), assine no DocuSign e anexe aqui")
                itens.append({"chave": f"frc:{m['id']}", "medicao_id": m["id"],
                              "rotulo": "FRC assinada" + (f" · {medicoes.titulo(m)}" if len(ms) > 1 else ""),
                              "detalhe": detalhe, "frc_gerada": g["numero"] if g and not g["desatualizada"] else None,
                              "estado": "ok" if d else "falta", "acao": None if d else "anexar_frc",
                              "bloqueia": bool(a["recusa"])})
            notas_faltam = [f for f in faltas if not f.endswith("FRC assinada não anexada")]
            itens.append({"chave": "consorcio", "rotulo": "Notas das consorciadas",
                          "detalhe": "; ".join(notas_faltam) or "todas anexadas",
                          "estado": "falta" if notas_faltam else "ok"})
            curtos += faltas
    natureza = "execucao" if any(m["tipo"] != "reajuste" for m in ms) else "reajuste"
    ex = documentos.exigidos(conn, c["id"], natureza)
    varias = len(ex["entidades"]) > 1
    for eid in ex["entidades"] if ex["tipos"] else []:
        ent = dict(conn.execute("SELECT * FROM entidades WHERE id=?", (eid,)).fetchone())
        nome = ent["nome_curto"] or ent["nome"]
        estado, msgs = "ok", []
        for t in ex["tipos"]:
            s = documentos.situacao(conn, eid, t, hoje)
            rot = documentos.ROTULO.get(t["chave"], t["nome"])
            if s["situacao"] == "vencida":
                est, msg = "vencida", f"{rot} vencida em {_br(s['certidao']['validade'], '%d/%m')}"
            elif s["situacao"] == "faltando":
                est, msg = "falta", f"{rot} sem certidão"
            elif s["situacao"] in ("ok", "vencendo") and s["dias"] < AVISO_DIAS:
                est, msg = "aviso", f"{rot} vence hoje" if s["dias"] == 0 else \
                    f"{rot} vence em {s['dias']} dia{'s' if s['dias'] > 1 else ''}"
            else:
                continue
            msgs.append(msg)
            estado = max(estado, est, key=_PIOR.get)
        item = {"chave": f"certidoes:{ent['chave'] or eid}", "rotulo": f"Certidões {nome} ({len(ex['tipos'])})",
                "detalhe": " · ".join(msgs) or "todas válidas", "estado": estado, "entidade_id": eid}
        if estado in ("vencida", "falta"):
            item["acao"] = "anexar_certidao"
        itens.append(item)
        curtos += [f"{nome}: {x}" if varias else x for x in msgs]
    if ex["regularidade"] and "regularidade" in e.soltos:
        eid = ex["regularidade"]
        ent = dict(conn.execute("SELECT * FROM entidades WHERE id=?", (eid,)).fetchone())
        s = documentos.situacao_regularidade(conn, eid, hoje)
        mes = f"{s['esperada'][5:7]}/{s['esperada'][:4]}"
        item = {"chave": f"regularidade:{ent['chave'] or eid}", "rotulo": "Regularidade mensal",
                "entidade_id": eid, "competencia": s["esperada"]}
        if s["situacao"] == "ok":
            item.update(detalhe=f"{s['competencia'][5:7]}/{s['competencia'][:4]}", estado="ok")
        else:
            item.update(detalhe=f"O DP ainda não enviou o arquivo de {mes}", estado="falta",
                        acao="anexar_regularidade")
            curtos.append("Falta a regularidade")
        itens.append(item)
    return itens, notas, curtos


def _irmas(conn, c: dict, familia: str, o: dict, ms: list[dict], hoje: datetime.date) -> list[dict]:
    """Issue #172: onde medicao e reajuste vao no mesmo e-mail (SINFRA, Pref. VG), a irma (mesmo numero, o outro tipo
    do par execucao x reajuste) com nota emitida que ficou fora deste envio, para o registro por fora leva-la junto.
    Nao se oferece a irma bloqueada (certidao vencida da natureza dela ou FRC assinada que nao vale: o registro por
    fora contornaria o bloqueio)
    nem a que tem envio proprio ja' montado ou assinado (o registro descartaria esse protocolo); rascunho nao conta."""
    regras = json.loads(o.get("regras") or "{}")
    if not protocolo.junta_naturezas(regras, o, protocolo._etapa(familia, _etapa(familia))):
        return []
    dentro = {m["id"] for m in ms}
    outro = {"execucao": "reajuste", "reajuste": "execucao"}
    achadas: dict[int, dict] = {}
    for m in ms:
        if m["tipo"] not in outro:
            continue
        for r in conn.execute("SELECT * FROM medicoes WHERE contrato_id=? AND numero=? AND tipo=? "
                              "AND estado='nota_emitida' ORDER BY id", (c["id"], m["numero"], outro[m["tipo"]])):
            if r["id"] in dentro or any(p["situacao"] != "rascunho" for p in _ativos(conn, _etapa(familia), r["id"])):
                continue
            # rodada 3 da PR #179: nem a irma com item que bloqueia (FRC assinada recusada, sem espelho, sem cadastro)
            if any(i["estado"] == "vencida" or i.get("bloqueia") for i in _itens(conn, c, familia, [dict(r)], hoje)[0]):
                continue
            achadas[r["id"]] = {"medicao_id": r["id"], "titulo": medicoes.titulo(r), "tipo": r["tipo"]}
    return list(achadas.values())


def _envio(conn, c: dict, familia: str, o: dict, ms: list[dict], protocolo_id: int | None,
           hoje: datetime.date) -> dict:
    itens, nfs, curtos = _itens(conn, c, familia, ms, hoje)
    estados = {i["estado"] for i in itens}
    esperas = [x for m in ms if (x := espera(conn, m, c))]
    # issue #188: a espera vem antes do resto, porque e' ela que segura o envio
    situacao = "esperando" if esperas else \
        "bloqueado" if "vencida" in estados or any(i.get("bloqueia") for i in itens) else \
        "pendente" if "falta" in estados else "a_pedido" if o["chave"] == "pref-cuiaba" else "pronto"
    if esperas:
        curtos = [esperas[0]["texto"].capitalize(), *curtos]
    # rodada 4 da PR #179: o pacote montado com a FRC assinada anterior bloqueia o envio; a lista mostra
    elif protocolo_id and (r := [x for x in protocolo.frc_recusadas(conn, protocolo._linha(conn, protocolo_id))
                                 if x in protocolo.PACOTE_SEM_A_FRC_VIGENTE]):
        situacao = "bloqueado"
        curtos.append("Pacote com a FRC assinada anterior: monte de novo" if r[0] == protocolo.PACOTE_FRC_VELHA
                      else "Pacote sem a FRC assinada: monte de novo")
    ids = sorted(m["id"] for m in ms)
    emitida = max((m["desde"] for m in ms if m.get("desde")), default=None)
    return {"chave": f"c{c['id']}:" + "-".join(f"m{i}" for i in ids), "contrato_id": c["id"],
            "obra": c.get("nome_curto") or c.get("numero_instrumento"), "orgao": _grupo(familia, o),
            "orgao_sub": SUB_SINFRA.get(o["chave"]) if familia == "sinfra" else None, "familia": familia,
            "grupo": _grupo(familia, o), "a_pedido": o["chave"] == "pref-cuiaba", "medicao_ids": ids,
            "descricao": _descricao(ms), "notas": nfs, "espera": esperas[0] if esperas else None,
            "valor_centavos": sum(m.get("valor_centavos") or 0 for m in ms), "emitida_em": emitida,
            "dias": (hoje - datetime.date.fromisoformat(emitida)).days if emitida else None,
            "situacao": situacao, "aviso": " · ".join(dict.fromkeys(curtos)) or None, "itens": itens,
            "protocolo_id": protocolo_id, "irmas": _irmas(conn, c, familia, o, ms, hoje),
            # so' leitura (16/10/2026): o envio comecado cujo e-mail pode estar saindo; a pagina da medicao so' oferece "Liberar envio preso" com ele
            "envio_reservado_em": (conn.execute("SELECT envio_reservado_em FROM protocolos WHERE id=?", (protocolo_id,)).fetchone() or [None])[0]
            if protocolo_id else None}


# --- lista -----------------------------------------------------------------------------------------

def _agrupar(conn, familia: str, regras: dict, o: dict, ms: list[dict]) -> dict[tuple, list[dict]]:
    """Os envios de um contrato: protocolo ja' iniciado manda; senao a regra do orgao (competencia ou um por medicao).
    Tambem confere, no registro por fora, que as medicoes pedidas sao um envio da lista (gate Sol S1, PR #178)."""
    etapa = _etapa(familia)
    junta = protocolo.junta_naturezas(regras, o, protocolo._etapa(familia, etapa))
    grupos: dict[tuple, list[dict]] = {}
    for m in ms:
        ativos = _ativos(conn, etapa, m["id"])
        k = ("p", ativos[0]["id"]) if ativos else ("c", m["competencia"]) if junta else ("m", m["id"])
        grupos.setdefault(k, []).append(m)
    return grupos


def a_enviar(conn, hoje: datetime.date | None = None) -> dict:
    hoje = hoje or tempo.hoje_local()
    por_contrato: dict[int, list[dict]] = {}
    for m in medicoes.em_andamento(conn, estado="nota_emitida"):
        por_contrato.setdefault(m["contrato_id"], []).append(m)
    envios = []
    for cid, ms in por_contrato.items():
        c = protocolo._contrato(conn, cid)
        if not c.get("orgao_id"):
            continue                          # sem orgao no cadastro nao ha para quem mandar
        familia, regras, o = protocolo._orgao(conn, c)
        for k, gm in _agrupar(conn, familia, regras, o, ms).items():
            envios.append(_envio(conn, c, familia, o, gm, k[1] if k[0] == "p" else None, hoje))
    contadores = {"Todas": len(envios)}
    for x in envios:
        contadores[x["grupo"]] = contadores.get(x["grupo"], 0) + 1
    return {"envios": envios, "contadores": contadores}


# --- iniciar, detalhe, enviar ----------------------------------------------------------------------

def iniciar(conn, usuario_id: int, contrato_id: int, medicao_ids: list[int], numero_oficio: str | None = None) -> int:
    """Cria (ou devolve) o protocolo do envio. Outra composicao (juntar/separar) descarta o que nao foi enviado."""
    c = protocolo._contrato(conn, contrato_id)
    familia, regras, o = protocolo._orgao(conn, c)
    etapa = _etapa(familia)
    e = protocolo._etapa(familia, etapa)
    ids = sorted(set(medicao_ids or []))
    if not ids:
        raise ValueError("Escolha ao menos uma medição")
    for mid in ids:
        m = conn.execute("SELECT * FROM medicoes WHERE id=?", (mid,)).fetchone()
        if m is None or m["contrato_id"] != contrato_id:
            raise ValueError("Medição de outro contrato")
        if m["estado"] != "nota_emitida":
            raise ValueError(f"{medicoes.titulo(m)} não está com a nota emitida ({m['estado']})")
        recusar_se_espera(conn, m, c)
    if len(ids) > 1 and not protocolo.junta_naturezas(regras, o, e):
        raise ValueError("Neste órgão cada nota vai no seu e-mail (um ofício por nota)")
    ativos = {p["id"]: p for mid in ids for p in _ativos(conn, etapa, mid)}
    canon = None
    if e.carta and numero_oficio:
        sigla = conn.execute("SELECT sigla_oficio FROM entidades WHERE id=?",
                             (c["entidade_id"],)).fetchone()["sigla_oficio"] if c.get("entidade_id") else "LT"
        canon = oficios.canonico(numero_oficio, sigla, tempo.hoje_local().year)
    for p in ativos.values():
        atuais = sorted(r[0] for r in conn.execute("SELECT medicao_id FROM protocolo_medicoes WHERE protocolo_id=?",
                                                   (p["id"],)))
        if atuais == ids and (canon is None or canon == p["numero_oficio"]):
            return p["id"]
    anterior = next((p["numero_oficio"] for p in ativos.values() if p["numero_oficio"]), None)
    with db.mutacao(conn):
        for p in ativos.values():
            protocolo.descartar(conn, usuario_id, p["id"], "Envio recomposto na página Notas")
        return protocolo.criar(conn, usuario_id, contrato_id, etapa, ids, numero_oficio or anterior)


def _paginas(conn, p: dict, familia: str, regras: dict, hoje: datetime.date) -> list[str]:
    """O que vai dentro do PDF unico, na ordem de `montar` (MTPAR: oficio, NF, municipal, trabalhista...)."""
    e = protocolo._etapa(familia, p["etapa"])
    ms = protocolo._medicoes(conn, p["id"])
    out = ["Capa"] if e.capa else []
    for parte in e.partes:
        if parte == "carta":
            out.append(f"Ofício {oficios.na_carta(p['numero_oficio'])}" if p["numero_oficio"] else "Ofício")
        elif parte == "notas":
            out += [("FRC " if d["tipo_doc"] == "fatura" else "NF ") + (d["numero_nf"] or d["nome"])
                    for d in protocolo._docs_nota(conn, [m["id"] for m in ms])]
        elif parte == "certidoes":
            ex = documentos.exigidos(conn, p["contrato_id"], p["natureza"])
            ordem = regras.get("ordem_certidoes") or sorted(t["chave"] for t in ex["tipos"])
            tipos = sorted(ex["tipos"], key=lambda t: ordem.index(t["chave"]) if t["chave"] in ordem else 99)
            for eid in ex["entidades"]:
                ent = conn.execute("SELECT nome, nome_curto FROM entidades WHERE id=?", (eid,)).fetchone()
                for t in tipos:
                    v = certidoes.vigente(conn, eid, t["id"], hoje.isoformat())
                    if v and v.get("arquivo"):
                        out.append(f"Certidão {documentos.ROTULO.get(t['chave'], t['nome'])} – "
                                   f"{ent['nome_curto'] or ent['nome']}")
        elif parte == "pecas":
            out += [x["nome"] for x in protocolo._pecas(conn, p["id"]) if x["ext"] == "pdf" and x["tipo"] != protocolo.ANEXO]
    return out


def detalhe_envio(conn, protocolo_id: int, remetente: str | None = None, hoje: datetime.date | None = None) -> dict:
    hoje = hoje or tempo.hoje_local()
    p = protocolo._linha(conn, protocolo_id)
    if p["etapa"] not in ("nota", "unico"):
        raise ValueError("Este protocolo não é de envio de nota")
    c = protocolo._contrato(conn, p["contrato_id"])
    familia, regras, o = protocolo._orgao(conn, c)
    e = protocolo._etapa(familia, p["etapa"])
    mids = {m["id"] for m in protocolo._medicoes(conn, protocolo_id)}
    ms = [m for m in medicoes.em_andamento(conn, contrato_id=c["id"]) if m["id"] in mids]
    pv = protocolo.previa_envio(conn, [protocolo_id], remetente=remetente, hoje=hoje)
    carta = None
    if e.carta:
        try:
            corpo = p["corpo_carta"] or protocolo.corpo_padrao(conn, protocolo_id)
        except ValueError:
            corpo = None
        carta = {"oficio": oficios.na_carta(p["numero_oficio"]) if p["numero_oficio"] else None, "corpo": corpo,
                 "paginas": _paginas(conn, p, familia, regras, hoje), "montado": bool(p["montado_arquivo"]),
                 "assinado": bool(p["assinado_arquivo"]),
                 "nome_arquivo": protocolo.nome_arquivo(conn, p) if p["montado_arquivo"] else None}
    return {"envio": _envio(conn, c, familia, o, ms, protocolo_id, hoje) if ms else None, "familia": familia,
            "etapa": p["etapa"], "protocolo_id": protocolo_id, "situacao_protocolo": p["situacao"], "carta": carta,
            "previa": {k: pv[k] for k in ("para", "copia", "assunto", "corpo", "anexos", "total", "limite", "links")},
            # issue #213: com pendencia, o Enviar abre o aviso "ATENÇÃO" com esta lista e manda a lista confirmada
            "bloqueio": pv["bloqueio"], "pendencias": [x["mensagem"] for x in pv["pendencias"]],
            "extras": [{"id": x["id"], "nome": x["nome"], "tamanho": x["tamanho"]}
                       for x in protocolo._pecas(conn, protocolo_id) if x["tipo"] == protocolo.ANEXO]}


def enviar(conn, usuario: dict, protocolo_id: int, para: list[str], copia: list[str], assunto: str, corpo: str,
           justificativa: str | None, cco: list[str] | None = None, *, anexos_previa: list[dict],
           confirmadas: list[str] | None = None) -> int:
    """Envia pelo Outlook de quem esta' logado e marca `protocolada` (protocolo.enviar). Bloqueio -> protocolo.Bloqueio.
    `anexos_previa` (issue #100): os anexos que a tela mostrou; se o servidor montar outros, recusa antes de reservar
    (protocolo.AnexosMudaram). Obrigatorio (gate Sol S1, PR #141): None nao vira envio sem conferencia.
    `confirmadas` (issue #213): o que falta, confirmado no aviso; sem ela ou diferente -> protocolo.ConfirmarPendencias."""
    if anexos_previa is None:
        raise ValueError("Faltam os anexos da prévia: abra a prévia de novo para conferir o que vai no e-mail")
    p = protocolo._linha(conn, protocolo_id)
    if p["etapa"] not in ("nota", "unico"):
        raise ValueError("Este protocolo não é de envio de nota")
    # issue #188: a espera pela outra metade e' conferida dentro de protocolo.enviar, sob o lock da reserva
    return protocolo.enviar(conn, usuario, [protocolo_id], para, copia, assunto, corpo, justificativa, cco=cco,
                            anexos_previa=anexos_previa, confirmadas=confirmadas)


# --- envio feito por fora --------------------------------------------------------------------------

def _e_email(dados: bytes) -> bool:
    """E-mail salvo: nao comeca por assinatura de binario, From com endereco de verdade, Date interpretavel e To ou
    Subject preenchido (gate Sol S3, 10/10/2026: "From: x" e "Date: y" digitados num texto passavam). A data NAO e'
    comparada com a do envio informado: fuso e reencaminhamento tornariam isso fragil."""
    if dados.startswith(BINARIOS):
        return False
    try:
        cab = BytesParser(policy=policy.default).parsebytes(dados, headersonly=True)
        _, endereco = parseaddr(str(cab.get("From") or ""))
        usuario, _, dominio = endereco.rpartition("@")
        if not usuario or "." not in dominio:
            return False
        parsedate_to_datetime(str(cab.get("Date") or ""))
        return any(str(cab.get(k) or "").strip() for k in ("To", "Subject"))
    except Exception:       # cabecalho torto quebra o parser de varios jeitos: para nos e' "nao e' e-mail"
        return False


def _conferir_externo(conn, ids: list[int], irmas: set[int]) -> list[dict]:
    """As medicoes do registro por fora, conferidas. Roda antes de gravar o .eml e de novo DENTRO da transacao
    (revisor da PR #178): outro registro ou envio entre as duas leituras nao pode passar. Recusa a medicao fora de
    `nota_emitida`, contratos diferentes, protocolo com envio reservado (o e-mail esta' saindo pelo sistema) e, em
    `irmas` (as que a tela juntou a' medicao da pagina), a que `_irmas` nao ofereceria."""
    ms = []
    for mid in ids:
        m = conn.execute("SELECT * FROM medicoes WHERE id=?", (mid,)).fetchone()
        if m is None:
            raise ValueError(f"Medição {mid} não encontrada")
        if m["estado"] != "nota_emitida":
            raise ValueError(f"{medicoes.titulo(m)} não está com a nota emitida ({m['estado']})")
        ms.append(dict(m))
    for m in ms:
        recusar_se_espera(conn, m)                     # issue #188: o registro por fora tambem espera
    if len({m["contrato_id"] for m in ms}) > 1:       # issue #172: um e-mail e' de um contrato so'
        raise ValueError("Medição de outro contrato")
    for m in ms:
        if any(p["envio_reservado_em"] for etapa in ("nota", "unico") for p in _ativos(conn, etapa, m["id"])):
            raise ValueError(f"{medicoes.titulo(m)} está sendo enviada pelo sistema agora: confira o envio dela "
                             "antes de registrar por fora")
    principais = [m for m in ms if m["id"] not in irmas]
    if len(principais) > 1 or irmas:
        c = protocolo._contrato(conn, ms[0]["contrato_id"])
        familia, regras, o = protocolo._orgao(conn, c)
    if len(principais) > 1:
        # gate Sol S1 (PR #178): varias medicoes so' como um envio da lista (o cliente nao escolhe o que junta)
        grupos = _agrupar(conn, familia, regras, o, medicoes.em_andamento(conn, contrato_id=c["id"],
                                                                          estado="nota_emitida"))
        if sorted(m["id"] for m in principais) not in [sorted(m["id"] for m in g) for g in grupos.values()]:
            raise ValueError("Estas medições não vão no mesmo envio: registre cada uma no envio dela")
    if irmas:
        validas = {i["medicao_id"] for i in _irmas(conn, c, familia, o, principais, tempo.hoje_local())}
        for m in ms:
            if m["id"] in irmas and m["id"] not in validas:
                raise ValueError(f"{medicoes.titulo(m)} não pode ir neste registro (envio próprio montado ou "
                                 "assinado, bloqueio ou órgão que tramita separado): registre-a no envio dela")
    return ms


REGISTRO_EXTERNO = "o registro do envio"      # issue #230: o que a confirmacao do que falta libera aqui


def faltas_externo(conn, ms: list[dict], hoje: datetime.date | None = None) -> list[dict]:
    """Issue #230: o que falta no registro por fora, na regra do envio (#213): os itens do envio em falta ou vencidos
    e a FRC recusada, um por linha ("<item>: <detalhe>"). So' avisa: o registro por fora nao ganha bloqueio novo."""
    c = protocolo._contrato(conn, ms[0]["contrato_id"])
    if not c.get("orgao_id"):
        return []
    familia, _, _ = protocolo._orgao(conn, c)
    itens = _itens(conn, c, familia, ms, hoje or tempo.hoje_local())[0]
    return [{"codigo": i["chave"].split(":")[0], "mensagem": f"{i['rotulo']}: {i['detalhe']}"} for i in itens
            if i["estado"] in ("falta", "vencida") or i.get("bloqueia")]


def envio_externo(conn, usuario_id: int, medicao_ids: list[int], enviado_em: str, observacao: str,
                  eml: tuple[str, bytes] | None = None, irma_ids: list[int] | None = None,
                  confirmadas: list[str] | None = None, numero_oficio: str | None = None) -> None:
    """`irma_ids` (issue #172): a irma marcada no formulario, alem das medicoes do envio (`medicao_ids`).
    `confirmadas` (issue #230): o que falta, confirmado no aviso; sem ela ou diferente -> protocolo.ConfirmarPendencias.
    `numero_oficio` (issue #231): o oficio digitado vai para o protocolo da medicao; vazio, o do ultimo envio dela.
    Conferida aqui e de novo sob o lock; a observacao continua obrigatoria."""
    irmas = set(irma_ids or [])
    ids = sorted(set(medicao_ids or []) | irmas)
    if not set(medicao_ids or []):
        raise ValueError("Escolha ao menos uma medição")
    if irmas & set(medicao_ids):                      # gate Sol S1 (PR #178): a irma nao vira "medicao do envio"
        raise ValueError("A mesma medição veio como do envio e como irmã: abra o registro de novo")
    try:
        data = datetime.date.fromisoformat(enviado_em)
    except (TypeError, ValueError):
        raise ValueError("Data do envio inválida (use AAAA-MM-DD)") from None
    if data > tempo.hoje_local():
        raise ValueError("A data do envio não pode ser futura")
    obs = (observacao or "").strip()
    if not obs:
        raise ValueError("Informe a observação (como e para quem a nota foi enviada)")
    ms = _conferir_externo(conn, ids, irmas)
    oficio = _oficio_externo(conn, ms[0]["contrato_id"], numero_oficio, data)
    if eml:
        if len(eml[1]) > TETO_EML:
            raise ValueError("Arquivo .eml acima de 25 MB")
        if not _e_email(eml[1]):
            raise ValueError(NAO_E_EML)
    protocolo._conferir_confirmacao(faltas_externo(conn, ms), confirmadas, REGISTRO_EXTERNO)
    gravado: dict = {}
    try:
        _registrar_externo(conn, usuario_id, ids, irmas, data, obs, eml, gravado, confirmadas, oficio)
    except BaseException:
        if gravado.get("novo"):
            _remover_eml_sem_registro(conn, gravado["rel"])
        raise


def _oficio_externo(conn, contrato_id: int, digitado: str | None, data: datetime.date) -> str | None:
    """Issue #231: o oficio digitado no registro por fora, normalizado como no envio pelo sistema (`iniciar`):
    `oficios.canonico` com a sigla da entidade do contrato (LT sem entidade; entidade sem sigla, CARTA-NNN-AAAA).
    O ano, sem ano digitado, e' o do envio: o oficio saiu naquela data."""
    texto = (digitado or "").strip()
    if not texto:
        return None
    c = protocolo._contrato(conn, contrato_id)
    sigla = conn.execute("SELECT sigla_oficio FROM entidades WHERE id=?",
                         (c["entidade_id"],)).fetchone()["sigla_oficio"] if c.get("entidade_id") else "LT"
    return oficios.canonico(texto, sigla, data.year)


def _remover_eml_sem_registro(conn, rel: str) -> None:
    """Issue #180: o registro falhou no proprio COMMIT (ou a limpeza sob o lock falhou) depois de gravar um .eml que nao
    existia. O banco voltou atras; o arquivo sai, sob o lock de escrita, so' se nenhuma linha o cita: outro registro
    com o mesmo .eml que entrou depois do ROLLBACK e antes daqui o achou ja' gravado e o usa. Se nem isso der
    (disco ou banco fora), o arquivo fica: orfao e' melhor que registro apontando para o nada.
    So' le' o banco: o lock e' pego e devolvido com ROLLBACK, sem depender de um COMMIT que acabou de falhar."""
    proprio = not conn.in_transaction       # dentro de um envelope de fora, o lock ja' e' dele
    try:
        if proprio:
            conn.execute("BEGIN IMMEDIATE")
        try:
            if not conn.execute("SELECT 1 FROM medicao_documentos WHERE arquivo=? LIMIT 1", (rel,)).fetchone():
                arquivos.caminho_seguro(rel).unlink(missing_ok=True)
        finally:
            if proprio:
                conn.rollback()
    except Exception:
        log.warning("Envio por fora: o .eml %s ficou na pasta sem registro (a limpeza falhou)", rel, exc_info=True)


def _registrar_externo(conn, usuario_id: int, ids: list[int], irmas: set[int], data: datetime.date, obs: str,
                       eml: tuple[str, bytes] | None, gravado: dict, confirmadas: list[str] | None = None,
                       oficio: str | None = None) -> None:
    rel = sha = None
    with db.mutacao(conn):
        try:
            ms = _conferir_externo(conn, ids, irmas)        # de novo, sob o lock: a corrida perdida e' recusada
            # issue #230: o que falta, de novo sob o lock; e' esta lista (nao a lida antes) que vai na auditoria e na
            # ressalva, que junta a observacao e a lista
            no_lock = faltas_externo(conn, ms)
            protocolo._conferir_confirmacao(no_lock, confirmadas, REGISTRO_EXTERNO)
            faltam = [x["mensagem"] for x in no_lock]
            ressalva = f"Envio feito por fora: {obs}" + \
                (f"; {protocolo.CONFIRMADO_COM_FALTA}{'; '.join(faltam)}" if faltam else "")
            if eml:     # gate Sol S2 (PR #178): depois das conferencias, para a recusa nao deixar arquivo solto
                # issue #180: anota se ESTE registro criou o arquivo; o que ja' existia (mesmo hash) nunca e' apagado
                ja_existia = (arquivos.pasta("evidencias") / f"{arquivos.sha_de(eml[1])}.eml").exists()
                rel, sha = arquivos.gravar_bytes("evidencias", eml[1], "eml")
                gravado.update(rel=rel, novo=not ja_existia)
            for m in ms:
                medicoes.registrar_protocolo(conn, usuario_id, m["id"], data.isoformat(),
                                             oficio or protocolo._oficio_da_medicao(conn, m["id"]), None, "manual",
                                             apesar_das_pendencias=True, justificativa=ressalva)
                if faltam:      # quem confirmou e quando: o usuario e o carimbo da propria linha da auditoria
                    auditoria.registrar(conn, usuario_id, "protocolo.envio_confirmado", "medicao", m["id"], None,
                                        {"pendencias": faltam})
                conn.execute("UPDATE medicoes SET envio_origem='externo', envio_externo_em=?, envio_externo_obs=? "
                             "WHERE id=?", (data.isoformat(), obs, m["id"]))
                if rel:
                    conn.execute("INSERT OR IGNORE INTO medicao_documentos (medicao_id, fonte, tipo_doc, nome, item_id, "
                                 "arquivo, sha256, tamanho) VALUES (?,'operacao','evidencia_orgao',?,?,?,?,?)",
                                 (m["id"], (eml[0] or "envio.eml")[-200:], sha, rel, sha, len(eml[1])))
                for etapa in ("nota", "unico"):
                    for p in _ativos(conn, etapa, m["id"]):
                        protocolo.descartar(conn, usuario_id, p["id"], "Envio registrado como feito por fora")
            auditoria.registrar(conn, usuario_id, "notas.envio_externo", "medicao", ids[0], None,
                                {"medicoes": ids, "enviado_em": data.isoformat(), "observacao": obs, "eml": rel,
                                 **({"numero_oficio": oficio} if oficio else {}),       # issue #231
                                 # revisor adversarial da PR #237: o registro do protocolo da medicao so' grava a
                                 # justificativa com certidao pendente; a ressalva "<observacao>; <lista>" fica aqui
                                 **({"confirmadas": faltam, "ressalva": f"{obs}; {protocolo.CONFIRMADO_COM_FALTA}"
                                     + "; ".join(faltam)} if faltam else {})})
        except BaseException:
            # gate Sol S1 (PR #199): ainda sob o lock de escrita, antes do ROLLBACK. O arquivo que ESTE registro criou
            # ninguem mais cita (so' este caminho grava .eml em evidencias, sempre sob o lock): sai sem consultar o
            # banco nem pegar o lock de novo. So' a falha no proprio COMMIT fica para `_remover_eml_sem_registro`.
            if gravado.get("novo"):
                try:
                    arquivos.caminho_seguro(gravado["rel"]).unlink(missing_ok=True)
                    gravado["novo"] = False
                except Exception:
                    pass
            raise


# --- aguardando pagamento --------------------------------------------------------------------------

def _protocolo_enviado(conn, medicao_id: int):
    return conn.execute(
        "SELECT p.id, p.numero_orgao, e.enviado_em FROM protocolo_medicoes pm JOIN protocolos p ON p.id=pm.protocolo_id "
        "JOIN envios e ON e.id=p.envio_id WHERE pm.medicao_id=? AND p.situacao='enviado' AND p.etapa IN ('nota','unico') "
        "ORDER BY p.id DESC LIMIT 1", (medicao_id,)).fetchone()


def _ultimo_protocolo(conn, medicao_id: int):
    return conn.execute("SELECT id, data, numero_processo FROM medicao_protocolos WHERE medicao_id=? "
                        "ORDER BY id DESC LIMIT 1", (medicao_id,)).fetchone()


def aguardando_pagamento(conn) -> list[dict]:
    out = []
    for r in conn.execute(
            "SELECT m.*, c.nome_curto, c.numero_instrumento, o.familia, o.chave AS orgao_chave, o.nome AS orgao_nome "
            "FROM medicoes m JOIN contratos c ON c.id=m.contrato_id LEFT JOIN orgaos o ON o.id=c.orgao_id "
            "WHERE m.estado='protocolada'"):
        p = _protocolo_enviado(conn, r["id"])
        mp = _ultimo_protocolo(conn, r["id"])
        if r["envio_origem"] == "externo":
            enviada = r["envio_externo_em"]
        elif p:
            enviada = tempo.para_local(datetime.datetime.fromisoformat(p["enviado_em"])).date().isoformat()
        else:
            enviada = mp["data"][:10] if mp else None
        numero = (p["numero_orgao"] if p else None) or (mp["numero_processo"] if mp else None)
        out.append({"medicao_id": r["id"], "contrato_id": r["contrato_id"],
                    "obra": r["nome_curto"] or r["numero_instrumento"],
                    "orgao": _grupo(r["familia"], {"chave": r["orgao_chave"], "nome": r["orgao_nome"]})
                    if r["familia"] else None,
                    "descricao": medicoes.titulo(r).replace("Medição", "medição"),
                    "valor_centavos": r["valor_protocolado_centavos"], "enviada_em": enviada, "numero_orgao": numero,
                    "familia": r["familia"], "origem": r["envio_origem"] or ("sistema" if p else None),
                    "protocolo_id": p["id"] if p else None,
                    "sem_numero_orgao": r["familia"] == "mtpar" and not numero})
    return sorted(out, key=lambda x: (x["enviada_em"] or "", x["medicao_id"]), reverse=True)


def registrar_numero_orgao(conn, usuario_id: int, medicao_id: int, numero: str) -> None:
    """D10: nº do SIGA (MTPAR). Envio pelo sistema: no protocolo; feito por fora: no registro do protocolo."""
    numero = (numero or "").strip()
    if not numero:  # A-15 (10/10/2026): vazio apagava o numero gravado; nao ha' "apagar" na tela
        raise ValueError(protocolo.NUMERO_ORGAO_VAZIO)
    p = _protocolo_enviado(conn, medicao_id)
    if p:
        protocolo.registrar_numero_orgao(conn, usuario_id, p["id"], numero, None)
        return
    mp = _ultimo_protocolo(conn, medicao_id)
    if mp is None:
        raise ValueError("Medição sem envio registrado")
    with db.mutacao(conn):
        conn.execute("UPDATE medicao_protocolos SET numero_processo=? WHERE id=?", (numero, mp["id"]))
        auditoria.registrar(conn, usuario_id, "medicao.numero_orgao", "medicao", medicao_id,
                            {"numero_processo": mp["numero_processo"]}, {"numero_processo": numero})
