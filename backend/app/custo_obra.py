"""Custo lancado no RM por grupo da planilha, medicao a medicao (issue #491, aba Custo da Carteira; piloto MT-388).

Decisao do Leo de 06/11/2026: a tela mostra "custo lançado no RM", nunca margem nem lucro (a razao custo por receita
so' existe com fechamento mensal, que o RM ainda nao tem). Tudo no valor cheio. So' entram as obras com cadastro de
custo (secao `custo:` do yaml, issue #489); obra de consorcio fica fora do piloto (o custo esta' na coligada dele).

Por competencia (o mes de emissao do lancamento igual a' competencia da medicao):
- custo apontado de um grupo: o rateio do RM (`rm_custo_tarefas`, issue #488) da coligada e dos centros da obra (o
  atual e os anteriores), no projeto do cadastro, cujas tarefas caem nos prefixos do grupo; as naturezas
  `nao_e_custo` ficam fora. Tarefa que nao cai em grupo nenhum (ou de outro projeto) fica numa linha propria.
- custo rateado: o custo do centro sem tarefa (folha, encargos, impostos) mais a baixa de estoque do centro
  (`rm_estoque_baixas`), pela regra `sem_tarefa` do cadastro (`proporcional`: na proporcao do apontado de cada grupo
  no mes; mes sem apontado em grupo nenhum deixa o rateado numa linha "sem grupo").
- medido: o valor da medicao de execucao (atestado, senao o pedido); por grupo, a leitura da planilha
  (`medicao_grupos`, issue #490). Medicao sem leitura entra com o total numa linha "medido por grupo nao lido"; a
  diferenca entre o medido e a soma da planilha lida (glosa no atestado, centavos) numa linha "ajuste ao medido".
- previsto: o do cronograma vigente na competencia (total, sem grupo).
O acumulado soma as linhas: material comprado num mes pode ser medido no seguinte.
"""
import datetime
import json

from app import contratos, cronograma, dinheiro, medicao_grupos, tempo
from app.cadastro_arquivos import _dentro_do_prefixo

DESATUALIZADO_HORAS = 24
# fora do medido: o que nao foi medido de fato (como na Carteira, `diretoria.FORA`)
ESTADOS_FORA = ("cancelada", "desistida", "prevista")
NAO_LIDO = "Medido por grupo não lido"
AJUSTE = "Ajuste ao medido"
SEM_GRUPO = "Sem grupo"
FORA_DOS_GRUPOS = "Tarefa fora dos grupos"
MENSAGEM_SEM_CADASTRO = "Esta obra não tem cadastro de custo."


class SemCadastro(Exception):
    """Obra inexistente, sem cadastro de custo ou de consorcio (fora do piloto)."""


_OBRA = """FROM contratos c JOIN entidades e ON e.id=COALESCE(c.entidade_id, 1)
           WHERE e.papel <> 'consorcio' AND c.projeto_rm IS NOT NULL
             AND EXISTS (SELECT 1 FROM custo_grupos g WHERE g.contrato_id=c.id)"""


def obras(conn) -> list[dict]:
    """As obras do seletor: com cadastro de custo e fora de consorcio."""
    return [dict(r) for r in conn.execute(
        f"SELECT c.id AS contrato_id, COALESCE(c.nome_curto, c.numero_instrumento) AS obra {_OBRA} ORDER BY obra, c.id")]


def _natureza_fora(natureza, nao_e_custo: list[str]) -> bool:
    return bool(natureza) and any(_dentro_do_prefixo(natureza, p) for p in nao_e_custo)


def _grupo_da_tarefa(tarefa: str, grupos: list[dict]) -> str | None:
    for g in grupos:
        if any(_dentro_do_prefixo(tarefa, p) for p in g["tarefas"]):
            return g["nome"]
    return None


