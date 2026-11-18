"""Pagina Resumo das medicoes (issues #749 e #805): em que etapa do ciclo esta' a medicao de cada obra numa
competencia, as obras sem medicao nela e as medicoes de competencias anteriores ainda em aberto. So' leitura.

A pergunta da tela (decisao do dono de 18/11/2026, #805) e' de quem le: "onde esta' o dinheiro do mes?". A resposta e'
um quadro com uma coluna por etapa e um cartao por medicao; os numeros de cada coluna, as referencias das variacoes e
os dois lados da diferenca saem daqui, prontos (a tela nao soma).

As etapas sao as do glossario, na ordem do ciclo: em analise, boletim, nota, protocolado, recebido.

A ETAPA DA VEZ sai do ESTADO da medicao (`etapa_da_vez`), nunca de data, de valor nem dos passos: planilha/carta
enviada = em analise; boletim recebido e espelho (gerado ou enviado) = boletim, a medicao que espera a nota; nota
emitida = nota; protocolada = protocolado; recebida = recebido. A planilha/carta gerada e ainda nao enviada fica
`antes` do ciclo.

OS PASSOS (`medicoes.passos_das_medicoes`: a familia do orgao e a chave `passos_medicao` do contrato) so' dizem quais
etapas a obra tem (`etapas_do_fluxo`):

- em analise: a obra tem os passos "Planilha e carta" e "Análise do órgão" (a planilha/carta vai ao orgao e espera a
  analise dele). Na MT-PAR (#753) a "Análise do órgão" vem sem "Planilha e carta": e' o passo do boletim assinado, a
  planilha/carta nao vai ao orgao e a obra nao tem a etapa "em analise";
- boletim: tem "Espelhos" ou "Notas" (a medicao aprovada espera a nota);
- nota e recebido: sempre (o passo "Pagamento" e' obrigatorio no cadastro, e so' se paga contra a nota);
- protocolado: tem "Envio da nota" (a obra sem esse passo vai da nota ao recebido).

Quando o estado poe a medicao numa etapa que a obra nao tem (a lista do cadastro mudou depois, ou e' uma lista em que
o estado nao tem passo: planilha/carta enviada na obra sem "Análise do órgão", protocolo registrado na obra sem "Envio
da nota"), a linha DESSA medicao mostra a etapa do estado mesmo assim (`etapas_da_medicao`): o estado e' o registro, e
empurrar a medicao para a etapa vizinha diria que ela foi aprovada, teve nota ou foi protocolada sem ter sido. As
outras etapas que a obra nao tem continuam fora da linha.

A SITUACAO de cada etapa da linha: `atual` na etapa da vez (`feito` no recebido, que encerra o ciclo); `futuro` nas
seguintes; nas anteriores, `feito` so' com o registro do evento e `sem_registro` sem ele (a medicao protocolada direto
da prevista, a que seguiu sem boletim, a que veio do historico). A posicao nao prova nada: a pagina so' afirma o que
tem registro. O registro de cada etapa: em analise, o envio da planilha/carta; boletim, o valor aprovado ou a data do
boletim; nota, a data da emissao; protocolado, o primeiro protocolo da nota. A data e' a do evento registrado; sem ela,
vem nula e a tela mostra o traco. Nada e' estimado.

Valor: o medido (o aprovado e, sem boletim, o pedido) na COTA da Lotufo, medicao a medicao, com o arredondamento
unico de `contratos.cota`; medicao sem valor nenhum vem nula. So' mede a medicao enviada ao orgao
(`medicoes.ESTADOS_NO_MEDIDO`, a regra do glossario e de `docs/adr/0012`): a planilha/carta gerada e ainda nao enviada
aparece na linha, sem valor, e a soma do mes fecha com o medido do Fechamento (`fechamento.py`). Execucao, projeto e
reajuste tem linha e valor: aqui o medido e' o de cada medicao, nao o medido da obra (que deixa o reajuste fora). O
valor de cada etapa na contagem do mes e' esse medido das medicoes que estao nela; nao e' o bruto das notas, que e'
o que o Fechamento chama de protocolado e de recebido.

A prevista, a cancelada e a desistida nao contam: a obra so' com elas esta' sem medicao no mes (a regra do quadro do
mes, `medicoes._quadro_do_mes`).

Obra sem o passo "Envio da nota" (#743): nao tem a etapa protocolado; a nota emitida fica na etapa da nota, desde a
emissao, ate' a baixa do RM (ou o registro do administrador) leva'-la a recebido, sem protocolo.

O QUE A #805 ACRESCENTOU (todo numero na cota, em centavos inteiros):

- MEDIDO DO MES (`medido`): o medido da competencia, o MESMO numero do Fechamento (`fechamento.medido_das_competencias`:
  as medicoes e a conta de `fechamento.medido_na_cota`). E' a soma dos valores das cinco etapas: as duas contas tem a
  mesma regra (a medicao enviada ao orgao; o aprovado e, sem boletim, o pedido), e um teste confere que fecham. As
  referencias da variacao sao esse mesmo medido na competencia anterior (`mes_anterior`) e na mesma competencia do
  ano anterior (`ano_anterior`). So' na competencia ja' encerrada (anterior ao mes de hoje: o mes em curso ainda
  recebe medicao, a regra de `fechamento._medido_do_ano_anterior`), e so' quando a referencia e' de `ANO_INICIAL` em
  diante e teve medido; senao, nula.
- A MESMA ALTURA DO MES ANTERIOR (`mesma_altura`): a referencia da variacao do protocolado e do recebido. O valor de
  uma etapa e' um retrato de hoje (o medido das medicoes que estao nela), entao a referencia e' o mesmo retrato da
  competencia anterior na data em que faltavam para ela os mesmos dias: o mesmo dia de hoje, um mes antes (`ate`; dia
  31 num mes de 30 vira o ultimo dia). Hoje em 18/11 e a competencia de outubro: o que as medicoes de setembro tinham
  no protocolado e no recebido em 18/10. Onde cada medicao estava naquele dia sai das datas dos eventos, nunca da
  competencia: estava recebida com a data do recebimento ate' `ate`; estava no protocolado com a data do primeiro
  protocolo ate' `ate` e sem recebimento ate' la'. O valor e' o medido de hoje dessas medicoes.
  So' aparece o que tem lastro: se uma medicao da competencia anterior chegou a' etapa sem a data do evento (recebida
  sem a data do recebimento; protocolada, ou recebida depois de `ate`, sem a data do protocolo na obra que tem a
  etapa), a referencia daquela etapa vem nula e a tela nao mostra a variacao. Competencia anterior a `ANO_INICIAL` nao
  serve de referencia: `mesma_altura` vem nulo.
- TEMPO NA ETAPA (`na_etapa_desde`, `dias_uteis_na_etapa`): a data do evento que pos a medicao na etapa da vez e os
  dias uteis dela ate' hoje (`feriados.dias_uteis_entre`: o dia do evento conta, hoje nao). Sem a data, nulos: nada e'
  contado da competencia. A recebida nao esta' parada: leva a data e, com a emissao da nota registrada, os dias
  corridos da nota ao recebimento (`dias_da_nota_ao_recebimento`).
- DIFERENCA ENTRE O APROVADO E O PEDIDO (`pedido_do_aprovado_centavos`, `abaixo_do_pedido_centavos`,
  `acima_do_pedido_centavos`): a conta do Fechamento, medicao a medicao (`fechamento.diferenca_do_pedido`: a
  tolerancia de R$ 0,05 no valor cheio, tudo na cota); nulos sem os dois valores. O limite que separa a diferenca
  pequena da critica vai em `diferenca_critica_por_mil` (`avisos_medicao.ABAIXO_DO_PEDIDO_POR_MIL`, #741).
- FILTRO POR CONTRATANTE (`contratante`): recorta tudo (linhas, etapas, medido, referencias, obras sem medicao e meses
  anteriores) para as obras daquele contratante. `contratantes` lista, sem recorte, quem tem medicao na competencia
  ou em meses anteriores, com a quantidade de cada.
- MESES ANTERIORES: so' de `diretoria.ANO_INICIAL` em diante (decisao do dono: pendencia anterior a 2025 fica fora
  das telas da diretoria), por competencia, com a quantidade e o medido de cada uma e a contagem por etapa
  (`anteriores_etapas`).
"""
import calendar
import datetime

