"""Prazo do contrato (spec 2026-09-21 §7.3 e §7.4), bloco 7.

O relogio e' a EXECUCAO. Vigencia so' conta onde o orgao nao prorroga sozinho. Paralisacao aberta
suspende o relogio. Instrumento retroativo e' sinalizado, nunca recusado. Em encerramento os avisos de
prazo param e fica so' a comunicacao de conclusao.
"""
import datetime
import json
import re

from app import avisos as _av, contratos, tempo

DIAS_EXECUCAO, DIAS_CRITICO, DIAS_VIGENCIA = 60, 30, 60
ENDOSSO_PRAZO, ENDOSSO_JANELA = 5, 60


def _d(s: str | None) -> datetime.date | None:
    """Data do banco; ilegivel (cadastro antigo) vira None em vez de derrubar a tela."""
    try:
        return datetime.date.fromisoformat(s[:10]) if s else None
    except ValueError:
        return None


def _br(s: str | None) -> str:
    return f"{s[8:10]}/{s[5:7]}/{s[:4]}" if s else ""


def _instrumentos_prazo(conn, contrato_id: int) -> list[dict]:
    """Aditivos e apostilamentos de prazo assinados, em ordem, cada um com a execucao que ele prorroga e o
    sinal de retroativo (assinado depois do fim da execucao anterior)."""
    c = conn.execute("SELECT execucao_fim FROM contratos WHERE id=?", (contrato_id,)).fetchone()
    exe_ant = c["execucao_fim"] if c else None
    out = []
    for a in conn.execute("SELECT * FROM aditivos WHERE contrato_id=? AND status='assinado' "
                          "AND (nova_execucao_fim IS NOT NULL OR nova_vigencia_fim IS NOT NULL) "
                          "ORDER BY data_assinatura, id", (contrato_id,)):
        a = dict(a)
        a["retroativo"] = bool(exe_ant and a["data_assinatura"] and a["data_assinatura"] > exe_ant)
        a["execucao_anterior"] = exe_ant
        exe_ant = a["nova_execucao_fim"] or exe_ant
        out.append(a)
    return out


def _outros(conn, contrato_id: int, tipo: str) -> list[dict]:
    return [{**dict(r), "dados": json.loads(r["dados"] or "{}")} for r in conn.execute(
        "SELECT * FROM instrumentos WHERE contrato_id=? AND tipo=? ORDER BY data, id", (contrato_id, tipo))]


def _paralisacao(conn, contrato_id: int) -> dict | None:
    """A ultima paralisacao sem reinicio depois dela."""
    eventos = sorted(_outros(conn, contrato_id, "paralisacao") + _outros(conn, contrato_id, "reinicio"),
                     key=lambda x: (x["data"], x["id"]))
    if eventos and eventos[-1]["tipo"] == "paralisacao":
        return {"desde": eventos[-1]["data"], "numero": eventos[-1]["numero"]}
    return None


def _regras(conn, c: dict) -> dict:
    if not c.get("orgao_id"):
        return {}
    r = conn.execute("SELECT regras FROM orgaos WHERE id=?", (c["orgao_id"],)).fetchone()
    return json.loads(r["regras"] or "{}") if r else {}


def _pleito(conn, contrato_id: int, tipo: str) -> dict | None:
    r = conn.execute("SELECT * FROM pleitos WHERE contrato_id=? AND tipo=? AND situacao='enviado' "
                     "ORDER BY enviado_em DESC, id DESC LIMIT 1", (contrato_id, tipo)).fetchone()
    return dict(r) if r else None


