"""Tela Medicoes como fila de trabalho (issue #805, etapa 3a da reestrutura; decisao do dono de 18/11/2026). So' leitura.

A tela e' de quem OPERA e responde "o que eu preciso fazer agora?". Tres vistas saem daqui, de uma resposta so':
- `grupos`: a FILA DE TRABALHO da competencia, um grupo por quem tem de agir (`COM_QUEM`), cada um da medicao mais
  parada para a menos; `concluidas` (as recebidas da competencia) e `sem_medicao` (as obras ativas sem medicao nela);
- `quadro`: o quadro do mes (obra x passo, issue #643), agrupado por contratante, sem as obras sem medicao;
- `anteriores`: as medicoes de competencias anteriores que ainda pedem acao de quem opera; as que so' esperam o
  pagamento e as anteriores a `diretoria.ANO_INICIAL` viram contagem (o em aberto mora na pagina Em aberto, #816).

Nada daqui e' regra nova de estado nem de passo. As medicoes abertas, a linha unica de medicao + reajuste e o marco de
cada situacao sao os de `medicoes.linhas_em_andamento`; o quadro, as obras e o "Iniciar", os de `medicoes.resumo`; os
passos de cada medicao, os de `medicoes.passos_das_medicoes`. Este modulo so' acrescenta o que a tela nova mostra:

COM QUEM ESTA' (`com_quem`): sai do passo da vez. Planilha e carta (1), Espelhos (3) e Envio da nota (5) sao da
Lotufo; Notas (4), a emissao, e' do faturamento; Análise do órgão (2) e Pagamento (6) sao do orgao. Uma excecao, que
vem do estado: no passo 2 sem a planilha/carta enviada (a MT-PAR, issue #753, em que a empresa preenche o boletim e
colhe a assinatura do fiscal) nada foi ao orgao ainda, e a medicao esta' com a Lotufo.

PARADA HA' (`_parada`): conta do dia do EVENTO que abriu a situacao da medicao (o `marco` de `linhas_em_andamento`:
a planilha gerada, o envio da planilha/carta, o boletim, o espelho vigente, o e-mail ao faturamento, a emissao da
nota, o protocolo), nunca da competencia nem do lancamento. Em DIAS UTEIS, pela conta que o sistema ja' tem
(`feriados.dias_uteis_entre`: o dia do evento conta, hoje nao). A situacao e' a da familia "tempo parado"
(docs/identidade-visual.md), com os limites do SIGA (`siga.DIAS_ATENCAO` e `siga.DIAS_ACAO`): o evento de hoje e'
feito; ate' 4 dias uteis, em andamento; de 5 a 9, vence em breve; 10 ou mais, critico. No Pagamento a regua e' outra,
porque esperar o orgao dentro do prazo dele nao e' alerta: critico so' depois da data esperada do recebimento
(`diretoria.esperada`: o primeiro protocolo + o prazo do orgao, docs/adr/0007, o mesmo "Atrasado" do Inicio); antes
dela, ou sem prazo do orgao, em andamento. Sem marco, nao ha' dias nem situacao.

DIFERENCA aprovado x pedido: a conta e' a do Fechamento (`fechamento.aprovado_contra_o_pedido`: so' a medicao com os
dois valores gravados, a partir do boletim; o corte soma so' o aprovado abaixo do pedido; ate' R$ 0,05 e' igual) e o
limite e' o do aviso (`avisos_medicao.ABAIXO_DO_PEDIDO_POR_MIL`). A BASE e' outra: aqui Pedido e Aprovado sao o VALOR
CHEIO gravado na medicao (`valor_protocolado_centavos` e `valor_atestado_centavos`), como a tela Medicoes sempre
mostrou; o Fechamento mostra a cota. Em obra propria os dois sao iguais.
"""
import datetime

from app import avisos_medicao, diretoria, fechamento, feriados, medicoes, siga, tempo

COM_QUEM = ("lotufo", "faturamento", "orgao")       # a ordem dos grupos na fila
_DO_PASSO = {1: "lotufo", 2: "orgao", 3: "lotufo", 4: "faturamento", 5: "lotufo", 6: "orgao"}
PASSO_ANALISE, PASSO_ESPELHOS, PASSO_PAGAMENTO = 2, 3, 6
# o ato de quem opera no passo da vez, para o botao que leva a' pagina da medicao; nos passos dos outros, nenhum
_ACAO_DO_PASSO = {1: "enviar_planilha", 2: "registrar_boletim", 5: "enviar_nota"}
_COMPARAVEIS = (*fechamento.COMPARAVEIS, "acima_do_pedido_centavos")