def _custo_por_mes(conn, c, grupos: list[dict]) -> tuple[dict, dict, dict]:
    """({mes: {grupo: apontado}}, {mes: fora dos grupos}, {mes: sem tarefa + estoque}) da coligada e dos centros."""
    apontado: dict[str, dict[str, int]] = {}
    fora: dict[str, int] = {}
    rateado: dict[str, int] = {}
    centros = [c["centro_custo_rm"], *json.loads(c["centros_custo_anteriores_rm"] or "[]")]
    centros = sorted({x.strip() for x in centros if x and x.strip()})
    if c["coligada_rm"] is None or not centros:
        return apontado, fora, rateado
    nao_e_custo = json.loads(c["custo_nao_e_custo"] or "[]")
    filtro = f"coligada=? AND centro_custo IN ({','.join('?' * len(centros))})"
    args = (c["coligada_rm"], *centros)
    for r in conn.execute(f"SELECT projeto, tarefa, natureza, mes, valor_centavos FROM rm_custo_tarefas WHERE {filtro}",
                          args):
        if _natureza_fora(r["natureza"], nao_e_custo):
            continue
        mes, valor = r["mes"], r["valor_centavos"]
        if r["tarefa"] is None:
            rateado[mes] = rateado.get(mes, 0) + valor
            continue
        nome = _grupo_da_tarefa(r["tarefa"], grupos) if r["projeto"] == c["projeto_rm"] else None
        if nome is None:
            fora[mes] = fora.get(mes, 0) + valor
        else:
            por = apontado.setdefault(mes, {})
            por[nome] = por.get(nome, 0) + valor
    for r in conn.execute(f"SELECT mes, valor_centavos FROM rm_estoque_baixas WHERE {filtro}", args):
        rateado[r["mes"]] = rateado.get(r["mes"], 0) + r["valor_centavos"]
    return apontado, fora, rateado


def _medido_por_mes(conn, contrato_id: int) -> dict[str, dict]:
    """{mes: {"medicoes", "medido", "lida" (houve leitura), "grupos" {nome: medido}, "nao_lido", "ajuste"}}."""
    meses: dict[str, dict] = {}
    for m in conn.execute(
            f"""SELECT id, numero, competencia, COALESCE(valor_atestado_centavos, valor_protocolado_centavos) AS valor
                FROM medicoes WHERE contrato_id=? AND tipo='execucao' AND estado NOT IN ({','.join('?' * len(ESTADOS_FORA))})
                  AND COALESCE(valor_atestado_centavos, valor_protocolado_centavos) IS NOT NULL
                ORDER BY competencia, numero""", (contrato_id, *ESTADOS_FORA)):
        mes = meses.setdefault(m["competencia"], {"medicoes": [], "medido": 0, "lida": False, "grupos": {},
                                                   "nao_lido": 0, "ajuste": 0})
        mes["medicoes"].append({"id": m["id"], "numero": m["numero"], "nome": f"{m['numero']}ª medição"})
        mes["medido"] += m["valor"]
        lido = medicao_grupos.grupos(conn, m["id"])
        if lido["leitura"] is None:
            mes["nao_lido"] += m["valor"]
            continue
        mes["lida"] = True
        soma = 0
        for g in lido["grupos"]:
            mes["grupos"][g["nome"]] = mes["grupos"].get(g["nome"], 0) + g["valor_medido_centavos"]
            soma += g["valor_medido_centavos"]
        mes["ajuste"] += m["valor"] - soma
    return meses


def _linha_grupo(nome: str, tipo: str, medido, apontado: int = 0, rateado: int = 0) -> dict:
    custo = apontado + rateado
    return {"nome": nome, "tipo": tipo, "medido_centavos": medido, "apontado_centavos": apontado,
            "rateado_centavos": rateado, "custo_centavos": custo, "diferenca_centavos": (medido or 0) - custo}


