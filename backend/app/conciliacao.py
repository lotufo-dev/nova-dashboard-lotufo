"""Conciliacao dos recebidos do legado (2026-09-25).

As medicoes do legado ficaram `protocolada` sem nota ligada: a carga nunca ligou as notas e o casador do RM
as ignora de proposito (`sincronizacao_rm.COMPETENCIA_CORTE_RM`), para nao gerar ruido contra 24 meses de
notas. Aqui o caminho e' o inverso e roda UMA vez, por comando: parte de cada medicao antiga e procura a nota
do RM que a pagou. So' liga o que e' inequivoco; o recebimento sai pela regra de sempre
(`sincronizacao_rm._recebimentos`: titulo quitado no RM -> `recebida` com a data da baixa).

Casamento, todas as condicoes juntas:
- nota do RM ativa, sem alocacao, da coligada da entidade do contrato;
- centro de custo da nota = o do contrato, ou um dos `centros_custo_anteriores_rm` (o RM trocou os centros
  por volta de 2024); contrato sem centro numa coligada que cadastra centro nao casa (a coligada sozinha nao
  isola a obra);
- emitida entre JANELA_ANTES dias antes e JANELA_DEPOIS dias depois do ultimo protocolo (o legado grava o
  protocolo no fim da competencia e a nota sai semanas depois);
- valor da nota = valor da medicao (protocolado ou atestado, CHEIO), ou 2 a MAX_NOTAS notas do MESMO dia
  somando esse valor. Sem a cota: a nota olhada e' a da coligada da entidade do contrato, e o consorcio fatura
  o cheio (Parque Atalaia, coligada 12: razao nota/medicao 1,000 em todas as ligadas pelo ledger); a cota so'
  apareceria por coincidencia de soma.

Unicidade global: a medicao so' e' ligada com exatamente UMA opcao de notas, e nenhuma dessas notas pode
aparecer em opcao de outra medicao. Qualquer duvida fica como estava. `ensaio=True` relata e desfaz.

Notas antigas (`antigas=(nfs, baixas)`): as linhas das consultas DASH12/DASH13 do RM (jun/2021 a set/2024, fora
da janela de 24 meses da DASH10). Mesmas regras; so' a nota que liga e as baixas dela entram no banco
(`notas_fiscais`/`baixas`), o resto nao polui a reconciliacao.
"""
import datetime
import json
import re
from collections import Counter, defaultdict
from itertools import combinations

from app import db, medicoes, rm, sincronizacao_rm

REGRA = "conciliacao_historica"
CONFIANCA = 0.85
JANELA_ANTES, JANELA_DEPOIS = 15, 120
MAX_NOTAS = 3
INICIO_DASH12 = datetime.date(2021, 6, 1)   # a consulta das notas antigas comeca aqui


class _Ensaio(Exception):
    def __init__(self, rel):
        super().__init__("ensaio")
        self.rel = rel


def _data(s) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def _medicoes_do_legado(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("""
        SELECT m.id, m.contrato_id, m.numero, m.tipo, m.competencia,
               m.valor_protocolado_centavos, m.valor_atestado_centavos,
               c.numero_instrumento, c.centro_custo_rm, c.centros_custo_anteriores_rm, e.coligada_rm,
               (SELECT MAX(data) FROM medicao_protocolos p WHERE p.medicao_id=m.id AND p.etapa='nota') AS protocolo
        FROM medicoes m JOIN contratos c ON c.id=m.contrato_id
        JOIN entidades e ON e.id=COALESCE(c.entidade_id, 1)
        WHERE m.estado='protocolada' AND COALESCE(m.valor_protocolado_origem, '') <> 'espelho'
          AND m.competencia < ?
          AND NOT EXISTS (SELECT 1 FROM nf_alocacoes a WHERE a.medicao_id=m.id AND a.desfeita_em IS NULL)
        ORDER BY c.numero_instrumento, m.competencia, m.tipo, m.numero""",
        (sincronizacao_rm.COMPETENCIA_CORTE_RM,))]


def _alvos(m) -> set[int]:
    return {v for v in (m["valor_protocolado_centavos"], m["valor_atestado_centavos"]) if v}


def _opcoes(m, notas: list[dict]) -> list[frozenset]:
    """Conjuntos de notas que pagam a medicao m (cada um: 1 nota, ou 2..MAX_NOTAS do mesmo dia)."""
    alvos = _alvos(m)
    if not alvos:
        return []
    ops = [frozenset((n["id"],)) for n in notas if n["valor_centavos"] in alvos]
    por_dia = defaultdict(list)
    for n in notas:
        por_dia[n["emissao"][:10]].append(n)
    for grupo in por_dia.values():
        for k in range(2, MAX_NOTAS + 1):
            for comb in combinations(grupo, k):
                if sum(n["valor_centavos"] for n in comb) in alvos:
                    ops.append(frozenset(n["id"] for n in comb))
    return ops


