"""Pagina Notas (plano 2026-10-09): notas a enviar, envio pelo Outlook ou registrado por fora, aguardando
pagamento. Regras em `notas_envio` e `protocolo`; aqui so' entrada e HTTP. Certidao vencida -> 409."""
import sqlite3

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from app import envio_reserva, graph, notas_envio, protocolo
from app.api_auth import conexao
from app.api_espelhos import _emails
from app.api_medicoes import ID, MAX_INT64, _contrato_existe
from app.api_protocolos import AnexoVistoIn, Confirmadas, _existe
from app.permissoes import exigir

router = APIRouter()


class IniciarIn(BaseModel):
    contrato_id: int = Field(ge=1, le=MAX_INT64)
    medicao_ids: list[int] = Field(min_length=1, max_length=10)
    numero_oficio: str | None = Field(default=None, max_length=40)     # MTPAR/SES/prefeitura: ofício da carta


class EnviarIn(BaseModel):
    para: list[str] = Field(max_length=30)
    copia: list[str] = Field(max_length=30)
    cco: list[str] = Field(default_factory=list, max_length=30)   # A-17 (10/10/2026): antes caia calado
    assunto: str = Field(min_length=1, max_length=300)
    corpo: str = Field(max_length=20000)
    justificativa: str | None = Field(default=None, max_length=2000)
    # issue #100: os anexos que a pessoa viu na previa; se o servidor montar outros, o envio e' recusado.
    # Obrigatorio (revisor na PR #141): sem a lista nao ha' o que conferir, e o e-mail nao sai sem conferencia
    anexos: list[AnexoVistoIn] = Field(max_length=200)
    # issue #213: o que falta, como a pessoa viu e confirmou no aviso "ATENÇÃO"
    confirmadas: Confirmadas = None


class NumeroIn(BaseModel):
    numero: str = Field(max_length=100)


def _medicao_existe(conn, mid: int) -> None:
    if not 1 <= mid <= MAX_INT64 or conn.execute("SELECT 1 FROM medicoes WHERE id=?", (mid,)).fetchone() is None:
        raise HTTPException(404, "Medição não encontrada")


@router.get("/api/notas/a-enviar")
def a_enviar(_=Depends(exigir("ver_paineis", com_csrf=False)), conn: sqlite3.Connection = Depends(conexao)):
    return notas_envio.a_enviar(conn)


@router.post("/api/notas/envio/iniciar")
def iniciar(dados: IniciarIn, usuario: dict = Depends(exigir("editar_cadastros")),
            conn: sqlite3.Connection = Depends(conexao)):
    _contrato_existe(conn, dados.contrato_id)
    try:
        pid = notas_envio.iniciar(conn, usuario["id"], dados.contrato_id, dados.medicao_ids, dados.numero_oficio)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return {"protocolo_id": pid}


@router.get("/api/notas/envio/{pid}")
def detalhe(pid: ID, usuario: dict = Depends(exigir("ver_paineis", com_csrf=False)),
            conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, pid)
    try:
        return notas_envio.detalhe_envio(conn, pid, remetente=usuario.get("email"))
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


@router.post("/api/notas/envio/{pid}/enviar")
def enviar(pid: ID, dados: EnviarIn, usuario: dict = Depends(exigir("editar_cadastros")),
           conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, pid)
    try:
        eid = notas_envio.enviar(conn, {"id": usuario["id"], "email": usuario["email"]}, pid, _emails(dados.para),
                                 _emails(dados.copia), dados.assunto.strip(), dados.corpo, dados.justificativa,
                                 cco=_emails(dados.cco),
                                 anexos_previa=[a.model_dump() for a in dados.anexos], confirmadas=dados.confirmadas)
    except envio_reserva.EnvioEmAndamento as e:
        conn.rollback()
        raise HTTPException(409, detail=e.detalhe()) from None
    except protocolo.ConfirmarPendencias as e:
        conn.rollback()
        raise HTTPException(422, detail=e.detalhe()) from None
    except protocolo.AnexosMudaram as e:
        conn.rollback()
        raise HTTPException(422, detail={"codigo": e.codigo, "mensagem": str(e)}) from None
    except protocolo.Bloqueio as e:
        conn.rollback()
        raise HTTPException(409, str(e)) from None
    except (ValueError, graph.ErroGraph) as e:
        conn.rollback()
        raise HTTPException(422, str(e)) from None
    return {"envio_id": eid}


@router.post("/api/notas/envio-externo")
def envio_externo(medicao_ids: list[int] = Form(...), enviado_em: str = Form(..., max_length=10),
                  observacao: str = Form(..., max_length=2000), eml: UploadFile | None = File(None),
                  irma_ids: list[int] = Form(default=[]),       # issue #172: a irma marcada no formulario
                  # issue #230: o que falta, como a pessoa viu e confirmou no aviso "ATENÇÃO" (um campo por item)
                  confirmadas: list[str] = Form(default=[]),
                  # issue #231: o oficio digitado, com o mesmo teto do `IniciarIn.numero_oficio`
                  numero_oficio: str | None = Form(default=None, max_length=40),
                  usuario: dict = Depends(exigir("editar_cadastros")), conn: sqlite3.Connection = Depends(conexao)):
    try:            # os mesmos limites do `Confirmadas` das rotas JSON (api_protocolos)
        TypeAdapter(Confirmadas).validate_python(confirmadas)
    except ValidationError:
        raise HTTPException(422, "Lista do que falta grande demais: abra o registro de novo") from None
    for mid in [*medicao_ids, *irma_ids]:
        _medicao_existe(conn, mid)
    arquivo = None
    if eml is not None and eml.filename:
        dados = eml.file.read(notas_envio.TETO_EML + 1)
        arquivo = (eml.filename, dados)
    try:
        notas_envio.envio_externo(conn, usuario["id"], medicao_ids, enviado_em, observacao, arquivo, irma_ids,
                                  confirmadas or None, numero_oficio)
    except protocolo.ConfirmarPendencias as e:
        raise HTTPException(422, detail=e.detalhe()) from None
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return {"ok": True}


@router.get("/api/notas/aguardando-pagamento")
def aguardando(_=Depends(exigir("ver_paineis", com_csrf=False)), conn: sqlite3.Connection = Depends(conexao)):
    return notas_envio.aguardando_pagamento(conn)


@router.post("/api/notas/{medicao_id}/numero-orgao")
def numero_orgao(medicao_id: ID, dados: NumeroIn, usuario: dict = Depends(exigir("editar_cadastros")),
                 conn: sqlite3.Connection = Depends(conexao)):
    _medicao_existe(conn, medicao_id)
    try:
        notas_envio.registrar_numero_orgao(conn, usuario["id"], medicao_id, dados.numero)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return {"ok": True}
