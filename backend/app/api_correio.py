"""Conta Microsoft de cada usuario: conectar, ver o estado e mandar um e-mail de teste."""
import sqlite3
import threading
import time

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app import correio, graph, instalacao, respostas_orgao
from app.api_auth import conexao
from app.api_medicoes import ID, MAX_INT64
from app.permissoes import exigir

router = APIRouter(prefix="/api/correio")

# Estado do login por codigo de dispositivo, POR USUARIO, em memoria do processo (reiniciar o
# servidor no meio cancela o login; a pessoa pede outro codigo).
_LOGINS: dict[int, dict] = {}
_CODIGO: dict[int, str] = {}       # device_code do login mais recente de cada pessoa (nao vai para a tela)
_LOCK = threading.Lock()
_NENHUM = {"estado": "nenhum", "user_code": None, "verification_uri": None}


def _status(usuario_id: int) -> dict:
    cfg = correio.configuracao()
    with _LOCK:
        login = dict(_LOGINS.get(usuario_id, _NENHUM))
    return {"configurado": bool(cfg["client_id"] and cfg["tokens_dir"]) or bool(cfg["simulador"]),
            "conectado": correio.conectado(usuario_id), "login": login,
            "assinatura": correio.assinatura(usuario_id) is not None}


@router.get("/status")
def status(usuario: dict = Depends(exigir("ver_paineis", com_csrf=False))):
    # B-09 (10/10/2026): a diretoria abre /conta (e-mail e senha); so' ler o estado, as acoes seguem editar_cadastros
    return _status(usuario["id"])


def _gravar(usuario_id: int, device_code: str, estado: dict) -> None:
    """So' o acompanhamento do codigo mais recente da pessoa muda o estado: com dois cliques seguidos em Conectar,
    o primeiro, ao expirar, nao apaga o "conectado" do segundo (14/10/2026)."""
    with _LOCK:
        if _CODIGO.get(usuario_id) == device_code:
            _LOGINS[usuario_id] = estado


def _acompanhar(usuario_id: int, cfg: dict, device_code: str, intervalo: int, expira: float) -> None:
    while time.time() < expira:
        time.sleep(intervalo)
        try:
            r = graph.concluir_device_code(cfg["tenant"], cfg["client_id"], device_code,
                                           correio.arquivo_token(usuario_id))
        except Exception as e:      # qualquer falha vira "erro" na tela; nao deixa o "aguardando" preso para sempre
            msg = str(e) if isinstance(e, graph.ErroGraph) else "Não foi possível concluir a conexão; tente de novo"
            _gravar(usuario_id, device_code, {"estado": "erro", "erro": msg, "user_code": None,
                                              "verification_uri": None})
            return
        if r != "pendente":
            _gravar(usuario_id, device_code, {"estado": r, "user_code": None, "verification_uri": None})
            return
    _gravar(usuario_id, device_code, {"estado": "expirado", "user_code": None, "verification_uri": None})


@router.post("/conectar")
def conectar(usuario: dict = Depends(exigir("editar_cadastros"))):
    cfg = correio.configuracao()
    if not (cfg["client_id"] and cfg["tokens_dir"]):
        raise HTTPException(422, "Microsoft 365 não configurado neste servidor "
                                 "(DASH_GRAPH_CLIENT_ID / DASH_GRAPH_TOKENS_DIR) — ver docs/runbook.md")
    uid = usuario["id"]
    # Ver e reservar sob a mesma trava: dois cliques juntos (ou duas abas) pedem UM codigo a' Microsoft; o segundo
    # recebe o "aguardando" do primeiro. _status pega a mesma trava (nao reentrante): so' depois de solta-la.
    with _LOCK:
        antes = _LOGINS.get(uid)
        aguardando = (antes or {}).get("estado") == "aguardando"
        if not aguardando:
            _LOGINS[uid] = {"estado": "aguardando", "user_code": None, "verification_uri": None}
            _CODIGO.pop(uid, None)
    if aguardando:
        return _status(uid)
    # Da reserva ate' o acompanhamento rodando, qualquer falha (Microsoft, resposta incompleta, thread que nao sobe)
    # desfaz a reserva: o "aguardando" nunca fica preso sem ninguem para conclui-lo ou expira-lo.
    try:
        d = graph.iniciar_device_code(cfg["tenant"], cfg["client_id"], correio.ESCOPOS_LOGIN)
        login = {"estado": "aguardando", "user_code": d["user_code"], "verification_uri": d["verification_uri"]}
        acompanhamento = threading.Thread(target=_acompanhar, daemon=True, args=(
            uid, cfg, d["device_code"], int(d["interval"]), time.time() + int(d["expires_in"])))
        with _LOCK:
            _LOGINS[uid] = login
            _CODIGO[uid] = d["device_code"]
        acompanhamento.start()
    except Exception as e:
        with _LOCK:
            _CODIGO.pop(uid, None)
            if antes is None:
                _LOGINS.pop(uid, None)
            else:
                _LOGINS[uid] = antes
        if isinstance(e, graph.ErroGraph):
            raise HTTPException(502, str(e)) from None
        raise HTTPException(502, "Não foi possível pedir o código à Microsoft; tente de novo") from None
    return _status(uid)


