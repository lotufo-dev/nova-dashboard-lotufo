"""Pagina Fechamento (issue #748): o que foi medido, aprovado, protocolado e recebido em cada mes de competencia de
2025 e 2026, na COTA da empresa, e o que esta' em aberto, nota a nota. So' leitura.

Pergunta da tela (decisao do dono de 10 e 16/11/2026): "quanto foi medido, aprovado, faturado em nota protocolada e
recebido em cada mes, e o que falta receber, nota a nota". Poucos numeros, exatos, que abrem por obra e por medicao.

O MES de todo numero e' a competencia da medicao. A nota e o recebimento caem na competencia da medicao a que a nota
esta' ligada (vinculo vigente em `nf_alocacoes`), nunca no mes da emissao ou da baixa.

Os numeros, por medicao (centavos inteiros; a cota de cada parcela por `contratos.cota`, arredondamento unico por
parcela; os totais sao somas dessas parcelas, entao fecham ao centavo com as linhas abertas):
- Medido: medicao enviada ao orgao (`medicoes.ESTADOS_NO_MEDIDO`: da planilha/carta enviada em diante; cancelada,
  desistida, prevista e planilha so' gerada ficam fora), pelo glossario: o aprovado e, sem boletim, o pedido.
  Medicao sem valor nenhum nao entra no medido.
- Aprovado: medicao com boletim (estado de `ESTADOS_APROVADO`), pelo aprovado; sem o valor do boletim gravado (o
  legado), o pedido, como o medido. Assim, medido - aprovado e' exatamente o que ainda esta' em analise.
- Protocolado: as notas das medicoes protocoladas (`ESTADOS_PROTOCOLADO`), pelo valor bruto da nota. So' contam as
  notas que cobram o orgao: ativas, nao desconsideradas, da coligada da entidade do contrato (em consorcio, a fatura
  do consorcio, no valor cheio; a NFS-e da consorciada fica fora para nao contar duas vezes), de tipo de cobranca
  (`diretoria.CODTMV_COBRANCA`) ou ainda so' lida do PDF. A nota ligada a mais de uma medicao entra em cada uma pelo
  valor do vinculo (`valor_alocado_centavos`); ligada a uma so', pelo valor atual da nota.
- Recebido: das notas do protocolado, as recebidas, pelo mesmo valor bruto (o recebido nunca passa do protocolado e
  protocolado - recebido = em aberto, ao centavo). Recebida e' a nota da medicao recebida (baixa no RM ou registro do
  administrador, docs/adr/0006) ou a nota com todos os titulos baixados no RM, faltando ate'
  `diretoria.TOLERANCIA_CENTAVOS` (titulo a titulo, `sincronizacao_rm._falta_por_titulo`). Titulo baixado sem valor
  (glosa, compensacao) nao e' recebimento: a nota fica em aberto. Nota paga em parte fica em aberto inteira.
- Em aberto: as notas do protocolado ainda nao recebidas, uma linha por nota (e medicao), com a data do primeiro
  protocolo da nota da medicao.

So' aparece o que tem lancamento: mes sem medicao nao vira linha, e nada e' estimado. Duas contagens ficam fora dos
meses e dos totais: as notas de cobranca emitidas em 2025 e 2026 sem medicao ligada (sem competencia, nao tem mes) e
o em aberto de competencias anteriores a 2025.
"""
from app import contratos, db, diretoria, medicoes, sincronizacao_rm

ANOS = ("2025", "2026")
ESTADOS_APROVADO = ("boletim_recebido", "espelho_gerado", "espelho_enviado", "nota_emitida", "protocolada",
                    "nf_emitida", "recebida")
ESTADOS_PROTOCOLADO = ("protocolada", "nf_emitida", "recebida")
NUMEROS = ("medido_centavos", "aprovado_centavos", "protocolado_centavos", "recebido_centavos", "em_aberto_centavos")


def _zero() -> dict:
    return dict.fromkeys(NUMEROS, 0)