from app import avisos_medicao, contratos, db, diretoria, fechamento, feriados, medicoes, tempo

ETAPAS = ("em_analise", "boletim", "nota", "protocolado", "recebido")
ROTULO = {"antes": "Planilha/carta a enviar", "em_analise": "Em análise", "boletim": "Boletim", "nota": "Nota",
          "protocolado": "Protocolado", "recebido": "Recebido"}
# o estado da medicao -> a etapa em que ela esta'. `nf_emitida` e' o legado, que espera o orgao como a protocolada
_ETAPA_DO_ESTADO = {"planilha_gerada": "antes", "planilha_enviada": "em_analise", "boletim_recebido": "boletim",
                    "espelho_gerado": "boletim", "espelho_enviado": "boletim", "nota_emitida": "nota",
                    "protocolada": "protocolado", "nf_emitida": "protocolado", "recebida": "recebido"}
# o passo da barra da medicao (`medicoes.PASSOS`) cujo dia e' o evento que poe a medicao na etapa
_PASSO_DA_DATA = {"em_analise": 1, "boletim": 2, "nota": 4, "protocolado": 5, "recebido": 6}
_FORA = ("prevista", "cancelada", "desistida")
_ORDEM_TIPO = ("execucao", "projeto", "reajuste")


def etapas_do_fluxo(passos) -> tuple[str, ...]:
    """As etapas do ciclo que a obra tem, pelos passos da medicao (numeros de `medicoes.PASSOS`)."""
    tem = set(passos)
    # #753: o passo 2 sem o 1 e' o do boletim da MT-PAR, nao a espera pela analise da planilha/carta
    return tuple(e for e, vale in (("em_analise", {1, 2} <= tem), ("boletim", bool(tem & {3, 4})), ("nota", True),
                                   ("protocolado", 5 in tem), ("recebido", True)) if vale)


