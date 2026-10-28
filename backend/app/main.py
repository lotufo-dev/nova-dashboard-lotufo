import logging
import os
import sqlite3
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import backup as backup_mod
from app import correio, db, logs

class FrontendSpa(StaticFiles):
    """Build do React com fallback para o index em caminho de TELA (fase 3,5).

    O frontend passou a ter URL por tela ("/contratos/7/protocolo"). Esses caminhos
    nao existem em `dist/`: sem o fallback, F5 e link colado davam 404 do servidor de
    arquivos. A regra e' estreita de proposito -- so' caminho SEM extensao vira index:
    "/assets/app.js" que nao existe continua 404 (um index.html no lugar de um .js
    quebraria a pagina em silencio), e `/api/*` nunca chega aqui porque os routers
    entram antes do mount (mas fica a guarda, para um /api inexistente continuar 404
    em vez de virar HTML).
    """

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as e:
            # O Starlette entrega o caminho ja normalizado para o SO (barra invertida no
            # Windows) e com ou sem barra inicial conforme a versao: normalizar antes.
            normal = path.replace("\\", "/").lstrip("/")
            ultimo = normal.rsplit("/", 1)[-1]
            if (e.status_code == 404 and "." not in ultimo
                    and normal != "api" and not normal.startswith("api/")):
                return await super().get_response("index.html", scope)
            raise


def _caracteres(n) -> str:
    return f"{n} caractere" if n == 1 else f"{n} caracteres"


# B-12 (10/10/2026): o validador falava ingles na tela ("Input should be less than or equal to 3650"). Os tipos
# mais comuns em portugues; o resto cai em "valor inválido" (nunca o texto cru do pydantic).
_VALIDACAO = {
    "missing": lambda c: "campo obrigatório",
    "less_than_equal": lambda c: f"no máximo {c['le']}",
    "less_than": lambda c: f"menor que {c['lt']}",
    "greater_than_equal": lambda c: f"no mínimo {c['ge']}",
    "greater_than": lambda c: f"maior que {c['gt']}",
    "string_too_long": lambda c: f"no máximo {_caracteres(c['max_length'])}",
    "string_too_short": lambda c: f"no mínimo {_caracteres(c['min_length'])}",
    "literal_error": lambda c: "valor fora das opções",
    "json_invalid": lambda c: "JSON inválido ou incompleto",    # gate Sol S3 (10/10/2026)
}


def _msg_validacao(erro: dict) -> str:
    traduzir = _VALIDACAO.get(erro.get("type"))
    try:
        return traduzir(erro.get("ctx") or {}) if traduzir else "valor inválido"
    except KeyError:
        return "valor inválido"


