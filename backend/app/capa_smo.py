"""Conferencia da capa do SMO contra o cadastro (issue #286; spec 2026-10-20 §2.3 e §4 item 6, D5; decisao do Leo de
08/11/2026). O instrumento so' entra pelo YAML; a dashboard so' avisa.

No "Registrar boletim" o servidor le a capa do PDF (so' o texto, `leitura_smo.ler_pdf_texto`) e grava os campos em
`medicao_boletim_capas` (migracao 076), ligados ao evento de atesto. A conferencia sai desses campos:

- `capa_prazo_divergente`: fim de execucao ou de vigencia da capa diferente de `execucao_fim_vigente` /
  `vigencia_fim_vigente` do cadastro, sem ajuste por dias paralisados. So' a capa mais recente do contrato (pela data
  de realizacao) conta.
- `capa_instrumento_ausente`: "Valor Aditivo" da capa, passado para a cota, diferente da soma dos aditivos de valor
  assinados do cadastro sem os de reajuste (a mesma conta do vigente a precos iniciais). Tambem da capa mais recente.
- `capa_valor_contrato_divergente`: "Valor informado PI do contrato", passado para a cota, diferente do valor
  original do cadastro. Tambem da capa mais recente.
- `capa_acumulado_divergente`: acumulado da capa (do boletim vigente da medicao) diferente da soma das medicoes ate'
  o numero da capa: precos iniciais contra execucao e projeto, reajustamento contra reajuste; vale o aprovado, senao
  o pedido; fora as canceladas e desistidas. Exato ao centavo.

Some quando o cadastro e' corrigido (instrumento aplicado muda o vigente) ou com a diferenca aceita do boletim (o ato
"Aceitar a diferença" da #288, que vale so' para aquele boletim: boletim novo com a mesma diferenca traz o aviso de
volta). Nivel `acao`, so' para a operacao.
"""
import datetime

from app import avisos as _av, contratos
from app.dinheiro import format_brl

_CAMPOS = ("numero", "data_realizacao", "vigencia_fim", "execucao_fim", "valor_contrato_centavos",
           "valor_aditivo_centavos", "acumulado_pi_centavos", "acumulado_reajuste_centavos")
_FORA = ("cancelada", "desistida")


def gravar(conn, atesto_id: int, medicao_id: int, campos: dict | None) -> None:
    """Grava a capa lida do boletim (dentro da transacao do registro). Sem capa lida, nada."""
    if not campos:
        return
    valores = {k: campos.get(k) for k in _CAMPOS}
    if all(v is None for v in valores.values()):
        return
    conn.execute(f"INSERT INTO medicao_boletim_capas (atesto_id, medicao_id, {', '.join(_CAMPOS)}) "
                 f"VALUES (?, ?, {', '.join('?' * len(_CAMPOS))})", (atesto_id, medicao_id, *valores.values()))


