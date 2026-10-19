"""Aditivos (fase 4): em andamento -> assinado, com o delta conferido na assinatura.

Spec §5: "ao confirmar, usuario informa o delta (valor com sinal e/ou novas datas) --
unica digitacao estrutural do sistema; vigente recalculado". Spec §15.3 (sem IA): "o
delta e' digitado e conferido aritmeticamente (novo = anterior + delta; datas novas
posteriores as vigentes). Ganha campo de ressalva de reajuste na confirmacao."

Regras:
- Em andamento e' rascunho: edita-se e cancela-se. Assinado e' congelado: nada muda;
  errou, faz outro aditivo (ou um de estorno). Cancelado tambem nao muda mais.
- Assinar exige o VALOR NOVO digitado pelo operador e confere `novo == anterior + delta`
  contra o vigente DO MOMENTO (dentro da transacao). Digitar o novo, e nao so' o delta,
  e' a conferencia: dois numeros de fontes diferentes (termo e sistema) que tem que
  bater. Datas novas tem que ser posteriores as vigentes.
- `contratos.vigente` soma os assinados em ordem de assinatura; aqui so' se grava.
"""
import datetime
import sqlite3

from app import auditoria, contratos, db
from app.dinheiro import format_brl

TIPOS = ("prazo", "valor", "escopo", "misto")
CAMPOS_EDITAVEIS = ("tipo", "numero", "objeto", "observacao", "delta_valor_centavos",
                    "nova_vigencia_fim", "nova_execucao_fim")


def _validar(dados: dict) -> None:
    if dados.get("tipo") not in TIPOS:
        raise ValueError(f"Tipo de aditivo inválido: {dados.get('tipo')!r}")
    delta = dados.get("delta_valor_centavos") or 0
    if isinstance(delta, bool) or not isinstance(delta, int):
        raise ValueError("Delta de valor deve ser inteiro em centavos")
    if not delta and not dados.get("nova_vigencia_fim") and not dados.get("nova_execucao_fim"):
        raise ValueError("Aditivo sem efeito: informe delta de valor ou nova data")
    if dados["tipo"] == "prazo" and delta:
        raise ValueError("Aditivo de prazo não altera valor (use 'misto')")
    if dados["tipo"] == "valor" and (dados.get("nova_vigencia_fim") or dados.get("nova_execucao_fim")):
        raise ValueError("Aditivo de valor não altera datas (use 'misto')")


def listar(conn: sqlite3.Connection, contrato_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM aditivos WHERE contrato_id=? ORDER BY status DESC, COALESCE(data_assinatura, '9999'), id",
        (contrato_id,))]


def detalhe(conn: sqlite3.Connection, aditivo_id: int) -> dict | None:
    r = conn.execute("SELECT * FROM aditivos WHERE id=?", (aditivo_id,)).fetchone()
    return dict(r) if r else None


def criar(conn: sqlite3.Connection, usuario_id: int, contrato_id: int, dados: dict) -> int:
    dados = {c: dados.get(c) for c in CAMPOS_EDITAVEIS}
    dados["delta_valor_centavos"] = dados["delta_valor_centavos"] or 0
    _validar(dados)
    with db.mutacao(conn):
        if conn.execute("SELECT 1 FROM contratos WHERE id=?", (contrato_id,)).fetchone() is None:
            raise ValueError("Contrato não encontrado")
        cur = conn.execute(
            "INSERT INTO aditivos (contrato_id, tipo, numero, objeto, observacao, delta_valor_centavos, "
            "nova_vigencia_fim, nova_execucao_fim) VALUES (?,?,?,?,?,?,?,?)",
            (contrato_id, dados["tipo"], dados["numero"], dados["objeto"], dados["observacao"],
             dados["delta_valor_centavos"], dados["nova_vigencia_fim"], dados["nova_execucao_fim"]))
        auditoria.registrar(conn, usuario_id, "aditivo.criar", "aditivo", cur.lastrowid, None,
                            {"contrato_id": contrato_id, **dados})
    return cur.lastrowid


def _rascunho(conn, aditivo_id: int) -> dict:
    a = detalhe(conn, aditivo_id)
    if a is None:
        raise ValueError("Aditivo não encontrado")
    if a["status"] == "assinado":
        raise ValueError("Aditivo assinado não muda mais: registre outro aditivo")
    if a["cancelado_em"]:
        raise ValueError("Aditivo cancelado não muda mais")
    return a


