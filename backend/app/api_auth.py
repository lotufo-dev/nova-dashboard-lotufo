import os
import re
import secrets
import sqlite3
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from app import auditoria, auth, db

router = APIRouter(prefix="/api/auth")

# A-10 (10/10/2026): so' texto com cara de e-mail vai a' auditoria de login falho. Quem cola a
# senha no campo e-mail deixava a senha no log append-only. Gate Sol S3: o dominio precisa ter ponto
# e terminar em letras ("Senha@2026" passava no padrao antigo). Residuo conhecido: uma senha que
# seja ela mesma um e-mail valido ("fulano@exemplo.com") ainda entraria.
_PARECE_EMAIL = re.compile(r"^[^@\s]{1,64}@([^@\s.]+\.)+[a-z]{2,}$")


def _faixa(n: int) -> str:
    """Gate Sol S6: o tamanho exato do texto recusado diria quantos caracteres tem a senha colada ali."""
    return "1-16" if n <= 16 else "17-32" if n <= 32 else ">32"

def conexao():
    conn = db.get_conn()
    try:
        yield conn
    finally:
        conn.close()

def usuario_atual(request: Request, conn: sqlite3.Connection = Depends(conexao)) -> dict:
    token = request.cookies.get("sessao")
    s = auth.sessao_valida(conn, token) if token else None
    if s is None:
        raise HTTPException(401, "Sessão inválida ou expirada")
    u = conn.execute("SELECT id, nome, email, perfil FROM usuarios WHERE id=? AND ativo=1",
                     (s["usuario_id"],)).fetchone()
    if u is None:
        raise HTTPException(401, "Sessão inválida ou expirada")
    return {**dict(u), "csrf_token": s["csrf_token"]}

def exigir_csrf(request: Request, usuario: dict = Depends(usuario_atual)) -> dict:
    # compare_digest: comparacao em tempo constante, sem vazar por timing quantos
    # caracteres do token o atacante acertou. Em bytes porque o header e' controlado
    # pelo cliente e pode trazer nao-ASCII (compare_digest com str exigiria ASCII).
    enviado = (request.headers.get("X-CSRF-Token") or "").encode("utf-8")
    esperado = (usuario["csrf_token"] or "").encode("utf-8")
    if not secrets.compare_digest(enviado, esperado):
        raise HTTPException(403, "CSRF token ausente ou inválido")
    return usuario

class LoginIn(BaseModel):
    # max_length=254 (limite pratico de e-mail, RFC): a tentativa falha grava o
    # e-mail digitado no log de auditoria, que e' append-only. Sem teto, um POST
    # com uma string enorme incha o log a vontade. Nada legitimo passa de 254.
    email: str = Field(max_length=254)
    senha: str

