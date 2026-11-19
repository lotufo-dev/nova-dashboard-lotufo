"""Pagina Fechamento (issue #748): o que foi medido, aprovado, protocolado e recebido em cada mes de competencia de
2025 e 2026, na COTA da empresa, e o que esta' em aberto. So' leitura.

Pergunta da tela (decisao do dono de 10 e 16/11/2026): "quanto foi medido, aprovado, faturado em nota protocolada e
recebido em cada mes, e o que falta receber". Poucos numeros, exatos, que abrem por obra e por medicao.

O MES de todo numero e' a competencia da medicao. A nota e o recebimento caem na competencia da medicao a que a nota
esta' ligada (vinculo vigente em `nf_alocacoes`), nunca no mes da emissao ou da baixa.

Os numeros, por medicao (centavos inteiros; a cota de cada parcela por `contratos.cota`, arredondamento unico por
parcela; os totais sao somas dessas parcelas, entao fecham ao centavo com as linhas abertas). As faturas do
consorcio de uma mesma medicao sao UMA parcela: a cota e' a da soma delas, repartida entre elas (`_cotas`), para o
protocolado da medicao fechar com o aprovado quando as faturas somam o valor aprovado:
- Medido: medicao enviada ao orgao (`medicoes.ESTADOS_NO_MEDIDO`: da planilha/carta enviada em diante; cancelada,
  desistida, prevista e planilha so' gerada ficam fora), pelo glossario: o aprovado e, sem boletim, o pedido.
  Medicao sem valor nenhum nao entra no medido.
- Aprovado: `_aprovado` (o valor do boletim; sem ele gravado, o pedido so' quando a nota ja' foi emitida, que e' a
  prova de que o orgao aprovou; antes disso a medicao fica so' no medido).
- Protocolado: as notas das medicoes protocoladas (`_cobrada`: `ESTADOS_PROTOCOLADO` e, na obra cujo cadastro nao
  tem o passo "Envio da nota", tambem a medicao com nota emitida: la' a nota emitida ja' e' a cobranca, issue #743,
  `medicoes.recebe_sem_protocolo`), pelo valor bruto da nota. So' contam as
  notas ligadas ativas, nao desconsideradas, que sao cobranca ao orgao no contrato da medicao
  (`cobranca_orgao.e_cobranca`, docs/adr/0015: a lista geral de tipos de movimento e os tipos extras que o cadastro
  daquele contrato declara) ou ainda so' lidas do PDF (`_notas_por_medicao`), e, delas, as que `_notas_da_conta` escolhe, a UNICA definicao de quais notas contam e
  com que percentual:
  - obra propria: as notas da empresa, pelo valor da nota;
  - consorcio COM a nota da propria empresa ao consorcio ligada a' medicao (decisao do dono de 17/11/2026, issue
    #756): so' ela, pelo valor de FACE (ela ja' e' a cota: nao se multiplica pelo percentual). A fatura do consorcio
    ligada a' mesma medicao nao entra na conta dela; sai em `notas_fora_da_conta`, sem valor;
  - consorcio SEM a nota da empresa ligada: a fatura do consorcio (coligada da entidade do contrato), valor cheio
    vezes a cota.
  Nunca as duas na mesma medicao: contaria a cobranca duas vezes. A nota ligada a mais de uma medicao entra em cada
  uma pelo valor do vinculo (`valor_alocado_centavos`); ligada a uma so', pelo valor atual da nota.
- Recebido: `_recebimento`, a UNICA definicao (bruto por competencia: das notas do protocolado, as pagas, pelo mesmo
  valor bruto; da nota paga em parte, o valor bruto menos o que falta nos titulos do RM). A medicao recebida leva as
  notas dela inteiras ao recebido, MENOS a nota da empresa ao consorcio (decisao do dono de 17/11/2026, "pela baixa
  do titulo"): essa so' entra no recebido pelo que foi baixado nos titulos DELA no RM, e a falta nao leva a cota. A
  medicao de consorcio vira recebida quando o orgao paga o consorcio; a cota so' entrou quando o consorcio repassou.
- Em aberto (a receber), em partes que a tela diz uma a uma:
  a) nota protocolada e nao paga, nota a nota, com a data do protocolo. A nota paga em parte (alguma baixa com valor
     no RM e falta acima da tolerancia) entra pelo que falta nos titulos, marcada "paga em parte";
  a') repasse sem baixa (`tipo_aberto` "repasse", `em_aberto_repasse_centavos`): a nota da empresa ao consorcio de
     medicao ja' RECEBIDA (o orgao pagou o consorcio) cujos titulos seguem sem baixa, ou baixados em parte. Quem
     deve e' o consorcio, nao o orgao: fica em grupo proprio, fora de (a), para a tela nao dizer "nao paga" do que
     o orgao pagou;
  b) medicao protocolada (e nao recebida) SEM nota ligada, pelo valor da medicao (aprovado, senao o pedido), com a
     data do protocolo. Entra no em aberto do mes;
  A medicao com nota emitida da obra sem o passo "Envio da nota" entra em (a) e (b) como a protocolada
  (`_em_cobranca`). Ela nao tem protocolo: a linha do em aberto leva a data da emissao da nota (`emitida_em`), de
  onde a espera pelo pagamento conta (docs/adr/0006);
  c) nota de cobranca em aberto no RM SEM medicao ligada (`_notas_sem_medicao`), com a data da emissao. Nao tem
     competencia: fica fora dos meses e do total, como subtotal a' parte. Pode ser a mesma cobranca de uma medicao de
     (b) enquanto o vinculo nao e' feito; nao se casa por valor (`docs/adr/0005`), a tela diz isso numa frase. A
     paga em parte entra pelo que falta nos titulos, como em (a).
  O total do em aberto e' (a) + (a') + (b), por ano de competencia (`por_ano`), e protocolado - recebido e'
  (a) + (a'): o painel "Em aberto" da tela segue o ano escolhido e fecha com o numero do alto e com o total do ano
  na tabela do mes. Com o total a receber ainda nao
  liberado no cadastro (`geral.yaml: diretoria.total_a_receber_liberado`, `diretoria._liberado`), o em aberto nao sai
  do servidor, nem o recebido, que o deixaria deduzir (`_esconder_a_receber`). O estado da medicao nao sai na
  resposta, com ou sem a trava (revisao da PR #754): a tela nao o usa, e com ele e o protocolado dava para refazer o
  em aberto que a trava esconde (protocolada = em aberto; recebida = paga).
- Cobertura do vinculo, por ano: quanto do aprovado das medicoes com nota emitida (ou alem) tem nota ligada que
  conta (`_notas_da_conta`; em consorcio, a nota da empresa ou a fatura do consorcio).
- Nota da empresa diferente da cota (`notas_diferem`): a cobertura so' diz se ha' nota ligada, nao se o valor fecha.
  Em consorcio, as notas da empresa ligadas a' medicao deveriam somar a cota dela; quando a diferenca passa de
  `diretoria.TOLERANCIA_CENTAVOS`, a medicao sai nessa lista, com os dois valores. So' avisa: nenhum numero muda.
- Par misto (`pares_mistos`): a execucao e o reajuste de mesmo numero, na mesma obra de consorcio, em que uma conta
  pela nota da empresa e a outra pela fatura do consorcio. A fatura unica do consorcio cobre as duas: enquanto a
  nota da empresa nao e' ligada tambem a' outra, a mesma cobranca pode estar somada duas vezes. So' avisa.

Excluido no RM (issue #755, docs/adr/0006): a nota e o titulo que o RM deixou de devolver (`excluida_rm_em`) ficam
fora de todo numero desta pagina. A nota marcada deixa de ser ativa e perde o vinculo, entao sai do protocolado, do
em aberto e das notas sem medicao; o titulo marcado nao entra na situacao da nota nos titulos (`_no_rm`), nem no
recebido, nem na falta.

So' aparece o que tem lancamento: mes sem medicao nao vira linha, e nada e' estimado. O em aberto de competencias
anteriores a 2025 fica contado a' parte.

Familias de valor (issue #805, decisao do dono de 18/11/2026): a tela mostra a variacao do medido e a diferenca entre
o aprovado e o pedido, e as duas referencias saem daqui, prontas:
- Diferenca aprovado x pedido: `aprovado_com_pedido_centavos` e `pedido_do_aprovado_centavos`, na cota, somados so'
  das medicoes que tem o valor do boletim gravado E o pedido (`_linha_medicao`). A medicao ainda em analise nao entra:
  nela nao ha' diferenca, ha' etapa nao alcancada, e somar o pedido dela faria o mes parecer aprovado a menor. A
  medicao com nota emitida e sem o valor do boletim (o pedido conta como aprovado, `_aprovado`) tambem nao: nao ha'
  dois valores para comparar. Por isso a diferenca NAO e' medido - aprovado. Os dois numeros somam como os outros
  (medicao, obra, mes, ano) e sao a base do percentual. O limite que separa a diferenca pequena da critica vai em
  `diferenca_critica_por_mil` e e' o do aviso "aprovado abaixo do pedido" (`avisos_medicao.ABAIXO_DO_PEDIDO_POR_MIL`,
  issue #741): um numero so'.
  O que a tela mostra como diferenca do mes, da obra e do ano e' so' o CORTE: `abaixo_do_pedido_centavos`, a soma de
  (pedido - aprovado), na cota, das medicoes com o aprovado ABAIXO do pedido; tambem soma como os outros. O aprovado
  ACIMA do pedido nao entra nessa soma (revisao da PR #806 sobre a copia da producao): quase sempre e' pedido gravado
  errado, e somado no mes anulava o corte real de outra obra. Ele sai so' na linha da medicao
  (`acima_do_pedido_centavos`), onde se confere o pedido (issue #807).
  Diferenca de ate' `TOLERANCIA_DO_PEDIDO_CENTAVOS` por medicao, no valor cheio, e' arredondamento do orgao (decisao
  do dono de 10/11/2026) e conta como igual: nao entra no corte nem no acima.
- Variacao do medido: `medido_ano_anterior_centavos`, em cada mes, e' o medido do mesmo mes do ano anterior. So' nos
  meses de competencia ja' encerrada (anteriores ao mes de hoje: o mes em curso ainda recebe medicao) e so' quando o
  ano anterior esta' na pagina e teve medido nesse mes; senao, nulo.

Por contratante (issue #815, decisao do dono de 18/11/2026): `por_contratante`, por ano, uma linha por contratante com
os mesmos numeros do ano (`SOMAS`). Nao ha' conta nova: cada medicao da pagina e' de UM contrato, e o contrato de UM
contratante (`_contratantes`: a sigla da lista de Obras, a SINFRA inteira num grupo so'), entao a linha do contratante
e' a soma das MESMAS linhas de medicao (`_linha_medicao`) que somam a obra, o mes e o ano, no mesmo laco. Por isso as
linhas de um ano somam o total do ano (`por_ano`) em toda coluna, ao centavo: a nota de consorcio e a nota partilhada
entre medicoes ja' entraram uma vez so' na linha da medicao. A participacao (`participacao_medido_por_mil`) e' a do
medido do contratante no medido do ano, em milesimos, repartida por `dinheiro.ratear_proporcional` (as linhas somam
1000); nula quando o ano nao tem medido ou algum contratante tem medido negativo (nao ha' parte de um total assim).
A ordem e' a do medido, o maior primeiro. Com a trava do total a receber, o recebido e o em aberto das linhas vem
nulos, como nos outros niveis.
"""
import datetime
from decimal import ROUND_HALF_UP, Decimal

