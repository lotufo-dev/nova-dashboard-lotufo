"""Cliente de LEITURA do TOTVS RM (fase 5), pela API REST + Consultas SQL cadastradas.

Conduto provado no spike da fase 0 (docs/superpowers/research/2026-08-spike-rm.md):

- `GET {url}/api/framework/v1/consultaSQLServer/RealizaConsulta/{codigo}/{coligada}/{sistema}`
  com HTTP Basic. O usuario e' o CODIGO do usuario no RM (ex.: "FULANO DE TAL", com
  espaco); a instalacao da Lotufo cadastra as consultas na aplicacao Fluxus (sistema
  "F"), coligada 0 ("visivel a todas").
- A resposta e' um array JSON em que TODA CHAVE COM VALOR NULL E' OMITIDA (a baixa sem
  data simplesmente nao traz `DATABAIXA`), as datas vem com fuso
  ("2026-08-25T00:00:00-04:00") e os decimais com 4 casas (1128.8755).
- Consulta SQL do RM e' SELECT-only por construcao do cadastro: este cliente nao tem
  como escrever no RM, e nada aqui tenta.

Sem custo de API (spec §15): o RM ja e' pago pela empresa.

Credencial: `DASH_RM_USUARIO` e a senha por `DASH_RM_SENHA_ARQUIVO` (arquivo de uma
linha numa pasta com ACL restrita -- ver runbook) ou `DASH_RM_SENHA` (so' dev). A senha
nunca e' logada nem devolvida em erro. `DASH_RM_SIMULADOR=<pasta>` troca a rede por
arquivos `<CODIGO>.json` no formato exato da API -- e' como os testes e o dev rodam sem
credencial.
"""
import base64
import datetime
import datetime as _dt
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from app import tempo

log = logging.getLogger("app.rm")

# Codigos das consultas cadastradas no RM (SQL no runbook). Configuraveis porque o
# cadastro e' feito a mao no RM.exe e o codigo pode ter que mudar por politica da TI.
CONSULTA_NF = os.environ.get("DASH_RM_CONSULTA_NF", "DASH10")
CONSULTA_BAIXA = os.environ.get("DASH_RM_CONSULTA_BAIXA", "DASH11")
# Issue #488: custo a pagar pelo rateio por centro, tarefa e natureza, e baixa de estoque, por mes.
CONSULTA_CUSTO = os.environ.get("DASH_RM_CONSULTA_CUSTO", "DASH25")
CONSULTA_ESTOQUE = os.environ.get("DASH_RM_CONSULTA_ESTOQUE", "DASH26")

# Faixa plausivel para data vinda do RM. Fora dela (o spike achou uma baixa em
# 2036-06-16) a data vira None e o valor bruto fica guardado ao lado.
ANO_MINIMO = 2000
ANOS_A_FRENTE = 1


class ErroRM(Exception):
    """Falha de rede, autenticacao ou formato ao consultar o RM. Mensagem sem segredo."""


def centavos(valor) -> int:
    """Decimal de 4 casas do RM -> centavos inteiros, arredondamento unico (meio para cima).

    Passa por `Decimal(str(...))`, nunca por float*100: 1128.8755 em float e' 1128.87549...
    e truncaria um centavo. Valor ausente ou ilegivel vira 0 -- e' assim que "sem valor"
    chega do RM (chave omitida).
    """
    if valor is None:
        return 0
    try:
        d = Decimal(str(valor))
    except InvalidOperation as e:
        raise ErroRM(f"Valor monetário ilegível vindo do RM: {valor!r}") from e
    return int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def data(valor, hoje: datetime.date | None = None) -> str | None:
    """'2026-08-25T00:00:00-04:00' -> '2026-08-25'; ausente ou implausivel -> None.

    So' a parte de data interessa: o RM grava 00:00 no fuso local, e converter para UTC
    deslocaria o dia. A faixa plausivel corta typo de digitacao (ano 2036) sem
    esconder o dado -- quem chama guarda o bruto ao lado.
    """
    if not valor:
        return None
    texto = str(valor)[:10]
    try:
        d = datetime.date.fromisoformat(texto)
    except ValueError:
        return None
    hoje = hoje or tempo.hoje_local()
    # Soma de dias, nao `replace(year=...)`: em 29/02 o replace estoura ValueError.
    if d.year < ANO_MINIMO or d > hoje + _dt.timedelta(days=366 * ANOS_A_FRENTE):
        return None
    return d.isoformat()