def etapa_da_vez(estado: str) -> str | None:
    """A etapa em que a medicao esta', pelo estado dela: `antes` (planilha/carta gerada e ainda nao enviada), uma de
    `ETAPAS`, ou None para a prevista, a cancelada e a desistida (quem chama as deixa de fora, `_FORA`). Os passos da
    obra nao entram aqui: eles nao mudam onde a medicao esta'."""
    return _ETAPA_DO_ESTADO.get(estado)


def etapas_da_medicao(estado: str, passos) -> tuple[str, ...]:
    """As etapas da linha de uma medicao, na ordem do ciclo: as que a obra tem e, quando o estado poe a medicao numa
    etapa que a obra nao tem, tambem essa (o estado e' o registro; ver o texto do modulo)."""
    do_fluxo = etapas_do_fluxo(passos)
    da_vez = etapa_da_vez(estado)
    return tuple(e for e in ETAPAS if e in do_fluxo or e == da_vez)


def _com_registro(m: dict, datas: dict) -> dict[str, bool]:
    """Se o sistema tem o registro do evento de cada etapa que pode ficar para tras: o envio da planilha/carta, o
    boletim (o valor aprovado ou a data dele), a emissao da nota e o protocolo da nota."""
    return {"em_analise": bool(m["planilha_enviada_em"]),
            "boletim": m["valor_atestado_centavos"] is not None or datas[2] is not None,
            "nota": bool(m["nota_emitida_em"]), "protocolado": bool(m["protocolado_em"])}


def _cota(m: dict) -> int | None:
    """O medido da medicao na cota; nulo sem valor e na medicao que ainda nao mede (planilha/carta nao enviada)."""
    if m["estado"] not in medicoes.ESTADOS_NO_MEDIDO:
        return None
    valor = m["valor_atestado_centavos"] if m["valor_atestado_centavos"] is not None else m["valor_protocolado_centavos"]
    return None if valor is None else contratos.cota(valor, m["pct"])


def _medicao(conn, m: dict, passos_de) -> dict | None:
    """A medicao com a etapa da vez e, de cada etapa da linha dela, a situacao (feito, sem_registro, atual, futuro) e
    a data registrada."""
    da_vez = etapa_da_vez(m["estado"])
    if da_vez is None:
        return None
    da_linha = etapas_da_medicao(m["estado"], passos_de(m))
    datas = medicoes._datas_dos_passos(conn, m)
    registro = _com_registro(m, datas)
    pos = da_linha.index(da_vez) if da_vez in da_linha else -1       # `antes`: nenhuma etapa alcancada
    etapas = []
    for i, e in enumerate(da_linha):
        if i > pos:
            situacao = "futuro"
        elif i == pos:
            situacao = "feito" if e == "recebido" else "atual"      # recebida, o ciclo acabou
        else:
            situacao = "feito" if registro[e] else "sem_registro"   # a posicao nao prova que a etapa aconteceu
        dia = datas[_PASSO_DA_DATA[e]] if situacao in ("feito", "atual") else None
        etapas.append({"etapa": e, "situacao": situacao, "data": dia.isoformat() if dia else None})
    return {"id": m["id"], "contrato_id": m["contrato_id"], "numero": m["numero"], "tipo": m["tipo"],
            "competencia": m["competencia"], "titulo": medicoes.titulo(m), "etapa": da_vez, "etapas": etapas,
            "valor_centavos": _cota(m),
            # #805: os dois lados da diferenca aprovado x pedido, a conta do Fechamento; nulo sem os dois valores
            "diferenca": fechamento.diferenca_do_pedido(m["estado"], m["valor_atestado_centavos"],
                                                        m["valor_protocolado_centavos"], m["pct"])}