from app import (avisos_medicao, cobranca_orgao, contratos, db, diretoria, dinheiro, medicoes, notas as notas_fiscais,
                 sincronizacao_rm, tempo)

# o primeiro ano e' `diretoria.ANO_INICIAL`: a UNICA definicao de "anterior", a mesma do a receber do Inicio (adr 0006)
ANOS = (diretoria.ANO_INICIAL, "2026")
ESTADOS_APROVADO = ("boletim_recebido", "espelho_gerado", "espelho_enviado", "nota_emitida", "protocolada",
                    "nf_emitida", "recebida")
# a nota emitida e' a prova de que o orgao aprovou: sem o valor do boletim gravado, o pedido conta como aprovado daqui em diante
ESTADOS_COM_NOTA = ("nota_emitida", "protocolada", "nf_emitida", "recebida")
ESTADOS_PROTOCOLADO = ("protocolada", "nf_emitida", "recebida")
ESTADOS_EM_COBRANCA = ("protocolada", "nf_emitida")       # protocolada e ainda nao recebida
NUMEROS = ("medido_centavos", "aprovado_centavos", "protocolado_centavos", "recebido_centavos", "em_aberto_centavos")
# as tres partes que somam o em aberto: (a) `em_aberto_notas`, (a') `em_aberto_repasse` e (b) `sem_nota`
PARTES_DO_ABERTO = ("em_aberto_notas_centavos", "em_aberto_repasse_centavos", "sem_nota_centavos")
# issue #805: os dois lados da diferenca aprovado x pedido, so' das medicoes que tem os dois valores, e o corte (a
# soma do que o orgao aprovou abaixo do pedido); ver o cabecalho
COMPARAVEIS = ("aprovado_com_pedido_centavos", "pedido_do_aprovado_centavos", "abaixo_do_pedido_centavos")
# Decisao do dono de 10/11/2026: "ate' R$ 0,05 e' arredondamento do orgao". O aprovado que difere do pedido por ate'
# cinco centavos, no valor cheio da medicao (o valor em que o orgao arredonda), conta como igual ao pedido.
TOLERANCIA_DO_PEDIDO_CENTAVOS = 5
SOMAS = NUMEROS + PARTES_DO_ABERTO + COMPARAVEIS
ESCONDIDOS = ("recebido_centavos", "em_aberto_centavos") + PARTES_DO_ABERTO                               # pela trava
PAR = ("execucao", "reajuste")                           # os tipos que a fatura unica do consorcio cobre juntos