def _sincronizacao(conn) -> dict:
    """A ultima rodada do RM que trouxe o custo; desatualizada sem rodada ou com mais de um dia."""
    r = conn.execute("""SELECT COALESCE(terminado_em, iniciado_em) AS em FROM rm_sincronizacoes
                        WHERE custo_tarefas IS NOT NULL ORDER BY em DESC, id DESC LIMIT 1""").fetchone()
    if r is None:
        return {"sincronizado_em": None, "desatualizado": True}
    em = datetime.datetime.fromisoformat(r["em"]).replace(tzinfo=datetime.timezone.utc)
    return {"sincronizado_em": tempo.iso_utc(r["em"]),
            "desatualizado": tempo.agora_utc() - em > datetime.timedelta(hours=DESATUALIZADO_HORAS)}


def custo_da_obra(conn, contrato_id: int) -> dict:
    """A tabela da aba Custo: uma linha por competencia (com medicao ou com custo), as linhas de grupo de cada uma e
    o acumulado. SemCadastro na obra fora do seletor."""
    c = conn.execute(f"SELECT c.*, e.coligada_rm {_OBRA} AND c.id=?", (contrato_id,)).fetchone()
    if c is None:
        raise SemCadastro(MENSAGEM_SEM_CADASTRO)
    grupos = contratos.custo_grupos(conn, contrato_id)
    nomes = [g["nome"] for g in grupos]
    apontado, fora, rateado = _custo_por_mes(conn, c, grupos)
    medido = _medido_por_mes(conn, contrato_id)
    previsto = cronograma.previsto_efetivo(conn, contrato_id)
    linhas = []
    for mes in sorted({*apontado, *fora, *rateado, *medido}):
        md = medido.get(mes)
        ap = apontado.get(mes, {})
        r_total = rateado.get(mes, 0)
        pesos = [max(0, ap.get(n, 0)) for n in nomes]
        partes = dinheiro.ratear_proporcional(r_total, pesos) if sum(pesos) > 0 else [0] * len(nomes)

        def medido_de(nome):
            if md is None or not md["lida"]:
                return None
            return md["grupos"].get(nome, 0)

        itens = [_linha_grupo(n, "grupo", medido_de(n), ap.get(n, 0), partes[i]) for i, n in enumerate(nomes)]
        # grupo da planilha que o cadastro nao tem (o "outros" da leitura): so' o medido
        itens += [_linha_grupo(n, "grupo", v) for n, v in (md["grupos"].items() if md else ()) if n not in nomes]
        if fora.get(mes):
            itens.append(_linha_grupo(FORA_DOS_GRUPOS, "fora", None, fora[mes]))
        if r_total and sum(pesos) <= 0:
            itens.append(_linha_grupo(SEM_GRUPO, "sem_grupo", None, 0, r_total))
        if md and md["ajuste"]:
            itens.append(_linha_grupo(AJUSTE, "ajuste", md["ajuste"]))
        if md and md["nao_lido"]:
            itens.append(_linha_grupo(NAO_LIDO, "nao_lido", md["nao_lido"]))
        total_medido = md["medido"] if md else 0
        custo = sum(i["custo_centavos"] for i in itens)
        linhas.append({"competencia": mes, "medicoes": md["medicoes"] if md else [], "medido_centavos": total_medido,
                       "apontado_centavos": sum(i["apontado_centavos"] for i in itens),
                       "rateado_centavos": sum(i["rateado_centavos"] for i in itens),
                       "custo_centavos": custo, "diferenca_centavos": total_medido - custo,
                       "previsto_centavos": previsto.get(mes), "grupos": itens})
    acumulado = {k: sum(x[k] for x in linhas) for k in ("medido_centavos", "apontado_centavos", "rateado_centavos",
                                                         "custo_centavos", "diferenca_centavos")}
    acumulado["previsto_centavos"] = sum(x["previsto_centavos"] or 0 for x in linhas)
    return {"contrato_id": contrato_id, "obra": c["nome_curto"] or c["numero_instrumento"], "grupos": nomes,
            "linhas": linhas, "acumulado": acumulado, "rm": _sincronizacao(conn)}
