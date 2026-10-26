"""Rotas do cronograma versionado (fase 2): ler a versao vigente e criar uma nova.

Nao existe rota de EDITAR/APAGAR versao de proposito: revisar o cronograma e' sempre
criar a proxima versao (spec §5). O "passado congelado" e' derivado das versoes
guardadas -- apagar uma reescreveria meses ja decorridos.

Toda escrita desta fase grava origem "manual"; a deteccao automatica ("detectado"/
"aceito") entra nas fases 5-6.
"""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import cronograma
from app.api_auth import conexao
from app.api_medicoes import ID
from app.dinheiro import parse_brl
from app.permissoes import exigir

router = APIRouter(prefix="/api/contratos/{contrato_id}/cronograma")

# Mesmo formato "AAAA-MM" que o CHECK (GLOB) de cronograma_itens exige.
# [0-9] em vez de \d de proposito: o \d do Python casa DIGITO UNICODE (arabe-indico,
# devanagari...). "٢٠٢٦-09" passaria por aqui e so morreria no GLOB '[0-9]...' do
# SQLite, como IntegrityError dentro do handler -> 500. Mesma nota de api_medicoes.py.
COMPETENCIA = r"^[0-9]{4}-(0[1-9]|1[0-2])$"

# Maior inteiro que o SQLite grava numa coluna INTEGER (int64). Acima disso o driver
# levanta OverflowError DENTRO do handler -> 500. Mesmo teto de api_contratos.py.
MAX_INT64 = 9223372036854775807

# Teto de itens por versao: 600 competencias mensais = 50 anos, folga larga sobre
# qualquer contrato real. Sem o teto, um POST com milhoes de itens vira um
# executemany gigante (e uma linha de auditoria) antes de qualquer validacao util.
MAX_ITENS = 600


class ItemIn(BaseModel):
    competencia: str = Field(pattern=COMPETENCIA)
    # max_length: parse_brl aceita qualquer quantidade de digitos (int do Python nao
    # estoura), entao um texto de megabytes seria convertido antes do teto de int64.
    # 40 caracteres cobrem qualquer contrato real com folga.
    valor: str = Field(max_length=40)  # BRL "100.000,00"


class VersaoIn(BaseModel):
    itens: list[ItemIn] = Field(min_length=1, max_length=MAX_ITENS)


def _contrato_existe(conn: sqlite3.Connection, contrato_id: int) -> None:
    """404 antes de tocar no repositorio (padrao das rotas da fase)."""
    if conn.execute("SELECT id FROM contratos WHERE id=?", (contrato_id,)).fetchone() is None:
        raise HTTPException(404, "Contrato não encontrado")


def _erro_do_cliente(conn: sqlite3.Connection, e: ValueError) -> HTTPException:
    """ValueError do repositorio -> 422, com a transacao desfeita.

    Desde a fase 3 quem desfaz e' o proprio `db.mutacao` do repositorio, e este
    rollback e' no-op. Fica como defesa: garante que a conexao nunca volte ao pool
    de dependencias com transacao aberta, segurando o lock de escrita ate o fim da
    requisicao. Mesmo padrao de api_medicoes.py.
    """
    conn.rollback()
    return HTTPException(422, str(e))


@router.get("")
def obter(contrato_id: ID, usuario: dict = Depends(exigir("ver_paineis", com_csrf=False)),
          conn: sqlite3.Connection = Depends(conexao)):
    _contrato_existe(conn, contrato_id)
    return cronograma.vigente(conn, contrato_id)


@router.get("/versoes")
def listar_versoes(contrato_id: ID, usuario: dict = Depends(exigir("ver_paineis", com_csrf=False)),
                   conn: sqlite3.Connection = Depends(conexao)):
    """Issue #256: uma linha por versao, na ordem da linha do tempo, com a data do documento quando veio do cadastro."""
    _contrato_existe(conn, contrato_id)
    return cronograma.versoes(conn, contrato_id)


@router.post("", status_code=201)
def nova_versao(contrato_id: ID, dados: VersaoIn,
                usuario: dict = Depends(exigir("editar_cadastros")),
                conn: sqlite3.Connection = Depends(conexao)):
    _contrato_existe(conn, contrato_id)
    try:
        itens = []
        for i in dados.itens:
            centavos = parse_brl(i.valor)
            if centavos > MAX_INT64:
                raise ValueError(f"Valor monetário fora do limite ({i.competencia})")
            itens.append((i.competencia, centavos))
        versao = cronograma.nova_versao(conn, usuario["id"], contrato_id, itens, "manual")
    except ValueError as e:  # BRL invalido, acima do int64, competencia duplicada, corrida
        raise _erro_do_cliente(conn, e)
    return {"versao": versao}
