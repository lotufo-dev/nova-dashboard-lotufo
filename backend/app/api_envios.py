"""Liberacao manual da reserva de envio (revisao do pacote 1, 10/10/2026). Regra em `envio_reserva`; aqui so'
entrada e HTTP. A reserva presa nao expira sozinha: so' sai por aqui, com justificativa, depois de a pessoa
conferir a caixa de Enviados."""
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import envio_reserva
from app.api_auth import conexao
from app.api_medicoes import MAX_INT64
from app.permissoes import exigir

router = APIRouter()


class LiberarIn(BaseModel):
    tabela: Literal["protocolos", "espelhos", "pleitos", "medicao_planilha_envios"]
    id: int = Field(ge=1, le=MAX_INT64)
    justificativa: str = Field(max_length=2000)
    conferi_enviados: bool          # declaracao explicita (gate Sol S5)


@router.post("/api/envios/liberar")
def liberar(dados: LiberarIn, usuario: dict = Depends(exigir("editar_cadastros")),
            conn: sqlite3.Connection = Depends(conexao)):
    try:
        envio_reserva.liberar_manual(conn, usuario["id"], dados.tabela, dados.id, dados.justificativa,
                                     dados.conferi_enviados)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return {"ok": True}