def _data_br(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.date.fromisoformat(iso[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return iso


def aceita(conn, atesto_id: int) -> bool:
    """A diferenca do boletim foi aceita com justificativa (o ato da #288)."""
    return conn.execute("SELECT 1 FROM medicao_diferencas_aceitas WHERE atesto_id=? LIMIT 1",
                        (atesto_id,)).fetchone() is not None


def _mais_recente(conn, contrato_id: int) -> dict | None:
    """A capa mais recente do contrato, pela data de realizacao (sem data, por ultimo), das medicoes que valem. So'
    a do boletim vigente de cada medicao: a capa de um boletim substituido nao avisa (code-review)."""
    r = conn.execute(
        "SELECT cap.* FROM medicao_boletim_capas cap JOIN medicoes m ON m.id=cap.medicao_id "
        f"WHERE m.contrato_id=? AND m.estado NOT IN ({','.join('?' * len(_FORA))}) "
        "AND cap.atesto_id=(SELECT MAX(id) FROM medicao_atestos WHERE medicao_id=cap.medicao_id) "
        "ORDER BY cap.data_realizacao IS NULL, cap.data_realizacao DESC, cap.id DESC LIMIT 1",
        (contrato_id, *_FORA)).fetchone()
    return dict(r) if r else None


def _do_boletim_vigente(conn, medicao_id: int) -> dict | None:
    """A capa do boletim vigente da medicao (o ultimo evento de atesto), ou None."""
    r = conn.execute("SELECT cap.* FROM medicao_boletim_capas cap WHERE cap.medicao_id=? AND cap.atesto_id="
                     "(SELECT MAX(id) FROM medicao_atestos WHERE medicao_id=?)", (medicao_id, medicao_id)).fetchone()
    return dict(r) if r else None


def _contrato(conn, capa: dict) -> list[dict]:
    """Prazos, valor aditivo e valor do contrato da capa contra o cadastro."""
    cid = conn.execute("SELECT contrato_id FROM medicoes WHERE id=?", (capa["medicao_id"],)).fetchone()[0]
    v = contratos.vigente(conn, cid)
    out = []
    for campo, vigente, rotulo in (("execucao_fim", "execucao_fim_vigente", "Fim da execução"),
                                   ("vigencia_fim", "vigencia_fim_vigente", "Fim da vigência")):
        lido, cadastro = capa[campo], (v[vigente] or "")[:10] or None
        if lido and lido != cadastro:
            out.append({"tipo": "capa_prazo_divergente", "valor_centavos": None,
                        "mensagem": f"{rotulo}: capa do SMO diz {_data_br(lido)}, cadastro diz {_data_br(cadastro)}"})
    bp = v["percentual_direito_bp"]
    if capa["valor_aditivo_centavos"] is not None:
        lido = contratos.cota(capa["valor_aditivo_centavos"], bp)
        cadastro = v["valor_vigente_execucao_centavos"] - v["valor_original_centavos"]
        if lido != cadastro:
            # code-review: com o cadastro acima da capa, o que falta e' no SMO, nao no cadastro
            frase = ("Capa do SMO cita instrumento que o cadastro não tem" if lido > cadastro
                     else "Cadastro tem aditivo que a capa do SMO não traz")
            out.append({"tipo": "capa_instrumento_ausente", "valor_centavos": lido - cadastro,
                        "mensagem": f"{frase}: valor aditivo de {format_brl(lido)} na capa, "
                                    f"{format_brl(cadastro)} no cadastro"})
    if capa["valor_contrato_centavos"] is not None:
        lido = contratos.cota(capa["valor_contrato_centavos"], bp)
        cadastro = v["valor_original_centavos"]
        if lido != cadastro:
            out.append({"tipo": "capa_valor_contrato_divergente", "valor_centavos": lido - cadastro,
                        "mensagem": f"Valor do contrato: capa do SMO diz {format_brl(lido)}, "
                                    f"cadastro diz {format_brl(cadastro)}"})
    return out


def _somas_ate(conn, contrato_id: int, numero: int) -> tuple[int, int]:
    """(precos iniciais, reajustamento) das medicoes do contrato ate' o numero (o do orgao, senao o da Lotufo):
    o aprovado, senao o pedido; fora as canceladas e desistidas."""
    pi = reaj = 0
    for r in conn.execute(
            "SELECT tipo, COALESCE(valor_atestado_centavos, valor_protocolado_centavos, 0) AS v FROM medicoes "
            f"WHERE contrato_id=? AND estado NOT IN ({','.join('?' * len(_FORA))}) "
            "AND COALESCE(numero_orgao, numero) <= ?", (contrato_id, *_FORA, numero)):
        if r["tipo"] == "reajuste":
            reaj += r["v"]
        else:
            pi += r["v"]
    return pi, reaj


def _acumulado(conn, capa: dict) -> list[dict]:
    if capa["numero"] is None:
        return []
    cid = conn.execute("SELECT contrato_id FROM medicoes WHERE id=?", (capa["medicao_id"],)).fetchone()[0]
    pi, reaj = _somas_ate(conn, cid, capa["numero"])
    out = []
    for campo, soma, rotulo in (("acumulado_pi_centavos", pi, "a preços iniciais"),
                                ("acumulado_reajuste_centavos", reaj, "do reajustamento")):
        lido = capa[campo]
        if lido is not None and lido != soma:
            out.append({"tipo": "capa_acumulado_divergente", "valor_centavos": lido - soma,
                        "mensagem": f"Acumulado {rotulo} até a {capa['numero']}ª medição: capa do SMO diz "
                                    f"{format_brl(lido)}, soma das medições diz {format_brl(soma)}"})
    return out


def divergencias(conn, medicao_id: int, com_aceitas: bool = False) -> list[dict]:
    """As divergencias da capa do boletim vigente da medicao que hoje sao aviso: o acumulado sempre; prazo, valor
    aditivo e valor do contrato so' se a capa e' a mais recente do contrato. Diferenca aceita: nenhuma (salvo
    `com_aceitas`, que o proprio aceite usa para saber se ha' o que aceitar)."""
    capa = _do_boletim_vigente(conn, medicao_id)
    if capa is None or (not com_aceitas and aceita(conn, capa["atesto_id"])):
        return []
    m = conn.execute("SELECT contrato_id, estado FROM medicoes WHERE id=?", (medicao_id,)).fetchone()
    if m["estado"] in _FORA:
        return []
    recente = _mais_recente(conn, m["contrato_id"])
    out = _contrato(conn, capa) if recente is not None and recente["id"] == capa["id"] else []
    return out + _acumulado(conn, capa)


def avisos(conn, hoje: datetime.date) -> list[dict]:
    """Os avisos das obras ativas: os do contrato pela capa mais recente, o acumulado pela capa vigente de cada
    medicao (a mesma capa em duas medicoes do mesmo numero, execucao e reajuste, avisa uma vez)."""
    from app.medicoes import titulo
    out = []
    for c in _av.ativos(conn):
        nome = c["nome_curto"] or c["numero_instrumento"]
        destino = {"tela": "contrato", "id": c["id"], "aba": "medicoes"}
        recente = _mais_recente(conn, c["id"])
        if recente is not None and not aceita(conn, recente["atesto_id"]):
            for d in _contrato(conn, recente):
                out.append({**_av.aviso(d["tipo"], "acao", d["mensagem"], c["id"], nome,
                                        valor_centavos=d["valor_centavos"], destino=destino),
                            "medicao_id": recente["medicao_id"]})
        vistos = set()
        for m in conn.execute(f"SELECT * FROM medicoes WHERE contrato_id=? AND estado NOT IN ({','.join('?' * len(_FORA))}) "
                              "ORDER BY tipo, numero, id", (c["id"], *_FORA)).fetchall():
            capa = _do_boletim_vigente(conn, m["id"])
            if capa is None or aceita(conn, capa["atesto_id"]):
                continue
            for d in _acumulado(conn, capa):
                chave = (capa["numero"], d["mensagem"])
                if chave in vistos:
                    continue
                vistos.add(chave)
                out.append({**_av.aviso(d["tipo"], "acao", f"{titulo(dict(m))}: {d['mensagem']}", c["id"], nome,
                                        valor_centavos=d["valor_centavos"], destino=destino),
                            "medicao_id": m["id"]})
    return out
