"""Pagina Fechamento (issue #748): o que foi medido, aprovado, protocolado e recebido em cada mes de competencia de
2025 e 2026, na COTA da empresa, e o que esta' em aberto. So' leitura.

Pergunta da tela (decisao do dono de 10 e 16/11/2026): "quanto foi medido, aprovado, faturado em nota protocolada e
recebido em cada mes, e o que falta receber". Poucos numeros, exatos, que abrem por obra e por medicao.

O MES de todo numero e' a competencia da medicao. A nota e o recebimento caem na competencia da medicao a que a nota
esta' ligada (vinculo vigente em `nf_alocacoes`), nunca no mes da emissao ou da baixa.

Os numeros, por medicao (centavos inteiros; a cota de cada parcela por `contratos.cota`, arredondamento unico por
parcela; os totais sao somas dessas parcelas, entao fecham ao centavo com as linhas abertas):
- Medido: medicao enviada ao orgao (`medicoes.ESTADOS_NO_MEDIDO`: da planilha/carta enviada em diante; cancelada,
  desistida, prevista e planilha so' gerada ficam fora), pelo glossario: o aprovado e, sem boletim, o pedido.
  Medicao sem valor nenhum nao entra no medido.
- Aprovado: `_aprovado` (o valor do boletim; sem ele gravado, o pedido so' quando a nota ja' foi emitida, que e' a
  prova de que o orgao aprovou; antes disso a medicao fica so' no medido).
- Protocolado: as notas das medicoes protocoladas (`ESTADOS_PROTOCOLADO`), pelo valor bruto da nota. So' contam as
  notas que cobram o orgao (`_notas_por_medicao`): ativas, nao desconsideradas, da coligada da entidade do contrato
  (em consorcio, a fatura do consorcio, no valor cheio; a NFS-e da consorciada fica fora para nao contar duas vezes),
  de tipo de cobranca (`diretoria.CODTMV_COBRANCA`) ou ainda so' lida do PDF. A nota ligada a mais de uma medicao
  entra em cada uma pelo valor do vinculo (`valor_alocado_centavos`); ligada a uma so', pelo valor atual da nota.
- Recebido: `_recebimento`, a UNICA definicao (bruto por competencia: das notas do protocolado, as pagas, pelo mesmo
  valor bruto).
- Em aberto (a receber), em tres partes que a tela diz uma a uma:
  a) nota protocolada e nao paga, nota a nota, com a data do protocolo;
  b) medicao protocolada (e nao recebida) SEM nota ligada, pelo valor da medicao (aprovado, senao o pedido), com a
     data do protocolo. Entra no em aberto do mes;
  c) nota de cobranca em aberto no RM SEM medicao ligada (`_notas_sem_medicao`), com a data da emissao. Nao tem
     competencia: fica fora dos meses e do total, como subtotal a' parte. Pode ser a mesma cobranca de uma medicao de
     (b) enquanto o vinculo nao e' feito; nao se casa por valor (`docs/adr/0005`), a tela diz isso numa frase.
  O total do em aberto e' (a) + (b). Com o total a receber ainda nao liberado no cadastro
  (`geral.yaml: diretoria.total_a_receber_liberado`, `diretoria._liberado`), os valores do em aberto vem nulos, como
  na lista de Obras.
- Cobertura do vinculo, por ano: quanto do aprovado das medicoes com nota emitida (ou alem) tem nota ligada.

So' aparece o que tem lancamento: mes sem medicao nao vira linha, e nada e' estimado. O em aberto de competencias
anteriores a 2025 fica contado a' parte.
"""
from decimal import ROUND_HALF_UP, Decimal

from app import contratos, db, diretoria, medicoes, sincronizacao_rm

ANOS = ("2025", "2026")
ESTADOS_APROVADO = ("boletim_recebido", "espelho_gerado", "espelho_enviado", "nota_emitida", "protocolada",
                    "nf_emitida", "recebida")
# a nota emitida e' a prova de que o orgao aprovou: sem o valor do boletim gravado, o pedido conta como aprovado daqui em diante
ESTADOS_COM_NOTA = ("nota_emitida", "protocolada", "nf_emitida", "recebida")
ESTADOS_PROTOCOLADO = ("protocolada", "nf_emitida", "recebida")
ESTADOS_EM_COBRANCA = ("protocolada", "nf_emitida")       # protocolada e ainda nao recebida
NUMEROS = ("medido_centavos", "aprovado_centavos", "protocolado_centavos", "recebido_centavos", "em_aberto_centavos")
SOMAS = NUMEROS + ("sem_nota_centavos",)                    # sem_nota: a parte (b) do em aberto, ja' dentro dele


def _zero() -> dict:
    return dict.fromkeys(SOMAS, 0)