def _dia(iso: str | None) -> datetime.date | None:
    return datetime.date.fromisoformat(iso) if iso else None


def _tempo_na_etapa(etapa: str, datas: dict, hoje: datetime.date) -> dict:
    """#805: desde quando a linha esta' na etapa da vez (a data do evento) e ha' quantos dias uteis; na recebida, os
    dias corridos da emissao da nota ao recebimento. Sem a data do evento, nulo: nada conta da competencia."""
    desde = _dia(datas.get(etapa))
    parada = desde is not None and etapa != "recebido"
    nota, recebido = _dia(datas.get("nota")), _dia(datas.get("recebido"))
    da_nota = (recebido - nota).days if etapa == "recebido" and nota and recebido and recebido >= nota else None
    return {"na_etapa_desde": desde.isoformat() if desde else None,
            "dias_uteis_na_etapa": feriados.dias_uteis_entre(desde, hoje) if parada else None,
            "dias_da_nota_ao_recebimento": da_nota}


def _linhas(partes: list[dict], obras: dict[int, dict], hoje: datetime.date) -> list[dict]:
    """Uma linha por medicao. A execucao e o reajuste de mesmo numero, na mesma competencia e na mesma etapa, viram
    uma linha so' ("24ª Medição + Reajuste", como em `medicoes.linhas_em_andamento`): o valor e' a soma das duas cotas
    e cada etapa leva a data da ultima das duas a chegar nela. So' se juntam quando as duas dizem o mesmo de cada
    etapa que tem em comum (uma com o registro do boletim e a outra sem ficam em duas linhas): a linha conjunta nao
    afirma de uma o que so' a outra tem. A diferenca entre o aprovado e o pedido da linha conjunta soma a das duas
    (cada uma com a propria tolerancia), e o tempo na etapa conta da data da ultima a chegar nela."""
    grupos: dict[tuple, list[dict]] = {}
    for p in partes:
        grupos.setdefault((p["contrato_id"], p["competencia"], p["numero"], p["etapa"]), []).append(p)
    linhas = []
    for ps in grupos.values():
        tipos = {p["tipo"]: p for p in ps}
        par = [tipos["execucao"], tipos["reajuste"]] if {"execucao", "reajuste"} <= set(tipos) else []
        if par:
            situacoes = [{x["etapa"]: x["situacao"] for x in p["etapas"]} for p in par]
            if any(situacoes[0][e] != situacoes[1][e] for e in situacoes[0].keys() & situacoes[1].keys()):
                par = []
        for juntas in ([par] if par else []) + [[p] for p in ps if p not in par]:
            principal = juntas[0]
            etapas = []
            for e in principal["etapas"]:
                dias = [x["data"] for p in juntas for x in p["etapas"] if x["etapa"] == e["etapa"] and x["data"]]
                etapas.append({**e, "data": max(dias) if dias else None})
            valores = [p["valor_centavos"] for p in juntas if p["valor_centavos"] is not None]
            diferencas = [p["diferenca"] for p in juntas if p["diferenca"] is not None]
            da_diferenca = {k: sum(d[k] for d in diferencas) if diferencas else None
                            for k in ("pedido_do_aprovado_centavos", "abaixo_do_pedido_centavos", "acima_do_pedido_centavos")}
            o = obras.get(principal["contrato_id"], {})
            linhas.append({
                "contrato_id": principal["contrato_id"], "obra": o.get("obra"), "contratante": o.get("contratante"),
                "medicao_id": principal["id"], "medicao_ids": [p["id"] for p in juntas],
                "titulo": f"{principal['titulo']} + Reajuste" if len(juntas) == 2 else principal["titulo"],
                "numero": principal["numero"], "tipo": principal["tipo"], "competencia": principal["competencia"],
                "etapa": principal["etapa"], "etapas": etapas,
                "valor_centavos": sum(valores) if valores else None,
                **_tempo_na_etapa(principal["etapa"], {e["etapa"]: e["data"] for e in etapas}, hoje), **da_diferenca})
    linhas.sort(key=lambda x: (medicoes._chave_nome(x["obra"]), x["contrato_id"], _ORDEM_TIPO.index(x["tipo"]),
                               x["numero"], x["medicao_id"]))
    return linhas


