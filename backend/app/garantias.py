"""Garantia contratual como documento do contrato (issue #65, decisao de 15/10/2026; a ART saiu do contrato na #239).

GARANTIA tem validade: o cadastro traz `garantia: {apolice, vigencia_fim, arquivo}` e cada instrumento
`endosso_garantia` com `vigencia_fim` e `apolice` (so' vale o da apolice do contrato) substitui a vigencia anterior (o mais recente por data vale; o historico
fica nos instrumentos).

Aviso de garantia, como o das certidoes: atencao a 30 dias do fim, acao a 15, critico vencida; operacao e
diretoria. Contrato em encerramento continua avisando ate' o marco `baixa_garantia`; encerrado nao avisa.
Contrato sem data de garantia no cadastro nao avisa (nao ha' o que contar).
"""
import datetime
import json

from app import tempo

LIMIAR_ATENCAO, LIMIAR_ACAO = 30, 15


def _d(s: str | None) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(s[:10]) if s else None
    except ValueError:
        return None


def _instrumentos(conn, contrato_id: int, tipo: str) -> list[dict]:
    return [{**dict(r), "dados": json.loads(r["dados"] or "{}")} for r in conn.execute(
        "SELECT * FROM instrumentos WHERE contrato_id=? AND tipo=? ORDER BY data, id", (contrato_id, tipo))]


def garantia(conn, contrato_id: int, hoje: datetime.date | None = None) -> dict | None:
    """A garantia do contrato, ou None se o cadastro nao trouxe vigencia nenhuma."""
    hoje = hoje or tempo.hoje_local()
    c = conn.execute("SELECT garantia_apolice, garantia_vigencia_fim, garantia_arquivo FROM contratos WHERE id=?",
                     (contrato_id,)).fetchone()
    if c is None:
        return None
    fim, origem, chave = c["garantia_vigencia_fim"], "contrato", None
    todos = _instrumentos(conn, contrato_id, "endosso_garantia")
    corrigidos = {e["dados"].get("corrige") for e in todos}       # correcao e' instrumento novo: o corrigido sai
    apolice = (c["garantia_apolice"] or "").strip()
    for e in todos:       # so' vale endosso DA apolice do contrato; entre eles, o mais recente por data do instrumento
        if (apolice and str(e["dados"].get("apolice") or "").strip() == apolice
                and e["chave"] not in corrigidos and _d(e["dados"].get("vigencia_fim"))):
            fim, origem, chave = str(e["dados"]["vigencia_fim"])[:10], "endosso", e["chave"]
    if not _d(fim):
        return None
    baixada = any(m["dados"].get("marco") == "baixa_garantia"
                  for m in _instrumentos(conn, contrato_id, "marco_encerramento"))
    dias = (_d(fim) - hoje).days
    situacao = "vencida" if dias < 0 else "vencendo" if dias <= LIMIAR_ATENCAO else "ok"
    return {"apolice": c["garantia_apolice"], "vigencia_fim": fim, "dias": dias, "origem": origem,
            "endosso": chave, "arquivo": c["garantia_arquivo"], "baixada": baixada,
            "situacao": "baixada" if baixada else situacao}


def avisos(conn, hoje: datetime.date | None = None) -> list[dict]:
    """[{tipo, nivel, publico, contrato_id, dias, data, mensagem}] dos contratos ativos (inclui em encerramento)."""
    hoje = hoje or tempo.hoje_local()
    out = []
    for r in conn.execute("SELECT id, encerramento_iniciado_em FROM contratos WHERE estado='ativo' ORDER BY id"):
        cid = r["id"]
        g = garantia(conn, cid, hoje)
        if g and not g["baixada"] and g["dias"] <= LIMIAR_ATENCAO:
            br = f"{g['vigencia_fim'][8:10]}/{g['vigencia_fim'][5:7]}/{g['vigencia_fim'][:4]}"
            dias = g["dias"]
            if dias < 0:
                nivel, msg = "critico", f"garantia vencida há {-dias} dia{'s' if dias < -1 else ''} ({br})"
            else:
                nivel = "acao" if dias <= LIMIAR_ACAO else "atencao"
                msg = f"garantia vence hoje ({br})" if dias == 0 else \
                    f"garantia vence em {dias} dia{'s' if dias > 1 else ''} ({br})"
            out.append({"tipo": "garantia_vencendo", "nivel": nivel, "publico": ["operacao", "diretoria"],
                        "contrato_id": cid, "dias": dias, "data": g["vigencia_fim"], "mensagem": msg})
    return out
