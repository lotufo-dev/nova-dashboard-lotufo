"""Teto de tamanho do corpo de qualquer pedido (A-04, testes de quebra 10/10/2026).

O FastAPI le o corpo inteiro ANTES de resolver as dependencias: um POST de 100 MB sem login era lido todo e
so' depois recebia o 401 (1,4 s contra 4 ms). Este middleware ASGI puro corta antes de qualquer rota:
- com `Content-Length` acima do teto: 413 na hora, sem ler um byte do corpo;
- sem `Content-Length` (chunked): conta os bytes a cada `receive` e, ao passar do teto, para de ler e
  responde 413.
Os tetos de cada rota (10 MB da certidao, 40 MB do pacote) continuam valendo dentro delas; este e' o geral.
"""
import re

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

# A maior rota de upload aceita 40 MB (pdfs.TETO_BYTES_PACOTE); a folga cobre as bordas do multipart.
# Gate Sol S2 (10/10/2026): vale so' para as ROTAS de upload abaixo E com multipart; declarar multipart para
# outra rota nao abre o teto grande (um JSON de 44 MB "multipart" para rota JSON era lido inteiro).
TETO_MULTIPART = 45 * 1024 * 1024
# Todo o resto e' JSON pequeno: o maior legitimo e' o corpo de e-mail (20.000 caracteres) com listas curtas.
TETO_OUTROS = 2 * 1024 * 1024
MENSAGEM = "Pedido acima do tamanho permitido"

# Rotas com UploadFile/Form (grep "UploadFile\|File(" em app/api_*.py, 10/10/2026). Rota nova de upload entra aqui;
# tests/test_limites.py confere que toda rota com formulario esta' na lista.
_ID = r"\d+"
ROTAS_UPLOAD = tuple((metodo, re.compile(padrao)) for metodo, padrao in (
    ("POST", r"/api/correio/assinatura"),                         # imagem da assinatura
    ("POST", r"/api/documentos/certidoes(/ler)?"),                # certidao: gravar e ler o PDF
    ("POST", r"/api/documentos/regularidades"),
    ("POST", rf"/api/(contratos|medicoes)/{_ID}/planilhas"),      # issue #281: planilha/carta (oficio + planilha)
    ("POST", rf"/api/medicoes/{_ID}/(documentos|notas)"),         # evidencia do orgao e nota fiscal
    ("POST", rf"/api/medicoes/{_ID}/envio-planilha/pecas"),       # issue #282: pecas do orgao no e-mail da planilha
    ("POST", r"/api/notas/envio-externo"),                        # .eml do envio feito fora
    ("POST", rf"/api/pleitos/{_ID}/(anexos|assinado)"),
    ("POST", rf"/api/protocolos/{_ID}/(pecas|assinado|numero-orgao)"),
))


def rota_de_upload(metodo: str, caminho: str) -> bool:
    return any(metodo == m and padrao.fullmatch(caminho) for m, padrao in ROTAS_UPLOAD)


class _CorpoGrande(HTTPException):
    """Levantada de dentro do `receive`: o FastAPI repassa HTTPException de middleware sem embrulhar em 400."""
    def __init__(self):
        super().__init__(413, MENSAGEM)


class LimiteDeCorpo:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        cabecalhos = dict(scope["headers"])
        tipo = cabecalhos.get(b"content-type", b"").split(b";")[0].strip().lower()
        upload = tipo == b"multipart/form-data" and rota_de_upload(scope["method"], scope["path"])
        teto = TETO_MULTIPART if upload else TETO_OUTROS
        declarado = cabecalhos.get(b"content-length", b"")
        if declarado.isdigit() and int(declarado) > teto:
            await _recusar(scope, receive, send)
            return

        lidos = 0
        respondeu = False

        async def receive_contado():
            nonlocal lidos
            mensagem = await receive()
            if mensagem["type"] == "http.request":
                lidos += len(mensagem.get("body", b""))
                if lidos > teto:
                    raise _CorpoGrande()
            return mensagem

        async def send_marcado(mensagem):
            nonlocal respondeu
            if mensagem["type"] == "http.response.start":
                respondeu = True
            await send(mensagem)

        try:
            await self.app(scope, receive_contado, send_marcado)
        except _CorpoGrande:
            # Normalmente o FastAPI ja' transformou em 413; aqui so' chega quem leu o corpo fora de uma rota.
            if respondeu:
                raise
            await _recusar(scope, receive, send)


async def _recusar(scope, receive, send):
    await JSONResponse({"detail": MENSAGEM}, status_code=413)(scope, receive, send)