def create_app() -> FastAPI:
    logs.configurar()  # antes de qualquer coisa que possa logar (migracoes, backup)
    conn = db.get_conn()
    db.migrate(conn)
    conn.close()

    app = FastAPI(title="Dashboard Lotufo")
    # A-04 (10/10/2026): corpo acima do teto da' 413 antes de qualquer rota (ver app/limites.py).
    from app.limites import LimiteDeCorpo
    app.add_middleware(LimiteDeCorpo)
    # #3 (limite de login por origem): cota de tentativas erradas por IP, uma por app
    from app.auth import LimitePorOrigem
    app.state.limite_login = LimitePorOrigem()

    @app.get("/api/health")
    def health():
        """Toca o banco de verdade e expoe a ultima rodada de backup.

        `status` continua "ok" quando o banco responde; a copia externa atrasada ou
        falha de snapshot aparece nos campos, nao derruba o health (quem monitora
        decide o que e' alarme). Banco inacessivel -> 503.
        """
        try:
            c = db.get_conn()
            try:
                c.execute("SELECT 1 FROM schema_migrations LIMIT 1").fetchone()
            finally:
                c.close()
        except sqlite3.Error:
            logging.getLogger("app.health").exception("banco nao respondeu ao health")
            return JSONResponse(status_code=503, content={"status": "erro", "banco": "indisponivel"})
        return {"status": "ok", "banco": "ok", "backup": backup_mod.estado()}

    @app.exception_handler(sqlite3.OperationalError)
    def banco_ocupado(request: Request, exc: sqlite3.OperationalError):
        """Lock de escrita alem do busy_timeout -> 503, nao 500.

        Com a mutacao inteira sob BEGIN IMMEDIATE, dois escritores simultaneos passam
        a se serializar de verdade; o perdedor que espera demais recebia
        `sqlite3.OperationalError: database is locked` crua (500, sem mensagem util).
        503 + Retry-After diz a verdade: nada foi gravado e a operacao pode ser
        repetida. Qualquer OUTRO OperationalError (tabela inexistente, SQL torto) e'
        bug nosso e continua subindo como 500.
        """
        if not db.eh_lock(exc):
            raise exc
        return JSONResponse(status_code=503, headers={"Retry-After": "1"},
                            content={"detail": "Banco de dados ocupado — tente novamente "
                                               "em instantes."})

    @app.exception_handler(RequestValidationError)
    def validacao(request: Request, exc: RequestValidationError):
        """A lista `detail` com `loc` (a tela diz o campo) e `msg` em portugues; sem `input`, que ecoava o corpo."""
        # gate Sol S3 (10/10/2026): no JSON torto o pydantic poe a POSICAO do erro na `loc` ("body", 5); a tela
        # mostraria "5" como nome de campo
        return JSONResponse(status_code=422, content={"detail": [
            {"type": e.get("type"), "loc": ["body"] if e.get("type") == "json_invalid" else list(e.get("loc", ())),
             "msg": _msg_validacao(e)} for e in exc.errors()]})

    @app.exception_handler(correio.EnvioNaoRegistrado)
    def envio_nao_registrado(request: Request, exc: correio.EnvioNaoRegistrado):
        """O e-mail SAIU e o banco nao gravou (A-03, 10/10/2026). Nao e' o 503 acima: "tente novamente"
        mandaria o segundo e-mail ao orgao. A reserva do envio fica, e repetir da' 409 ate' alguem liberar."""
        return JSONResponse(status_code=500, content={
            "detail": "O e-mail SAIU, mas o registro no sistema falhou. NÃO envie de novo: confira a caixa de "
                      f"Enviados do Outlook e avise o administrador. Assunto: {exc.assunto}."})

    @app.exception_handler(correio.EnvioIncerto)
    def envio_incerto(request: Request, exc: correio.EnvioIncerto):
        """A conexao caiu no proprio /send (gate Sol S2): nao se sabe se saiu. A reserva fica; liberar so' depois
        de conferir os Enviados e de passados 15 minutos (envio_reserva.IDADE_MINIMA_LIBERACAO)."""
        return JSONResponse(status_code=500, content={
            "detail": "Não deu para confirmar se o e-mail saiu (a conexão com o Microsoft 365 caiu no envio). NÃO "
                      "envie de novo agora: confira a caixa de Enviados do Outlook; se não saiu, libere o envio "
                      "depois de 15 minutos."})

    from app.api_aditivos import router as aditivos_router
    from app.api_admin import router as admin_router
    from app.api_auth import router as auth_router
    from app.api_certidoes import router as certidoes_router
    from app.api_contratos import router as contratos_router
    from app.api_correio import router as correio_router
    from app.api_cronograma import router as cronograma_router
    from app.api_medicoes import router as medicoes_router
    from app.api_paineis import router as paineis_router
    from app.api_rm import router as rm_router
    from app.api_usuarios import router as usuarios_router
    app.include_router(auth_router)
    from app.api_inicio import router as inicio_router      # antes de medicoes (rota /andamento)
    app.include_router(inicio_router)
    app.include_router(admin_router)
    app.include_router(aditivos_router)
    app.include_router(certidoes_router)
    app.include_router(contratos_router)
    app.include_router(correio_router)
    app.include_router(cronograma_router)
    from app.api_espelhos import router as espelhos_router
    app.include_router(espelhos_router)
    app.include_router(medicoes_router)
    from app.api_notas import router as notas_router
    from app.api_documentos import router as documentos_router
    app.include_router(documentos_router)
    from app.api_protocolos import router as protocolos_router
    app.include_router(protocolos_router)
    from app.api_pleitos import router as pleitos_router
    app.include_router(pleitos_router)
    from app.api_diretoria import router as diretoria_router
    app.include_router(diretoria_router)
    app.include_router(notas_router)
    from app.api_notas_envio import router as notas_envio_router
    app.include_router(notas_envio_router)
    from app.api_envios import router as envios_router
    app.include_router(envios_router)
    app.include_router(paineis_router)
    app.include_router(rm_router)
    from app.api_siga import router as siga_router
    app.include_router(siga_router)
    app.include_router(usuarios_router)

    if os.environ.get("DASH_SEM_JOBS") != "1":
        # as pastas saem de backup.py, as mesmas que Administracao > Saude le (issue #31)
        backup_mod.agendar_backup_horario(db.db_path(), backup_mod.pasta_local(),
                                          backup_mod.pasta_externa())
        # Sincronizacao horaria com o RM (fase 5): so' sobe se o RM estiver configurado.
        # Bloco 9: a observacao do Outlook e do SharePoint (fase 6) saiu; o RM e' a unica fonte automatica.
        from app import sincronizacao_rm
        sincronizacao_rm.agendar()
        # Cobranca de certidoes por e-mail ao Leonardo (plano 2026-10-09): vencidas a cada 2 h, vencendo 1x/dia.
        from app import cobranca_certidoes
        cobranca_certidoes.agendar()

    # O build do React e montado por ultimo: a rota "/" so pega o que sobrou de /api/*.
    # Atencao: um mount em "/" engole qualquer rota registrada DEPOIS de create_app()
    # -- por isso os testes desligam o frontend com DASH_SEM_FRONTEND=1 (eles registram
    # rotas ad-hoc no app pronto) e o resultado nao depende de haver build local ou nao.
    # html=True serve o index em "/"; `FrontendSpa` estende isso aos caminhos de tela
    # do roteador do frontend (deep link, F5), e so' a eles.
    padrao_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    dist = Path(os.environ.get("DASH_DIST_PATH") or padrao_dist)
    if os.environ.get("DASH_SEM_FRONTEND") != "1" and dist.exists():
        app.mount("/", FrontendSpa(directory=dist, html=True), name="frontend")

    return app
