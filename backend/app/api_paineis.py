"""Rotas dos paineis (spec §6/§7) e export CSV de toda listagem (spec §7).

Todas as rotas aqui sao SO DE LEITURA: exigem `ver_paineis` sem CSRF (o header
so faz sentido em escrita) e nao registram auditoria -- nada muda no banco, logo
tambem nao ha ValueError de repositorio para converter em 422 nem transacao para
desfazer (padrao das rotas de escrita da fase).

CSV com BOM (`utf-8-sig`), separador `;` e quebra CRLF: e' o unico formato que o
Excel pt-BR abre com acentuacao correta e colunas separadas por duplo clique.
"""
import csv
import io
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app import cronograma, medicoes, paineis
from app.api_auth import conexao
from app.api_medicoes import ID
from app.dinheiro import format_brl
from app.permissoes import exigir

router = APIRouter()


def _csv(nome: str, cabecalho: list[str], linhas: list[list[str]]) -> Response:
    # csv.writer (QUOTE_MINIMAL, RFC 4180) em vez de ";".join: objeto de contrato real
    # tem ";" ("Obra X; trecho Y") e um join cru partiria o campo em duas colunas,
    # desalinhando a planilha inteira a partir dali.
    buf = io.StringIO(newline="")
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(cabecalho)
    w.writerows(linhas)
    # utf-8-sig: o BOM faz o Excel pt-BR abrir acentuacao correta com separador ;
    return Response(buf.getvalue().encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nome}"'})


# Caracteres com que o Excel/LibreOffice comeca a interpretar a celula como FORMULA.
_GATILHOS_DE_FORMULA = ("=", "+", "-", "@")


def _texto_seguro(valor) -> str:
    """Neutraliza formula injection em campo TEXTUAL vindo do cadastro.

    csv.writer resolve a ESTRUTURA (aspas e separador), nao a planilha: um objeto
    cadastrado como `=HYPERLINK(...)` volta como formula viva ao abrir o CSV no Excel.
    O prefixo `'` faz o Excel exibir o literal sem calcular nada.

    So para texto livre de cadastro. Valores de `format_brl` e enums do dominio ficam
    de fora de proposito: um "-R$ 1.000,00" prefixado com `'` viraria texto e o usuario
    perderia a coluna para somar na planilha.
    """
    s = "" if valor is None else str(valor)
    return "'" + s if s[:1] in _GATILHOS_DE_FORMULA else s


def _contrato_existe(conn: sqlite3.Connection, contrato_id: int) -> None:
    """404 antes de tocar no repositorio (padrao das rotas da fase)."""
    if conn.execute("SELECT id FROM contratos WHERE id=?", (contrato_id,)).fetchone() is None:
        raise HTTPException(404, "Contrato não encontrado")


@router.get("/api/paineis/alertas")
def alertas(usuario: dict = Depends(exigir("ver_paineis", com_csrf=False)),
            conn: sqlite3.Connection = Depends(conexao)):
    return paineis.alertas(conn)


@router.get("/api/contratos/{contrato_id}/curva")
def curva(contrato_id: ID, usuario: dict = Depends(exigir("ver_paineis", com_csrf=False)),
          conn: sqlite3.Connection = Depends(conexao)):
    _contrato_existe(conn, contrato_id)
    return {"curva": paineis.curva(conn, contrato_id), "saldo": paineis.saldo(conn, contrato_id),
            **cronograma.curva_comparativa(conn, contrato_id)}


@router.get("/api/contratos/{contrato_id}/medicoes.csv")
def medicoes_csv(contrato_id: ID, usuario: dict = Depends(exigir("ver_paineis", com_csrf=False)),
                 conn: sqlite3.Connection = Depends(conexao)):
    _contrato_existe(conn, contrato_id)
    linhas = []
    for m in medicoes.listar(conn, contrato_id):
        linhas.append([str(m["numero"]), m["tipo"], m["competencia"], m["estado"],
                       format_brl(m["valor_protocolado_centavos"]) if m["valor_protocolado_centavos"] is not None else "",
                       format_brl(m["valor_atestado_centavos"]) if m["valor_atestado_centavos"] is not None else "",
                       m["valor_protocolado_origem"] or ""])
    return _csv(f"medicoes-contrato-{contrato_id}.csv",
                ["numero", "tipo", "competencia", "estado", "valor_protocolado",
                 "valor_atestado", "origem_protocolado"], linhas)