def _somar(destino: dict, origem: dict) -> None:
    for k in SOMAS:
        destino[k] += origem[k]


def _aprovado(m: dict) -> int | None:
    """O aprovado de uma medicao, em valor cheio (decisao da revisao da PR #754; `GLOSSARY.md`, Aprovado): o valor do
    boletim; sem ele gravado, o pedido, mas so' com a nota ja' emitida (ou alem). Antes da nota, sem o valor do
    boletim, a medicao nao conta como aprovada."""
    if m["estado"] not in ESTADOS_APROVADO:
        return None
    if m["aprovado"] is not None:
        return m["aprovado"]
    return m["pedido"] if m["estado"] in ESTADOS_COM_NOTA else None


def _recebimento(conn, m: dict, nota: dict, valor_cota: int) -> tuple[bool, int]:
    """A UNICA definicao do recebido desta pagina: (recebida, valor que entra no recebido). Hoje e' "bruto por
    competencia": a nota da medicao recebida (baixa no RM ou registro do administrador, docs/adr/0006) ou a nota com
    todos os titulos baixados no RM, faltando ate' `diretoria.TOLERANCIA_CENTAVOS`, entra pelo seu valor bruto (o
    mesmo do protocolado), no mes da competencia da medicao. Titulo baixado sem valor (glosa, compensacao) nao e'
    recebimento; nota paga em parte fica inteira em aberto. Trocar para outra base (o liquido baixado, pelo mes do
    pagamento) e' trocar esta funcao e o mes em `_fechamento`."""
    recebida = m["estado"] == "recebida" or _quitada(conn, nota["nota_id"])
    return recebida, valor_cota if recebida else 0


def _medicoes(conn) -> list[dict]:
    estados = medicoes.ESTADOS_NO_MEDIDO
    return [dict(r) for r in conn.execute(
        f"""SELECT m.id, m.contrato_id, m.numero, m.tipo, m.competencia, m.estado,
                   m.valor_protocolado_centavos AS pedido, m.valor_atestado_centavos AS aprovado,
                   c.percentual_direito_bp AS pct, COALESCE(c.nome_curto, c.numero_instrumento) AS obra,
                   e.coligada_rm AS coligada,
                   (SELECT MIN(mp.data) FROM medicao_protocolos mp WHERE mp.medicao_id=m.id AND mp.etapa='nota') AS protocolo_em
            FROM medicoes m JOIN contratos c ON c.id=m.contrato_id
            JOIN entidades e ON e.id=COALESCE(c.entidade_id, 1)
            WHERE m.estado IN ({','.join('?' * len(estados))})
            ORDER BY m.competencia, obra, m.contrato_id, m.numero, m.tipo""", estados)]


def _notas_por_medicao(conn, ids: set[int]) -> dict[int, list[dict]]:
    """As notas que cobram o orgao, por medicao, com o valor de cada vinculo (ver o docstring do modulo)."""
    cobranca = diretoria.CODTMV_COBRANCA
    linhas = [dict(r) for r in conn.execute(
        f"""SELECT a.medicao_id, a.valor_alocado_centavos, n.id AS nota_id, n.numero, n.valor_centavos, n.coligada
            FROM nf_alocacoes a JOIN notas_fiscais n ON n.id=a.nota_id
            WHERE a.desfeita_em IS NULL AND n.situacao='ativa' AND n.desconsiderada_em IS NULL
              AND (n.codtmv IS NULL OR n.codtmv IN ({','.join('?' * len(cobranca))}))
            ORDER BY n.emissao, n.id""", cobranca) if r["medicao_id"] in ids]
    vinculos: dict[int, int] = {}
    for x in linhas:
        vinculos[x["nota_id"]] = vinculos.get(x["nota_id"], 0) + 1
    out: dict[int, list[dict]] = {}
    for x in linhas:
        valor = x["valor_centavos"] if vinculos[x["nota_id"]] == 1 else x["valor_alocado_centavos"]
        out.setdefault(x["medicao_id"], []).append({**x, "valor_cheio": valor})
    return out


def _quitada(conn, nota_id: int) -> bool:
    """Todos os titulos (nao cancelados) da nota baixados no RM, faltando ate' a tolerancia. Sem titulo, nao."""
    if not conn.execute("SELECT 1 FROM baixas WHERE nota_id=? AND status_lan<>2", (nota_id,)).fetchone():
        return False
    falta = sincronizacao_rm._falta_por_titulo(conn, nota_id)
    return falta is not None and falta <= diretoria.TOLERANCIA_CENTAVOS


def _numero_nota(numero) -> str:
    s = str(numero or "").strip()
    return str(int(s)) if s.isdigit() else s


