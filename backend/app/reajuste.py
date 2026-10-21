"""Ciclo do reajuste por data-base (spec 2026-09-21 §7.2), bloco 7.

O sistema nao calcula indice nem valor. Sabe so' o calendario: o reajuste vale a partir do MES do
aniversario (OT 028/2015/CGE item 3.2.1; clausula 11.45 SINFRA); o aviso comeca 30 dias antes do 1o dia
desse mes; o ciclo fecha com o APOSTILAMENTO, nao com o oficio (reenviado a cada aditivo).
"""
import datetime
import json

from app import avisos as _av, tempo

JANELA_DIAS, DIRETORIA_DIAS = 30, 90


def aniversario(mes_base: str, ano: int) -> datetime.date:
    return datetime.date(ano, int(mes_base[5:7]), 1)


def _ciclo_corrente(mes_base: str, hoje: datetime.date) -> int | None:
    """Maior ano Y em que (1o dia do mes de aniversario de Y) - 30 dias ja' chegou."""
    anos = [y for y in range(int(mes_base[:4]) + 1, hoje.year + 2)
            if aniversario(mes_base, y) - datetime.timedelta(days=JANELA_DIAS) <= hoje]
    return max(anos) if anos else None


def ciclo_do_apostilamento(dados: dict, data: str) -> int | None:
    """O ciclo (ano) que o apostilamento fecha: `ciclo`, senao o ano da `eficacia`, senao o da data do termo."""
    try:
        return int(str(dados.get("ciclo") or dados.get("eficacia") or data)[:4])      # "2026-06" -> 2026
    except ValueError:
        return None


def _apostilamento(conn, contrato_id: int, mes_base: str, ciclo: int, unica: bool) -> dict | None:
    """Apostilamento de reajuste com a mesma data-base e o mesmo ciclo. Sem `data_base` nos dados, vale a
    data-base unica do contrato; sem `ciclo`, o ano da `eficacia` (ou da data do instrumento)."""
    for r in conn.execute("SELECT * FROM instrumentos WHERE contrato_id=? AND tipo='apostilamento_reajuste' "
                          "ORDER BY data DESC, id DESC", (contrato_id,)):
        d = json.loads(r["dados"] or "{}")
        base = d.get("data_base") or (mes_base if unica else None)
        ano = ciclo_do_apostilamento(d, r["data"])
        if ano is None:
            continue
        if base == mes_base and ano == ciclo:
            return {**dict(r), "dados": d}
    return None


def _pleito(conn, contrato_id: int, mes_base: str, ciclo: int) -> dict | None:
    """O ultimo pleito enviado do ciclo vale (reemissao a cada aditivo e' novo pleito no mesmo ciclo)."""
    r = conn.execute("SELECT * FROM pleitos WHERE contrato_id=? AND tipo='reajuste' AND data_base_mes=? AND ciclo=? "
                     "AND situacao='enviado' ORDER BY enviado_em DESC, id DESC LIMIT 1",
                     (contrato_id, mes_base, ciclo)).fetchone()
    return dict(r) if r else None


# Origem mais forte primeiro (spec 2026-10-20 §2.2): o apostilamento manda, o pleito vem depois, o manual por ultimo.
ORDEM_ORIGEM = ("apostilamento", "pleito", "manual")


def previsoes_vigentes(conn, contrato_id: int, data_base_mes: str | None = None) -> list[dict]:
    """Previsao vigente de cada competencia (por data-base e ciclo): a mais recente da origem mais forte.
    As previsoes sao eventos (migracao 043): nada se sobrescreve, a leitura escolhe.

    Previsao de pleito so' vale enquanto o pleito vale: pleito descartado, ou reemitido por outro pleito ja'
    enviado, sai da conta inteiro (a reemissao traz o cronograma todo; competencia que ela nao traz deixa de ter
    previsao de pleito e cai para o manual, se houver). Reemissao ainda em rascunho nao derruba o anterior."""
    ordem = " ".join(f"WHEN '{o}' THEN {i}" for i, o in enumerate(ORDEM_ORIGEM))
    filtro, args = ("AND p.data_base_mes=?", (contrato_id, data_base_mes)) if data_base_mes is not None \
        else ("", (contrato_id,))
    rows = conn.execute(
        f"SELECT * FROM (SELECT p.*, ROW_NUMBER() OVER (PARTITION BY p.data_base_mes, p.ciclo, p.competencia "
        f"ORDER BY CASE p.origem {ordem} END, datetime(p.criado_em) DESC, p.id DESC) AS _ordem "
        f"FROM reajuste_previsoes p WHERE p.contrato_id=? {filtro} "
        f"AND (p.origem <> 'pleito' OR (NOT EXISTS (SELECT 1 FROM pleitos pl WHERE pl.id = p.pleito_id "
        f"AND pl.situacao = 'descartado') AND NOT EXISTS (SELECT 1 FROM pleitos r "
        f"WHERE r.reemite_pleito_id = p.pleito_id AND r.situacao = 'enviado')))) WHERE _ordem=1 "
        f"ORDER BY data_base_mes, ciclo, competencia", args)
    return [{k: r[k] for k in r.keys() if k != "_ordem"} for r in rows]