def _somar(destino: dict, origem: dict) -> None:
    for k in NUMEROS:
        destino[k] += origem[k]


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
    n = _zero()
    n["medido_centavos"] = cota(valor) if valor is not None else 0
    n["aprovado_centavos"] = cota(valor) if valor is not None and m["estado"] in ESTADOS_APROVADO else 0
    saida = []
    if m["estado"] in ESTADOS_PROTOCOLADO:
        for x in notas:
            if x["coligada"] != m["coligada"]:
                continue                       # em consorcio, a NFS-e da consorciada nao cobra o orgao
            recebida = m["estado"] == "recebida" or _quitada(conn, x["nota_id"])
            v = cota(x["valor_cheio"])
            n["protocolado_centavos"] += v
            if recebida:
                n["recebido_centavos"] += v
            else:
                n["em_aberto_centavos"] += v
            saida.append({"nota_id": x["nota_id"], "numero": _numero_nota(x["numero"]), "valor_centavos": v,
                          "recebida": recebida})
    return {"medicao_id": m["id"], "contrato_id": m["contrato_id"], "obra": m["obra"], "numero": m["numero"],
            "tipo": m["tipo"], "estado": m["estado"], "competencia": m["competencia"],
            "protocolo_em": (m["protocolo_em"] or "")[:10] or None, **n, "notas": saida}


def _notas_sem_medicao(conn) -> dict:
    """Notas de cobranca ativas, emitidas em 2025 e 2026, na obra pelo centro de custo (`diretoria._notas_do_rm`),
    sem vinculo com medicao enviada: nao tem competencia, entao ficam fora dos meses, contadas a' parte, na cota."""
    quantidade, valor = 0, 0
    for n, c, tem_medicao in diretoria._notas_do_rm(conn):
        if tem_medicao or n["situacao"] != "ativa" or (n["emissao"] or "")[:4] not in ANOS:
            continue
        quantidade += 1
        valor += contratos.cota(n["valor_centavos"], c["pct"]) or 0
    return {"quantidade": quantidade, "valor_centavos": valor}


def fechamento(conn) -> dict:
    with db.leitura(conn):
        return _fechamento(conn)


def _fechamento(conn) -> dict:
    ms = _medicoes(conn)
    notas = _notas_por_medicao(conn, {m["id"] for m in ms})
    linhas = [_linha_medicao(conn, m, notas.get(m["id"], [])) for m in ms]

    meses: dict[str, dict] = {}
    anteriores = {"quantidade": 0, "valor_centavos": 0}
    em_aberto = []
    for x in linhas:
        ano = x["competencia"][:4]
        if ano < ANOS[0]:
            for nt in x["notas"]:
                if not nt["recebida"]:
                    anteriores["quantidade"] += 1
                    anteriores["valor_centavos"] += nt["valor_centavos"]
            continue
        if ano not in ANOS:
            continue
        mes = meses.setdefault(x["competencia"], {"competencia": x["competencia"], **_zero(), "obras": {}})
        obra = mes["obras"].setdefault(x["contrato_id"], {"contrato_id": x["contrato_id"], "obra": x["obra"],
                                                          **_zero(), "medicoes": []})
        obra["medicoes"].append(x)
        _somar(obra, x)
        _somar(mes, x)
        em_aberto += [{"nota_id": nt["nota_id"], "numero": nt["numero"], "contrato_id": x["contrato_id"],
                       "obra": x["obra"], "medicao_id": x["medicao_id"], "medicao_numero": x["numero"],
                       "tipo": x["tipo"], "competencia": x["competencia"], "protocolo_em": x["protocolo_em"],
                       "valor_centavos": nt["valor_centavos"]} for nt in x["notas"] if not nt["recebida"]]

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
    em_aberto.sort(key=lambda e: (e["protocolo_em"] or "9999", e["obra"], e["competencia"], e["numero"]))
    return {"anos": list(ANOS), "meses": lista, "por_ano": por_ano,
            "acumulado": {"ate_mes": ate, **acumulado}, "em_aberto": em_aberto,
            "em_aberto_centavos": sum(e["valor_centavos"] for e in em_aberto),
            "em_aberto_anteriores": anteriores, "notas_sem_medicao": _notas_sem_medicao(conn)}