def _cobrada(m: dict) -> bool:
    """A medicao ja' foi cobrada do orgao: protocolada (ou alem) ou, na obra sem o passo "Envio da nota", com a nota
    emitida (`sem_protocolo`, de `medicoes.recebe_sem_protocolo`). As notas dela entram no protocolado."""
    return m["estado"] in ESTADOS_PROTOCOLADO or m["sem_protocolo"]


def _em_cobranca(m: dict) -> bool:
    """Cobrada e ainda nao recebida: a protocolada e a de nota emitida da obra sem o passo "Envio da nota"."""
    return m["estado"] in ESTADOS_EM_COBRANCA or m["sem_protocolo"]


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


def _notas_da_conta(m: dict, ligadas: list[dict]) -> tuple[list[dict], list[dict]]:
    """A UNICA definicao de quais notas ligadas a' medicao entram no protocolado, no recebido, no em aberto e na
    cobertura, e com que percentual: (as que contam, cada uma com `pct` e `pela_baixa`; as que ficam fora da conta).
    Em medicao de contrato de consorcio com a nota da PROPRIA empresa ao consorcio ligada (decisao do dono de
    17/11/2026, issue #756), contam so' as da empresa, pelo valor de face (`pct` nulo = integral: a nota ja' e' a
    cota), e a fatura do consorcio ligada a' mesma medicao fica fora. Sem ela, e em obra propria, contam as notas da
    coligada da entidade do contrato, pelo percentual do contrato. Nunca as duas na mesma medicao. Nota de qualquer
    outra coligada (a NFS-e de outra consorciada) nao conta nem aparece.
    `pela_baixa` marca a nota da empresa ao consorcio: o recebido dela vem so' da baixa dos titulos dela
    (`_recebimento`), nao do estado da medicao.
    Cada nota que conta sai com `cota`, o valor dela na cota (`_cotas`): e' esse o numero que entra em toda soma."""
    do_contrato = [x for x in ligadas if x["coligada"] == m["coligada"]]
    empresa = m["coligada_empresa"]
    da_empresa = [x for x in ligadas if x["coligada"] == empresa] if m["consorcio"] and empresa != m["coligada"] else []
    if da_empresa:
        return [{**x, "pct": None, "pela_baixa": True, "cota": x["valor"] or 0} for x in da_empresa], do_contrato
    return [{**x, "pct": m["pct"], "pela_baixa": False, "cota": v}
            for x, v in zip(do_contrato, _cotas([x["valor"] or 0 for x in do_contrato], m["pct"]))], []


def _cotas(valores: list[int], pct: int | None) -> list[int]:
    """A cota de cada fatura do consorcio de UMA medicao. O arredondamento e' um so', no total: a cota da soma das
    faturas, repartida entre elas na proporcao do valor cheio, com o residuo nos maiores restos
    (`dinheiro.ratear_proporcional`). Arredondar a cota fatura a fatura somava um centavo a mais (ou a menos) que a
    cota do valor aprovado quando a medicao tem varias faturas: o protocolado do mes passava do aprovado. Com uma
    fatura so', ou em obra propria, e' `contratos.cota` de sempre."""
    if len(valores) < 2 or any(v < 0 for v in valores) or sum(valores) <= 0:
        return [contratos.cota(v, pct) or 0 for v in valores]
    return dinheiro.ratear_proporcional(contratos.cota(sum(valores), pct) or 0, valores)


def _recebimento(m: dict, nota: dict, valor_cota: int) -> tuple[int, int]:
    """A UNICA definicao do recebido desta pagina: (valor que entra no recebido, valor que fica em aberto), que somam
    o valor bruto da nota (o mesmo do protocolado), no mes da competencia da medicao. "Bruto por competencia":
    - a nota da medicao recebida (baixa no RM ou registro do administrador, docs/adr/0006) e a nota com os titulos
      baixados no RM, faltando ate' `diretoria.TOLERANCIA_CENTAVOS`, entram inteiras no recebido;
    - a nota da empresa ao consorcio (`pela_baixa`, de `_notas_da_conta`) e' a excecao a' primeira parte (decisao do
      dono de 17/11/2026): o estado da medicao nao a leva ao recebido. A medicao de consorcio vira recebida quando o
      orgao paga a fatura do consorcio (`sincronizacao_rm._recebimentos` so' olha a coligada do contrato), e a cota
      da empresa so' entrou quando o consorcio repassou, que e' a baixa dos titulos da nota dela. Vale para ela so' o
      que os titulos dizem, como nas linhas abaixo; sem titulo no RM, fica inteira em aberto;
    - a nota paga em parte (alguma baixa com valor e falta acima da tolerancia, `_no_rm`) fica em aberto pelo que
      falta nos titulos do RM, na cota (pelo percentual da nota, `_notas_da_conta`: a falta da nota da empresa ao
      consorcio ja' e' a cota), limitado ao valor da nota; o recebido e' o valor bruto menos essa falta;
    - a nota sem nenhuma baixa com valor fica inteira em aberto, pelo bruto. Titulo baixado sem valor (glosa,
      compensacao) nao e' recebimento.
    Trocar para outra base (o liquido baixado, pelo mes do pagamento) e' trocar esta funcao e o mes em `_fechamento`."""
    if nota["no_rm"] == "paga" or (m["estado"] == "recebida" and not nota["pela_baixa"]):
        return valor_cota, 0
    aberto = _falta_na_cota(nota["falta"], nota["pct"], valor_cota) if nota["no_rm"] == "parte" else valor_cota
    return valor_cota - aberto, aberto


def _falta_na_cota(falta: int, pct: int | None, teto: int) -> int:
    """O que falta nos titulos de uma nota paga em parte, na cota (`pct` nulo: a falta ja' e' a cota), sem passar do
    valor da nota (`teto`)."""
    return min(contratos.cota(falta, pct) or 0, teto)


