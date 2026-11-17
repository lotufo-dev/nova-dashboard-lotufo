"""Boletim SINTETICO no modelo da MT-PAR, para os testes da issue #753: o texto de cada pagina como o modelo o
imprime (capa, dados gerais, Visto, controle financeiro) e o PDF montado com ele. Obra, valores e nomes inventados;
as pessoas aparecem pelo papel.

`colado`: o valor do Visto sai logo depois do rotulo. `colado=False`: os valores saem num bloco separado dos rotulos,
como a extracao de texto devolve em parte das obras.
"""
import datetime

from fpdf import FPDF

from tests import ficticios

CONTRATO = "045/2025"
OBRA = "EXECUÇÃO DAS OBRAS DE EXEMPLO NO PARQUE DE EXEMPLO"
EMPRESA = "CONSTRUTORA EXEMPLO LTDA"
ASSINAM = ("Eng.º Civil - ENGENHEIRO DA OBRA CREA - EX0000 " + EMPRESA
           + " Eng.º Civil - FISCAL DO CONTRATO CREA N.º EX0001/D Fiscal - MTPAR")
ENVELOPE = " Docusign Envelope ID: 00000000-0000-0000-0000-000000000000"


def brl(centavos: int) -> str:
    """12345678 -> "123.456,78" (so' inteiros)."""
    inteiro, frac = divmod(centavos, 100)
    return f"{inteiro:,}".replace(",", ".") + f",{frac:02d}"


def capa(numero=7, mes="Julho/2026", contrato=CONTRATO, rodape="", periodo="01/07/26 a 31/07/26") -> str:
    return (f"Município: Contrato: MTPAR MT PARTICIPAÇÕES E PROJETOS S.A. GOVERNO DO ESTADO DE EXEMPLO "
            f"Contratada: {EMPRESA} CNPJ: {ficticios.mascara(ficticios.LOTUFO)} {numero}ª Medição - {mes} {OBRA} "
            f"RODOVIA DE EXEMPLO, KM 1, CIDADE DE EXEMPLO-EX. Período: {periodo} {contrato} MTPAR Obra: Localização: "
            f"Cidade de Exemplo - EX, 1 de Agosto de 2026 {rodape}" + ENVELOPE)


def dados_gerais(numero=7) -> str:
    """Rotulos num bloco e valores noutro, como a pagina sai: o "N.º da Medição" fica longe do "7ª"."""
    return ("Resp. Técnico Unid. Unid. Dias --- --- R$ Descrição Nome Título CREA N.º Registro Conselho de Classe "
            "Fonte do Índice do Fator de Reajuste Medição: Provisória Empresa Gerenciadora/Supervisora: Nome de Empresa "
            f"CNPJ {numero}ª 01/07/2026 31/07/2026 N.º Tipo do Aditivo Data Assinatura Valores da obra: Item Valor % "
            "A 9.000.000,00 R$ 100,00% Valor Contratado 01/08/2026 Cidade de Exemplo - EX Status da Medição "
            "N.º da Medição Data Início da Medição Data Final da Medição Data Assinatura Medição" + ENVELOPE)


def visto(numero=7, valor=12_345_679, colado=True, contrato=CONTRATO, data="1 de Agosto de 2026",
          anteriores=55_555_555, saldo=1_111_111) -> str:
    p = "." * 40
    if colado:
        return (f"Atenciosamente Visto GOVERNO DO ESTADO DE EXEMPLO MTPAR - MT PARTICIPAÇÕES E PROJETOS S.A. "
                f"Dados da Obra: Obra: {OBRA} Dados do Contrato: Contratada {p} {EMPRESA} "
                f"Instrumento Contratual N.º {p} {contrato} MTPAR Data Assinatura do Contrato {p} 03/02/25 "
                f"Valores: Valor Contratual (PI) {p} 9.000.000,00 R$ "
                f"Valor Total Contratual (Contrato + Aditivos) {p} 9.000.000,00 R$ "
                f"Valor Total da {numero}ª Medição {p} {brl(valor)} R$ "
                f"Valor Total Acumulado das Medições Anteriores {p} {brl(anteriores)} R$ "
                f"Saldo à Medir/Executar {p} {brl(saldo)} R$ Prazos: Prazo Contratual de Execução {p} 300 dias "
                f"Término Previsto {p} 20/12/2026 Cidade de Exemplo - EX, {data} " + ASSINAM + ENVELOPE)
    return ("Atenciosamente Visto " + ASSINAM + f" Prazo Aditado {p} Prazo Total {p} Término Previsto {p} 20/12/2026 "
            f"300 dias 9.000.000,00 R$ {brl(valor)} R$ {brl(saldo)} R$ Saldo à Medir/Executar {p} "
            f"Valor Total da {numero}ª Medição {p} Valor Total Contratual (Contrato + Aditivos) {p} "
            f"Valor Aditivos - Supressão {p} Instrumento Contratual N.º {p} GOVERNO DO ESTADO DE EXEMPLO {OBRA} "
            f"Dados da Obra: Dados do Contrato: MTPAR - MT PARTICIPAÇÕES E PROJETOS S.A. {contrato} MTPAR 03/02/25 "
            f"Valor Total Acumulado das Medições Anteriores {p} {brl(anteriores)} R$ Valor Contratual (PI) {p} "
            f"Cidade de Exemplo - EX, {data} Valores: 9.000.000,00 R$ - R$" + ENVELOPE)