def _livres_do_banco(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("""
        SELECT id, coligada, centro_custo, emissao, valor_centavos FROM notas_fiscais n
        WHERE idmov IS NOT NULL AND situacao='ativa' AND emissao IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM nf_alocacoes a WHERE a.nota_id=n.id AND a.desfeita_em IS NULL)""")]


def _livres_do_rm(conn, linhas: list[dict]) -> list[dict]:
    """Notas antigas do RM que ainda nao estao no banco (a DASH10 pode ter trazido a borda da janela)."""
    ja = {(r[0], r[1]) for r in conn.execute("SELECT coligada, idmov FROM notas_fiscais WHERE idmov IS NOT NULL")}
    out = []
    for l in linhas:
        col, idmov = int(l["CODCOLIGADA"]), int(l["IDMOV"])
        emissao = rm.data(l.get("DATAEMISSAO"))
        if str(l.get("STATUS", "")).upper() == "C" or (col, idmov) in ja or not emissao:
            continue
        out.append({"id": f"rm:{col}:{idmov}", "coligada": col, "centro_custo": l.get("CODCCUSTO"),
                    "emissao": emissao, "valor_centavos": rm.centavos(l.get("VALORBRUTO")), "linha": l})
    return out


def conciliar(conn, usuario_id: int, ensaio: bool, antigas: tuple[list, list] | None = None) -> dict:
    rel = {"ensaio": ensaio, "legado_sem_nota": 0, "ligadas": 0, "recebidas": 0, "ligadas_em_aberto": 0,
           "ambiguas": 0, "sem_nota": 0, "sem_protocolo_ou_valor": 0, "antes_do_rm": 0, "obra_sem_centro": 0,
           "por_obra": {}}
    try:
        with db.mutacao(conn):
            meds = _medicoes_do_legado(conn)
            rel["legado_sem_nota"] = len(meds)
            if antigas is None:
                livres = _livres_do_banco(conn)
                # inicio da janela que o RM entrega (DASH10: 24 meses), por TODAS as notas, nao so' as livres
                inicio_rm = _data(conn.execute("SELECT MIN(emissao) FROM notas_fiscais WHERE idmov IS NOT NULL").fetchone()[0])
            else:
                livres = _livres_do_rm(conn, antigas[0])
                inicio_rm = INICIO_DASH12
                linha_da = {n["id"]: n["linha"] for n in livres}
                baixas_de = defaultdict(list)
                for b in antigas[1]:
                    if b.get("IDMOV") is not None:
                        baixas_de[f"rm:{int(b['CODCOLIGADA'])}:{int(b['IDMOV'])}"].append(b)
            estritas = sincronizacao_rm._coligadas_com_centro(conn)
            por_obra = defaultdict(Counter)
            opcoes = {}
            for m in meds:
                obra = m["numero_instrumento"]
                prot = _data(m["protocolo"])
                if prot is None or not _alvos(m):
                    motivo = "sem_protocolo_ou_valor"
                elif inicio_rm is None or prot < inicio_rm - datetime.timedelta(days=JANELA_ANTES):
                    motivo = "antes_do_rm"
                elif not (m["centro_custo_rm"] or "").strip() and m["coligada_rm"] in estritas:
                    motivo = "obra_sem_centro"
                else:
                    cc = (m["centro_custo_rm"] or "").strip()
                    centros = {cc, *json.loads(m["centros_custo_anteriores_rm"] or "[]")}
                    notas = [n for n in livres if n["coligada"] == m["coligada_rm"]
                             and (not cc or (n["centro_custo"] or "").strip() in centros)
                             and -JANELA_ANTES <= (_data(n["emissao"]) - prot).days <= JANELA_DEPOIS]
                    opcoes[m["id"]] = _opcoes(m, notas)
                    continue
                rel[motivo] += 1
                por_obra[obra][motivo] += 1
            uso = Counter(nid for ops in opcoes.values() for op in set(ops) for nid in op)
            ligadas = []
            for m in meds:
                ops = opcoes.get(m["id"])
                if ops is None:
                    continue
                obra = m["numero_instrumento"]
                unicas = set(ops)
                if not unicas:
                    rel["sem_nota"] += 1
                    por_obra[obra]["sem_nota"] += 1
                    continue
                if len(unicas) > 1 or any(uso[nid] > 1 for nid in next(iter(unicas))):
                    rel["ambiguas"] += 1
                    por_obra[obra]["ambiguas"] += 1
                    continue
                for nid in sorted(next(iter(unicas))):
                    if antigas is not None:          # nota antiga: entra no banco so' agora, com as baixas dela
                        chave, nid = nid, sincronizacao_rm._upsert_nf(conn, linha_da[nid])
                        for b in baixas_de.get(chave, []):
                            sincronizacao_rm._upsert_baixa(conn, b)
                    sincronizacao_rm.alocar(conn, usuario_id, nid, m["id"], "detectado", CONFIANCA, REGRA)
                ligadas.append(m)
                rel["ligadas"] += 1
                por_obra[obra]["ligadas"] += 1
            sincronizacao_rm._recebimentos(conn)
            for m in ligadas:
                estado = conn.execute("SELECT estado FROM medicoes WHERE id=?", (m["id"],)).fetchone()[0]
                chave = "recebidas" if estado == "recebida" else "ligadas_em_aberto"
                rel[chave] += 1
                por_obra[m["numero_instrumento"]][chave] += 1
            rel["por_obra"] = {k: dict(v) for k, v in sorted(por_obra.items())}
            if ensaio:
                raise _Ensaio(rel)
    except _Ensaio as e:
        return e.rel
    return rel