def _pela_nota_da_empresa(conn) -> tuple[dict[int, int], set[int], set[int]]:
    """A escolha de `_notas_da_conta` em todas as medicoes de consorcio COBRADAS (`_cobrada`) que contam pela nota da
    PROPRIA empresa (`pela_baixa`), lida uma vez, para os lugares fora desta pagina nao terem cada um a sua definicao:
    - medicao -> o que esta' em aberto nas notas da empresa dela, ja' na cota (`_recebimento`: a face menos o que foi
      baixado nos titulos delas; zero quando o repasse ja' foi baixado);
    - as notas da empresa que contam nessas medicoes;
    - as faturas do consorcio que ficaram fora da conta em toda medicao cobrada a que estao ligadas (as preteridas pela
      nota da empresa). A fatura que ainda conta em alguma medicao (o par misto) nao sai."""
    with db.leitura(conn):
        ms = _medicoes(conn)
        notas = _notas_por_medicao(conn, {m["id"] for m in ms})
        aberto: dict[int, int] = {}
        contam_em_alguma, fora_em_alguma, da_empresa = set(), set(), set()
        for m in ms:
            contam, fora = _notas_da_conta(m, notas.get(m["id"], []))
            contam_em_alguma |= {x["nota_id"] for x in contam}
            if not _cobrada(m) or not any(x["pela_baixa"] for x in contam):
                continue
            aberto[m["id"]] = sum(_recebimento(m, x, x["cota"])[1] for x in contam)
            da_empresa |= {x["nota_id"] for x in contam}
            fora_em_alguma |= {x["nota_id"] for x in fora}
        return aberto, da_empresa, fora_em_alguma - contam_em_alguma


def cota_pela_nota_da_empresa(conn) -> tuple[dict[int, int], set[int]]:
    """Para o a receber do Inicio e da lista de Obras (`diretoria.a_receber_na_cota`, issue #756): por medicao de
    consorcio que conta pela nota da propria empresa, o que esta' em aberto nelas; e as faturas do consorcio
    preteridas (`_pela_nota_da_empresa`)."""
    aberto, _, preteridas = _pela_nota_da_empresa(conn)
    return aberto, preteridas


def notas_do_recebido_em_consorcio(conn) -> tuple[set[int], set[int]]:
    """Para o recebido do Inicio (`diretoria._pct_do_recebido`; decisao do dono de 17/11/2026, issue #756, levada ao
    Inicio na mesma data): (as notas da propria empresa que contam em medicao de consorcio cobrada, cujas baixas sao o
    recebido da cota, pela face; as faturas do consorcio preteridas por elas, cujas baixas nao entram). A mesma
    escolha desta pagina (`_pela_nota_da_empresa`)."""
    _, da_empresa, preteridas = _pela_nota_da_empresa(conn)
    return da_empresa, preteridas


def notas_da_cota_em_consorcio(conn, medicao_id: int) -> tuple[list[dict], list[dict]] | None:
    """Para a pagina da medicao (passo Pagamento, issue #756): numa medicao de contrato de consorcio, a escolha de
    `_notas_da_conta` entre as notas de cobranca ligadas a ela (`_notas_por_medicao`): (as que contam na cota, cada
    uma com `pct`, `pela_baixa` e `quitada`; as faturas do consorcio que a nota da empresa tirou da conta). `quitada`
    e' a leitura de `_recebimento`: nada em aberto na nota (os titulos baixados, faltando ate' a tolerancia, ou a
    fatura do consorcio de medicao recebida; a nota da empresa, so' pela baixa dos titulos dela). None quando a
    medicao nao e' de consorcio (ou ainda nao mede): ali o passo Pagamento segue a regra dele."""
    ms = _medicoes(conn)
    m = next((x for x in ms if x["id"] == medicao_id), None)
    if m is None or not m["consorcio"] or m["coligada_empresa"] in (None, m["coligada"]):
        return None
    # as notas de todas as medicoes, como a pagina le: o valor da nota ligada a mais de uma medicao depende dos
    # outros vinculos dela (`_notas_por_medicao`)
    contam, fora = _notas_da_conta(m, _notas_por_medicao(conn, {x["id"] for x in ms}).get(medicao_id, []))
    for x in contam:
        x["quitada"] = _recebimento(m, x, x["cota"])[1] == 0
    return contam, fora


def _medicoes(conn) -> list[dict]:
    estados = medicoes.ESTADOS_NO_MEDIDO
    empresa = notas_fiscais._coligada_lotufo(conn)           # a coligada da propria empresa no RM
    passos_de = medicoes.passos_das_medicoes(conn)
    return [{**dict(r), "coligada_empresa": empresa,
             # #743: na obra sem o passo "Envio da nota", a nota emitida ja' e' a cobranca (espera o pagamento)
             "sem_protocolo": medicoes.recebe_sem_protocolo(r["estado"], passos_de(r))} for r in conn.execute(
        f"""SELECT m.id, m.contrato_id, m.numero, m.tipo, m.competencia, m.estado, m.planilha_enviada_em,
                   m.nota_emitida_em,
                   m.valor_protocolado_centavos AS pedido, m.valor_atestado_centavos AS aprovado,
                   c.percentual_direito_bp AS pct, COALESCE(c.nome_curto, c.numero_instrumento) AS obra,
                   e.coligada_rm AS coligada, e.papel='consorcio' AS consorcio,
                   (SELECT MIN(mp.data) FROM medicao_protocolos mp WHERE mp.medicao_id=m.id AND mp.etapa='nota' AND mp.desfeita_em IS NULL) AS protocolo_em
            FROM medicoes m JOIN contratos c ON c.id=m.contrato_id
            JOIN entidades e ON e.id=COALESCE(c.entidade_id, 1)
            WHERE m.estado IN ({','.join('?' * len(estados))})
            ORDER BY m.competencia, obra, m.contrato_id, m.numero, m.tipo""", estados)]


