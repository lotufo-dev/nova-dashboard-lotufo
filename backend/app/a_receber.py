"""Pagina Em aberto (issue #816, etapa 5 da reestrutura #805; decisao do dono de 18/11/2026; ate' 19/11/2026 ela se
chamava "A receber", e o endereco `/a-receber` e a rota `/api/a-receber` ficaram): o em aberto do Fechamento
nota a nota, agrupado por contratante e, dentro dele, pela data do protocolo, a mais antiga primeiro. So' leitura.

Pergunta da tela: "o que esta' protocolado e ainda nao entrou, e ha' quanto tempo". A conta NAO e' nova: as linhas sao
as do em aberto do Fechamento (`fechamento._em_aberto_da_medicao`, sobre as mesmas linhas de medicao,
`fechamento._linhas_das_medicoes`), entao o total desta pagina e' o em aberto do Fechamento de 2025 e 2026 somados, e o
subtotal de cada contratante e' o `em_aberto_centavos` dele na aba "Por contratante" do Fechamento, somado nos anos.
As tres partes de sempre: (a) nota protocolada nao paga (a paga em parte, pelo que falta nos titulos), (a') repasse
sem baixa (o orgao ja' pagou o consorcio; quem deve e' o consorcio) e (b) medicao protocolada sem nota ligada. A nota de
consorcio partilhada entre medicoes, a nota da empresa ao consorcio e a fatura do consorcio da mesma medicao ja' entram
uma vez so' na linha da medicao, como no Fechamento.

Duas definicoes de dinheiro a receber, de proposito (docs/adr/0006): esta pagina e' a casa do "em aberto" do Fechamento,
pelo valor bruto da nota e pela competencia; o "a receber" do Inicio e da lista de Obras (`diretoria.a_receber_na_cota`)
soma tambem as cobrancas do RM que nenhuma medicao em aberto representa, pelo que falta nos titulos. Por isso a pagina
se chama "Em aberto", o rotulo do Fechamento (decisao do dono de 19/11/2026: o nome do outro numero saiu da pagina, e
com ele a frase que explicava a diferenca); o numero "a receber" da Inicio e de Obras nao muda de nome nem de conta.

A' parte, fora do total, como no Fechamento: a nota de cobranca em aberto no RM sem medicao ligada
(`fechamento._notas_sem_medicao`, sem competencia) e o em aberto de competencia anterior a 2025 (o "a receber antigo",
`fechamento.ANOS`). Os dois descem ao contratante da obra, para o recorte por contratante; a lista inteira das notas
sem medicao vai tambem no alto, na ordem do Fechamento (a emissao, a mais antiga primeiro). A nota sem medicao que
esta' ligada a medicao ainda nao enviada ao orgao (prevista ou com a planilha/carta so' gerada: o vinculo existe, mas a
medicao ainda nao mede, `medicoes.ESTADOS_NO_MEDIDO`) leva `ligada_a_medicao_nao_enviada` (decisao do dono de
19/11/2026: rotulo proprio). E' so' a marca: a lista, o valor e o subtotal sao os do Fechamento.

O que a tela mostra nasce aqui, pronto:
- por contratante (`contratantes`): a chave da pagina dele em Obras (`fechamento._contratantes`, a mesma de
  `/obras/contratante/<chave>`, que e' o valor de `?contratante=`), o prazo de pagamento do orgao (docs/adr/0007,
  `diretoria.prazos_do_orgao`; nulo = sem previsao), quantas linhas, o subtotal, o subtotal de cada ano, quantas
  linhas passaram da data esperada e o que fica a' parte. Entram os contratantes com alguma linha (no total ou a'
  parte) e os de contrato ativo ou suspenso sem nada em aberto, com zero, para a opcao continuar na fileira do filtro.
  O contratante e' o par (nome, chave), como na aba "Por contratante" do Fechamento (`diretoria.linha_do_contratante`,
  issue #864). A ordem: o maior em aberto primeiro, empate pelo nome e depois pela chave;
- por linha: o tempo parado (`parada`) desde o protocolo (sem protocolo, na obra sem o passo "Envio da nota", desde a
  emissao da nota), pela regra do passo Pagamento da fila de Medicoes (`fila_medicoes._parada`): critico so' depois da
  data esperada do recebimento (`diretoria.esperada`: o primeiro protocolo + o prazo do orgao, o mesmo "Atrasado" do
  Inicio); antes dela, ou sem prazo do orgao, em andamento; o protocolo de hoje e' feito. `esperada` e' a data
  prevista, so' quando o prazo do orgao e' conhecido. Conta do PRIMEIRO protocolo, o mesmo da data na linha e da data
  esperada, com a data esperada de cada medicao, como a fila de Medicoes e o Resumo das medicoes (issue #914: a
  mesma medicao, os mesmos dias e a mesma situacao nas telas). Na medicao reapresentada o `parada` leva a revisao
  (`medicoes.revisoes_do_protocolo`), como na fila. No repasse sem baixa o orgao ja' pagou: nao ha' tempo parado com o
  orgao, e a linha leva a data do recebimento (`orgao_pagou_em`, nula quando a medicao foi recebida sem data).

Com o total a receber ainda nao liberado no cadastro (`diretoria._liberado`, a trava do Fechamento, do Inicio e da
lista de Obras), nada do em aberto sai do servidor: nem valor, nem linha, nem contagem (a contagem de notas em aberto
deixaria deduzir quais foram pagas). Quem ve o Fechamento ve esta pagina (`ver_paineis`).
"""
import datetime