def _linha_medicao(conn, m: dict, notas: list[dict]) -> dict:
    cota = lambda v: contratos.cota(v, m["pct"]) or 0
    valor = m["aprovado"] if m["aprovado"] is not None else m["pedido"]
    aprovado = _aprovado(m)
    n = _zero()
    n["medido_centavos"] = cota(valor) if valor is not None else 0
    n["aprovado_centavos"] = cota(aprovado) if aprovado is not None else 0
    # em consorcio, a NFS-e da consorciada nao cobra o orgao
    ligadas = [x for x in notas if x["coligada"] == m["coligada"]]
    saida = []
    if m["estado"] in ESTADOS_PROTOCOLADO:
        for x in ligadas:
            v = cota(x["valor_cheio"])
            recebida, recebido = _recebimento(conn, m, x, v)
            n["protocolado_centavos"] += v
            n["recebido_centavos"] += recebido
            n["em_aberto_centavos"] += v - recebido
            saida.append({"nota_id": x["nota_id"], "numero": _numero_nota(x["numero"]), "valor_centavos": v,
                          "recebida": recebida})
    sem_nota = m["estado"] in ESTADOS_EM_COBRANCA and not ligadas
    if sem_nota and valor is not None:                       # (b): protocolada sem nota ligada, pelo valor da medicao
        n["sem_nota_centavos"] = n["medido_centavos"]
        n["em_aberto_centavos"] += n["sem_nota_centavos"]
    return {"medicao_id": m["id"], "contrato_id": m["contrato_id"], "obra": m["obra"], "numero": m["numero"],
            "tipo": m["tipo"], "estado": m["estado"], "competencia": m["competencia"],
            "protocolo_em": (m["protocolo_em"] or "")[:10] or None, **n, "notas": saida, "sem_nota": sem_nota,
            # cobertura do vinculo: o aprovado das medicoes que ja' deveriam ter nota, e se alguma esta' ligada
            "_base_cobertura": n["aprovado_centavos"] if m["estado"] in ESTADOS_COM_NOTA else 0,
            "_coberta": bool(ligadas)}


def _notas_sem_medicao(conn) -> dict:
    """Notas de cobranca ativas sem vinculo com medicao enviada, na obra pelo centro de custo
    (`diretoria._notas_do_rm`), na cota e pelo valor bruto. Em aberto no RM (nenhum titulo, ou titulo nao baixado):
    uma linha por nota, com a data da emissao, de qualquer ano (e' cobranca que ainda nao entrou). Paga: so' contada,
    das emitidas em 2025 e 2026. Nenhuma das duas tem competencia, entao ficam fora dos meses e dos totais."""
    abertas, pagas = [], {"quantidade": 0, "valor_centavos": 0}
    for n, c, tem_medicao in diretoria._notas_do_rm(conn):
        if tem_medicao or n["situacao"] != "ativa":
            continue
        v = contratos.cota(n["valor_centavos"], c["pct"]) or 0
        if _quitada(conn, n["id"]):
            if (n["emissao"] or "")[:4] in ANOS:
                pagas["quantidade"] += 1
                pagas["valor_centavos"] += v
            continue
        numero = conn.execute("SELECT numero FROM notas_fiscais WHERE id=?", (n["id"],)).fetchone()[0]
        abertas.append({"nota_id": n["id"], "numero": _numero_nota(numero), "contrato_id": c["id"], "obra": c["obra"],
                        "emissao": (n["emissao"] or "")[:10] or None, "valor_centavos": v})
    abertas.sort(key=lambda e: (e["emissao"] or "9999", e["obra"], e["numero"]))
    return {"em_aberto": abertas, "em_aberto_centavos": sum(e["valor_centavos"] for e in abertas), "pagas": pagas}


def _cobertura(linhas: list[dict]) -> dict:
    """Por ano: o aprovado das medicoes com nota emitida (ou alem), quanto dele tem nota ligada e o percentual (uma
    casa, meio para cima; nulo sem base)."""
    out = {}
    for ano in ANOS:
        xs = [x for x in linhas if x["competencia"][:4] == ano and x["_base_cobertura"]]
        base = sum(x["_base_cobertura"] for x in xs)
        ligado = sum(x["_base_cobertura"] for x in xs if x["_coberta"])
        pct = (Decimal(ligado) * 100 / Decimal(base)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP) if base else None
        out[ano] = {"aprovado_centavos": base, "com_nota_centavos": ligado, "sem_nota_centavos": base - ligado,
                    "medicoes_sem_nota": sum(1 for x in xs if not x["_coberta"]),
                    "percentual": float(pct) if pct is not None else None}
    return out


def fechamento(conn) -> dict:
    with db.leitura(conn):
        return _fechamento(conn)