def com_quem(passo: int, estado: str) -> str:
    """Quem tem de agir na medicao que esta' no `passo` (numero de `medicoes.PASSOS`) com o `estado`; ver o cabecalho."""
    if passo == PASSO_ANALISE and estado != "planilha_enviada":
        return "lotufo"
    return _DO_PASSO[passo]


def acao(passo: int, estado: str) -> str | None:
    """A chave do proximo ato de quem opera (a tela escreve o rotulo do botao); None quando a vez e' de outro."""
    if com_quem(passo, estado) != "lotufo":
        return None
    if passo == PASSO_ESPELHOS:
        return "enviar_espelho" if estado == "espelho_gerado" else "gerar_espelho"
    return _ACAO_DO_PASSO[passo]


def _parada(desde: datetime.date | None, hoje: datetime.date, passo: int, esperada: datetime.date | None,
            prazo_dias: int | None) -> dict:
    """Ha' quanto tempo a medicao esta' na situacao atual e a leitura disso (ver o cabecalho, "PARADA HA'")."""
    alem = passo == PASSO_PAGAMENTO and esperada is not None and esperada < hoje
    dias = feriados.dias_uteis_entre(desde, hoje) if desde else None
    if desde is None:
        situacao = "critico" if alem else None
    elif passo == PASSO_PAGAMENTO:
        situacao = "critico" if alem else "feito" if desde >= hoje else "andamento"
    elif desde >= hoje:
        situacao = "feito"
    else:
        situacao = "critico" if dias >= siga.DIAS_ACAO else "breve" if dias >= siga.DIAS_ATENCAO else "andamento"
    no_pagamento = passo == PASSO_PAGAMENTO
    return {"desde": desde.isoformat() if desde else None, "dias_uteis": dias, "hoje": bool(desde and desde >= hoje),
            "situacao": situacao, "prazo_orgao_dias": prazo_dias if no_pagamento else None,
            "esperada": esperada.isoformat() if no_pagamento and esperada else None, "alem_do_prazo": alem}


def _parada_da_linha(x: dict, ms: list[dict], hoje: datetime.date, prazos: dict) -> dict:
    """O `parada` de uma linha de `medicoes.linhas_em_andamento` (`x`), com as medicoes dela (`ms`, as de
    `diretoria._medicoes`) e os prazos de `diretoria.prazos_do_orgao`: o marco e o passo sao os da linha; a data
    esperada do recebimento (docs/adr/0007) e' a mais proxima entre as medicoes dela."""
    esperadas = [e for e in (diretoria.esperada(i, prazos) for i in ms) if e]
    marco = datetime.date.fromisoformat(x["marco"]) if x["marco"] else None
    return _parada(marco, hoje, x["passo"]["numero"], min(esperadas) if esperadas else None,
                   prazos.get(diretoria._contratante(ms[0])))


def paradas(conn, hoje: datetime.date, obras: dict[int, dict] | None = None) -> dict[int, dict]:
    """Medicao aberta -> o `parada` da linha dela na fila de trabalho, de qualquer competencia. E' a UNICA leitura do
    tempo parado de uma medicao: a da tela Medicoes (`fila`) e a do cartao do Resumo das medicoes
    (`resumo_medicoes.py`), para a mesma medicao nao sair critica numa tela e em andamento na outra. A medicao e o
    reajuste que a fila junta numa linha levam o mesmo `parada`. `obras` e' o de `medicoes._obras_com_contratante`,
    para quem ja' o leu."""
    todas = diretoria._medicoes(conn)
    de = {m["id"]: m for m in todas}
    prazos = diretoria.prazos_do_orgao(todas, hoje)
    out: dict[int, dict] = {}
    for x in medicoes.linhas_em_andamento(conn, hoje, obras=obras):
        parada = _parada_da_linha(x, [de[i] for i in x["medicao_ids"]], hoje, prazos)
        out.update(dict.fromkeys(x["medicao_ids"], parada))
    return out


