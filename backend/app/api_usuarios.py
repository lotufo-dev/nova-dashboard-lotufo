import sqlite3
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import auditoria, auth, db, seguranca, tempo
from app.api_auth import conexao
from app.api_medicoes import ID
from app.permissoes import exigir

router = APIRouter(prefix="/api/admin/usuarios")

# espelha o CHECK da tabela usuarios (migracao 001) e as chaves de PERFIS:
# validar aqui devolve 422 em vez de deixar o CHECK estourar como 500.
PERFIS_VALIDOS = ("engenharia", "diretoria", "admin")


class UsuarioIn(BaseModel):
    nome: str
    email: str
    senha: str
    perfil: str


class UsuarioPatch(BaseModel):
    ativo: bool | None = None
    perfil: str | None = None


class SenhaIn(BaseModel):
    senha: str


def _bloqueio_local(valor: str | None) -> str | None:
    """A-05 (10/10/2026): o bloqueio em vigor, na hora de Cuiaba; vencido ou ausente = None (o banco
    so' limpa o carimbo no proximo login certo, e um bloqueio vencido nao tranca mais nada)."""
    if not valor:
        return None
    ate = datetime.fromisoformat(valor)
    return tempo.para_local(ate).isoformat(timespec="seconds") if ate > tempo.agora_utc() else None


@router.get("")
def listar(usuario: dict = Depends(exigir("administrar", com_csrf=False)),
           conn: sqlite3.Connection = Depends(conexao)):
    # colunas explicitas: senha_hash nunca sai daqui.
    return [{**dict(r), "bloqueado_ate": _bloqueio_local(r["bloqueado_ate"])} for r in conn.execute(
        "SELECT id, nome, email, perfil, ativo, criado_em, bloqueado_ate, tentativas_falhas FROM usuarios ORDER BY nome")]


@router.get("/{alvo_id}/acessos")
def acessos(alvo_id: ID, usuario: dict = Depends(exigir("administrar", com_csrf=False)),
            conn: sqlite3.Connection = Depends(conexao)):
    """#418: os ultimos acessos de uma pessoa. So' o admin ve os de outra; cada um ve os proprios em Minha conta."""
    if conn.execute("SELECT 1 FROM usuarios WHERE id=?", (alvo_id,)).fetchone() is None:
        raise HTTPException(404, "Usuário não encontrado")
    return seguranca.acessos(conn, alvo_id)


@router.post("", status_code=201)
def criar(dados: UsuarioIn, usuario: dict = Depends(exigir("administrar")),
          conn: sqlite3.Connection = Depends(conexao)):
    if dados.perfil not in PERFIS_VALIDOS:
        raise HTTPException(422, "Perfil inválido")
    if len(dados.senha) < auth.SENHA_MIN:
        raise HTTPException(422, f"Senha deve ter no mínimo {auth.SENHA_MIN} caracteres")
    try:
        # usuario + registro no mesmo commit; a auditoria vai SEM a senha.
        with db.mutacao(conn):
            uid = auth.criar_usuario(conn, dados.nome, dados.email, dados.senha, dados.perfil)
            auditoria.registrar(conn, usuario["id"], "usuario.criar", "usuario", str(uid),
                                depois={"nome": dados.nome, "email": dados.email,
                                        "perfil": dados.perfil})
    except sqlite3.IntegrityError:
        # UNIQUE(email): e-mail repetido e erro rotineiro do admin, nao 500.
        # db.mutacao ja desfez tudo; o rollback fica como defesa (no-op).
        conn.rollback()
        raise HTTPException(409, "E-mail já cadastrado")
    return {"id": uid}


@router.put("/{alvo_id}")
def atualizar(alvo_id: ID, dados: UsuarioPatch,
              usuario: dict = Depends(exigir("administrar")),
              conn: sqlite3.Connection = Depends(conexao)):
    # validar ANTES de qualquer escrita: o CHECK da tabela estouraria como 500.
    if dados.perfil is not None and dados.perfil not in PERFIS_VALIDOS:
        raise HTTPException(422, "Perfil inválido")
    # Trava (2026-09-28): o admin nao se desativa nem tira o proprio perfil de administrador. Sem ela, um clique
    # trancava o unico administrador fora do sistema (`usuario_atual` exige ativo=1 a cada pedido).
    if alvo_id == usuario["id"] and (dados.ativo is False or (dados.perfil is not None and dados.perfil != "admin")):
        raise HTTPException(409, "Não dá para desativar a própria conta nem tirar o próprio perfil de administrador; "
                                 "peça a outro administrador.")
    if conn.execute("SELECT id FROM usuarios WHERE id=?", (alvo_id,)).fetchone() is None:
        raise HTTPException(404, "Usuário não encontrado")
    novos = {k: v for k, v in dados.model_dump().items() if v is not None}
    with db.mutacao(conn):
        antes = conn.execute("SELECT perfil, ativo FROM usuarios WHERE id=?", (alvo_id,)).fetchone()
        if antes is None:
            # O 404 la' de cima roda ANTES do BEGIN IMMEDIATE: a linha pode sumir nesse
            # meio-tempo (outro admin apagando). Sem esta guarda, `dict(None)` estouraria
            # TypeError dentro do handler -> 500 em vez do mesmo 404 honesto.
            raise HTTPException(404, "Usuário não encontrado")
        # `campo` so pode ser um nome de campo do UsuarioPatch ('ativo'/'perfil'):
        # a f-string nao ve entrada do cliente.
        for campo, valor in novos.items():
            conn.execute(f"UPDATE usuarios SET {campo}=? WHERE id=?",
                         (int(valor) if campo == "ativo" else valor, alvo_id))
        # Issue #28: a trava de cima nao cobre dois admins se desativando ao mesmo tempo (o `exigir` de cada um
        # confere antes do BEGIN IMMEDIATE). Aqui, ja' sob lock: se a mudanca zera os admins ativos, desfaz.
        if conn.execute("SELECT COUNT(*) FROM usuarios WHERE perfil='admin' AND ativo=1").fetchone()[0] == 0:
            raise HTTPException(409, "A mudança deixaria o sistema sem nenhum administrador ativo.")
        auditoria.registrar(conn, usuario["id"], "usuario.atualizar", "usuario", str(alvo_id),
                            antes=dict(antes), depois=novos)
    return {"ok": True}


# A-05/B-10 (10/10/2026): destravar a conta e dar senha nova sem mexer no banco na mao.
@router.post("/{alvo_id}/desbloquear")
def desbloquear(alvo_id: ID, usuario: dict = Depends(exigir("administrar")),
                conn: sqlite3.Connection = Depends(conexao)):
    try:
        auth.desbloquear(conn, usuario["id"], alvo_id)
    except LookupError as e:
        raise HTTPException(404, str(e)) from None
    return {"ok": True}


@router.post("/{alvo_id}/senha")
def redefinir_senha(alvo_id: ID, dados: SenhaIn, usuario: dict = Depends(exigir("administrar")),
                    conn: sqlite3.Connection = Depends(conexao)):
    try:
        auth.redefinir_senha(conn, usuario["id"], alvo_id, dados.senha)
    except LookupError as e:
        raise HTTPException(404, str(e)) from None
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return {"ok": True}