# --- corte (decisao do Leonardo em 2026-09-25) --------------------------------------------------------------
# O faturado ate a data do QDOP conta como pago, menos o que o RM mostra em aberto. As medicoes do legado com
# protocolo ate o corte que continuam `protocolada` fecham como `recebida` (sem data: ninguem sabe o dia), com o
# motivo na auditoria. O que o RM ainda cobra dessas obras entra no "a receber" pelas notas
# (`diretoria._notas_em_aberto`), nao pela medicao.

MOTIVO_CORTE = ("corte de {data}: faturado até o QDOP conta como pago; o que o RM mostra em aberto segue a "
                "receber pelas notas")
# So' o comeco do motivo ("corte de DD/MM/AAAA:"): o resto do texto pode ter mudado desde o corte em producao.
_MOTIVO_CORTE_RE = re.compile(r"corte de \d{2}/\d{2}/\d{4}:")


def recebidas_a_mao(conn) -> set[int]:
    """Issue #203 (decisao do Leo de 15/10/2026, opcao A): as medicoes que uma pessoa marcou como recebidas
    (o "Registrar recebimento" da medicao), nem pelo RM nem pelo corte. O registro manual vale: a nota ligada a
    elas sai do "a receber" (`diretoria._notas_em_aberto`) e a Saude avisa enquanto o RM nao tiver a baixa
    (`sincronizacao_rm.reconciliacao`).

    Quem marcou sai da auditoria, pela `origem` que o servidor grava (`medicoes.mudar_estado`): "manual" pela rota
    de estado, "corte" pelo comando do corte; o RM marca sem usuario (`sincronizacao_rm._recebimentos`). O que foi
    gravado antes da `origem` existir (sem a chave) e' manual quando teve usuario e o motivo nao e' o do corte
    (o corte em producao rodou uma vez, em 25/09/2026, sempre com o `MOTIVO_CORTE`)."""
    # parte das medicoes recebidas e acha a auditoria pelo indice (entidade, entidade_id, acao)
    linhas = conn.execute("""
        SELECT m.id, json_extract(a.depois, '$.motivo') AS motivo, json_extract(a.depois, '$.origem') AS origem
        FROM medicoes m JOIN audit_log a ON a.entidade='medicao' AND a.entidade_id=CAST(m.id AS TEXT)
                                         AND a.acao='medicao.estado'
        WHERE m.estado='recebida' AND a.usuario_id IS NOT NULL AND json_extract(a.depois, '$.estado')='recebida'""")
    return {r["id"] for r in linhas
            if r["origem"] == "manual" or (r["origem"] is None and not _MOTIVO_CORTE_RE.match(r["motivo"] or ""))}


def cortar(conn, usuario_id: int, data_corte: str, ensaio: bool) -> dict:
    datetime.date.fromisoformat(data_corte)
    rel = {"ensaio": ensaio, "data": data_corte, "fechadas": 0, "com_nota": 0, "valor_centavos": 0, "por_obra": {}}
    motivo = MOTIVO_CORTE.format(data=datetime.date.fromisoformat(data_corte).strftime("%d/%m/%Y"))
    try:
        with db.mutacao(conn):
            linhas = conn.execute("""
                SELECT m.id, m.valor_protocolado_centavos v, c.numero_instrumento obra,
                       EXISTS (SELECT 1 FROM nf_alocacoes a WHERE a.medicao_id=m.id AND a.desfeita_em IS NULL) com_nota
                FROM medicoes m JOIN contratos c ON c.id=m.contrato_id
                WHERE m.estado IN ('protocolada', 'nf_emitida') AND COALESCE(m.valor_protocolado_origem, '') <> 'espelho'
                  AND m.competencia < ?
                  AND (SELECT MAX(data) FROM medicao_protocolos p WHERE p.medicao_id=m.id AND p.etapa='nota') <= ?
                ORDER BY c.numero_instrumento, m.competencia, m.tipo, m.numero""",
                (sincronizacao_rm.COMPETENCIA_CORTE_RM, data_corte)).fetchall()
            por_obra = Counter()
            for r in linhas:
                medicoes.mudar_estado(conn, usuario_id, r["id"], "recebida", motivo, None, origem="corte")
                rel["fechadas"] += 1
                rel["com_nota"] += 1 if r["com_nota"] else 0
                rel["valor_centavos"] += r["v"] or 0
                por_obra[r["obra"]] += 1
            rel["por_obra"] = dict(sorted(por_obra.items()))
            if ensaio:
                raise _Ensaio(rel)
    except _Ensaio as e:
        return e.rel
    return rel
