"""Microsoft Graph: so' o que o e-mail usa (bloco 9; spec 2026-09-21 §5.1).

A leitura do Outlook e do SharePoint (fase 6) saiu no corte: o sistema nao le caixa nem biblioteca; de e-mail, le
so' a conversa que ele mesmo enviou (issue #644, em `correio.py`). Fica o login delegado por codigo de dispositivo
de cada pessoa (Minha conta), o token com renovacao e a guarda que nunca segue redirecionamento com o bearer. O
envio em si mora em `correio.py`.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"
TIMEOUT = 60


class ErroGraph(Exception):
    """Falha de rede, token ou formato. Mensagem sem segredo.

    `status`: o HTTP que o servidor respondeu, ou None quando nao houve resposta (timeout, conexao caida). No
    envio de e-mail isso decide se o /send foi recusado com certeza (4xx) ou pode ter saido (gate Sol, 10/10/2026).
    """

    def __init__(self, mensagem: str = "", status: int | None = None):
        super().__init__(mensagem)
        self.status = status


class _SemRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_SEM_REDIRECT = urllib.request.build_opener(_SemRedirect)


# --- token delegado ------------------------------------------------------------------

def _post_form(url: str, campos: dict, timeout: int = TIMEOUT) -> dict:
    dados = urllib.parse.urlencode(campos).encode("ascii")
    req = urllib.request.Request(url, data=dados, headers={
        "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # O endpoint de token responde 400 com JSON {error, error_description}: o
        # `error` e' o codigo que o fluxo de dispositivo usa (authorization_pending...).
        try:
            corpo = json.loads(e.read().decode("utf-8"))
        except Exception:
            corpo = {}
        if isinstance(corpo, dict) and corpo.get("error"):
            return corpo
        raise ErroGraph(f"Login Microsoft respondeu HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ErroGraph(f"Login Microsoft inacessível ({e.__class__.__name__})") from None


def iniciar_device_code(tenant: str, client_id: str, escopos: str) -> dict:
    """Passo 1 do login: devolve o codigo que a pessoa digita em microsoft.com/devicelogin."""
    r = _post_form(f"{LOGIN}/{tenant}/oauth2/v2.0/devicecode",
                   {"client_id": client_id, "scope": escopos})
    if "device_code" not in r:
        raise ErroGraph(f"Login Microsoft recusou o pedido: {r.get('error', 'resposta inesperada')}")
    return {"device_code": r["device_code"], "user_code": r["user_code"],
            "verification_uri": r["verification_uri"], "expires_in": int(r.get("expires_in", 900)),
            "interval": int(r.get("interval", 5)), "message": r.get("message", "")}


def concluir_device_code(tenant: str, client_id: str, device_code: str, arquivo: Path) -> str:
    """Passo 2 (uma tentativa): 'pendente' | 'ok' | 'expirado' | 'recusado'.

    Em 'ok' o refresh token vai para `arquivo` (a pasta e' a de segredos, ja' com ACL).
    """
    r = _post_form(f"{LOGIN}/{tenant}/oauth2/v2.0/token", {
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        "client_id": client_id, "device_code": device_code})
    erro = r.get("error")
    if erro in ("authorization_pending", "slow_down"):
        return "pendente"
    if erro == "expired_token":
        return "expirado"
    if erro:
        return "recusado"
    if "refresh_token" not in r:
        raise ErroGraph("Login concluído sem refresh token: o aplicativo precisa do escopo offline_access")
    gravar_token(arquivo, r["refresh_token"])
    return "ok"


def gravar_token(arquivo: Path, refresh_token: str) -> None:
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    tmp = arquivo.with_suffix(arquivo.suffix + ".tmp")
    tmp.write_text(refresh_token.strip() + "\n", encoding="utf-8")
    os.replace(tmp, arquivo)


class Token:
    """Token de acesso a partir do refresh token em arquivo; renova quando vence."""

    def __init__(self, tenant: str, client_id: str, arquivo: Path, escopos: str):
        self.tenant, self.client_id, self.arquivo, self.escopos = tenant, client_id, arquivo, escopos
        self._acesso: str | None = None
        self._vence_em = 0.0

    def acesso(self) -> str:
        if self._acesso and time.time() < self._vence_em - 60:
            return self._acesso
        try:
            refresh = self.arquivo.read_text(encoding="utf-8").strip()
        except OSError:
            raise ErroGraph("Sua conta Microsoft não está conectada: conecte em Minha conta") from None
        if not refresh:
            raise ErroGraph("Arquivo do token Microsoft vazio: refaça o login")
        r = _post_form(f"{LOGIN}/{self.tenant}/oauth2/v2.0/token", {
            "grant_type": "refresh_token", "client_id": self.client_id,
            "refresh_token": refresh, "scope": self.escopos})
        if "access_token" not in r:
            # invalid_grant = refresh token revogado/expirado (90 dias sem uso, troca de
            # senha com revogacao...). A saida e' refazer o login; nada aqui e' segredo.
            raise ErroGraph(f"Token Microsoft recusado ({r.get('error', 'sem access_token')}): "
                            "conecte de novo em Minha conta")
        self._acesso = r["access_token"]
        self._vence_em = time.time() + int(r.get("expires_in", 3600))
        if r.get("refresh_token"):
            gravar_token(self.arquivo, r["refresh_token"])
        return self._acesso