def _notas_por_medicao(conn, ids: set[int]) -> dict[int, list[dict]]:
    """As notas de cobranca ligadas a cada medicao (vinculo vigente; ativas, nao desconsideradas, de tipo de cobranca
    ou so' lidas do PDF), de qualquer coligada, com o valor de cada vinculo e a situacao nos titulos do RM. `valor` e
    `falta` estao na base da propria nota (valor cheio na fatura do consorcio; ja' a cota na nota da empresa ao
    consorcio). Quais delas contam em cada medicao, e com que percentual, e' de `_notas_da_conta`.
    "De tipo de cobranca" e' de `cobranca_orgao.e_cobranca` (docs/adr/0015), com o contrato da MEDICAO a que a nota
    esta' ligada: a lista geral vale em toda obra, e o tipo extra so' na obra cujo cadastro o declara. A mesma nota
    ligada a medicoes de dois contratos e' julgada em cada um. A consulta so' estreita por `tipos_buscados`."""
    extras = cobranca_orgao.extras_por_contrato(conn)
    tipos = cobranca_orgao.tipos_buscados(extras)
    linhas = [dict(r) for r in conn.execute(
        f"""SELECT a.medicao_id, a.id AS alocacao_id, a.valor_alocado_centavos, a.partilhada, n.id AS nota_id, n.numero,
                   n.valor_centavos, n.coligada, n.codtmv, m.contrato_id
            FROM nf_alocacoes a JOIN notas_fiscais n ON n.id=a.nota_id JOIN medicoes m ON m.id=a.medicao_id
            WHERE a.desfeita_em IS NULL AND n.situacao='ativa' AND n.desconsiderada_em IS NULL
              AND n.excluida_rm_em IS NULL
              AND (n.codtmv IS NULL OR n.codtmv IN ({','.join('?' * len(tipos))}))
            ORDER BY n.emissao, n.id""", tipos)
        if r["medicao_id"] in ids and (r["codtmv"] is None or cobranca_orgao.e_cobranca(r["codtmv"], r["contrato_id"], extras))]
    vinculos: dict[int, int] = {}
    for x in linhas:
        vinculos[x["nota_id"]] = vinculos.get(x["nota_id"], 0) + 1
    out: dict[int, list[dict]] = {}
    por_nota: dict[int, list[dict]] = {}
    for x in linhas:
        # o vinculo de PARTE da nota (`partilhada`, docs/adr/0005) vale o valor da parte, mesmo sendo o unico
        inteira = vinculos[x["nota_id"]] == 1 and not x["partilhada"]
        y = {**x, "valor": x["valor_centavos"] if inteira else x["valor_alocado_centavos"]}
        out.setdefault(x["medicao_id"], []).append(y)
        por_nota.setdefault(x["nota_id"], []).append(y)
    for nota_id, xs in por_nota.items():
        no_rm, falta = _no_rm(conn, nota_id)
        if any(x["partilhada"] for x in xs):
            # nota partilhada: a falta dos titulos reparte-se entre as partes e o resto que nenhuma medicao levou
            # (`sincronizacao_rm.partes_da_nota`, a mesma conta do a receber do Inicio)
            da_parte = sincronizacao_rm.partes_da_nota(conn, nota_id, falta)
            partes = [da_parte.get(x["alocacao_id"], 0) for x in xs]
        else:
            # a falta e' da nota: ligada a mais de uma medicao, reparte-se na proporcao do valor de cada vinculo
            pesos = [max(0, x["valor"] or 0) for x in xs]
            partes = dinheiro.ratear_proporcional(falta, pesos) if len(xs) > 1 and sum(pesos) > 0 else [falta] * len(xs)
        for x, parte in zip(xs, partes):
            x["no_rm"], x["falta"] = no_rm, parte
    return out


def _no_rm(conn, nota_id: int) -> tuple[str, int]:
    """A nota nos titulos (nao cancelados nem excluidos no RM, issue #755) do RM: ("paga", 0), ("parte", o que falta)
    ou ("aberta", 0). A falta vem na base da propria nota: valor cheio na fatura do consorcio, ja' a cota na nota da
    empresa ao consorcio.
    Sem nenhuma baixa COM VALOR, aberta (sem titulo, titulo sem baixa ou baixado sem valor: glosa e compensacao nao
    sao recebimento). Com alguma, conta o que falta titulo a titulo (`sincronizacao_rm._falta_por_titulo`; o titulo
    sem baixa com valor entra inteiro, e juros num titulo nao cobrem outro): ate' `diretoria.TOLERANCIA_CENTAVOS`,
    paga; acima, paga em parte."""
    recebido = sincronizacao_rm.STATUS_RECEBIDO
    if not conn.execute(f"SELECT 1 FROM baixas WHERE nota_id=? AND status_lan IN ({','.join('?' * len(recebido))}) "
                        "AND valor_baixado_centavos>0 AND excluida_rm_em IS NULL", (nota_id, *recebido)).fetchone():
        return "aberta", 0
    falta = sincronizacao_rm._falta_por_titulo(conn, nota_id, aberto_inteiro=True) or 0
    return ("paga", 0) if falta <= diretoria.TOLERANCIA_CENTAVOS else ("parte", falta)


def _numero_nota(numero) -> str:
    s = str(numero or "").strip()
    return str(int(s)) if s.isdigit() else s


def _difere_da_cota(conn, m: dict, ligadas: list[dict]) -> dict | None:
    """Em consorcio, as notas da propria empresa que contam na medicao (`_notas_da_conta`) deveriam somar a cota dela.
    Devolve a soma das notas, a cota e a diferenca (notas - cota) quando ela passa de `diretoria.TOLERANCIA_CENTAVOS`
    (a cota arredonda meio para cima; a nota pode ter arredondado para o outro lado); senao, nada. Vale da nota
    emitida em diante, a mesma base da cobertura do vinculo. A cota e' a do valor que a nota cobre
    (`medicoes.valor_do_par`, issue #589: a execucao que absorveu reajuste negativo e' faturada pelo liquido do par)."""
    if m["estado"] not in ESTADOS_COM_NOTA or not any(x["pela_baixa"] for x in ligadas):
        return None
    valor = medicoes.valor_do_par(conn, m["id"], _aprovado(m))
    if valor is None:
        return None
    cota = contratos.cota(valor, m["pct"]) or 0
    soma = sum(x["cota"] for x in ligadas)
    if abs(soma - cota) <= diretoria.TOLERANCIA_CENTAVOS:
        return None
    return {"notas_centavos": soma, "cota_centavos": cota, "diferenca_centavos": soma - cota}


def _conta_por(m: dict, ligadas: list[dict]) -> str | None:
    """Em medicao de consorcio com nota emitida ou alem (a base da cobertura), por qual nota ela conta: "empresa" (a
    nota da propria empresa ao consorcio), "consorcio" (a fatura do consorcio vezes a cota) ou nada (sem nota que
    conte, ou obra propria)."""
    if not m["consorcio"] or m["estado"] not in ESTADOS_COM_NOTA or not ligadas:
        return None
    return "empresa" if any(x["pela_baixa"] for x in ligadas) else "consorcio"


def _pares_mistos(linhas: list[dict]) -> list[dict]:
    """A execucao e o reajuste de mesmo numero, na mesma obra de consorcio, contando por notas diferentes: uma pela
    nota da empresa e a outra pela fatura do consorcio. A fatura unica do consorcio cobre as duas; ligada so' a uma
    delas, enquanto a outra ja' conta pela nota da empresa, a mesma cobranca entra duas vezes no mes (a escolha de
    `_notas_da_conta` e' por medicao). Sai a medicao que ainda conta pela fatura do consorcio, que e' onde falta ligar
    a nota da empresa, com a que ja' conta por ela (`par_*`); so' das competencias da pagina. So' avisa."""
    grupos: dict[tuple, list[dict]] = {}
    for x in linhas:
        if x["_conta_por"] and x["tipo"] in PAR:
            grupos.setdefault((x["contrato_id"], x["numero"]), []).append(x)
    out = []
    for xs in grupos.values():
        pela_empresa = [x for x in xs if x["_conta_por"] == "empresa"]
        for x in xs:
            if x["_conta_por"] == "consorcio" and pela_empresa and x["competencia"][:4] in ANOS:
                out.append({"contrato_id": x["contrato_id"], "obra": x["obra"], "medicao_id": x["medicao_id"],
                            "medicao_numero": x["numero"], "tipo": x["tipo"], "competencia": x["competencia"],
                            "par_medicao_id": pela_empresa[0]["medicao_id"], "par_tipo": pela_empresa[0]["tipo"]})
    return sorted(out, key=lambda e: (e["competencia"], e["obra"], e["contrato_id"], e["medicao_numero"], e["tipo"]))


