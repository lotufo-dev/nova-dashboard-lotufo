"""Pleitos de reajuste, prazo e conclusao (bloco 7; spec 2026-09-21 §5.2, §7.2 a §7.4). Tudo o que recusa
vem do servico (`pleitos`); aqui so' validacao de entrada e HTTP, no molde de `api_protocolos`."""
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StrictInt

from app import arquivos, envio_reserva, graph, leitura_planilha_reajuste, pdfs, pleitos, prazos, reajuste
from app.api_auth import conexao
from app.api_espelhos import _emails
from app.api_medicoes import ID, MAX_INT64, _contrato_existe
from app.permissoes import exigir

router = APIRouter()
TETO_PLANILHA = 25 * 1024 * 1024


class CriarIn(BaseModel):
    tipo: Literal["reajuste", "prazo", "conclusao"]
    numero_oficio: str = Field(min_length=1, max_length=40)
    data_base_mes: str | None = Field(default=None, pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")  # A-14: \d casa "٢٠٢٤"
    dias: int | None = Field(default=None, gt=0, le=3650)
    justificativa: str | None = Field(default=None, max_length=20000)


class MontarIn(BaseModel):
    corpo: str | None = Field(default=None, max_length=20000)


class EnvioIn(BaseModel):
    para: list[str] = Field(max_length=30)
    copia: list[str] = Field(max_length=30)
    cco: list[str] = Field(default_factory=list, max_length=30)
    assunto: str = Field(min_length=1, max_length=300)
    corpo: str = Field(max_length=20000)
    justificativa: str | None = Field(default=None, max_length=2000)


class DescartarIn(BaseModel):
    motivo: str = Field(min_length=1, max_length=500)


class LinhaPrevisaoIn(BaseModel):
    competencia: str = Field(max_length=7)
    valor_centavos: StrictInt          # 1.5 nao vira 1: dinheiro chega em centavos inteiros ou nao chega


class PrevisaoDigitadaIn(BaseModel):
    # sem campo de origem: a digitada e' sempre 'manual'; a 'pleito' so' nasce da planilha relida no servidor
    linhas: list[LinhaPrevisaoIn] = Field(max_length=pleitos.MAX_COMPETENCIAS)


def _existe(conn, pid: int) -> None:
    if not 1 <= pid <= MAX_INT64 or conn.execute("SELECT 1 FROM pleitos WHERE id=?", (pid,)).fetchone() is None:
        raise HTTPException(404, "Pleito não encontrado")


def _detalhe(conn, pid: int) -> dict:
    d = pleitos.detalhe(conn, pid)
    if d["origem"] == "sistema" and not d["corpo_carta"] and d["situacao"] != "enviado":
        try:
            d["corpo_padrao"] = pleitos.corpo_padrao(conn, pid)
        except ValueError as e:
            d["corpo_padrao"], d["erro_carta"] = None, str(e)
    return d


def _arquivo(rel: str | None, nome: str) -> FileResponse:
    if not rel:
        raise HTTPException(404, "Arquivo não encontrado")
    try:
        caminho = arquivos.caminho_seguro(rel)
    except ValueError:
        raise HTTPException(404, "Arquivo não encontrado") from None
    if not caminho.is_file():
        raise HTTPException(404, "Arquivo não encontrado")
    return FileResponse(caminho, media_type=arquivos.MIME, filename=nome, headers={"X-Content-Type-Options": "nosniff"})


@router.get("/api/contratos/{contrato_id}/reajuste")
def reajuste_da_obra(contrato_id: ID, _=Depends(exigir("ver_paineis", com_csrf=False)),
                     conn: sqlite3.Connection = Depends(conexao)):
    _contrato_existe(conn, contrato_id)
    return {"ciclos": reajuste.ciclos(conn, contrato_id),
            "pleitos": [_detalhe(conn, p["id"]) for p in pleitos.listar(conn, contrato_id, ("reajuste",))],
            "previsoes": reajuste.previsoes_vigentes(conn, contrato_id)}


@router.get("/api/contratos/{contrato_id}/prazos")
def prazos_da_obra(contrato_id: ID, _=Depends(exigir("ver_paineis", com_csrf=False)),
                   conn: sqlite3.Connection = Depends(conexao)):
    _contrato_existe(conn, contrato_id)
    return {"situacao": prazos.situacao(conn, contrato_id), "historico": prazos.historico_texto(conn, contrato_id),
            "pleitos": [_detalhe(conn, p["id"]) for p in pleitos.listar(conn, contrato_id, ("prazo", "conclusao"))]}


@router.post("/api/contratos/{contrato_id}/pleitos", status_code=201)
def criar(contrato_id: ID, dados: CriarIn, usuario: dict = Depends(exigir("editar_cadastros")),
          conn: sqlite3.Connection = Depends(conexao)):
    _contrato_existe(conn, contrato_id)
    try:
        pid = pleitos.criar(conn, usuario["id"], contrato_id, dados.tipo, dados.numero_oficio, dados.data_base_mes,
                            dados.dias, dados.justificativa)
    except pleitos.RascunhoAberto as e:
        raise HTTPException(409, str(e)) from None
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return _detalhe(conn, pid)


@router.get("/api/pleitos/{pid}")
def detalhe(pid: ID, _=Depends(exigir("ver_paineis", com_csrf=False)), conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, pid)
    return _detalhe(conn, pid)


@router.post("/api/pleitos/{pid}/anexos")
def anexo(pid: ID, tipo: Literal[pleitos.TIPOS_ANEXO] = Form(...),
          arquivo: UploadFile = File(...), usuario: dict = Depends(exigir("editar_cadastros")),
          conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, pid)
    nome = (arquivo.filename or "anexo")[-200:]
    if nome.lower().endswith(".xlsx"):
        dados, ext = b"".join(arquivos.blocos_validados(arquivo, teto_bytes=TETO_PLANILHA, tipo="xlsx")), "xlsx"
    else:
        dados, ext = b"".join(arquivos.blocos_validados(arquivo, teto_bytes=pdfs.TETO_BYTES_PACOTE)), "pdf"
    try:
        pleitos.adicionar_anexo(conn, usuario["id"], pid, tipo, nome, dados, ext)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return _detalhe(conn, pid)


@router.post("/api/pleitos/{pid}/previsao/ler")
def ler_previsao(pid: ID, arquivo: UploadFile = File(...), _=Depends(exigir("editar_cadastros")),
                 conn: sqlite3.Connection = Depends(conexao)):
    """Le a planilha de previsao (modelo "Mem. e Cron. - Prev. de Reajuste") para a pessoa conferir. Nao grava:
    o aceite e' `POST /previsao/planilha`, com o `sha256` daqui. Fora do modelo, devolve a mensagem e a tabela
    vazia para digitar."""
    _existe(conn, pid)
    dados = b"".join(arquivos.blocos_validados(arquivo, teto_bytes=TETO_PLANILHA, tipo="xlsx"))
    try:
        return {"reconhecida": True, "linhas": leitura_planilha_reajuste.ler(dados), "sha256": arquivos.sha_de(dados)}
    except leitura_planilha_reajuste.PlanilhaNaoReconhecida as e:
        return {"reconhecida": False, "mensagem": str(e), "motivo": e.motivo, "linhas": []}


def _gravar(conn, pid: int, gravar) -> dict:
    try:
        n = gravar()
    except envio_reserva.EnvioEmAndamento as e:
        raise HTTPException(409, detail=e.detalhe()) from None
    except leitura_planilha_reajuste.PlanilhaNaoReconhecida as e:
        raise HTTPException(422, f"{e} ({e.motivo})") from None
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    # quantas competencias o SERVIDOR gravou: e' o que a confirmacao da tela diz
    return {**_detalhe(conn, pid), "previsao_gravada": n}


@router.post("/api/pleitos/{pid}/previsao/planilha")
def aceitar_previsao_planilha(pid: ID, arquivo: UploadFile = File(...), sha256: str = Form(..., max_length=64),
                              usuario: dict = Depends(exigir("editar_cadastros")),
                              conn: sqlite3.Connection = Depends(conexao)):
    """Aceite da planilha conferida: o servidor rele o arquivo e grava o que leu, com origem 'pleito'. O `sha256`
    e' o que a leitura devolveu: arquivo diferente do conferido e' recusado."""
    _existe(conn, pid)
    dados = b"".join(arquivos.blocos_validados(arquivo, teto_bytes=TETO_PLANILHA, tipo="xlsx"))
    return _gravar(conn, pid, lambda: pleitos.gravar_previsao_planilha(conn, usuario["id"], pid, dados, sha256))


@router.post("/api/pleitos/{pid}/previsao/digitada")
def gravar_previsao_digitada(pid: ID, dados: PrevisaoDigitadaIn, usuario: dict = Depends(exigir("editar_cadastros")),
                             conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, pid)
    linhas = [x.model_dump() for x in dados.linhas]
    return _gravar(conn, pid, lambda: pleitos.gravar_previsao_digitada(conn, usuario["id"], pid, linhas))


@router.post("/api/pleitos/{pid}/anexos/{anexo_id}/remover")
def remover_anexo(pid: ID, anexo_id: ID, usuario: dict = Depends(exigir("editar_cadastros")),
                  conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, pid)
    try:
        pleitos.remover_anexo(conn, usuario["id"], pid, anexo_id)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return _detalhe(conn, pid)


@router.post("/api/pleitos/{pid}/montar")
def montar(pid: ID, dados: MontarIn, usuario: dict = Depends(exigir("editar_cadastros")),
           conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, pid)
    try:
        pleitos.montar(conn, usuario["id"], pid, dados.corpo)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return _detalhe(conn, pid)


@router.get("/api/pleitos/{pid}/documento")
def documento(pid: ID, _=Depends(exigir("ver_paineis", com_csrf=False)), conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, pid)
    d = pleitos.detalhe(conn, pid)
    return _arquivo(d["assinado_arquivo"] or d["montado_arquivo"], d["nome_documento"] or "pleito.pdf")


@router.post("/api/pleitos/{pid}/assinado")
def assinado(pid: ID, arquivo: UploadFile = File(...), usuario: dict = Depends(exigir("editar_cadastros")),
             conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, pid)
    pdf = b"".join(arquivos.blocos_validados(arquivo, teto_bytes=pdfs.TETO_BYTES_PACOTE))
    try:
        pleitos.receber_assinado(conn, usuario["id"], pid, pdf)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return _detalhe(conn, pid)


@router.post("/api/pleitos/{pid}/previa")
def previa(pid: ID, usuario: dict = Depends(exigir("editar_cadastros")), conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, pid)
    try:
        return pleitos.previa_envio(conn, pid, remetente=usuario.get("email"))
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


@router.post("/api/pleitos/{pid}/enviar")
def enviar(pid: ID, dados: EnvioIn, usuario: dict = Depends(exigir("editar_cadastros")),
           conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, pid)
    try:
        eid = pleitos.enviar(conn, {"id": usuario["id"], "email": usuario["email"]}, pid, _emails(dados.para),
                             _emails(dados.copia), dados.assunto.strip(), dados.corpo, dados.justificativa,
                             cco=_emails(dados.cco))
    except envio_reserva.EnvioEmAndamento as e:
        conn.rollback()
        raise HTTPException(409, detail=e.detalhe()) from None
    except (ValueError, graph.ErroGraph) as e:
        conn.rollback()
        raise HTTPException(422, str(e)) from None
    return {"envio_id": eid}


@router.post("/api/pleitos/{pid}/descartar")
def descartar(pid: ID, dados: DescartarIn, usuario: dict = Depends(exigir("editar_cadastros")),
              conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, pid)
    try:
        pleitos.descartar(conn, usuario["id"], pid, dados.motivo)
    except envio_reserva.EnvioEmAndamento as e:
        raise HTTPException(409, detail=e.detalhe()) from None
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return {"ok": True}