from app import db, diretoria, fechamento, fila_medicoes, medicoes, tempo

# o contrato ainda em execucao: o contratante dele fica na fileira do filtro mesmo sem nada em aberto
ESTADOS_NA_FILEIRA = ("ativo", "suspenso")
# a medicao que ainda nao foi ao orgao: nao mede (`medicoes.ESTADOS_NO_MEDIDO`), nao foi cancelada nem desistida
ESTADOS_NAO_ENVIADA = ("prevista", "planilha_gerada")


def a_receber(conn, hoje: datetime.date | None = None) -> dict:
    with db.leitura(conn):
        return _a_receber(conn, hoje or tempo.hoje_local())


def _dia(iso: str | None) -> datetime.date | None:
    return datetime.date.fromisoformat(iso[:10]) if iso else None


def _grupo(nome: str, chave: str | None) -> dict:
    return {"contratante": nome, "chave": chave, "prazo_orgao_dias": None, "quantidade": 0, "em_aberto_centavos": 0,
            "por_ano": dict.fromkeys(fechamento.ANOS, 0), "alem_do_prazo": 0, "linhas": [],
            "notas_sem_medicao": [], "notas_sem_medicao_centavos": 0, "anteriores": {"quantidade": 0, "valor_centavos": 0}}


def _linha(e: dict, m: dict, hoje: datetime.date, prazos: dict[str, int], revisoes: dict[int, dict]) -> dict:
    """Uma linha do em aberto (`fechamento._em_aberto_da_medicao`) com o tempo parado dela; `m` e' a medicao em
    `diretoria._medicoes` (o primeiro protocolo, o recebimento e o orgao, de onde sai o prazo); `revisoes`, o de
    `medicoes.revisoes_do_protocolo`."""
    if e["tipo_aberto"] == "repasse":
        return {**e, "parada": None, "orgao_pagou_em": (m["recebida_em"] or "")[:10] or None}
    parada = fila_medicoes._parada(_dia(e["protocolo_em"] or e["emitida_em"]), hoje, fila_medicoes.PASSO_PAGAMENTO,
                                   diretoria.esperada(m, prazos), prazos.get(diretoria._contratante(m)),
                                   revisoes.get(m["id"]))
    return {**e, "parada": parada, "orgao_pagou_em": None}


def _ligadas_a_medicao_nao_enviada(conn, nota_ids: list[int]) -> set[int]:
    """Das notas sem medicao ligada (`fechamento._notas_sem_medicao`: nenhum vinculo ativo com medicao que mede), as
    que tem vinculo ativo com medicao ainda nao enviada ao orgao (`ESTADOS_NAO_ENVIADA`)."""
    if not nota_ids:
        return set()
    marcas = ",".join("?" * len(nota_ids))
    estados = ",".join("?" * len(ESTADOS_NAO_ENVIADA))
    return {r[0] for r in conn.execute(
        f"SELECT DISTINCT a.nota_id FROM nf_alocacoes a JOIN medicoes m ON m.id=a.medicao_id WHERE a.desfeita_em IS NULL "
        f"AND a.nota_id IN ({marcas}) AND m.estado IN ({estados})", (*nota_ids, *ESTADOS_NAO_ENVIADA))}