def medido_na_cota(m: dict) -> int:
    """O medido de UMA medicao de `_medicoes`, na cota: o aprovado e, sem boletim, o pedido (`GLOSSARY.md`, Medido);
    sem valor nenhum, zero. A UNICA conta do medido por competencia: a desta pagina (`_linha_medicao`) e a do "medido
    no mes" da lista de Obras (`medido_do_mes_fechado`)."""
    valor = m["aprovado"] if m["aprovado"] is not None else m["pedido"]
    return (contratos.cota(valor, m["pct"]) or 0) if valor is not None else 0


def medido_das_competencias(conn, competencias, contratos_ids=None) -> dict[str, int]:
    """Issue #805 (Resumo das medicoes em quadro): o medido de cada competencia pedida, na cota. E' o `medido_centavos`
    que esta pagina mostra no mes: as mesmas medicoes (`_medicoes`) e a mesma conta por medicao (`medido_na_cota`),
    sem montar o fechamento inteiro. `contratos_ids` recorta as obras (o filtro por contratante do Resumo das
    medicoes); sem ele, todas. Competencia sem medicao vem com zero."""
    soma = dict.fromkeys(competencias, 0)
    for m in _medicoes(conn):
        if m["competencia"] in soma and (contratos_ids is None or m["contrato_id"] in contratos_ids):
            soma[m["competencia"]] += medido_na_cota(m)
    return soma


def medido_do_mes_fechado(conn, hoje: datetime.date) -> dict:
    """Issue #805 (Obras por contratante): o medido de cada obra na ultima competencia FECHADA (o mes anterior ao de
    `hoje`; o mes em curso ainda recebe medicao, como em `_medido_do_ano_anterior`) e na competencia anterior a ela, a
    referencia da variacao. E' o `medido_centavos` que esta pagina mostra para a obra naquele mes: as mesmas medicoes
    (`_medicoes`) e a mesma conta por medicao (`medido_na_cota`), sem montar o fechamento inteiro (notas e titulos).
    `referencia_competencia` e' nula quando o mes de referencia e' anterior ao primeiro ano que as telas da diretoria
    contam (`ANOS`): nao serve de referencia. Obra sem medicao no mes fica fora de `por_obra`."""
    mes, anterior = diretoria._mes(hoje, -1), diretoria._mes(hoje, -2)
    por_obra: dict[str, dict[int, int]] = {mes: {}, anterior: {}}
    for m in _medicoes(conn):
        da_competencia = por_obra.get(m["competencia"])
        if da_competencia is not None:
            da_competencia[m["contrato_id"]] = da_competencia.get(m["contrato_id"], 0) + medido_na_cota(m)
    com_referencia = anterior[:4] >= ANOS[0]
    return {"competencia": mes, "por_obra": por_obra[mes],
            "referencia_competencia": anterior if com_referencia else None,
            "referencia_por_obra": por_obra[anterior] if com_referencia else {}}


def aprovado_contra_o_pedido(estado: str, pedido: int | None, aprovado: int | None, pct: int | None = None) -> dict | None:
    """A diferenca aprovado x pedido de UMA medicao (cabecalho, "Diferenca aprovado x pedido"), a UNICA conta dela: a
    do Fechamento (`_linha_medicao`, na cota) e a da tela Medicoes (`fila_medicoes`, no valor cheio, sem `pct`).
    `pedido` e `aprovado` sao o valor cheio gravado na medicao (o pedido e o valor do boletim); `pct`, a cota do
    contrato (`percentual_direito_bp`). So' ha' o que comparar a partir do boletim (`ESTADOS_APROVADO`) e com os dois
    valores gravados: senao, None. Devolve os tres `COMPARAVEIS` (os dois lados e o corte) e
    `acima_do_pedido_centavos`, que nao soma em mes, obra nem ano. A tolerancia de arredondamento e' do valor cheio
    (o do orgao); o corte e o acima saem na base pedida, como os outros numeros."""
    if estado not in ESTADOS_APROVADO or aprovado is None or pedido is None:
        return None
    n = {"aprovado_com_pedido_centavos": contratos.cota(aprovado, pct) or 0,
         "pedido_do_aprovado_centavos": contratos.cota(pedido, pct) or 0,
         "abaixo_do_pedido_centavos": 0, "acima_do_pedido_centavos": 0}
    falta = pedido - aprovado
    if falta > TOLERANCIA_DO_PEDIDO_CENTAVOS:
        n["abaixo_do_pedido_centavos"] = max(0, n["pedido_do_aprovado_centavos"] - n["aprovado_com_pedido_centavos"])
    elif -falta > TOLERANCIA_DO_PEDIDO_CENTAVOS:
        n["acima_do_pedido_centavos"] = max(0, n["aprovado_com_pedido_centavos"] - n["pedido_do_aprovado_centavos"])
    return n


def _linha_medicao(conn, m: dict, notas: list[dict]) -> dict:
    cota = lambda v: contratos.cota(v, m["pct"]) or 0
    valor = m["aprovado"] if m["aprovado"] is not None else m["pedido"]
    aprovado = _aprovado(m)
    n = _zero()
    n["medido_centavos"] = medido_na_cota(m)
    n["aprovado_centavos"] = cota(aprovado) if aprovado is not None else 0
    # issue #805: a diferenca aprovado x pedido so' existe com o valor do boletim gravado e o pedido; a medicao em
    # analise e a de nota emitida sem o valor do boletim ficam fora dos dois lados
    comparada = aprovado_contra_o_pedido(m["estado"], m["pedido"], m["aprovado"], m["pct"])
    acima = comparada.pop("acima_do_pedido_centavos") if comparada else 0
    n.update(comparada or {})
    ligadas, fora = _notas_da_conta(m, notas)
    saida, saida_fora = [], []
    if _cobrada(m):
        # a fatura do consorcio preterida pela nota da empresa: aparece na medicao, sem valor, e nao entra em soma
        saida_fora = [{"nota_id": x["nota_id"], "numero": _numero_nota(x["numero"])} for x in fora]
        for x in ligadas:
            v = x["cota"]
            recebido, aberto = _recebimento(m, x, v)
            # (a'): o orgao ja' pagou o consorcio (medicao recebida) e a nota da empresa segue sem baixa do repasse
            repasse = x["pela_baixa"] and m["estado"] == "recebida" and aberto > 0
            n["protocolado_centavos"] += v
            n["recebido_centavos"] += recebido
            n["em_aberto_repasse_centavos" if repasse else "em_aberto_notas_centavos"] += aberto
            n["em_aberto_centavos"] += aberto
            saida.append({"nota_id": x["nota_id"], "numero": _numero_nota(x["numero"]), "valor_centavos": v,
                          "recebido_centavos": recebido, "em_aberto_centavos": aberto,
                          "recebida": aberto == 0, "paga_em_parte": 0 < aberto < v, "aguarda_repasse": repasse})
    sem_nota = _em_cobranca(m) and not ligadas
    if sem_nota and valor is not None:                       # (b): protocolada sem nota ligada, pelo valor da medicao
        n["sem_nota_centavos"] = n["medido_centavos"]
        n["em_aberto_centavos"] += n["sem_nota_centavos"]
    return {"medicao_id": m["id"], "contrato_id": m["contrato_id"], "obra": m["obra"], "numero": m["numero"],
            "tipo": m["tipo"], "competencia": m["competencia"],
            "protocolo_em": (m["protocolo_em"] or "")[:10] or None, **n, "notas": saida,
            # so' na medicao (nao soma): o aprovado acima do pedido, que e' pedido a conferir, e nao corte
            "acima_do_pedido_centavos": acima,
            # so' para a linha do em aberto (`_fechamento`): de onde a espera conta na medicao sem protocolo
            "_emitida_em": ((m["nota_emitida_em"] or "")[:10] or None) if m["sem_protocolo"] else None,
            "notas_fora_da_conta": saida_fora, "sem_nota": sem_nota,
            # cobertura do vinculo: o aprovado das medicoes que ja' deveriam ter nota, e se alguma que conta esta' ligada
            "_base_cobertura": n["aprovado_centavos"] if m["estado"] in ESTADOS_COM_NOTA else 0,
            "_coberta": bool(ligadas),
            # em consorcio, as notas da empresa ligadas que nao somam a cota da medicao (`notas_diferem`)
            "_difere": _difere_da_cota(conn, m, ligadas),
            # em consorcio, por qual nota a medicao conta: a da empresa ou a fatura do consorcio (`pares_mistos`)
            "_conta_por": _conta_por(m, ligadas)}