def _comparar(ms: list[dict]) -> dict:
    """Pedido, aprovado e a diferenca entre eles de um conjunto de medicoes (a linha, a obra, o contratante, o mes),
    no valor cheio. Pedido e aprovado somam as medicoes que tem cada valor (nulo sem nenhuma), como o quadro do mes
    sempre fez; os comparaveis, so' as que tem os dois (`fechamento.aprovado_contra_o_pedido`), e ficam nulos quando
    nenhuma tem: a tela nao desenha diferenca do que nao se compara."""
    pedidos = [m["valor_protocolado_centavos"] for m in ms if m["valor_protocolado_centavos"] is not None]
    aprovados = [m["valor_atestado_centavos"] for m in ms if m["valor_atestado_centavos"] is not None]
    comparadas = [c for c in (fechamento.aprovado_contra_o_pedido(
        m["estado"], m["valor_protocolado_centavos"], m["valor_atestado_centavos"]) for m in ms) if c]
    return {"pedido_centavos": sum(pedidos) if pedidos else None,
            "aprovado_centavos": sum(aprovados) if aprovados else None,
            **{k: sum(c[k] for c in comparadas) if comparadas else None for k in _COMPARAVEIS}}


def _mais_parada(linha: dict) -> tuple:
    """A ordem da fila: mais dias uteis parada, depois o evento mais antigo; a sem marco vai para o fim."""
    p = linha["parada"]
    return (-(p["dias_uteis"] if p["dias_uteis"] is not None else -1), p["desde"] or "9",
            medicoes._chave_nome(linha["obra"]), linha["contrato_id"], linha["medicao_id"])


def _contagem(linhas: list[dict]) -> dict:
    situacoes = [x["parada"]["situacao"] for x in linhas]
    return {"quantidade": len(linhas), "criticas": situacoes.count("critico"), "breves": situacoes.count("breve"),
            "alem_do_prazo": sum(1 for x in linhas if x["parada"]["alem_do_prazo"])}


def fila(conn, hoje: datetime.date | None = None, mes: str | None = None, com_siga: bool = True) -> dict:
    """A resposta da tela Medicoes na competencia `mes` (AAAA-MM; padrao, o mes de hoje, como `medicoes.resumo`).
    `com_siga` (#853): sem ele, o quadro sai sem a posicao do processo no SIGA (`medicoes.resumo`)."""
    hoje = hoje or tempo.hoje_local()
    base = medicoes.resumo(conn, hoje, mes, com_siga=com_siga)
    mes = base["mes"]
    todas = diretoria._medicoes(conn)
    de = {m["id"]: m for m in todas}
    passos_de = medicoes.passos_das_medicoes(conn)
    prazos = diretoria.prazos_do_orgao(todas, hoje)

    def linha(x: dict) -> dict:
        ms = [de[i] for i in x["medicao_ids"]]
        # a medicao da vez na linha de medicao + reajuste: a menos adiantada, como o passo de `linhas_em_andamento`
        m = min(ms, key=lambda m: medicoes.passo_do_estado(m["estado"], passos_de(m)))
        tem, n = passos_de(m), x["passo"]["numero"]
        return {"contrato_id": x["contrato_id"], "obra": x["obra"], "contratante": x["contratante"],
                "orgao_sub": x["orgao_sub"], "medicao_id": x["medicao_id"], "medicao_ids": x["medicao_ids"],
                "titulo": x["titulo"], "competencia": x["competencia"], "com_quem": com_quem(n, m["estado"]),
                "passo": {**x["passo"], "posicao": tem.index(n) + 1 if n in tem else None, "total": len(tem)},
                "passos": [{"numero": p, "nome": medicoes.PASSOS[p - 1],
                            "situacao": "feito" if p < n else "atual" if p == n else "futuro"} for p in tem],
                "parada": _parada_da_linha(x, ms, hoje, prazos),
                **_comparar(ms), "acao": acao(n, m["estado"])}

    abertas = [linha(x) for x in medicoes.linhas_em_andamento(conn, hoje) if x["competencia"]]
    do_mes = sorted((x for x in abertas if x["competencia"] == mes), key=_mais_parada)
    grupos = [{"com_quem": quem, "linhas": [x for x in do_mes if x["com_quem"] == quem]} for quem in COM_QUEM]
    grupos = [g for g in grupos if g["linhas"]]

    # as medicoes da competencia que o quadro conta (as mesmas de `medicoes._quadro_do_mes`)
    da_competencia = [m for m in todas if m["competencia"] == mes and m["estado"] not in ("prevista", "cancelada", "desistida")]
    concluidas = sorted(({"contrato_id": m["contrato_id"], "obra": m["obra"], "medicao_id": m["id"],
                          "titulo": medicoes.titulo(m), "recebida_em": (m["recebida_em"] or "")[:10] or None}
                         for m in da_competencia if m["estado"] == "recebida"),
                        key=lambda c: (c["recebida_em"] or "9", medicoes._chave_nome(c["obra"]), c["medicao_id"]))
    sem_medicao = [{"contrato_id": x["contrato_id"], "obra": x["obra"], "contratante": x["contratante"]}
                   for x in base["quadro"] if x["iniciar"]]

    return {"hoje": hoje.isoformat(), "mes": mes, "obras": base["obras"],
            "limites": {"dias_atencao": siga.DIAS_ATENCAO, "dias_critico": siga.DIAS_ACAO,
                        "diferenca_critica_por_mil": avisos_medicao.ABAIXO_DO_PEDIDO_POR_MIL},
            "numeros": {"com": {quem: _contagem([x for x in do_mes if x["com_quem"] == quem]) for quem in COM_QUEM},
                        "concluidas": len(concluidas), "sem_medicao": len(sem_medicao), **_soma_do_mes(da_competencia)},
            "grupos": grupos, "concluidas": concluidas, "sem_medicao": sem_medicao,
            "quadro": _quadro(base["quadro"], de, abertas),
            "anteriores": _anteriores(mes, abertas)}


