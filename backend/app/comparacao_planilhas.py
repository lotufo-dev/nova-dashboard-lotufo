"""O que mudou, item a item, entre duas versoes da planilha de uma medicao (issue #610).

So' leitura: os dois xlsx ja' guardados com as versoes de `medicao_planilhas` passam pelo leitor da aba de resumo
(`leitura_planilha_medicao`, sem cadastro de custo: o grupo nao importa aqui) e se comparam. Nada se grava (D3 de
20/10/2026: a dashboard registra so' o total pedido e o aprovado).

- Chave do item: o nº do item quando as duas planilhas tem essa coluna; sem ela, codigo + discriminacao + ordem de
  ocorrencia (o "s/c" se repete). Nº repetido tambem conta a ocorrencia.
- Mudou: valor desta medicao (centavos) ou quantidade desta medicao (3 casas) diferente; o item que so' existe numa
  versao e' "incluido" ou "retirado". Item igual nao entra.
- A soma dos itens de cada versao tem de fechar, no centavo, com o TOTAL DESTA MEDIÇÃO (ou TOTAL GERAL) escrito na
  propria planilha, quando ela o escreve: diferenca que nao fecha nao se mostra.
- Versao que o leitor recusa, planilha em PDF, sem planilha ou acima do teto do leitor: "nao comparavel".
"""
from decimal import ROUND_HALF_UP, Decimal

from app import arquivos
from app import leitura_planilha_medicao as leitura

MENSAGEM = "Não reconheci a planilha desta versão para comparar; abra os dois arquivos"
UMA_VERSAO = "Esta medição tem uma versão só da planilha/carta"
SEM_VERSAO = "Esta medição não tem planilha/carta registrada"
MESMA_VERSAO = "Escolha duas versões diferentes para comparar"
SEM_ANTERIOR = "Não há versão anterior a esta para comparar"
NAO_ENCONTRADA = "Versão da planilha/carta não encontrada nesta medição"
_MILESIMO = Decimal("0.001")


def _quantidade(q: str | None) -> Decimal:
    """Quantidade desta medicao arredondada a 3 casas (vazia conta zero)."""
    d = Decimal(q).quantize(_MILESIMO, rounding=ROUND_HALF_UP) if q is not None else Decimal("0.000")
    return d if d != 0 else Decimal("0.000")      # sem "-0.000"


def _texto_qtd(d: Decimal | None) -> str | None:
    return None if d is None else format(d, "f")


def _chaves(itens: list[dict], por_numero: bool) -> list[tuple]:
    vistos: dict[tuple, int] = {}
    saida = []
    for it in itens:
        base = (it["item"],) if por_numero else (it["codigo"] or "", it["descricao"] or "")
        vistos[base] = vistos.get(base, 0) + 1
        saida.append((*base, vistos[base]))
    return saida


def _fecha(lido: dict) -> None:
    """A soma dos itens fecha com o total escrito na planilha (quando ela escreve um)."""
    escrito = lido.get("total_planilha_centavos")
    if escrito is not None and escrito != lido["total_centavos"]:
        raise leitura.PlanilhaRecusada("a soma dos itens não fecha com o total da planilha")


def comparar_leituras(de: dict, para: dict) -> dict:
    """{"total_de", "total_para", "diferenca_centavos", "itens"} entre duas leituras de `leitura.ler`. Levanta
    `leitura.PlanilhaRecusada` se a soma de uma delas nao fecha com o total da propria planilha."""
    _fecha(de)
    _fecha(para)
    itens_de, itens_para = de["itens"], para["itens"]
    por_numero = all(it["item"] for it in itens_de + itens_para)
    lado_para = dict(zip(_chaves(itens_para, por_numero), itens_para))
    usados = set()
    saida = []

    def linha(base: dict, situacao: str, a: dict | None, b: dict | None) -> dict:
        qa = _quantidade(a["quantidade_medida"]) if a else None
        qb = _quantidade(b["quantidade_medida"]) if b else None
        va = a["valor_medido_centavos"] if a else None
        vb = b["valor_medido_centavos"] if b else None
        return {"codigo": base["codigo"], "discriminacao": base["descricao"], "unidade": base["unidade"],
                "situacao": situacao, "quantidade_de": _texto_qtd(qa), "quantidade_para": _texto_qtd(qb),
                "valor_de_centavos": va, "valor_para_centavos": vb, "diferenca_centavos": (vb or 0) - (va or 0)}

    for chave, a in zip(_chaves(itens_de, por_numero), itens_de):
        b = lado_para.get(chave)
        if b is None:
            saida.append(linha(a, "retirado", a, None))
            continue
        usados.add(chave)
        if (a["valor_medido_centavos"] != b["valor_medido_centavos"]
                or _quantidade(a["quantidade_medida"]) != _quantidade(b["quantidade_medida"])):
            saida.append(linha(a, "alterado", a, b))
    for chave, b in lado_para.items():
        if chave not in usados:
            saida.append(linha(b, "incluido", None, b))
    diferenca = sum(i["diferenca_centavos"] for i in saida)
    if diferenca != para["total_centavos"] - de["total_centavos"]:      # invariante: o total e' a soma dos itens
        raise leitura.PlanilhaRecusada("a diferença dos itens não fecha com a diferença dos totais")
    return {"total_de": de["total_centavos"], "total_para": para["total_centavos"], "diferenca_centavos": diferenca,
            "itens": saida}