def situacao(conn, contrato_id: int, hoje: datetime.date | None = None) -> dict:
    hoje = hoje or tempo.hoje_local()
    v = contratos.vigente(conn, contrato_id)
    regras = _regras(conn, v)
    insts = _instrumentos_prazo(conn, contrato_id)
    pedido = _pleito(conn, contrato_id, "prazo")
    # O pedido e' atendido por qualquer instrumento de prazo assinado no dia do envio ou depois.
    if pedido and any((a["data_assinatura"] or "") >= pedido["enviado_em"][:10] for a in insts):
        pedido = None
    exe, vig = v.get("execucao_fim_vigente"), v.get("vigencia_fim_vigente")
    exigida = v.get("folga_vigencia_dias") if v.get("folga_vigencia_dias") is not None \
        else regras.get("folga_vigencia_dias")
    exe_d, vig_d = _d(exe), _d(vig)
    real = (vig_d - exe_d).days if exe_d and vig_d else None
    endosso = None
    if insts:
        ult = insts[-1]
        endossos = _outros(conn, contrato_id, "endosso_garantia")
        entregue = any((e["dados"].get("referente") and e["dados"]["referente"] == ult.get("chave_cadastro"))
                       or e["data"] >= (ult["data_assinatura"] or "") for e in endossos)
        assinado = _d(ult["data_assinatura"])
        dias = (hoje - assinado).days if assinado else None
        endosso = {"instrumento": ult.get("numero") or ult.get("chave_cadastro"), "chave": ult.get("chave_cadastro"),
                   "assinado_em": ult["data_assinatura"], "dias": dias, "entregue": entregue}
    enc = None
    if v.get("encerramento_iniciado_em"):
        marcos = {m["dados"].get("marco"): m["data"] for m in _outros(conn, contrato_id, "marco_encerramento")}
        enc = {"desde": v["encerramento_iniciado_em"], "marcos": marcos,
               "conclusao_comunicada": _pleito(conn, contrato_id, "conclusao") is not None}
    return {"execucao_fim": exe, "dias_execucao": (exe_d - hoje).days if exe_d else None,
            "vigencia_fim": vig, "dias_vigencia": (vig_d - hoje).days if vig_d else None,
            "vigencia_automatica": bool(regras.get("vigencia_automatica")),
            "folga": {"exigida": exigida, "real": real,
                      "quebrada": exigida is not None and real is not None and real < exigida},
            "paralisacao": _paralisacao(conn, contrato_id), "pedido": pedido, "instrumentos": insts,
            "endosso": endosso, "encerramento": enc}


def resumo(conn, contrato_id: int, hoje: datetime.date | None = None) -> dict:
    """O prazo de uma obra para a lista de Obras (mapa de 2026-09-28, mudanca A9): os dias ate' o fim da
    execucao e da vigencia, se o orgao prorroga a vigencia junto, e o pedido de prorrogacao em curso (enviado e
    ainda sem instrumento), com os dias desde o envio."""
    hoje = hoje or tempo.hoje_local()
    s = situacao(conn, contrato_id, hoje)
    p = s["pedido"]
    enviado = _d(p["enviado_em"]) if p else None
    return {"dias_execucao": s["dias_execucao"], "dias_vigencia": s["dias_vigencia"],
            "vigencia_automatica": s["vigencia_automatica"],
            "paralisada_desde": s["paralisacao"]["desde"] if s["paralisacao"] else None,
            "pedido_prorrogacao": {"enviado_em": p["enviado_em"][:10], "numero_oficio": p.get("numero_oficio"),
                                   "dias": (hoje - enviado).days if enviado else None} if p else None}


# Numero do termo no formato contrato/ano/tipo/termo ("099/2020/01/14", "088/2023/02/10-SINFRA"): o
# ultimo bloco e' o numero do termo. Termo 00 e' o proprio contrato.
# So' o sufixo institucional (ex.: "-SINFRA") pode seguir; qualquer outro resto invalida a leitura.
_TERMO_NO_NUMERO = re.compile(r"\s*\d+/\d{4}/\d{1,2}/(\d{1,3})(-[A-Z]+)?\s*")


def _ordinal(a: dict, contado: int) -> int:
    """Issue #261: o ordinal do termo sai do numero (sufixo /14), depois do `ordinal` do cadastro e so' na
    falta dos dois da contagem dos instrumentos carregados (cadastro parcial escreveria "1º" no 14º)."""
    m = _TERMO_NO_NUMERO.fullmatch(a.get("numero") or "")
    if m and int(m.group(1)) > 0:
        return int(m.group(1))
    return a.get("ordinal") or contado


def historico_texto(conn, contrato_id: int) -> str:
    """Secao "1. HISTORICO DO CONTRATO" da carta de prazo: um paragrafo por instrumento de prazo, com o
    ordinal do termo (`_ordinal`), contado por forma (termo aditivo x termo de apostilamento) na falta dele."""
    c = conn.execute("SELECT * FROM contratos WHERE id=?", (contrato_id,)).fetchone()
    linhas = [f"O Contrato n.º {c['numero_instrumento']} tem execução original até "
              f"{_br(c['execucao_fim'])} e vigência original até {_br(c['vigencia_fim'])}."]
    conta: dict[str, int] = {}
    for a in _instrumentos_prazo(conn, contrato_id):
        forma = a.get("forma") or "termo_aditivo"
        conta[forma] = conta.get(forma, 0) + 1
        nome = "termo aditivo" if forma == "termo_aditivo" else "termo de apostilamento"
        partes = []
        if a["nova_execucao_fim"]:
            partes.append(f"término da execução em {_br(a['nova_execucao_fim'])}")
        if a["nova_vigencia_fim"]:
            partes.append(f"da vigência em {_br(a['nova_vigencia_fim'])}")
        linhas.append(f"O {_ordinal(a, conta[forma])}º {nome} n.º {a['numero'] or 's/n'} foi assinado em "
                      f"{_br(a['data_assinatura'])}, com {' e '.join(partes)}.")
    return "\n\n".join(linhas)