def _soma_do_mes(ms: list[dict]) -> dict:
    """O pedido, o aprovado e o corte da competencia. O `acima` nao soma (so' aparece na linha da medicao)."""
    soma = _comparar(ms)
    del soma["acima_do_pedido_centavos"]
    return soma


def _quadro(quadro: list[dict], de: dict[int, dict], abertas: list[dict]) -> list[dict]:
    """O quadro do mes de `medicoes.resumo`, agrupado por contratante (o que tem mais obras primeiro; empate, pelo
    nome), sem as obras sem medicao (vao para `sem_medicao`). Cada obra ganha a diferenca aprovado x pedido das
    medicoes dela na competencia, e o passo da vez, o `parada` da medicao que esta' nele. O grupo leva o pedido, o
    aprovado e o corte somados (sem o `acima`)."""
    parada_de = {i: x["parada"] for x in abertas for i in x["medicao_ids"]}
    por: dict[str, list[dict]] = {}
    for x in quadro:
        if x["iniciar"]:
            continue
        ms = [de[m["id"]] for m in x["medicoes"]]
        passos = [{**p, "parada": parada_de.get(p["medicao_id"]) if p["situacao"] == "atual" else None} for p in x["passos"]]
        por.setdefault(x["contratante"], []).append({**x, "passos": passos, **_comparar(ms), "_ms": ms})
    grupos = []
    for nome, linhas in sorted(por.items(), key=lambda g: (-len(g[1]), medicoes._chave_nome(g[0]))):
        grupos.append({"contratante": nome, **_soma_do_mes([m for x in linhas for m in x["_ms"]]),
                       "linhas": [{k: v for k, v in x.items() if k != "_ms"} for x in linhas]})
    return grupos


def _anteriores(mes: str, abertas: list[dict]) -> dict:
    """As medicoes abertas de competencias anteriores a' do quadro. Em `linhas`, so' as que pedem acao de quem opera:
    com a Lotufo, com o faturamento ou em analise no orgao, de `diretoria.ANO_INICIAL` em diante (o que as telas da
    diretoria contam), da mais parada para a menos. O resto vira contagem: `esperam_pagamento` (as que so' esperam o
    orgao pagar) e `antes_do_ano_inicial` (as de competencia anterior, em qualquer passo)."""
    passadas = [x for x in abertas if x["competencia"] < mes]
    antigas = [x for x in passadas if x["competencia"][:4] < diretoria.ANO_INICIAL]
    recentes = [x for x in passadas if x["competencia"][:4] >= diretoria.ANO_INICIAL]
    pagamento = [x for x in recentes if x["passo"]["numero"] == PASSO_PAGAMENTO]
    return {"linhas": sorted((x for x in recentes if x["passo"]["numero"] != PASSO_PAGAMENTO), key=_mais_parada),
            "esperam_pagamento": len(pagamento), "antes_do_ano_inicial": len(antigas),
            "ano_inicial": diretoria.ANO_INICIAL}