def atualizar(conn: sqlite3.Connection, usuario_id: int, aditivo_id: int, dados: dict) -> None:
    with db.mutacao(conn):
        a = _rascunho(conn, aditivo_id)
        novo = {c: dados.get(c, a[c]) for c in CAMPOS_EDITAVEIS}
        novo["delta_valor_centavos"] = novo["delta_valor_centavos"] or 0
        _validar(novo)
        cur = conn.execute(
            "UPDATE aditivos SET tipo=?, numero=?, objeto=?, observacao=?, delta_valor_centavos=?, "
            "nova_vigencia_fim=?, nova_execucao_fim=? WHERE id=? AND status='em_andamento' AND cancelado_em IS NULL",
            (novo["tipo"], novo["numero"], novo["objeto"], novo["observacao"], novo["delta_valor_centavos"],
             novo["nova_vigencia_fim"], novo["nova_execucao_fim"], aditivo_id))
        db.exigir_uma_linha(cur, "Aditivo mudou concorrentemente; tente novamente")
        auditoria.registrar(conn, usuario_id, "aditivo.atualizar", "aditivo", aditivo_id,
                            {c: a[c] for c in CAMPOS_EDITAVEIS}, novo)


def cancelar(conn: sqlite3.Connection, usuario_id: int, aditivo_id: int, motivo: str | None) -> None:
    with db.mutacao(conn):
        _rascunho(conn, aditivo_id)
        cur = conn.execute(
            "UPDATE aditivos SET cancelado_em=datetime('now'), cancelado_motivo=? "
            "WHERE id=? AND status='em_andamento' AND cancelado_em IS NULL", (motivo, aditivo_id))
        db.exigir_uma_linha(cur, "Aditivo mudou concorrentemente; tente novamente")
        auditoria.registrar(conn, usuario_id, "aditivo.cancelar", "aditivo", aditivo_id,
                            {"cancelado": False}, {"cancelado": True, "motivo": motivo})


def assinar(conn: sqlite3.Connection, usuario_id: int, aditivo_id: int, data_assinatura: str,
            valor_novo_centavos: int, ressalva_reajuste: str | None) -> dict:
    """Confirma a assinatura: delta conferido contra o vigente do momento, datas na ordem.

    Tudo sob a mesma transacao (BEGIN IMMEDIATE): o vigente lido e' o vigente gravado.
    """
    with db.mutacao(conn):
        a = _rascunho(conn, aditivo_id)
        vig = contratos.vigente(conn, a["contrato_id"])
        anterior = vig["valor_vigente_centavos"]
        esperado = anterior + a["delta_valor_centavos"]
        if valor_novo_centavos != esperado:
            raise ValueError(f"Conferência do valor falhou: vigente {format_brl(anterior)} "
                             f"{'+' if a['delta_valor_centavos'] >= 0 else '−'} "
                             f"{format_brl(abs(a['delta_valor_centavos']))} = {format_brl(esperado)}, mas o termo "
                             f"diz {format_brl(valor_novo_centavos)}. Corrija o delta ou o valor novo antes de assinar")
        for campo, vigente_campo, rotulo in (("nova_vigencia_fim", "vigencia_fim_vigente", "vigência"),
                                             ("nova_execucao_fim", "execucao_fim_vigente", "execução")):
            nova, atual = a[campo], vig.get(vigente_campo)
            if nova and atual and nova <= atual:
                raise ValueError(f"Nova data de {rotulo} ({nova}) não é posterior à vigente ({atual})")
        if esperado < 0:
            raise ValueError("Aditivo deixaria o contrato com valor negativo")
        datetime.date.fromisoformat(data_assinatura)   # ValueError se ilegivel
        cur = conn.execute(
            "UPDATE aditivos SET status='assinado', data_assinatura=?, valor_anterior_centavos=?, "
            "valor_novo_centavos=?, ressalva_reajuste=?, assinado_por=? "
            "WHERE id=? AND status='em_andamento' AND cancelado_em IS NULL",
            (data_assinatura, anterior, esperado, ressalva_reajuste, usuario_id, aditivo_id))
        db.exigir_uma_linha(cur, "Aditivo mudou concorrentemente; tente novamente")
        auditoria.registrar(conn, usuario_id, "aditivo.assinar", "aditivo", aditivo_id,
                            {"status": "em_andamento"},
                            {"status": "assinado", "data_assinatura": data_assinatura,
                             "valor_anterior_centavos": anterior, "delta_valor_centavos": a["delta_valor_centavos"],
                             "valor_novo_centavos": esperado, "nova_vigencia_fim": a["nova_vigencia_fim"],
                             "nova_execucao_fim": a["nova_execucao_fim"], "ressalva_reajuste": ressalva_reajuste})
    return {"valor_anterior_centavos": anterior, "valor_novo_centavos": esperado}