@router.post("/teste")
def teste(usuario: dict = Depends(exigir("editar_cadastros")),
          conn: sqlite3.Connection = Depends(conexao)):
    c_usuario = {"id": usuario["id"], "email": usuario["email"]}
    instalacao.exigir_envio()          # issue #417: a copia recusa antes de falar com o Microsoft 365
    try:
        destino = correio.cliente(usuario["id"], usuario["email"]).remetente()
        eid = correio.enviar_e_registrar(
            conn, c_usuario, "teste", [destino], [], "Dashboard Lotufo — teste de envio",
            "<p>Este e-mail confirma que a Dashboard Lotufo consegue enviar pela sua conta.</p>",
            [("teste.txt", "Anexo de teste da Dashboard Lotufo.\n".encode("utf-8"))])
    except graph.ErroGraph as e:
        raise HTTPException(422, str(e)) from None
    return {"envio_id": eid, "remetente": destino}


@router.post("/respostas/ler")
def ler_respostas(usuario: dict = Depends(exigir("editar_cadastros")),
                  conn: sqlite3.Connection = Depends(conexao)):
    """Issue #644: a tela de quem envia chama ao entrar e a cada 5 minutos. Le so' as conversas dos envios da propria
    pessoa, com a conta Microsoft dela; quem so' consulta (diretoria) nao tem a permissao e nada e' lido para ela.
    Sem conta conectada ou com o Graph fora do ar: lista vazia, sem erro."""
    return {"novas": respostas_orgao.ler(conn, {"id": usuario["id"], "email": usuario["email"]})}


class VistasIn(BaseModel):
    ate: int = Field(ge=1, le=MAX_INT64)       # a ultima resposta que o aviso mostrou (`ate` de `nao-vistas`)


@router.get("/respostas/nao-vistas")
def respostas_nao_vistas(usuario: dict = Depends(exigir("editar_cadastros", com_csrf=False)),
                         conn: sqlite3.Connection = Depends(conexao)):
    """Issue #654: o aviso flutuante de quem enviou. Vem do banco, nao do retorno da leitura: a resposta registrada em
    outra sessao (ou com a pessoa fora) aparece ao entrar. So' os envios da propria pessoa."""
    return respostas_orgao.nao_vistas(conn, usuario["id"])


@router.post("/respostas/vistas/{mid}")
def marcar_respostas_vistas(mid: ID, dados: VistasIn, usuario: dict = Depends(exigir("editar_cadastros")),
                            conn: sqlite3.Connection = Depends(conexao)):
    """Fechar o aviso ou abrir a resposta: as respostas daquela medicao, dos envios da propria pessoa, nao avisam mais."""
    return {"marcadas": respostas_orgao.marcar_vistas(conn, usuario["id"], mid, dados.ate)}


@router.get("/remetente")
def remetente(usuario: dict = Depends(exigir("editar_cadastros", com_csrf=False))):
    """A conta que aparece em "De:" no envio (a conta Microsoft conectada)."""
    try:
        return {"remetente": correio.cliente(usuario["id"], usuario["email"]).remetente(), "erro": None}
    except graph.ErroGraph as e:
        return {"remetente": None, "erro": str(e)}


@router.get("/contatos")
def contatos(q: str = Query(default="", max_length=100), todos: bool = False,
             usuario: dict = Depends(exigir("editar_cadastros", com_csrf=False)),
             conn: sqlite3.Connection = Depends(conexao)):
    return correio.contatos(conn, usuario["id"], q, todos)


@router.get("/assinatura")
def ver_assinatura(usuario: dict = Depends(exigir("editar_cadastros", com_csrf=False))):
    a = correio.assinatura(usuario["id"])
    if a is None:
        raise HTTPException(404, "Sem assinatura cadastrada")
    return Response(a[0], media_type=a[1], headers={"Cache-Control": "no-store"})


@router.post("/assinatura")
def gravar_assinatura(arquivo: UploadFile = File(...), usuario: dict = Depends(exigir("editar_cadastros")),
                      conn: sqlite3.Connection = Depends(conexao)):
    dados = arquivo.file.read(correio.ASSINATURA_MAX + 1)
    try:
        correio.gravar_assinatura(conn, usuario["id"], dados)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return _status(usuario["id"])


@router.delete("/assinatura")
def remover_assinatura(usuario: dict = Depends(exigir("editar_cadastros")),
                       conn: sqlite3.Connection = Depends(conexao)):
    try:
        correio.remover_assinatura(conn, usuario["id"])
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return _status(usuario["id"])

