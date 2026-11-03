"""Curva e saldo da obra (aba Contrato; spec §6): reajuste como serie propria, saldo com formula
visivel. `alertas` delega ao registro de avisos. O Painel geral e o da Engenharia sairam no bloco 9
(a tela da Diretoria, `app/diretoria.py`, substitui o consolidado).

Repositorio SO DE LEITURA: nao escreve nada, logo nao registra auditoria nem
precisa dos padroes de corrida (UPDATE condicional) das camadas de escrita.
"""
import datetime
import sqlite3

from app import avisos, contratos, cronograma, tempo

ESTADOS_VALIDOS = ("protocolada", "nf_emitida", "recebida")  # medem; excecoes ficam fora
TIPOS = ("execucao", "reajuste", "projeto")
# Placeholders derivados da constante: se ESTADOS_VALIDOS mudar de tamanho, as
# queries acompanham sozinhas em vez de quebrar num "IN (?,?,?)" fixo.
_QS = ",".join("?" * len(ESTADOS_VALIDOS))


def _data_cadastro(valor) -> datetime.date | None:
    """Data ISO vinda do BANCO -> date; texto vazio/ilegivel -> None.

    A API valida datas com pydantic, mas aditivos ainda entram sem essa porta
    (nao ha rota de aditivo). Um unico registro torto nao pode derrubar o painel
    de alertas inteiro -- e, pela regra da casa, dado ilegivel simplesmente nao
    vira metrica (nenhum alerta) em vez de virar um alerta inventado.

    Tolerancia SO para dado ja gravado: parametro de quem chama (`hoje`) e' parseado
    estrito, para um argumento errado falhar na cara do chamador em vez de virar
    silenciosamente "hoje".
    """
    if not valor:
        return None
    try:
        return datetime.date.fromisoformat(str(valor))
    except ValueError:
        return None


def _medido(conn, contrato_id: int) -> dict[str, dict]:
    """competencia -> {execucao, reajuste, projeto} em centavos + `pendente` por tipo.

    A pendencia de atestado e por SERIE, nao por competencia: um reajuste ainda nao
    atestado no mesmo mes nao pode marcar como provisoria a execucao ja atestada
    (as series sao independentes, §6).
    """
    out: dict[str, dict] = {}
    for m in conn.execute(
            f"SELECT * FROM medicoes WHERE contrato_id=? AND estado IN ({_QS})",
            (contrato_id, *ESTADOS_VALIDOS)):
        comp = m["competencia"]
        p = out.setdefault(comp, {**{t: 0 for t in TIPOS},
                                  "pendente": {t: False for t in TIPOS}})
        if m["valor_atestado_centavos"] is not None:
            valor = m["valor_atestado_centavos"]
        else:
            valor = m["valor_protocolado_centavos"] or 0
            if valor:
                p["pendente"][m["tipo"]] = True   # §6: protocolado enquanto nao atestada -- marcado
        p[m["tipo"]] += valor
    return out


def curva(conn: sqlite3.Connection, contrato_id: int) -> list[dict]:
    previsto = cronograma.previsto_efetivo(conn, contrato_id)
    medido = _medido(conn, contrato_id)
    comps = sorted(set(previsto) | set(medido))
    vazio: dict = {t: 0 for t in TIPOS}
    saida = []
    for c in comps:
        m = medido.get(c, vazio)
        pend = m.get("pendente", {})
        saida.append({"competencia": c,
                      "previsto_centavos": previsto.get(c, 0),
                      "medido_execucao_centavos": m["execucao"],
                      "medido_reajuste_centavos": m["reajuste"],
                      "medido_projeto_centavos": m["projeto"],
                      # `atestado_pendente` qualifica a EXECUCAO (o numero-titulo, que
                      # tambem alimenta o saldo); as demais series vao em `pendente_por_tipo`.
                      "atestado_pendente": pend.get("execucao", False),
                      "pendente_por_tipo": {t: pend.get(t, False) for t in TIPOS}})
    return saida


def mede_execucao(m) -> bool:
    """A medicao entra no medido de execucao de `saldo` (a regra das consultas daqui, para quem ja' tem a linha:
    a carteira da Diretoria, #262): execucao, num dos estados que medem."""
    return m["tipo"] == "execucao" and m["estado"] in ESTADOS_VALIDOS


def medido_execucao_por_contrato(conn: sqlite3.Connection) -> dict[int, int]:
    """O `atestado_execucao_centavos` de `saldo`, de todos os contratos numa consulta so' (a lista de Obras). Mesma
    regra, e a soma tambem em Python, pelo motivo dito em `saldo`."""
    medido: dict[int, int] = {}
    for r in conn.execute(
            "SELECT contrato_id, COALESCE(valor_atestado_centavos, valor_protocolado_centavos, 0) AS v "
            f"FROM medicoes WHERE tipo='execucao' AND estado IN ({_QS})", ESTADOS_VALIDOS):
        medido[r["contrato_id"]] = medido.get(r["contrato_id"], 0) + r["v"]
    return medido


def saldo(conn: sqlite3.Connection, contrato_id: int) -> dict:
    vig = contratos.vigente(conn, contrato_id)
    # Mesma regra da curva (§6): vale o atestado; enquanto nao ha atestado, entra o
    # protocolado -- por isso a formula abaixo diz "medido" e explicita o fallback,
    # em vez de prometer um "atestado" que nem sempre existe.
    # A soma e' feita em PYTHON, nao com SUM() do SQLite: o acumulador do SQLite e'
    # int64 e estoura ("integer overflow", OperationalError) com duas medicoes que
    # individualmente CABEM na coluna. Como o erro vem do dado gravado, ele derrubaria
    # curva/saldo/consolidado/CSV com 500 ate' alguem apagar a medicao. O int do Python
    # e' ilimitado: o saldo fica absurdamente negativo -- aritmetica honesta sobre dado
    # absurdo -- e o painel continua respondendo.
    atestado = sum(r["v"] for r in conn.execute(
        "SELECT COALESCE(valor_atestado_centavos, valor_protocolado_centavos, 0) AS v "
        f"FROM medicoes WHERE contrato_id=? AND tipo='execucao' AND estado IN ({_QS})",
        (contrato_id, *ESTADOS_VALIDOS)))
    # #262 (spec 2026-10-20 §3.2): medido e contratado na mesma base, a precos iniciais. O aditivo de reajuste
    # (SES) entra no vigente do contrato, mas fica fora do saldo e aparece a parte.
    return {"vigente_centavos": vig["valor_vigente_centavos"],
            "vigente_execucao_centavos": vig["valor_vigente_execucao_centavos"],
            "reajuste_contratado_centavos": vig["valor_reajuste_centavos"],
            "atestado_execucao_centavos": atestado,
            "saldo_centavos": vig["valor_vigente_execucao_centavos"] - atestado,
            "formula": "saldo = vigente de execução (sem aditivo de reajuste) − medido (execução: atestado; "
                       "protocolado enquanto não atestado); reajustes em série própria"}


# ------------------------------------------------------------------ avisos

def alertas(conn: sqlite3.Connection, hoje: str | None = None) -> list[dict]:
    """Bloco 6: os avisos vem do registro unico (`app/avisos.py`, spec §11). Sem `hoje`, a data de Cuiaba
    (`tempo.hoje_local`), nao a do relogio da maquina. Sairam os alertas antigos de data-base, reajuste sem
    par, medicao sem protocolo e prazo vencido (virou nivel do aviso de prazo)."""
    hoje_d = datetime.date.fromisoformat(hoje) if hoje else tempo.hoje_local()
    return avisos.listar(conn, hoje_d)