def _notas_sem_medicao(conn) -> dict:
    """Notas de cobranca ativas sem vinculo com medicao enviada, na obra pelo centro de custo
    (`diretoria._notas_do_rm`), na cota. Em aberto no RM (`_no_rm`): uma linha por nota, com a data da emissao, de
    qualquer ano (e' cobranca que ainda nao entrou), pelo valor bruto; a paga em parte, pelo que falta nos titulos,
    limitado ao valor da nota, e marcada. Paga: so' contada, das emitidas em 2025 e 2026, pelo bruto. Nenhuma das
    duas tem competencia, entao ficam fora dos meses e dos totais, e nao dependem do ano escolhido na tela."""
    abertas, pagas = [], {"quantidade": 0, "valor_centavos": 0}
    for n, c, tem_medicao in diretoria._notas_do_rm(conn):
        if tem_medicao or n["situacao"] != "ativa":
            continue
        v = contratos.cota(n["valor_centavos"], c["pct"]) or 0
        no_rm, falta = _no_rm(conn, n["id"])
        if no_rm == "paga":
            if (n["emissao"] or "")[:4] in ANOS:
                pagas["quantidade"] += 1
                pagas["valor_centavos"] += v
            continue
        aberto = _falta_na_cota(falta, c["pct"], v) if no_rm == "parte" else v
        numero = conn.execute("SELECT numero FROM notas_fiscais WHERE id=?", (n["id"],)).fetchone()[0]
        abertas.append({"nota_id": n["id"], "numero": _numero_nota(numero), "contrato_id": c["id"], "obra": c["obra"],
                        "emissao": (n["emissao"] or "")[:10] or None, "valor_centavos": aberto,
                        "paga_em_parte": no_rm == "parte" and aberto < v})
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


def _contratantes(conn) -> dict[int, tuple[str, str | None]]:
    """Issue #815: contrato -> (o contratante, a chave da pagina dele). A sigla e a chave sao as da lista de Obras
    (`medicoes.contratante` e `diretoria.chave_do_contratante`, como em `api_contratos`): a SINFRA inteira e' um
    contratante so', e o contrato sem orgao no cadastro fica com o texto do proprio contrato, sem chave."""
    return {i: (o["contratante"], diretoria.chave_do_contratante(o["familia"], o["chave"]))
            for i, o in medicoes._obras_com_contratante(conn).items()}


def _linhas_por_contratante(grupos: dict[tuple[str, str | None], dict]) -> list[dict]:
    """Issue #815: as linhas de um ano da aba "Por contratante", o de maior medido primeiro (empate, pelo nome), cada
    uma com a participacao do medido dela no medido do ano, em milesimos. A reparticao e' de
    `dinheiro.ratear_proporcional` (so' inteiros, o residuo nos maiores restos): as participacoes somam 1000. Sem
    medido no ano, ou com medido negativo em algum contratante, a participacao vem nula."""
    linhas = sorted(grupos.values(), key=lambda g: (-g["medido_centavos"], medicoes._chave_nome(g["contratante"]),
                                                    g["contratante_chave"] or ""))
    pesos = [g["medido_centavos"] for g in linhas]
    partes = (dinheiro.ratear_proporcional(1000, pesos) if pesos and min(pesos) >= 0 and sum(pesos) > 0
              else [None] * len(linhas))
    for g, parte in zip(linhas, partes):
        g["participacao_medido_por_mil"] = parte
    return linhas


def fechamento(conn, hoje: datetime.date | None = None) -> dict:
    with db.leitura(conn):
        return _fechamento(conn, hoje or tempo.hoje_local())


def _medido_do_ano_anterior(lista: list[dict], hoje: datetime.date) -> None:
    """Issue #805: em cada mes, o medido do mesmo mes do ano anterior (`medido_ano_anterior_centavos`), a referencia
    da variacao da coluna Medido. E' o proprio `medido_centavos` daquele mes, a mesma origem da tabela que compara os
    dois anos. Nulo no mes de hoje e nos seguintes (competencia ainda aberta), e quando o ano anterior nao esta' na
    pagina ou nao teve medido no mes."""
    por_competencia = {m["competencia"]: m for m in lista}
    corrente = hoje.strftime("%Y-%m")
    for m in lista:
        comp = m["competencia"]
        anterior = por_competencia.get(f"{int(comp[:4]) - 1:04d}{comp[4:]}")
        encerrada = comp < corrente
        m["medido_ano_anterior_centavos"] = (anterior["medido_centavos"]
                                             if encerrada and anterior and anterior["medido_centavos"] > 0 else None)


def _linhas_das_medicoes(conn) -> list[dict]:
    """A linha (`_linha_medicao`) de cada medicao que mede, com as notas dela: a base de toda soma desta pagina e da
    pagina A receber (`a_receber.py`, issue #816), que le o em aberto daqui sem refazer a conta. As chaves que comecam
    com `_` sao internas e saem antes da resposta (`_fechamento`)."""
    ms = _medicoes(conn)
    notas = _notas_por_medicao(conn, {m["id"] for m in ms})
    return [_linha_medicao(conn, m, notas.get(m["id"], [])) for m in ms]