def _a_receber(conn, hoje: datetime.date) -> dict:
    anos = list(fechamento.ANOS)
    if not diretoria._liberado(conn):
        return {"anos": anos, "total_a_receber_liberado": False}
    contratante_de = fechamento._contratantes(conn)
    das_medicoes = diretoria._medicoes(conn)
    de = {m["id"]: m for m in das_medicoes}
    prazos = diretoria.prazos_do_orgao(das_medicoes, hoje)
    revisoes = medicoes.revisoes_do_protocolo(conn)
    # issue #864: o grupo e' o par (nome, chave), a linha do contratante na aba "Por contratante" do Fechamento
    # (`diretoria.linha_do_contratante`), nao o nome: o contrato sem orgao no cadastro cujo texto e' igual a' sigla de
    # um contratante fica no grupo dele, sem chave, e o subtotal de cada grupo e' o da linha do mesmo par no Fechamento
    grupos: dict[tuple[str, str | None], dict] = {}

    def grupo_de(contrato_id: int) -> dict:
        nome, chave = contratante_de[contrato_id]
        return grupos.setdefault((nome, chave), _grupo(nome, chave))

    for x in fechamento._linhas_das_medicoes(conn):
        ano = x["competencia"][:4]
        abertas = fechamento._em_aberto_da_medicao(x, x["_emitida_em"])
        if not abertas:
            continue
        g = grupo_de(x["contrato_id"])
        if ano < anos[0]:                    # o a receber antigo: a' parte, contado como no Fechamento
            g["anteriores"]["quantidade"] += len(abertas)
            g["anteriores"]["valor_centavos"] += sum(e["valor_centavos"] for e in abertas)
            continue
        if ano not in anos:                  # competencia que a pagina Fechamento nao conta: fora daqui tambem
            continue
        m = de[x["medicao_id"]]
        if g["prazo_orgao_dias"] is None:
            g["prazo_orgao_dias"] = prazos.get(diretoria._contratante(m))
        for e in abertas:
            linha = _linha(e, m, hoje, prazos, revisoes)
            g["linhas"].append(linha)
            g["quantidade"] += 1
            g["em_aberto_centavos"] += e["valor_centavos"]
            g["por_ano"][ano] += e["valor_centavos"]
            g["alem_do_prazo"] += bool(linha["parada"] and linha["parada"]["alem_do_prazo"])
    soltas = fechamento._notas_sem_medicao(conn)
    previstas = _ligadas_a_medicao_nao_enviada(conn, [n["nota_id"] for n in soltas["em_aberto"]])
    soltas["em_aberto"] = [{**n, "ligada_a_medicao_nao_enviada": n["nota_id"] in previstas} for n in soltas["em_aberto"]]
    for n in soltas["em_aberto"]:
        g = grupo_de(n["contrato_id"])
        g["notas_sem_medicao"].append(n)
        g["notas_sem_medicao_centavos"] += n["valor_centavos"]
    for contrato_id, o in medicoes._obras_com_contratante(conn).items():
        if o["estado"] in ESTADOS_NA_FILEIRA:
            grupo_de(contrato_id)
    for g in grupos.values():
        g["linhas"].sort(key=fechamento.ordem_do_em_aberto)
        # o contratante sem linha no total tambem tem prazo (o da pagina dele em Obras). O prazo e' pelo nome de
        # `diretoria._contratante`, que chama de `SEM_ORGAO` o contrato sem orgao no cadastro: o grupo sem chave nao
        # pega o prazo do contratante de verdade so' porque o texto do contrato e' igual a' sigla dele (issue #864)
        if g["prazo_orgao_dias"] is None:
            g["prazo_orgao_dias"] = prazos.get(g["contratante"] if g["chave"] is not None else diretoria.SEM_ORGAO)
    lista = sorted(grupos.values(), key=lambda g: (-g["em_aberto_centavos"],
                                                   *diretoria.ordem_do_contratante((g["contratante"], g["chave"]))))
    return {"anos": anos, "total_a_receber_liberado": True,
            "em_aberto_centavos": sum(g["em_aberto_centavos"] for g in lista),
            "por_ano": {a: sum(g["por_ano"][a] for g in lista) for a in anos},
            "quantidade": sum(g["quantidade"] for g in lista),
            "alem_do_prazo": sum(g["alem_do_prazo"] for g in lista),
            "notas_sem_medicao": soltas["em_aberto"], "notas_sem_medicao_centavos": soltas["em_aberto_centavos"],
            "anteriores": {"quantidade": sum(g["anteriores"]["quantidade"] for g in lista),
                           "valor_centavos": sum(g["anteriores"]["valor_centavos"] for g in lista)},
            "contratantes": lista}
