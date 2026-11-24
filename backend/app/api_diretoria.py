"""Numeros da diretoria (bloco 8; spec 2026-09-21 §10.5): o Resumo e o QDOP da lista de Obras, a exportacao do QDOP,
a pagina Fechamento (issue #748), a pagina Em aberto (issue #816) e a pagina Resumo das medicoes (issue #749). So'
leitura; a operacao tambem ve."""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app import a_receber, diretoria, fechamento, qdop, resumo_medicoes, tempo
from app.api_auth import conexao
from app.api_paineis import _csv, _texto_seguro
from app.dinheiro import format_brl
from app.permissoes import exigir

router = APIRouter()
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MES = r"^[0-9]{4}-(0[1-9]|1[0-2])$"


@router.get("/api/diretoria")
def painel(_=Depends(exigir("ver_paineis", com_csrf=False)), conn: sqlite3.Connection = Depends(conexao)):
    return diretoria.painel(conn)


@router.get("/api/fechamento")
def fechamento_mensal(_=Depends(exigir("ver_paineis", com_csrf=False)), conn: sqlite3.Connection = Depends(conexao)):
    """Issue #748: medido, aprovado, protocolado e recebido por mes de competencia de 2025 e 2026, na cota, com o em
    aberto nota a nota (`app/fechamento.py`). Issue #815: e os mesmos numeros de cada contratante no ano
    (`por_contratante`), que somam o total do ano."""
    return fechamento.fechamento(conn)


@router.get("/api/a-receber")
def a_receber_nota_a_nota(_=Depends(exigir("ver_paineis", com_csrf=False)), conn: sqlite3.Connection = Depends(conexao)):
    """Issue #816: o em aberto do Fechamento nota a nota, por contratante e pela data do protocolo, com o tempo parado
    e a data prevista de cada linha (`app/a_receber.py`). Quem ve o Fechamento ve esta pagina; com o total a receber
    nao liberado, so' a trava."""
    return a_receber.a_receber(conn)


# issue #805: o filtro por contratante da pagina; a sigla que a propria resposta lista em `contratantes`
CONTRATANTE = Query(None, min_length=1, max_length=120)


@router.get("/api/resumo-medicoes")
def resumo_das_medicoes(mes: str | None = Query(None, pattern=MES), contratante: str | None = CONTRATANTE,
                        _=Depends(exigir("ver_paineis", com_csrf=False)), conn: sqlite3.Connection = Depends(conexao)):
    """Issues #749 e #805: a etapa do ciclo da medicao de cada obra na competencia `mes` (AAAA-MM; sem ela, a
    competencia em trabalho), o medido do mes com as referencias, as obras sem medicao nela e as medicoes abertas de
    competencias anteriores (`app/resumo_medicoes.py`). `contratante` recorta tudo para as obras dele."""
    return resumo_medicoes.resumo(conn, mes=mes, contratante=contratante)


@router.get("/api/resumo-medicoes/matriz")
def resumo_das_medicoes_matriz(_=Depends(exigir("ver_paineis", com_csrf=False)), conn: sqlite3.Connection = Depends(conexao)):
    """Issue #659: a matriz obra por competencia, com a etapa da medicao de cada mes (`resumo_medicoes.matriz`). Ate'
    19/11/2026 vinha no painel da Inicio; a decisao do dono de 19/11/2026 (#805) a trouxe para o Resumo das medicoes,
    numa aba propria, lida so' quando a aba abre. O mesmo publico das duas paginas (`ver_paineis`)."""
    return resumo_medicoes.matriz(conn)


@router.get("/api/resumo-medicoes.csv")
def resumo_das_medicoes_csv(mes: str | None = Query(None, pattern=MES), contratante: str | None = CONTRATANTE,
                            _=Depends(exigir("ver_paineis", com_csrf=False)), conn: sqlite3.Connection = Depends(conexao)):
    """A relacao que a pagina mostra, na mesma ordem e com o mesmo recorte. Obra, contratante e medicao sao texto do
    cadastro: passam pelo `_texto_seguro` (formula em planilha)."""
    r = resumo_medicoes.resumo(conn, mes=mes, contratante=contratante)
    linhas = [[*(_texto_seguro(v) for v in linha[:4]), *linha[4:]] for linha in resumo_medicoes.linhas_csv(r, format_brl)]
    return _csv(f"resumo-das-medicoes-{r['mes']}.csv", resumo_medicoes.CABECALHO_CSV, linhas)


@router.get("/api/diretoria/qdop.xlsx")
def qdop_xlsx(_=Depends(exigir("ver_paineis", com_csrf=False)), conn: sqlite3.Connection = Depends(conexao)):
    try:
        dados = qdop.gerar_xlsx(conn)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    nome = f"GL.SGI.FRP.DE.250 - QDOP - {tempo.hoje_local().isoformat()}.xlsx"
    return Response(dados, media_type=MIME_XLSX, headers={"Content-Disposition": f'attachment; filename="{nome}"',
                                                          "X-Content-Type-Options": "nosniff"})