def _fechamento(conn) -> dict:
    ms = _medicoes(conn)
    notas = _notas_por_medicao(conn, {m["id"] for m in ms})
    linhas = [_linha_medicao(conn, m, notas.get(m["id"], [])) for m in ms]
    cobertura = _cobertura(linhas)

    meses: dict[str, dict] = {}
    anteriores = {"quantidade": 0, "valor_centavos": 0}
    em_aberto = []
    for x in linhas:
        x.pop("_base_cobertura"); x.pop("_coberta")
        ano = x["competencia"][:4]
        abertas = [{"tipo_aberto": "nota", "nota_id": nt["nota_id"], "numero": nt["numero"],
                    "valor_centavos": nt["valor_centavos"]} for nt in x["notas"] if not nt["recebida"]]
        if x["sem_nota_centavos"]:
            abertas.append({"tipo_aberto": "sem_nota", "nota_id": None, "numero": None, "valor_centavos": x["sem_nota_centavos"]})
        if ano < ANOS[0]:
            anteriores["quantidade"] += len(abertas)
            anteriores["valor_centavos"] += sum(e["valor_centavos"] for e in abertas)
            continue
        if ano not in ANOS:
            continue
        mes = meses.setdefault(x["competencia"], {"competencia": x["competencia"], **_zero(), "obras": {}})
        obra = mes["obras"].setdefault(x["contrato_id"], {"contrato_id": x["contrato_id"], "obra": x["obra"],
                                                          **_zero(), "medicoes": []})
        obra["medicoes"].append(x)
        _somar(obra, x)
        _somar(mes, x)
        em_aberto += [{**e, "contrato_id": x["contrato_id"], "obra": x["obra"], "medicao_id": x["medicao_id"],
                       "medicao_numero": x["numero"], "tipo": x["tipo"], "competencia": x["competencia"],
                       "protocolo_em": x["protocolo_em"]} for e in abertas]

    lista = []
    for comp in sorted(meses):
        m = meses[comp]
        m["obras"] = sorted(m["obras"].values(), key=lambda o: (o["obra"], o["contrato_id"]))
        lista.append(m)
    por_ano = {a: {**_zero(), "meses": 0} for a in ANOS}
    for m in lista:
        _somar(por_ano[m["competencia"][:4]], m)
        por_ano[m["competencia"][:4]]["meses"] += 1
    # comparacao: o acumulado de janeiro ate' o ultimo mes com lancamento do ano mais novo, nos dois anos
    novo = [m["competencia"] for m in lista if m["competencia"][:4] == ANOS[-1]]
    ate = novo[-1][5:7] if novo else None
    acumulado = {a: _zero() for a in ANOS}
    if ate:
        for m in lista:
            if m["competencia"][5:7] <= ate:
                _somar(acumulado[m["competencia"][:4]], m)
    em_aberto.sort(key=lambda e: (e["protocolo_em"] or "9999", e["obra"], e["competencia"], e["numero"] or ""))
    saida = {"anos": list(ANOS), "meses": lista, "por_ano": por_ano, "acumulado": {"ate_mes": ate, **acumulado},
             "em_aberto": em_aberto, "em_aberto_centavos": sum(e["valor_centavos"] for e in em_aberto),
             # as duas partes que somam o total: (a) nota protocolada nao paga e (b) medicao protocolada sem nota ligada
             "em_aberto_notas_centavos": sum(e["valor_centavos"] for e in em_aberto if e["tipo_aberto"] == "nota"),
             "em_aberto_sem_nota_centavos": sum(e["valor_centavos"] for e in em_aberto if e["tipo_aberto"] == "sem_nota"),
             "em_aberto_anteriores": anteriores, "notas_sem_medicao": _notas_sem_medicao(conn),
             "cobertura": cobertura, "total_a_receber_liberado": diretoria._liberado(conn)}
    if not saida["total_a_receber_liberado"]:
        _esconder_em_aberto(saida)
    return saida


def _esconder_em_aberto(f: dict) -> None:
    """Sem o total a receber liberado no cadastro, o em aberto nao mostra valor (a trava de `diretoria._liberado`, a
    mesma da lista de Obras): as linhas continuam, com o valor nulo. Medido, aprovado, protocolado e recebido ficam."""
    def nulo(x):
        x["em_aberto_centavos"] = None
        x["sem_nota_centavos"] = None
    for m in f["meses"]:
        nulo(m)
        for o in m["obras"]:
            nulo(o)
            for md in o["medicoes"]:
                nulo(md)
    for a in f["anos"]:
        nulo(f["por_ano"][a])
        nulo(f["acumulado"][a])
    for e in f["em_aberto"] + f["notas_sem_medicao"]["em_aberto"]:
        e["valor_centavos"] = None
    f["em_aberto_centavos"] = f["em_aberto_notas_centavos"] = f["em_aberto_sem_nota_centavos"] = None
    f["notas_sem_medicao"]["em_aberto_centavos"] = None
    f["em_aberto_anteriores"]["valor_centavos"] = None