def _ler_versao(arquivo: str | None) -> dict:
    """A leitura do xlsx da versao; `PlanilhaRecusada` para o que nao se compara (sem planilha, PDF, acima do teto
    do leitor). Arquivo gravado que sumiu da pasta e' LookupError (404, como no download do anexo)."""
    if not arquivo or not arquivo.lower().endswith(".xlsx"):
        raise leitura.PlanilhaRecusada("a planilha desta versão não é .xlsx")
    try:
        caminho = arquivos.caminho_seguro(arquivo)
    except ValueError:
        raise LookupError("Arquivo não encontrado") from None
    if not caminho.is_file():
        raise LookupError("Arquivo não encontrado")
    if caminho.stat().st_size > leitura.MAX_BYTES_ARQUIVO:
        raise leitura.PlanilhaRecusada(leitura.GRANDE_DEMAIS)       # nem se le para a memoria
    return leitura.ler(caminho.read_bytes())


def _escolher(versoes: list, de: int | None, para: int | None):
    """(versao de, versao para) pedidas; sem parametros, a penultima e a ultima. ValueError (422) ou LookupError
    (404: a versao nao e' desta medicao)."""
    if not versoes:
        raise ValueError(SEM_VERSAO)
    if len(versoes) == 1:
        raise ValueError(UMA_VERSAO)
    por_numero = {v["versao"]: v for v in versoes}
    if para is None:
        v_para = versoes[-1]
    elif para in por_numero:
        v_para = por_numero[para]
    else:
        raise LookupError(NAO_ENCONTRADA)
    if de is None:
        anteriores = [v for v in versoes if v["versao"] < v_para["versao"]]
        if not anteriores:
            raise ValueError(SEM_ANTERIOR)
        v_de = anteriores[-1]
    elif de in por_numero:
        v_de = por_numero[de]
    else:
        raise LookupError(NAO_ENCONTRADA)
    if v_de["versao"] == v_para["versao"]:
        raise ValueError(MESMA_VERSAO)
    return v_de, v_para


def comparar(conn, medicao_id: int, de: int | None = None, para: int | None = None) -> dict:
    """A resposta da rota (contrato com a tela da issue #611). So' le: nada se grava."""
    versoes = conn.execute("SELECT id, versao, arquivo_planilha FROM medicao_planilhas WHERE medicao_id=? "
                           "ORDER BY versao", (medicao_id,)).fetchall()
    v_de, v_para = _escolher(versoes, de, para)
    lado_de = {"versao": v_de["versao"], "planilha_id": v_de["id"]}
    lado_para = {"versao": v_para["versao"], "planilha_id": v_para["id"]}
    try:
        r = comparar_leituras(_ler_versao(v_de["arquivo_planilha"]), _ler_versao(v_para["arquivo_planilha"]))
    except leitura.PlanilhaRecusada:
        return {"comparavel": False, "mensagem": MENSAGEM, "de": lado_de, "para": lado_para}
    return {"comparavel": True, "de": {**lado_de, "total_centavos": r["total_de"]},
            "para": {**lado_para, "total_centavos": r["total_para"]},
            "diferenca_centavos": r["diferenca_centavos"], "itens": r["itens"]}
