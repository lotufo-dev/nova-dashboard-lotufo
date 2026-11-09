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
O acumulado soma as linhas (os meses do cronograma ate' a ultima medicao ou custo tambem viram linha): material comprado num mes pode ser medido no seguinte.
"""
import datetime
import json
from decimal import Decimal

from app import contratos, cronograma, db, dinheiro, medicao_grupos, tempo
from app.cadastro_arquivos import _dentro_do_prefixo, _segmentos
from app.diretoria import FORA as ESTADOS_FORA   # fora do medido: o mesmo recorte da Carteira

DESATUALIZADO_HORAS = 24
REGRA_PROPORCIONAL = "proporcional"
NAO_LIDO = "Medido por grupo não lido"
AJUSTE = "Ajuste ao medido"
SEM_GRUPO = "Sem grupo"
FORA_DOS_GRUPOS = "Tarefa fora dos grupos"
MENSAGEM_SEM_CADASTRO = "Esta obra não tem cadastro de custo."


class SemCadastro(Exception):
    """Obra inexistente, sem cadastro de custo ou de consorcio (fora do piloto)."""


class RegraDesconhecida(ValueError):
    """Regra `sem_tarefa` do cadastro que esta tela nao sabe aplicar (hoje so' existe `proporcional`)."""


class CentroDisputado(ValueError):
    """Um centro de custo da obra (atual ou anterior) tambem esta' em outra obra com cadastro de custo: o mesmo
    lancamento do RM entraria inteiro nas duas. O cadastro nao proibe; a tela recusa em vez de duplicar calada."""


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


def _centros(c) -> list[str]:
    """O centro de custo atual e os anteriores do contrato, sem repeticao."""
    centros = [c["centro_custo_rm"], *json.loads(c["centros_custo_anteriores_rm"] or "[]")]
    return sorted({x.strip() for x in centros if x and x.strip()})


def _conferir_centros(conn, c) -> None:
    """CentroDisputado quando outra obra com cadastro de custo, na mesma coligada, tem um dos centros desta."""
    meus = set(_centros(c))
    if c["coligada_rm"] is None or not meus:
        return
    choques = []
    for o in conn.execute(f"SELECT c.id, c.nome_curto, c.numero_instrumento, c.centro_custo_rm, "
                          f"c.centros_custo_anteriores_rm {_OBRA} AND c.id<>? AND e.coligada_rm=? ORDER BY c.id",
                          (c["id"], c["coligada_rm"])):
        comuns = meus & set(_centros(o))
        if comuns:
            choques.append(f"{', '.join(sorted(comuns))} na obra {o['nome_curto'] or o['numero_instrumento']}")
    if choques:
        raise CentroDisputado("O centro de custo desta obra também está em outra obra com cadastro de custo ("
                              + "; ".join(choques) + "). Corrija o cadastro para cada centro ficar numa obra só.")


def _custo_por_mes(conn, c, grupos: list[dict]) -> tuple[dict, dict, dict]:
    """({mes: {grupo: apontado}}, {mes: fora dos grupos}, {mes: sem tarefa + estoque}) da coligada e dos centros."""
    apontado: dict[str, dict[str, int]] = {}
    fora: dict[str, int] = {}
    rateado: dict[str, int] = {}
    centros = _centros(c)
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
    """{mes: {"medicoes", "medido", "lida" (houve leitura), "grupos" {nome: medido}, "nao_lido", "ajuste",
    "por_planilha" (alguma leitura agrupada pelos titulos da planilha, nao pelo cadastro: issue #612)}}."""
    meses: dict[str, dict] = {}
    for m in conn.execute(
            f"""SELECT id, numero, competencia, COALESCE(valor_atestado_centavos, valor_protocolado_centavos) AS valor
                FROM medicoes WHERE contrato_id=? AND tipo='execucao' AND estado NOT IN ({','.join('?' * len(ESTADOS_FORA))})
                  AND COALESCE(valor_atestado_centavos, valor_protocolado_centavos) IS NOT NULL
                ORDER BY competencia, numero""", (contrato_id, *ESTADOS_FORA)):
        mes = meses.setdefault(m["competencia"], {"medicoes": [], "medido": 0, "lida": False, "grupos": {},
                                                   "nao_lido": 0, "ajuste": 0, "leituras": [], "por_planilha": False})
        mes["medicoes"].append({"id": m["id"], "numero": m["numero"], "nome": f"{m['numero']}ª medição"})
        mes["medido"] += m["valor"]
        lido = medicao_grupos.grupos(conn, m["id"])
        # na ordem: a ultima e' a da medicao mais recente (None: sem leitura valida)
        mes["leituras"].append((mes["medicoes"][-1]["nome"], lido if lido["leitura"] is not None else None))
        if lido["leitura"] is None:
            mes["nao_lido"] += m["valor"]
            continue
        mes["lida"] = True
        mes["por_planilha"] = mes["por_planilha"] or lido["leitura"]["grupo_por"] != "cadastro"
        soma = 0
        for g in lido["grupos"]:
            mes["grupos"][g["nome"]] = mes["grupos"].get(g["nome"], 0) + g["valor_medido_centavos"]
            soma += g["valor_medido_centavos"]
        mes["ajuste"] += m["valor"] - soma
    return meses


def _linha_grupo(nome: str, tipo: str, medido, apontado: int = 0, rateado: int = 0, completo: bool = True) -> dict:
    """`completo` = False: o medido do grupo no mes nao e' todo conhecido (alguma medicao da competencia sem leitura
    da planilha); o medido lido aparece, mas a diferenca contra o custo do mes inteiro nao existe."""
    custo = apontado + rateado
    return {"nome": nome, "tipo": tipo, "medido_centavos": medido, "apontado_centavos": apontado,
            "rateado_centavos": rateado, "custo_centavos": custo,
            # medido desconhecido (mes sem leitura da planilha, ou so' parte das medicoes lida; linha so' de custo):
            # sem diferenca, nunca "-custo" nem "medido parcial - custo"
            "diferenca_centavos": None if medido is None or not completo else medido - custo}


def _itens_chave(grupos: list[dict], linhas: list[dict], medido: dict[str, dict]) -> list[dict]:
    """Issue #492: o custo por unidade medida do item-chave de cada grupo que o cadastro tem (um por grupo).
    Custo do grupo = o acumulado da tela (apontado + rateado, todas as competencias); quantidade acumulada e preco
    unitario = os do item, no grupo dele, na planilha lida mais recente que o tem (o preco de um aditivo vale dali em
    diante). Quantidade ausente ou nao positiva: "sem_medicao"; custo zero ou negativo (estorno maior que o lancado):
    "sem_custo"; nos dois, sem custo unitario nem diferenca.
    Diferenca = preco do contrato - custo por unidade, em centavos por unidade (o mesmo sentido da tela)."""
    leituras = [lt for mes in sorted(medido) for lt in medido[mes]["leituras"]]
    saida = []
    for g in grupos:
        chave = g.get("item_chave")
        if not chave:
            continue
        custo = sum(i["custo_centavos"] for x in linhas for i in x["grupos"]
                    if i["tipo"] == "grupo" and i["nome"] == g["nome"])
        # "1.2." e "1.2" sao o mesmo item (a mesma comparacao por segmento do cadastro)
        # so' a planilha da medicao mais recente: sem leitura valida ou sem o item no grupo, "sem_medicao" (uma
        # quantidade antiga contra o custo acumulado de agora daria custo por unidade errado; gate Sol, #492)
        nome_ult, lido_ult = leituras[-1] if leituras else (None, None)
        medicao, item = next(((nome_ult, it) for gr in (lido_ult["grupos"] if lido_ult else [])
                              if gr["nome"] == g["nome"] for it in gr["itens"]
                              if _segmentos(str(it["item"] or "").strip()) == _segmentos(chave["codigo"])),
                             (None, None))
        qtd = item["quantidade_acumulada"] if item else None
        preco = item["preco_unitario_centavos"] if item else None
        if qtd is None or Decimal(qtd) <= 0:
            situacao, unitario = "sem_medicao", None
        elif custo <= 0:
            situacao, unitario = "sem_custo", None
        else:
            situacao, unitario = "ok", dinheiro.por_unidade(custo, Decimal(qtd))
        saida.append({"grupo": g["nome"], "item": chave["codigo"], "descricao": item["descricao"] if item else None,
                      "unidade": chave["unidade"], "quantidade_acumulada": qtd,
                      "medicao": medicao, "custo_centavos": custo,
                      "custo_unitario_centavos": unitario, "preco_unitario_centavos": preco,
                      "diferenca_centavos": None if unitario is None or preco is None else preco - unitario,
                      "situacao": situacao})
    return saida


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
    o acumulado. SemCadastro na obra fora do seletor; CentroDisputado quando outra obra tem o mesmo centro. Tudo
    de um retrato so' do banco (a carga do RM troca o custo e o estoque numa transacao)."""
    with db.leitura(conn):
        return _custo_da_obra(conn, contrato_id)


def _custo_da_obra(conn, contrato_id: int) -> dict:
    c = conn.execute(f"SELECT c.*, e.coligada_rm {_OBRA} AND c.id=?", (contrato_id,)).fetchone()
    if c is None:
        raise SemCadastro(MENSAGEM_SEM_CADASTRO)
    regra = c["custo_sem_tarefa"] or REGRA_PROPORCIONAL
    if regra != REGRA_PROPORCIONAL:
        raise RegraDesconhecida(f"Regra do custo sem tarefa desconhecida no cadastro: {regra}")
    _conferir_centros(conn, c)
    grupos = contratos.custo_grupos(conn, contrato_id)
    nomes = [g["nome"] for g in grupos]
    apontado, fora, rateado = _custo_por_mes(conn, c, grupos)
    medido = _medido_por_mes(conn, contrato_id)
    previsto = cronograma.previsto_efetivo(conn, contrato_id)
    # meses com medicao ou custo e, como referencia, os do cronograma ate' o ultimo deles (sem nenhum: ate' o mes
    # atual), para a obra so' com cronograma mostrar o previsto e o acumulado ser a soma das linhas
    com_dado = {*apontado, *fora, *rateado, *medido}
    corte = max(com_dado) if com_dado else tempo.hoje_local().strftime("%Y-%m")
    linhas = []
    for mes in sorted(com_dado | {comp for comp in previsto if comp <= corte}):
        md = medido.get(mes)
        ap = apontado.get(mes, {})
        r_total = rateado.get(mes, 0)
        pesos = [max(0, ap.get(n, 0)) for n in nomes]
        partes = dinheiro.ratear_proporcional(r_total, pesos) if sum(pesos) > 0 else [0] * len(nomes)

        def medido_de(nome):
            # leitura pelos titulos da planilha (sem nº de item, issue #612): o medido do grupo do cadastro e'
            # desconhecido (ligar titulo a grupo e' outra issue), nunca 0 com a diferenca "-custo"
            if md is None or not md["lida"] or md["por_planilha"]:
                return None
            return md["grupos"].get(nome, 0)

        # a diferenca por grupo so' existe com todas as medicoes da competencia lidas
        completo = md is None or md["nao_lido"] == 0
        itens = [_linha_grupo(n, "grupo", medido_de(n), ap.get(n, 0), partes[i], completo)
                 for i, n in enumerate(nomes)]
        # grupo da planilha que o cadastro nao tem (o "outros" da leitura): so' o medido
        itens += [_linha_grupo(n, "grupo", v, completo=completo and not md["por_planilha"])
                  for n, v in (md["grupos"].items() if md else ()) if n not in nomes]
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
            "linhas": linhas, "acumulado": acumulado, "itens_chave": _itens_chave(grupos, linhas, medido),
            "rm": _sincronizacao(conn)}
