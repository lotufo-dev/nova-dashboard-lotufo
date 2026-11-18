"""Numeros da diretoria (bloco 8; spec 2026-09-21 §10.5): o Resumo e o QDOP da lista de Obras, a exportacao do QDOP,
a pagina Fechamento (issue #748) e a pagina Resumo das medicoes (issue #749). So' leitura; a operacao tambem ve."""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app import diretoria, fechamento, qdop, resumo_medicoes, tempo
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
    aberto nota a nota (`app/fechamento.py`)."""
    return fechamento.fechamento(conn)


@router.get("/api/resumo-medicoes")
def resumo_das_medicoes(mes: str | None = Query(None, pattern=MES), _=Depends(exigir("ver_paineis", com_csrf=False)),
                        conn: sqlite3.Connection = Depends(conexao)):
    """Issue #749: a etapa do ciclo da medicao de cada obra na competencia `mes` (AAAA-MM; sem ela, a competencia em
    trabalho), as obras sem medicao nela e as medicoes abertas de competencias anteriores (`app/resumo_medicoes.py`)."""
    return resumo_medicoes.resumo(conn, mes=mes)


@router.get("/api/resumo-medicoes.csv")
def resumo_das_medicoes_csv(mes: str | None = Query(None, pattern=MES), _=Depends(exigir("ver_paineis", com_csrf=False)),
                            conn: sqlite3.Connection = Depends(conexao)):
    """A relacao que a pagina mostra, na mesma ordem. Obra, contratante e medicao sao texto do cadastro: passam pelo
    `_texto_seguro` (formula em planilha)."""
    r = resumo_medicoes.resumo(conn, mes=mes)
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