@router.post("/login")
def login(dados: LoginIn, request: Request, response: Response, conn: sqlite3.Connection = Depends(conexao)):
    # #3 (limite de login por origem): a cota do IP e' conferida ANTES de autenticar(); estourada, a tentativa
    # nao chega a contar contra a conta. Origem e' o IP da conexao como o uvicorn a entrega (ele atende direto, sem
    # proxy na frente, com --no-proxy-headers em scripts/rodar_producao.ps1: X-Forwarded-For e' ignorado). Sem auditoria no
    # 429: o abuso ja' deixou LIMITE_ORIGEM eventos de login falho. Cota criada uma vez por app (create_app).
    lim, origem = request.app.state.limite_login, (request.client.host if request.client else "")
    marca = lim.reservar(origem)
    if marca is None:
        raise HTTPException(429, "Muitas tentativas de entrar a partir deste computador. Tente de novo em alguns minutos.",
                            headers={"Retry-After": str(lim.segundos_para_liberar(origem))})
    # So' quem entra devolve a vaga. Erro no meio (banco ocupado ao gravar o contador, /code-review) fica contado:
    # a senha pode ja' ter sido conferida.
    u = auth.autenticar(conn, dados.email, dados.senha)
    if u is not None:
        lim.liberar(origem, marca)
    if u is None:
        # Tentativa recusada tambem vira evento: sem isso, ataque de forca bruta e
        # bloqueio de conta nao deixam rastro nenhum. Grava-se so o e-mail (em
        # minusculas, como no banco) -- NUNCA a senha tentada.
        # auth.autenticar devolve None tanto para senha errada quanto para conta
        # bloqueada/inexistente/inativa, entao aqui ha uma unica acao possivel;
        # separar "auth.lockout" exigiria mudar o contrato de autenticar().
        # registrar() e' a unica escrita deste caminho, mas quem abre e fecha a
        # transacao e' sempre o chamador (db.mutacao).
        email = dados.email.strip().lower()
        depois = ({"email": email} if _PARECE_EMAIL.fullmatch(email)
                  else {"email": None, "motivo": "texto inválido no campo e-mail", "faixa": _faixa(len(dados.email))})
        with db.mutacao(conn):
            auditoria.registrar(conn, None, "auth.login_falha", "usuario", None, depois=depois)
        raise HTTPException(401, "E-mail ou senha inválidos, ou usuário bloqueado")
    # sessao e registro de login no MESMO commit: nao existe sessao valida sem o
    # evento que a explica, nem evento de login sem sessao.
    with db.mutacao(conn):
        token, csrf = auth.criar_sessao(conn, u["id"])
        auditoria.registrar(conn, u["id"], "auth.login")
    # secure=False em dev (proxy HTTP do Vite) e em producao HTTP na rede interna
    # (DASH_SEM_TLS=1, decisao de 2026-09-02: sem certificado a instalar em cada
    # maquina). O navegador rejeita cookie "secure" fora de HTTPS.
    cookie_secure = os.environ.get("DASH_DEV") != "1" and os.environ.get("DASH_SEM_TLS") != "1"
    response.set_cookie("sessao", token, httponly=True, samesite="strict",
                        secure=cookie_secure, max_age=12 * 3600)
    # gate Sol S6 (10/10/2026): o e-mail tambem, como em /eu (a tela da conta mostra com que e-mail se entra)
    return {"nome": u["nome"], "email": u["email"], "perfil": u["perfil"], "csrf": csrf}

@router.post("/logout")
def logout(request: Request, response: Response, conn: sqlite3.Connection = Depends(conexao)):
    token = request.cookies.get("sessao")
    if token:
        # ler a sessao ANTES de encerra-la: e a unica fonte do usuario_id aqui.
        # sessao ausente/expirada -> logout segue ok, mas nao ha o que auditar.
        with db.mutacao(conn):
            s = auth.sessao_valida(conn, token)
            auth.encerrar_sessao(conn, token)
            if s is not None:
                auditoria.registrar(conn, s["usuario_id"], "auth.logout")
    response.delete_cookie("sessao")
    return {"ok": True}

@router.get("/eu")
def eu(usuario: dict = Depends(usuario_atual)):
    # devolve o csrf da sessao: apos F5 o front perde o token (so vive em memoria)
    # e precisa recupera-lo aqui, senao toda mutacao da 403 ate o proximo login.
    return {**{k: usuario[k] for k in ("id", "nome", "email", "perfil")},
            "csrf": usuario["csrf_token"]}


class SenhaIn(BaseModel):
    senha_atual: str
    senha_nova: str

@router.post("/senha")
def trocar_senha(dados: SenhaIn, request: Request, usuario: dict = Depends(exigir_csrf),
                 conn: sqlite3.Connection = Depends(conexao)):
    # A-05/B-10 (10/10/2026): qualquer perfil troca a propria senha; as outras sessoes caem, esta fica.
    try:
        auth.trocar_senha(conn, usuario["id"], dados.senha_atual, dados.senha_nova, request.cookies["sessao"])
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return {"ok": True}