def _atualizacao(conn) -> dict:
    """De quando e' o dado: o ultimo lancamento feito por uma pessoa em qualquer medicao (a auditoria) e a ultima
    leitura do RM que terminou bem (de onde vem o recebido). Carimbos em UTC, como o banco guarda."""
    lancamento = conn.execute("SELECT MAX(criado_em) FROM audit_log WHERE entidade='medicao' "
                              "AND usuario_id IS NOT NULL").fetchone()[0]
    rm = conn.execute("SELECT MAX(terminado_em) FROM rm_sincronizacoes WHERE estado='success'").fetchone()[0]
    return {"ultimo_lancamento": lancamento, "rm_lido_em": rm}


def _por_etapa(partes: list[dict]) -> list[dict]:
    """Quantas medicoes estao em cada etapa e o medido delas, na cota (`antes`: planilha/carta ainda nao enviada)."""
    return [{"etapa": e, "medicoes": sum(1 for p in partes if p["etapa"] == e),
             "valor_centavos": sum(p["valor_centavos"] or 0 for p in partes if p["etapa"] == e)}
            for e in ("antes", *ETAPAS)]


def _subtotal(linhas: list[dict]) -> dict:
    """A quantidade de medicoes e o medido de um grupo de linhas (o contratante; nos meses anteriores, a competencia)."""
    return {"medicoes": sum(len(x["medicao_ids"]) for x in linhas),
            "valor_centavos": sum(x["valor_centavos"] or 0 for x in linhas)}


def _mes_mais(mes: str, soma: int) -> str:
    return diretoria._mes(datetime.date(int(mes[:4]), int(mes[5:7]), 1), soma)


def _um_mes_antes(d: datetime.date) -> datetime.date:
    """O mesmo dia do mes anterior; dia que o mes anterior nao tem (31, ou 29 e 30 em fevereiro) vira o ultimo dele."""
    ano, mes = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
    return datetime.date(ano, mes, min(d.day, calendar.monthrange(ano, mes)[1]))


def _medido(conn, hoje: datetime.date, mes: str, contratos_ids) -> dict:
    """O medido da competencia e as duas referencias da variacao dele (ver o texto do modulo): o numero do Fechamento."""
    anterior, ano_anterior = _mes_mais(mes, -1), _mes_mais(mes, -12)
    soma = fechamento.medido_das_competencias(conn, (mes, anterior, ano_anterior), contratos_ids)
    encerrada = mes < hoje.strftime("%Y-%m")

    def referencia(competencia: str) -> dict | None:
        serve = encerrada and competencia[:4] >= diretoria.ANO_INICIAL and soma[competencia] > 0
        return {"competencia": competencia, "valor_centavos": soma[competencia]} if serve else None
    return {"valor_centavos": soma[mes], "mes_anterior": referencia(anterior), "ano_anterior": referencia(ano_anterior)}