def avisos(conn, hoje: datetime.date | None = None) -> list[dict]:
    hoje = hoje or tempo.hoje_local()
    out = []
    for c in conn.execute("SELECT id, nome_curto, numero_instrumento FROM contratos WHERE estado='ativo'"):
        nome, cid = c["nome_curto"] or c["numero_instrumento"], c["id"]
        s = situacao(conn, cid, hoje)
        destino = {"tela": "contrato", "id": cid, "aba": "prazos"}
        if s["encerramento"]:
            desde = _d(s["encerramento"]["desde"])
            if not s["encerramento"]["conclusao_comunicada"] and desde:
                dias = (hoje - desde).days
                out.append(_av.aviso("conclusao_nao_comunicada", "acao",
                                     f"em encerramento desde {_br(s['encerramento']['desde'])} "
                                     f"({dias} dias); conclusão não comunicada",
                                     cid, nome, dias=dias, destino=destino,
                                     data=desde.isoformat(), sentido="desde"))
            continue
        if s["paralisacao"]:
            out.append(_av.aviso("obra_paralisada", "atencao",
                                 f"paralisada desde {_br(s['paralisacao']['desde'])}", cid, nome,
                                 publico=("diretoria",), destino=destino,
                                 data=s["paralisacao"]["desde"], sentido="desde"))
        else:
            dias = s["dias_execucao"]
            if s["pedido"]:
                desde = (hoje - (_d(s["pedido"]["enviado_em"]) or hoje)).days
                vencida = dias is not None and dias < 0
                msg = (f"prorrogação pedida em {_br(s['pedido']['enviado_em'])} "
                       f"({s['pedido']['numero_oficio']}); instrumento pendente há {desde} dias")
                if vencida:
                    msg += f"; execução vencida há {-dias} dias"
                out.append(_av.aviso("instrumento_pendente", "critico" if vencida else "atencao", msg, cid, nome,
                                     dias=dias, publico=("operacao", "diretoria") if vencida else ("operacao",),
                                     destino=destino, data=s["execucao_fim"], sentido="prazo"))
            elif dias is not None and dias < 0:
                out.append(_av.aviso("instrumento_pendente", "critico",
                                     f"execução vencida há {-dias} dias, sem pedido de prorrogação",
                                     cid, nome, dias=dias, publico=("operacao", "diretoria"), destino=destino,
                                     data=s["execucao_fim"], sentido="prazo"))
            elif dias is not None and dias <= DIAS_EXECUCAO:
                out.append(_av.aviso("execucao_vencendo", "critico" if dias <= DIAS_CRITICO else "atencao",
                                     f"execução termina em {dias} dias ({_br(s['execucao_fim'])})",
                                     cid, nome, dias=dias, destino=destino, data=s["execucao_fim"], sentido="prazo"))
        if not s["vigencia_automatica"] and s["dias_vigencia"] is not None and s["dias_vigencia"] <= DIAS_VIGENCIA:
            dv = s["dias_vigencia"]
            out.append(_av.aviso("vigencia_vencendo", "critico" if dv <= DIAS_CRITICO else "atencao",
                                 f"vigência termina em {dv} dias ({_br(s['vigencia_fim'])})" if dv >= 0
                                 else f"vigência vencida há {-dv} dias ({_br(s['vigencia_fim'])})",
                                 cid, nome, dias=dv, destino=destino, data=s["vigencia_fim"], sentido="prazo"))
        if s["folga"]["quebrada"]:
            out.append(_av.aviso("folga_quebrada", "acao",
                                 f"execução até {_br(s['execucao_fim'])} e vigência até {_br(s['vigencia_fim'])}: "
                                 f"folga de {s['folga']['real']} dias, o órgão pede {s['folga']['exigida']}",
                                 cid, nome, destino=destino))
        e = s["endosso"]
        if e and not e["entregue"] and e["dias"] is not None and e["dias"] <= ENDOSSO_JANELA:
            falta = ENDOSSO_PRAZO - e["dias"]
            quando = f"vence em {falta} dias" if falta >= 0 else f"atrasado {-falta} dias"
            out.append(_av.aviso("endosso_garantia", "atencao" if falta >= 0 else "acao",
                                 f"endosso do seguro-garantia do {e['instrumento']} "
                                 f"(assinado em {_br(e['assinado_em'])}) {quando}", cid, nome, dias=falta,
                                 destino=destino, data=(hoje + datetime.timedelta(days=falta)).isoformat(),
                                 sentido="prazo"))
    return out