class ClienteRM:
    def __init__(self, url: str, usuario: str, senha: str, sistema: str = "F",
                 coligada: str = "0", timeout: int = 120, permitir_http: bool = False):
        # Basic sobre HTTP entrega usuario e senha a quem escuta a LAN. O host do RM da
        # Lotufo so' oferece HTTP na porta da API hoje; aceitar isso e' decisao explicita do
        # operador (DASH_RM_HTTP_INSEGURO=1), registrada no runbook -- nunca o padrao.
        if url.lower().startswith("http://") and not permitir_http:
            raise ErroRM("URL do RM em HTTP puro: use https:// ou declare DASH_RM_HTTP_INSEGURO=1 "
                         "(credencial em claro na rede, ver runbook)")
        self.url = url.rstrip("/")
        self.sistema = sistema
        self.coligada = coligada
        self.timeout = timeout
        par = f"{usuario}:{senha}".encode("utf-8")
        self._auth = "Basic " + base64.b64encode(par).decode("ascii")

    def consultar(self, codigo: str, parametros: dict | None = None) -> list[dict]:
        url = (f"{self.url}/api/framework/v1/consultaSQLServer/RealizaConsulta/"
               f"{urllib.parse.quote(codigo)}/{self.coligada}/{self.sistema}")
        if parametros:
            # Convencao da API do RM: `parameters=NOME=VALOR;NOME2=VALOR`.
            q = ";".join(f"{k}={v}" for k, v in parametros.items())
            url += "?" + urllib.parse.urlencode({"parameters": q})
        req = urllib.request.Request(url, headers={"Authorization": self._auth,
                                                   "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                corpo = r.read()
        except urllib.error.HTTPError as e:
            # 401 = usuario/senha do RM (nao o login do Windows); 404 = codigo/coligada/
            # sistema diferentes do cadastro. Sem corpo na mensagem: pode ecoar a URL.
            raise ErroRM(f"RM respondeu HTTP {e.code} à consulta {codigo}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ErroRM(f"RM inacessível ({e.__class__.__name__}) na consulta {codigo}") from None
        return _decodificar(corpo, codigo)


class SimuladorRM:
    """Le `<pasta>/<CODIGO>.json` no lugar da rede. Mesmo formato da API."""

    def __init__(self, pasta: str | Path):
        self.pasta = Path(pasta)

    def consultar(self, codigo: str, parametros: dict | None = None) -> list[dict]:
        arquivo = self.pasta / f"{codigo}.json"
        if not arquivo.exists():
            raise ErroRM(f"Simulador do RM sem o arquivo da consulta {codigo}")
        return _decodificar(arquivo.read_bytes(), codigo)


def _decodificar(corpo: bytes, codigo: str) -> list[dict]:
    try:
        dados = json.loads(corpo.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ErroRM(f"Resposta da consulta {codigo} não é JSON") from e
    # Consulta sem linhas volta como lista vazia; uma linha so' pode vir como objeto.
    if dados is None:
        return []
    if isinstance(dados, dict):
        dados = [dados]
    if not isinstance(dados, list) or not all(isinstance(x, dict) for x in dados):
        raise ErroRM(f"Resposta da consulta {codigo} fora do formato esperado (lista de objetos)")
    return dados


def de_ambiente():
    """Cliente configurado pelo ambiente, ou None quando o RM nao esta' configurado.

    Simulador vence a rede (dev/teste). A senha e' lida do arquivo a cada chamada de
    boot -- nao fica em variavel de ambiente da tarefa, que qualquer processo do mesmo
    usuario le.
    """
    simulador = os.environ.get("DASH_RM_SIMULADOR")
    if simulador:
        return SimuladorRM(simulador)
    url = os.environ.get("DASH_RM_URL")
    usuario = os.environ.get("DASH_RM_USUARIO")
    if not url or not usuario:
        return None
    senha = os.environ.get("DASH_RM_SENHA")
    arquivo = os.environ.get("DASH_RM_SENHA_ARQUIVO")
    if arquivo:
        try:
            senha = Path(arquivo).read_text(encoding="utf-8").strip()
        except OSError as e:
            log.error("nao foi possivel ler a senha do RM em %s (%s)", arquivo, e.__class__.__name__)
            return None
    if not senha:
        log.error("RM configurado (DASH_RM_URL/USUARIO) mas sem senha: defina DASH_RM_SENHA_ARQUIVO")
        return None
    try:
        return ClienteRM(url, usuario, senha, sistema=os.environ.get("DASH_RM_SISTEMA", "F"),
                         permitir_http=os.environ.get("DASH_RM_HTTP_INSEGURO") == "1")
    except ErroRM as e:
        log.error("RM nao configurado: %s", e)
        return None