def linha(numero: int, pi: int, reajuste: int | None = 0, acumulado=90_000_000, marca="ª", palavra="medição",
          inicio="01/07/2026", fim="31/07/2026") -> str:
    """Uma linha do quadro. `reajuste=None`: o quadro sem as colunas de reajuste (cinco valores, e nao sete)."""
    saldo = 900_000_000 - acumulado
    valores = ([pi, acumulado, pi, pi, saldo] if reajuste is None
               else [pi, acumulado, reajuste, reajuste * 3, pi, pi + reajuste, saldo])
    return f"{numero}{marca} {palavra} {inicio} a {fim} 31 120 " + " ".join(f"R$ {brl(v)}" for v in valores)


def controle(linhas: list[str], contrato=CONTRATO, titulo=True) -> str:
    cabeca = (f"CONTRATO TOTAL {contrato} R$ 9.000.000,00 OBRA: TRECHO: OBRA DE EXEMPLO Nº DO DOC. SALDO P. INICIAIS "
              "PROCESSO REFERENCIA PERIODO ACUMULADO PERIODO ACUMULADO R$ 9.000.000,00 ") if titulo else ""
    pe = (" " + ASSINAM + (" GOVERNO DO ESTADO DE EXEMPLO MT PAR - MT PARTICIPAÇÕES E PROJETOS S/A CONTROLE FINANCEIRO "
                           "FIRMA: VALOR CONTRATUAL ADITAMENTO TOTAL GERAL 500 PERÍODO DA MEDIÇÃO PRAZO DIAS CORRIDOS "
                           "MEDIÇÕES P.I MEDIÇÕES REAJUST. TOTAL DA MEDIÇÃO" if titulo else ""))
    return cabeca + " ".join(linhas) + pe + ENVELOPE


def resumo(numero=7, pagina="Página 6 de 20") -> str:
    """A pagina do resumo item a item, com o rodape do arquivo (que ja' veio com o numero de outra medicao)."""
    return (f"A.1 ADMINISTRAÇÃO DA OBRA R$ 100.000,00 R$ 50.000,00 MTPAR - MT PARTICIPAÇÕES E PROJETOS S.A. "
            f"{numero}ª Medição Data da Ordem Serviço: Status da Medição - Provisória RESUMO DE MEDIÇÃO Contratada "
            f"{EMPRESA} Período Simples: 01/07/26 a 31/07/26 MED {numero:02d} - OBRA DE EXEMPLO REV01 {pagina}" + ENVELOPE)


def boletim(numero=7, valor=12_345_679, reajuste: int | None = 1_234_567, colado=True, visto_na=5,
            contrato=CONTRATO, valor_no_quadro: int | None = None, contrato_no_quadro: str | None = None,
            **extra) -> list[str]:
    """As paginas do boletim da medicao, com o Visto na pagina `visto_na` (5: capa, dois de dados gerais, a de
    medicoes, o Visto; 2: logo depois da capa) e o quadro em seguida, com as medicoes anteriores e a desta.
    `contrato_no_quadro`: o numero do contrato que o quadro imprime, quando nao e' o da capa (o ano trocado)."""
    quadro = controle([linha(numero - 2, 5_000_001, 0 if reajuste is not None else None, 60_000_000),
                       linha(numero - 1, 7_000_003, 700_001 if reajuste is not None else None, 77_654_321),
                       linha(numero, valor if valor_no_quadro is None else valor_no_quadro, reajuste)],
                      contrato_no_quadro or contrato)
    o_visto = visto(numero, valor, colado, contrato, **extra)
    if visto_na == 2:
        return [capa(numero, contrato=contrato), o_visto, dados_gerais(numero), dados_gerais(numero), quadro,
                resumo(numero)]
    return [capa(numero, contrato=contrato), dados_gerais(numero), dados_gerais(numero),
            "Descrição Observações: Medições: Prazos: Item Valor %" + ENVELOPE, o_visto, quadro, resumo(numero)]