def _mesma_altura(partes: list[dict], competencia: str, ate: datetime.date) -> dict | None:
    """O protocolado e o recebido que as medicoes da competencia anterior (`partes`, as de `_medicao`) tinham em `ate`,
    pelas datas dos eventos (ver o texto do modulo). A etapa sem lastro (alguma medicao chegou nela sem a data do
    evento) vem nula."""
    if competencia[:4] < diretoria.ANO_INICIAL:
        return None
    limite = ate.isoformat()
    protocolado = recebido = 0
    protocolado_tem_lastro = recebido_tem_lastro = True
    for p in partes:
        etapa = {e["etapa"]: e for e in p["etapas"]}
        valor = p["valor_centavos"] or 0
        recebida = p["etapa"] == "recebido"
        quando = etapa["recebido"]["data"] if recebida else None
        if recebida and quando is None:
            recebido_tem_lastro = False
        ja_recebida = recebida and quando is not None and quando <= limite
        if ja_recebida:
            recebido += valor
        do_protocolo = etapa.get("protocolado")
        # nunca passou pelo protocolado (a obra nao tem a etapa, ou a medicao ainda nao chegou la'), ou ja' tinha
        # saido dele em `ate`
        if do_protocolo is None or do_protocolo["situacao"] == "futuro" or ja_recebida:
            continue
        if do_protocolo["data"] is None or (recebida and quando is None):
            protocolado_tem_lastro = False       # nao da' para dizer se estava no protocolado naquele dia
        elif do_protocolo["data"] <= limite:
            protocolado += valor
    return {"competencia": competencia, "ate": limite,
            "protocolado_centavos": protocolado if protocolado_tem_lastro else None,
            "recebido_centavos": recebido if recebido_tem_lastro else None}


def resumo(conn, hoje: datetime.date | None = None, mes: str | None = None, contratante: str | None = None) -> dict:
    """A competencia `mes` (AAAA-MM; sem ela, a competencia em trabalho: o mes anterior ao de hoje): as linhas por
    contratante, a contagem por etapa, o medido do mes com as referencias, as obras ativas sem medicao nela (com a
    ultima medicao de cada uma) e as medicoes abertas de competencias anteriores, da mais antiga para a mais nova.
    `contratante` (a sigla, como em `contratantes`) recorta tudo para as obras dele. Tudo de um retrato so' do banco
    (`db.leitura`, como o Fechamento): uma gravacao no meio nao deixa as linhas de um instante e as obras sem medicao
    de outro."""
    with db.leitura(conn):
        return _resumo(conn, hoje, mes, contratante)