def _em_aberto_da_medicao(x: dict, emitida_em: str | None) -> list[dict]:
    """As linhas do em aberto de UMA medicao (`_linha_medicao`), a UNICA definicao delas: (a) e (a') nota a nota, pelo
    que falta de cada nota que conta e nao esta' recebida, e (b) a medicao sem nota ligada, pelo valor dela. Cada uma
    leva a obra, a medicao, a competencia e de quando a espera conta (`protocolo_em`; na medicao sem protocolo da obra
    sem o passo "Envio da nota", `emitida_em`). O em aberto do Fechamento (`_fechamento`, o do ano e o anterior a
    `ANOS`) e o da pagina A receber (issue #816) saem daqui."""
    abertas = [{"tipo_aberto": "repasse" if nt["aguarda_repasse"] else "nota", "nota_id": nt["nota_id"], "numero": nt["numero"],
                "valor_centavos": nt["em_aberto_centavos"], "paga_em_parte": nt["paga_em_parte"]}
               for nt in x["notas"] if not nt["recebida"]]
    if x["sem_nota_centavos"]:
        abertas.append({"tipo_aberto": "sem_nota", "nota_id": None, "numero": None,
                        "valor_centavos": x["sem_nota_centavos"], "paga_em_parte": False})
    return [{**e, "contrato_id": x["contrato_id"], "obra": x["obra"], "medicao_id": x["medicao_id"],
             "medicao_numero": x["numero"], "tipo": x["tipo"], "competencia": x["competencia"],
             "protocolo_em": x["protocolo_em"], "emitida_em": emitida_em} for e in abertas]


def ordem_do_em_aberto(e: dict) -> tuple:
    """A ordem das linhas do em aberto: de onde a espera conta (o protocolo; sem ele, a emissao da nota), a mais antiga
    primeiro, e a sem data no fim; depois a obra, a competencia e o numero da nota."""
    return (e["protocolo_em"] or e["emitida_em"] or "9999", e["obra"], e["competencia"], e["numero"] or "")


def _fechamento(conn, hoje: datetime.date) -> dict:
    linhas = _linhas_das_medicoes(conn)
    cobertura = _cobertura(linhas)
    mistos = _pares_mistos(linhas)

    meses: dict[str, dict] = {}
    # issue #815: a mesma linha de medicao soma tambem no contratante da obra dela, no ano da competencia
    contratante_de = _contratantes(conn)
    # a linha e' o par (nome, chave), nao o nome: o contrato sem orgao no cadastro cujo texto e' igual a' sigla de um
    # contratante ("SINFRA") fica na linha dele, sem chave, e nao dentro da do contratante (revisao da #815)
    do_contratante: dict[str, dict[tuple[str, str | None], dict]] = {a: {} for a in ANOS}
    anteriores = {"quantidade": 0, "valor_centavos": 0}
    em_aberto, diferem = [], []
    for x in linhas:
        x.pop("_base_cobertura"); x.pop("_coberta"); x.pop("_conta_por")
        difere = x.pop("_difere")
        emitida_em = x.pop("_emitida_em")
        ano = x["competencia"][:4]
        abertas = _em_aberto_da_medicao(x, emitida_em)
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
        nome, chave = contratante_de[x["contrato_id"]]
        _somar(do_contratante[ano].setdefault((nome, chave), {"contratante": nome, "contratante_chave": chave, **_zero()}), x)
        em_aberto += abertas
        if difere:
            diferem.append({"contrato_id": x["contrato_id"], "obra": x["obra"], "medicao_id": x["medicao_id"],
                            "medicao_numero": x["numero"], "tipo": x["tipo"], "competencia": x["competencia"], **difere})

    lista = []
    for comp in sorted(meses):
        m = meses[comp]
        m["obras"] = sorted(m["obras"].values(), key=lambda o: (o["obra"], o["contrato_id"]))
        lista.append(m)
    _medido_do_ano_anterior(lista, hoje)
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
    em_aberto.sort(key=ordem_do_em_aberto)
    # o em aberto (a) + (a') + (b), linha a linha; o total e as tres partes de cada ano estao em `por_ano` (a tela
    # mostra o painel do ano escolhido). (c) e o em aberto de antes de 2025 ficam a' parte, de qualquer ano.
    saida = {"anos": list(ANOS), "meses": lista, "por_ano": por_ano, "acumulado": {"ate_mes": ate, **acumulado},
             "por_contratante": {a: _linhas_por_contratante(do_contratante[a]) for a in ANOS},
             "em_aberto": em_aberto, "em_aberto_anteriores": anteriores, "notas_sem_medicao": _notas_sem_medicao(conn),
             "cobertura": cobertura, "notas_diferem": diferem, "pares_mistos": mistos,
             "diferenca_critica_por_mil": avisos_medicao.ABAIXO_DO_PEDIDO_POR_MIL,
             "total_a_receber_liberado": diretoria._liberado(conn)}
    if not saida["total_a_receber_liberado"]:
        _esconder_a_receber(saida)
    return saida


def _esconder_a_receber(f: dict) -> None:
    """Sem o total a receber liberado no cadastro (a trava de `diretoria._liberado`, a da lista de Obras e do Inicio),
    o em aberto nao sai do servidor, nem o que deixa deduzi-lo: o recebido (protocolado - recebido e' o em aberto das
    notas), a marca de recebida de cada nota, a de medicao sem nota ligada e as listas do em aberto. Como no Inicio,
    o bloco inteiro vem vazio, e a tela diz a trava em uma frase. Medido, aprovado e protocolado ficam, e os avisos
    `notas_diferem` e `pares_mistos` tambem (comparam nota com medicao; nada do recebido). O estado da medicao, que
    tambem deixaria deduzir, nao esta' na resposta em caso nenhum (`_linha_medicao`). As linhas por contratante
    (issue #815) perdem os mesmos numeros; a participacao fica, porque e' do medido."""
    def nulo(x):
        for k in ESCONDIDOS:
            x[k] = None
    for m in f["meses"]:
        nulo(m)
        for o in m["obras"]:
            nulo(o)
            for md in o["medicoes"]:
                nulo(md)
                md["sem_nota"] = False
                for nt in md["notas"]:
                    nt["recebido_centavos"] = nt["em_aberto_centavos"] = nt["recebida"] = nt["paga_em_parte"] = None
                    nt["aguarda_repasse"] = None
    for a in f["anos"]:
        nulo(f["por_ano"][a])
        nulo(f["acumulado"][a])
        for g in f["por_contratante"][a]:
            nulo(g)
    f["em_aberto"] = []
    f["em_aberto_anteriores"] = {"quantidade": 0, "valor_centavos": None}
    f["notas_sem_medicao"] = {"em_aberto": [], "em_aberto_centavos": None, "pagas": {"quantidade": 0, "valor_centavos": None}}