def sem_capa_reconhecida(paginas: list[str], sem_campo=False) -> list[str]:
    """As mesmas paginas com a capa como outra extracao a devolveria (sem o hifen entre "Medição" e o mes): o leitor
    nao a reconhece. `sem_campo`: os dados gerais tambem sem o campo "N.º da Medição" (so' o rotulo do Visto traz o
    numero)."""
    capa_nova = paginas[0].replace("ª Medição - ", "ª Medição ")
    assert capa_nova != paginas[0]
    resto = [("Dados gerais sem o campo" + ENVELOPE if sem_campo and "N.º da Medição" in p else p) for p in paginas[1:]]
    return [capa_nova, *resto]


def carta_reajuste(numero=7, valor=1_234_567, contrato=CONTRATO) -> str:
    return (f"Cidade de Exemplo-MT, 01/08/2026 Reajustamento da {numero}a Medição Provisória {brl(valor)} R$ "
            f"Atenciosamente, Eng.º Civil: FISCAL DO CONTRATO CREA N.º EX0001/D Fiscal - MTPAR Encaminho para "
            f"conhecimento e providências a planilha de Reajustamento da {numero}a (Sétima) Medição Provisória, "
            f"relativa ao período de 01/07/2026 a 31/07/2026, em conformidade com o Instrumento Contratual "
            f"N° {contrato}/MTPAR." + ENVELOPE)


def planilha_reajuste(numero=7, valor=1_234_567, pi=12_345_679) -> str:
    return (f"OBRA: ENDEREÇO: MUNICÍPIO: OBJETO: CONSTRUÇÃO Índice de exemplo - Mês Base do Orçamento: Io 1.000,000 "
            f"PERIODO ACUMULADO PERIODO ACUMULADO "
            f"{numero}ª medição 01/07/2026 a 31/07/2026 31 120 R$ {brl(pi)} R$ 900.000,00 {brl(valor)} R$ "
            f"3.703.701,00 R$ 1.100,00 0,1000 R$ {brl(valor)} Importa a presente Medição em R$ {brl(valor)} "
            f"PLANILHA DE MEDIÇÃO PROVISÓRIA PARA REAJUSTAMENTO MEDIÇÃO PERÍODO DA MEDIÇÃO Valor do Reajuste (R) 500 "
            f"TOTAL REAJUSTE R$ {brl(valor)} PRAZO DIAS CORRIDOS MEDIÇÕES P.I MEDIÇÕES REAJUSTAMENTO" + ENVELOPE)


def reajuste(numero=7, valor=1_234_567, pi=12_345_679, contrato=CONTRATO, no_quadro: int | None = 0) -> list[str]:
    """As tres paginas do PDF proprio do reajuste. `no_quadro=None`: o quadro sem as colunas de reajuste; 0: o quadro
    traz o mesmo valor do "TOTAL REAJUSTE"; outro numero: o reajuste que o quadro traz no lugar."""
    do_quadro = None if no_quadro is None else (no_quadro or valor)
    return [carta_reajuste(numero, valor, contrato), planilha_reajuste(numero, valor, pi),
            controle([linha(numero - 1, 7_000_003, None if do_quadro is None else 700_001, 77_654_321),
                      linha(numero, pi, do_quadro)], contrato)]


def pdf(paginas: list[str]) -> bytes:
    """PDF com uma pagina por texto, em Helvetica (o texto sai no pypdf na ordem em que foi escrito). Texto vazio:
    pagina sem texto nenhum (o PDF so' de imagem). Data de criacao fixa: as mesmas paginas dao os mesmos bytes (o
    registro so' e' `aceito` com o PDF da leitura, pelo sha256)."""
    f = FPDF(unit="pt", format="A4")
    f.set_creation_date(datetime.datetime(2026, 8, 1, tzinfo=datetime.timezone.utc))
    f.set_auto_page_break(False)
    f.set_font("Helvetica", size=5)
    for texto in paginas:
        f.add_page()
        if texto:
            f.set_xy(20, 20)
            f.multi_cell(w=550, h=7, text=texto)
    return bytes(f.output())