def _resumo(conn, hoje: datetime.date | None, mes: str | None, contratante: str | None) -> dict:
    hoje = hoje or tempo.hoje_local()
    em_trabalho = diretoria._mes(hoje, -1)
    mes = mes or em_trabalho
    anterior = _mes_mais(mes, -1)
    obras = medicoes._obras_com_contratante(conn)
    passos_de = medicoes.passos_das_medicoes(conn)
    marcas = ",".join("?" * len(_FORA))
    # a data do protocolo e' a do PRIMEIRO protocolo da nota (a que comeca a contar o prazo do orgao), como no Inicio
    sql = ("SELECT m.*, c.percentual_direito_bp AS pct, (SELECT MIN(p.data) FROM medicao_protocolos p "
           "WHERE p.medicao_id=m.id AND p.etapa='nota' AND p.desfeita_em IS NULL) AS protocolado_em FROM medicoes m "
           f"JOIN contratos c ON c.id=m.contrato_id WHERE m.estado NOT IN ({marcas}) ")
    # a competencia, as abertas de antes dela (so' de `ANO_INICIAL` em diante) e a competencia anterior inteira (as
    # recebidas tambem: e' a referencia da "mesma altura")
    do_mes, anteriores, da_anterior = [], [], []
    for r in conn.execute(sql + "AND (m.competencia IN (?,?) OR (m.competencia<? AND m.estado<>'recebida'))",
                          (*_FORA, mes, anterior, mes)):
        p = _medicao(conn, dict(r), passos_de)
        if p is None:
            continue
        if p["competencia"] == mes:
            do_mes.append(p)
            continue
        if p["competencia"] == anterior:
            da_anterior.append(p)
        if p["etapa"] != "recebido" and p["competencia"][:4] >= diretoria.ANO_INICIAL:
            anteriores.append(p)

    # quem tem medicao na competencia ou aberta em meses anteriores, antes do recorte: as opcoes do filtro
    nome_de = lambda p: obras.get(p["contrato_id"], {}).get("contratante") or "sem contratante"
    quantos: dict[str, dict] = {}
    for chave, partes in (("medicoes", do_mes), ("anteriores", anteriores)):
        for p in partes:
            quantos.setdefault(nome_de(p), {"medicoes": 0, "anteriores": 0})[chave] += 1
    contratantes = [{"contratante": k, **quantos[k]} for k in sorted(quantos, key=medicoes._chave_nome)]

    # #805: o recorte por contratante vale para tudo o que a pagina mostra
    do_recorte = None if contratante is None else {i for i, o in obras.items() if o["contratante"] == contratante}
    if do_recorte is not None:
        do_mes, anteriores, da_anterior = ([p for p in ps if p["contrato_id"] in do_recorte]
                                           for ps in (do_mes, anteriores, da_anterior))

    linhas = _linhas(do_mes, obras, hoje)
    grupos: dict[str, list[dict]] = {}
    for x in linhas:
        grupos.setdefault(x["contratante"] or "sem contratante", []).append(x)

    # a ultima medicao de execucao ou de projeto de cada obra, ate' a competencia da pagina (o reajuste acompanha a execucao)
    ultima: dict[int, dict] = {}
    for r in conn.execute(sql + "AND m.tipo IN ('execucao','projeto') AND m.competencia<=? "
                          "ORDER BY m.competencia DESC, m.numero DESC, m.id DESC", (*_FORA, mes)):
        if r["contrato_id"] not in ultima:
            m = dict(r)
            da_vez = etapa_da_vez(m["estado"])
            if da_vez is not None:
                ultima[m["contrato_id"]] = {"medicao_id": m["id"], "titulo": medicoes.titulo(m),
                                            "competencia": m["competencia"], "etapa": da_vez}
    com_medicao = {p["contrato_id"] for p in do_mes}
    sem_fluxo = medicoes.sem_fluxo(conn)
    sem_medicao = [{"contrato_id": o["id"], "obra": o["obra"], "contratante": o["contratante"], "ultima": ultima.get(o["id"])}
                   for o in sorted(obras.values(), key=lambda o: (medicoes._chave_nome(o["obra"]), o["id"]))
                   if o["id"] not in com_medicao and o["id"] not in sem_fluxo and o["estado"] == "ativo"
                   and not o["encerramento_iniciado_em"] and (do_recorte is None or o["id"] in do_recorte)]

    por_competencia: dict[str, list[dict]] = {}
    for x in _linhas(anteriores, obras, hoje):
        por_competencia.setdefault(x["competencia"], []).append(x)
    return {"hoje": hoje.isoformat(), "mes": mes, "em_trabalho": em_trabalho, "atualizacao": _atualizacao(conn),
            "contratante": contratante, "contratantes": contratantes,
            "etapas": _por_etapa(do_mes), "medido": _medido(conn, hoje, mes, do_recorte),
            "mesma_altura": _mesma_altura(da_anterior, anterior, _um_mes_antes(hoje)),
            "diferenca_critica_por_mil": avisos_medicao.ABAIXO_DO_PEDIDO_POR_MIL,
            "grupos": [{"contratante": k, **_subtotal(v), "linhas": v}
                       for k, v in sorted(grupos.items(), key=lambda kv: medicoes._chave_nome(kv[0]))],
            "sem_medicao": sem_medicao,
            "anteriores_etapas": _por_etapa(anteriores),
            "anteriores": [{"competencia": k, **_subtotal(por_competencia[k]), "linhas": por_competencia[k]}
                           for k in sorted(por_competencia)]}


def _data_br(iso: str | None) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso else ""


CABECALHO_CSV = ["parte", "contratante", "obra", "medicao", "competencia", "etapa",
                 *(f"data_{e}" for e in ETAPAS), "medido_cota"]


def linhas_csv(r: dict, brl) -> list[list[str]]:
    """A relacao que a pagina mostra, na ordem dela: as medicoes da competencia, as obras sem medicao e as medicoes
    abertas de competencias anteriores. `brl` formata os centavos (o de `app.dinheiro`)."""
    def comp(c: str) -> str:
        return f"{c[5:7]}/{c[:4]}"

    def da_linha(parte: str, x: dict) -> list[str]:
        datas = {e["etapa"]: e["data"] for e in x["etapas"]}
        return [parte, x["contratante"] or "", x["obra"] or "", x["titulo"], comp(x["competencia"]), ROTULO[x["etapa"]],
                *(_data_br(datas.get(e)) for e in ETAPAS), brl(x["valor_centavos"]) if x["valor_centavos"] is not None else ""]

    out = [da_linha("competência", x) for g in r["grupos"] for x in g["linhas"]]
    for o in r["sem_medicao"]:
        out.append(["sem medição no mês", o["contratante"] or "", o["obra"] or "", "", comp(r["mes"]), "", *[""] * len(ETAPAS), ""])
    out.extend(da_linha("meses anteriores", x) for g in r["anteriores"] for x in g["linhas"])
    return out