def competencias_apostiladas(conn, contrato_id: int) -> list[dict]:
    """Issue #271: as competencias cuja previsao vigente vem de apostilamento, com o termo e o nº da medicao que
    ele cita (do `competencias` do cadastro). Termo com `corrige` gravado depois vale no lugar do anterior."""
    termos = {r["id"]: r for r in conn.execute(
        "SELECT id, chave, numero, data, dados FROM instrumentos WHERE contrato_id=? "
        "AND tipo='apostilamento_reajuste'", (contrato_id,))}
    out = []
    for p in previsoes_vigentes(conn, contrato_id):
        t = termos.get(p["instrumento_id"]) if p["origem"] == "apostilamento" else None
        if t is None:
            continue
        itens = json.loads(t["dados"] or "{}").get("competencias") or []
        medicao = next((x.get("medicao") for x in itens
                        if isinstance(x, dict) and str(x.get("competencia")) == p["competencia"]), None)
        out.append({"data_base_mes": p["data_base_mes"], "ciclo": p["ciclo"], "competencia": p["competencia"],
                    "valor_centavos": p["valor_previsto_centavos"], "medicao": medicao,
                    "instrumento_chave": t["chave"], "instrumento_numero": t["numero"], "instrumento_data": t["data"]})
    return out


def ciclos(conn, contrato_id: int, hoje: datetime.date | None = None) -> list[dict]:
    """Um ciclo por data-base: o corrente (ou o proximo, `futuro`, antes da primeira janela)."""
    hoje = hoje or tempo.hoje_local()
    c = conn.execute("SELECT sem_reajuste FROM contratos WHERE id=?", (contrato_id,)).fetchone()
    if c is None or c["sem_reajuste"]:
        return []
    bases = [dict(r) for r in conn.execute("SELECT mes, indice, aplica_a FROM contrato_datas_base WHERE contrato_id=? "
                                           "ORDER BY mes", (contrato_id,))]
    out = []
    for b in bases:
        y = _ciclo_corrente(b["mes"], hoje)
        if y is None:
            y = int(b["mes"][:4]) + 1
            aniv = aniversario(b["mes"], y)
            out.append({"data_base_mes": b["mes"], "indice": b["indice"], "aplica_a": b["aplica_a"], "ciclo": y, "aniversario": aniv.isoformat(),
                        "situacao": "futuro", "dias": (aniv - hoje).days, "pleito": None, "apostilamento": None})
            continue
        aniv = aniversario(b["mes"], y)
        ap = _apostilamento(conn, contrato_id, b["mes"], y, len(bases) == 1)
        pl = _pleito(conn, contrato_id, b["mes"], y)
        if ap:
            sit, dias = "apostilado", None
        elif pl:
            sit, dias = "apostilamento_pendente", (hoje - datetime.date.fromisoformat(pl["enviado_em"][:10])).days
        else:
            sit, dias = "pleito_pendente", (aniv - hoje).days
        out.append({"data_base_mes": b["mes"], "indice": b["indice"], "aplica_a": b["aplica_a"], "ciclo": y, "aniversario": aniv.isoformat(),
                    "situacao": sit, "dias": dias, "pleito": pl, "apostilamento": ap})
    return out


def avisos(conn, hoje: datetime.date | None = None) -> list[dict]:
    """Pleito nao enviado (atencao antes do aniversario, acao depois) e apostilamento pendente (a diretoria
    ve depois de 90 dias). Contratos ativos ou suspensos; em encerramento o reajuste continua valendo
    (as ultimas medicoes tambem se reajustam). A10 (mapa de 2026-09-28): o aviso diz a data-base, para
    levar ao ciclo dela na aba Reajuste, e nao so' a aba."""
    hoje = hoje or tempo.hoje_local()
    out = []
    for c in conn.execute("SELECT id, nome_curto, numero_instrumento FROM contratos "
                          "WHERE estado IN ('ativo','suspenso')"):
        nome = c["nome_curto"] or c["numero_instrumento"]
        destino = {"tela": "contrato", "id": c["id"], "aba": "reajuste"}
        for k in ciclos(conn, c["id"], hoje):
            base = f"{k['data_base_mes'][5:7]}/{k['data_base_mes'][:4]}"
            if k.get("aplica_a"):              # D7: com duas bases, o aviso diz a parte do contrato de cada uma
                base += f" ({k['aplica_a']})"
            aniv = datetime.date.fromisoformat(k["aniversario"])
            if k["situacao"] == "pleito_pendente":
                quando = (f"faz aniversário em {aniv:%d/%m/%Y} (em {k['dias']} dias)" if k["dias"] >= 0
                          else f"fez aniversário em {aniv:%d/%m/%Y} (há {-k['dias']} dias)")
                out.append({**_av.aviso("reajuste_pleito", "atencao" if k["dias"] >= 0 else "acao",
                                        f"data-base {base} {quando}; pleito de reajuste não enviado",
                                        c["id"], nome, dias=k["dias"], destino=destino,
                                        data=k["aniversario"], sentido="prazo"),
                            "data_base_mes": k["data_base_mes"]})
            elif k["situacao"] == "apostilamento_pendente":
                publico = ("operacao", "diretoria") if k["dias"] > DIRETORIA_DIAS else ("operacao",)
                out.append({**_av.aviso("reajuste_apostilamento", "atencao",
                                        f"pleito da data-base {base} enviado há {k['dias']} dias; "
                                        f"apostilamento pendente", c["id"], nome, dias=k["dias"],
                                        publico=publico, destino=destino,
                                        data=k["pleito"]["enviado_em"][:10], sentido="desde"),
                            "data_base_mes": k["data_base_mes"]})
    return out
