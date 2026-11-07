"""Envio de e-mail pelo Microsoft Graph, pela conta de QUEM ENVIA (spec 2026-09-21 §5.1).

Cada pessoa conecta a propria conta uma vez (codigo de dispositivo). O refresh token fica num
arquivo por usuario na pasta de segredos (`DASH_GRAPH_TOKENS_DIR`), fora do repositorio e do
banco. O sistema NAO le caixa de e-mail: `Mail.ReadWrite` e' o que o Graph exige para criar o
rascunho e subir anexo acima de 3 MB; nenhuma funcao deste modulo lista ou le mensagem.
"""
import base64
import datetime
import hashlib
import html
import json
import logging
import os
import re
import secrets
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from contextlib import contextmanager
from pathlib import Path

from app import arquivos, auditoria, db, graph, instalacao

log = logging.getLogger("app.correio")

ESCOPOS = "offline_access User.Read Mail.Send Mail.ReadWrite"
# Sugestao de destinatarios como no Outlook (2026-09-25): pessoas com quem a conta fala e o diretorio da
# empresa. Nenhuma das duas exige consentimento de administrador. O ENVIO continua pedindo so' ESCOPOS: quem
# conectou antes delas envia normalmente e fica com as sugestoes do cadastro ate conectar de novo.
ESCOPOS_DIRETORIO = "People.Read User.ReadBasic.All"
ESCOPOS_LOGIN = f"{ESCOPOS} {ESCOPOS_DIRETORIO}"
# Assinatura de quem envia: imagem que a pessoa sobe em Minha conta (o Graph nao le a assinatura do Outlook).
ASSINATURA_MAX = 1024 * 1024
ASSINATURA_CID = "assinatura-remetente"
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
LIMITE_SIMPLES = 3 * 1024 * 1024       # acima disto o Graph exige sessao de upload
BLOCO = 3_276_800                      # multiplo de 320 KiB, como o Graph pede
# O Exchange Online recusa mensagem acima de ~35 MB JA' CODIFICADA; o Base64 incha o anexo
# em ~33%, entao o teto sobre os bytes crus e' 25 MB.
MAX_TOTAL = 25 * 1024 * 1024
_UPLOAD_HOSTS = ("https://outlook.office.com/", "https://outlook.office365.com/")


def configuracao() -> dict:
    return {"tenant": os.environ.get("DASH_GRAPH_TENANT") or "organizations",
            "client_id": os.environ.get("DASH_GRAPH_CLIENT_ID"),
            "tokens_dir": os.environ.get("DASH_GRAPH_TOKENS_DIR"),
            "simulador": os.environ.get("DASH_GRAPH_SIMULADOR")}


def arquivo_token(usuario_id: int) -> Path:
    pasta = configuracao()["tokens_dir"]
    if not pasta:
        raise RuntimeError("DASH_GRAPH_TOKENS_DIR não definida: sem pasta para as contas Microsoft")
    return Path(pasta) / f"usuario-{int(usuario_id)}.txt"


def conectado(usuario_id: int) -> bool:
    try:
        return bool(arquivo_token(usuario_id).read_text(encoding="utf-8").strip())
    except (OSError, RuntimeError):
        return False


ARQUIVO_REDIRECIONAR = "email-redirecionar.txt"


class RedirecionamentoInvalido(graph.ErroGraph):
    """O redirecionamento de teste esta' ligado e o endereco nao se le: nada sai, para o e-mail nao ir ao destinatario
    de verdade por engano."""


def _fonte_do_redirecionamento() -> str | None:
    """O texto cru do redirecionamento: a variavel `DASH_EMAIL_REDIRECIONAR` ou a primeira linha de
    `<raiz>/segredos/email-redirecionar.txt` (a raiz e' a pasta acima de `dados`, como na instalacao). None = desligado."""
    bruto = os.environ.get("DASH_EMAIL_REDIRECIONAR")
    if bruto is not None and bruto.strip():
        return bruto.strip()
    try:
        arquivo = db.db_path().parent.parent / "segredos" / ARQUIVO_REDIRECIONAR
        if not arquivo.is_file():
            return None
        linhas = arquivo.read_text(encoding="utf-8-sig").strip().splitlines()
    except (OSError, UnicodeDecodeError, RuntimeError):
        return ""          # o arquivo existe e nao se le: ligado e invalido
    return linhas[0].strip() if linhas else ""


def redirecionamento_ativo() -> bool:
    """Ha' redirecionamento de teste configurado (valido ou nao)? E' o que a faixa da tela mostra."""
    return _fonte_do_redirecionamento() is not None


def redirecionamento() -> str | None:
    """Teste em producao (pedido do dono, 06/11/2026): com o redirecionamento ligado, TODO e-mail do sistema vai so'
    para este endereco, com "[TESTE]" no assunto e os destinatarios de verdade escritos no alto do corpo. Lido a cada
    envio: apagar o arquivo desliga, sem reiniciar. Ligado com endereco que nao se le, o envio e' recusado."""
    fonte = _fonte_do_redirecionamento()
    if fonte is None:
        return None
    if not _EMAIL.fullmatch(fonte):
        raise RedirecionamentoInvalido("Redirecionamento de e-mail de teste mal configurado: nada foi enviado")
    return fonte


def registrar_envio(conn, usuario_id: int, tipo: str, remetente: str, para: list[str],
                    copia: list[str], assunto: str, mensagem_id: str | None,
                    anexos: list[tuple[str, bytes]], cco: list[str] | None = None,
                    redirecionado_para: str | None = None) -> int:
    cco = list(cco or [])
    with db.mutacao(conn):
        cur = conn.execute(
            "INSERT INTO envios (tipo, usuario_id, remetente, para, copia, cco, assunto, mensagem_id) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (tipo, usuario_id, remetente, json.dumps(para), json.dumps(copia), json.dumps(cco) if cco else None,
             assunto, mensagem_id))
        eid = cur.lastrowid
        resumo = []
        for nome, dados in anexos:
            h = hashlib.sha256(dados).hexdigest()
            conn.execute("INSERT INTO envio_anexos (envio_id, nome, tamanho, sha256) VALUES (?,?,?,?)",
                         (eid, nome, len(dados), h))
            resumo.append({"nome": nome, "tamanho": len(dados), "sha256": h})
        auditoria.registrar(conn, usuario_id, "correio.envio", "envio", eid, None,
                            {"tipo": tipo, "remetente": remetente, "para": para, "copia": copia, "cco": cco,
                             "assunto": assunto, "mensagem_id": mensagem_id, "anexos": resumo,
                             # teste em producao: o e-mail NAO foi aos destinatarios acima, foi so' para este endereco
                             **({"redirecionado_para": redirecionado_para} if redirecionado_para else {})})
    return eid


class EnvioNaoRegistrado(RuntimeError):
    """O e-mail SAIU e o registro no banco falhou (testes de quebra de 10/10/2026, A-03). Quem repete manda outro
    e-mail ao orgao: main.py responde 500 dizendo isso, e nao o 503 "tente novamente" do banco ocupado."""

    def __init__(self, mensagem_id: str | None, assunto: str, para: list[str], envio_id: int | None = None):
        super().__init__(f"e-mail enviado e nao registrado: {assunto}")
        self.mensagem_id, self.assunto, self.para, self.envio_id = mensagem_id, assunto, para, envio_id


class EnvioIncerto(EnvioNaoRegistrado):
    """A conexao caiu no proprio /send (gate Sol S2, 10/10/2026): o Graph pode ter aceitado e a resposta se perdido.
    Como o EnvioNaoRegistrado, segura a reserva; main.py responde 500 mandando conferir os Enviados."""


@contextmanager
def depois_do_envio(assunto: str, para: list[str], envio_id: int):
    """Envolve a marcacao feita DEPOIS do e-mail (protocolo/espelho/pleito `enviado`): QUALQUER falha ali (lock,
    IntegrityError, auditoria, bug) vira EnvioNaoRegistrado -- o e-mail ja' saiu (gate Sol S3, 10/10/2026). A
    reserva do envio fica, de proposito, para segurar a repeticao."""
    try:
        yield
    except Exception as e:
        log.critical("E-mail ENVIADO (envio %s) e nao marcado (%r): %s para %s", envio_id, e, assunto, para)
        raise EnvioNaoRegistrado(None, assunto, para, envio_id) from e


def contas_do_usuario(conn, email_login: str) -> set[str]:
    """Contas do Outlook de onde a pessoa ja' enviou (o login pode ser outro: alguem entra como
    fulano@exemplo.com.br e envia como fulano.tal@exemplo.com.br)."""
    return {r[0].lower() for r in conn.execute(
        "SELECT DISTINCT e.remetente FROM envios e JOIN usuarios u ON u.id=e.usuario_id WHERE lower(u.email)=?",
        ((email_login or "").lower(),)) if r[0]}


def _http(metodo: str, url: str, corpo: bytes | None = None, headers: dict | None = None,
          bearer: str | None = None) -> dict:
    """Uma requisicao. O bearer so' vai ao host do Graph; a URL de upload ja' e' autenticada."""
    if bearer is not None and not url.startswith(graph.GRAPH + "/"):
        raise graph.ErroGraph("URL fora do Microsoft Graph recusada")
    if bearer is None and not url.startswith(_UPLOAD_HOSTS):
        raise graph.ErroGraph("URL de upload fora do Outlook recusada")
    h = {"Accept": "application/json", **(headers or {})}
    if bearer is not None:
        h["Authorization"] = "Bearer " + bearer
    req = urllib.request.Request(url, data=corpo, headers=h, method=metodo)
    try:
        # Sem seguir redirect: o urllib repetiria o Authorization no destino do 3xx.
        with graph._SEM_REDIRECT.open(req, timeout=graph.TIMEOUT) as r:
            bruto = r.read()
    except urllib.error.HTTPError as e:
        raise graph.ErroGraph(f"Graph respondeu HTTP {e.code} ao enviar o e-mail", status=e.code) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise graph.ErroGraph(f"Graph inacessível ({e.__class__.__name__})") from None
    return json.loads(bruto.decode("utf-8")) if bruto.strip() else {}


def _enderecos(lista: list[str]) -> list[dict]:
    return [{"emailAddress": {"address": e}} for e in lista]


def _conferir_tamanho(anexos: list[tuple[str, bytes]]) -> None:
    total = sum(len(d) for _, d in anexos)
    if total > MAX_TOTAL:
        raise graph.ErroGraph(f"Anexos somam {total // 1024 // 1024} MB; o limite do e-mail é "
                              f"{MAX_TOTAL // 1024 // 1024} MB. Divida o envio.")


class ClienteCorreio:
    def __init__(self, token: graph.Token):
        self.token = token

    def _json(self, metodo: str, caminho: str, corpo: dict | None = None, headers: dict | None = None) -> dict:
        dados = None if corpo is None else json.dumps(corpo).encode("utf-8")
        return _http(metodo, graph.GRAPH + caminho, dados, {"Content-Type": "application/json", **(headers or {})},
                     bearer=self.token.acesso())

    def remetente(self) -> str:
        eu = self._json("GET", "/me")
        return (eu.get("mail") or eu.get("userPrincipalName") or "").lower()

    def enviar(self, para, copia, assunto, corpo_html, anexos, cco=(), inline=()) -> str | None:
        _conferir_tamanho([*anexos, *((n, d) for n, d, _ in inline)])
        rascunho = self._json("POST", "/me/messages", {
            "subject": assunto, "body": {"contentType": "HTML", "content": corpo_html},
            "toRecipients": _enderecos(para), "ccRecipients": _enderecos(copia), "bccRecipients": _enderecos(cco)})
        mid = rascunho["id"]
        try:
            for nome, dados, cid in inline:          # assinatura: imagem no corpo (cid), pequena
                self._json("POST", f"/me/messages/{mid}/attachments", {
                    "@odata.type": "#microsoft.graph.fileAttachment", "name": nome, "isInline": True,
                    "contentId": cid, "contentBytes": base64.b64encode(dados).decode("ascii")})
            for nome, dados in anexos:
                if len(dados) <= LIMITE_SIMPLES:
                    self._json("POST", f"/me/messages/{mid}/attachments", {
                        "@odata.type": "#microsoft.graph.fileAttachment", "name": nome,
                        "contentBytes": base64.b64encode(dados).decode("ascii")})
                    continue
                sessao = self._json("POST", f"/me/messages/{mid}/attachments/createUploadSession", {
                    "AttachmentItem": {"attachmentType": "file", "name": nome, "size": len(dados)}})
                for inicio in range(0, len(dados), BLOCO):
                    bloco = dados[inicio:inicio + BLOCO]
                    _http("PUT", sessao["uploadUrl"], bloco, {
                        "Content-Type": "application/octet-stream",
                        "Content-Range": f"bytes {inicio}-{inicio + len(bloco) - 1}/{len(dados)}"})
            self.token.acesso()          # token renovado AQUI: falha de login ainda e' antes do envio
        except graph.ErroGraph:
            self._apagar_rascunho(mid)
            raise
        # Ponto sem volta (gate Sol S2, 10/10/2026): so' o /send manda o e-mail. Recusa com 4xx e' certeza de que
        # nada saiu; sem resposta, 5xx ou resposta ilegivel o Graph pode ter aceitado -- nao se apaga nada (a
        # mensagem pode ja' estar em Enviados) e a reserva fica (EnvioIncerto).
        try:
            self._json("POST", f"/me/messages/{mid}/send")
        except graph.ErroGraph as e:
            if e.status is not None and 400 <= e.status < 500:
                self._apagar_rascunho(mid)
                raise
            log.critical("Envio INCERTO (%s): %s para %s", e, assunto, para)
            raise EnvioIncerto(None, assunto, para) from e
        except ValueError as e:
            log.critical("Envio INCERTO (resposta ilegivel do /send): %s para %s", assunto, para)
            raise EnvioIncerto(None, assunto, para) from e
        return rascunho.get("internetMessageId")

    def _apagar_rascunho(self, mid: str) -> None:
        try:
            self._json("DELETE", f"/me/messages/{mid}")
        except graph.ErroGraph:
            log.warning("rascunho %s ficou na caixa apos falha de envio", mid)


class CorreioSimulado:
    """`DASH_GRAPH_SIMULADOR=<pasta>`: grava o que seria enviado, para dev e testes de API."""

    def __init__(self, pasta: Path, remetente: str):
        self.pasta, self._remetente = pasta / "enviados", remetente

    def remetente(self) -> str:
        return self._remetente

    def enviar(self, para, copia, assunto, corpo_html, anexos, cco=(), inline=()) -> str:
        _conferir_tamanho([*anexos, *((n, d) for n, d, _ in inline)])
        self.pasta.mkdir(parents=True, exist_ok=True)
        # Nome unico (10/10/2026, N-02): contar os .json da pasta dava o MESMO nome a envios simultaneos, um
        # sobrescrevia o outro e o simulador subestimava os envios. Ordem alfabetica = ordem de envio.
        n = f"{datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')}-{secrets.token_hex(2)}"
        (self.pasta / f"{n}.json").write_text(json.dumps({
            "remetente": self._remetente, "para": para, "copia": copia, "cco": list(cco), "assunto": assunto,
            "corpo": corpo_html, "inline": [{"nome": nome, "cid": cid, "tamanho": len(d)} for nome, d, cid in inline],
            "anexos": [{"nome": nome, "tamanho": len(d), "sha256": hashlib.sha256(d).hexdigest()}
                       for nome, d in anexos]}, ensure_ascii=False, indent=1), encoding="utf-8")
        return f"<simulado-{n}@dashboard>"


def cliente(usuario_id: int, email_usuario: str = ""):
    cfg = configuracao()
    if cfg["simulador"]:
        return CorreioSimulado(Path(cfg["simulador"]), email_usuario or f"usuario-{usuario_id}@simulador")
    if not cfg["client_id"]:
        raise graph.ErroGraph("Microsoft 365 não configurado neste servidor (DASH_GRAPH_CLIENT_ID)")
    if not conectado(usuario_id):
        raise graph.ErroGraph("Sua conta Microsoft não está conectada: conecte em Minha conta")
    return ClienteCorreio(graph.Token(cfg["tenant"], cfg["client_id"], arquivo_token(usuario_id), ESCOPOS))


def enviar_e_registrar(conn, usuario: dict, tipo: str, para: list[str], copia: list[str], assunto: str,
                       corpo_html: str, anexos: list[tuple[str, bytes]], cco: list[str] | None = None) -> int:
    """Envia e SO' ENTAO registra: falha de envio nao deixa rastro de envio. Com assinatura cadastrada, ela vai
    no fim do corpo como imagem (anexo embutido, como o Outlook faz). Instalacao nao autorizada (issue #417): recusa
    antes de tudo, inclusive no envio que nao passa pela reserva (teste de envio, cobranca de certidoes)."""
    instalacao.exigir_envio()
    cco = list(cco or [])
    destino_teste = redirecionamento()      # antes de tudo: mal configurado, nada sai
    c = cliente(usuario["id"], usuario.get("email", ""))
    remetente = c.remetente()
    # Quem envia nao vai em copia de si mesmo: compara com a conta do Outlook, nao com o login (09/10/2026).
    copia = [x for x in copia if x.lower() != (remetente or "").lower()]
    cco = [x for x in cco if x.lower() != (remetente or "").lower()]
    inline = []
    a = assinatura(usuario["id"])
    if a is not None:
        dados, tipo_img = a
        corpo_html += (f'<p>&nbsp;</p><p><img src="cid:{ASSINATURA_CID}" alt="Assinatura" '
                       f'style="max-width:600px"></p>')
        inline.append((f"assinatura.{'png' if tipo_img == 'image/png' else 'jpg'}", dados, ASSINATURA_CID))
    if destino_teste:
        # Redirecionamento de teste: vai SO' para o endereco de teste. O registro guarda os destinatarios de verdade
        # (sao eles que o proximo envio propoe) e a auditoria diz para onde o e-mail foi de fato.
        lista = lambda nome, xs: f"{nome}: {html.escape(', '.join(xs))}" if xs else None
        quem = "; ".join(filter(None, (lista("para", para), lista("cópia", copia), lista("cco", cco))))
        aviso = ('<p style="border:1px solid #B45309;background:#FFFBEB;padding:8px 12px">'
                 f"<strong>TESTE da Dashboard Lotufo: este e-mail foi redirecionado.</strong> Iria {quem or 'sem destinatário'}.</p>")
        mensagem_id = c.enviar([destino_teste], [], f"[TESTE] {assunto}", aviso + corpo_html, anexos, cco=[], inline=inline)
    else:
        mensagem_id = c.enviar(para, copia, assunto, corpo_html, anexos, cco=cco, inline=inline)
    # O e-mail SAIU: daqui para baixo nenhuma falha pode virar "tente de novo" (A-03, 10/10/2026). Banco travado
    # alem do busy_timeout ganha mais duas chances; o que ainda falhar vira EnvioNaoRegistrado.
    for tentativa in range(3):
        if tentativa:
            time.sleep(1)
        try:
            return registrar_envio(conn, usuario["id"], tipo, remetente, para, copia, assunto, mensagem_id, anexos,
                                   cco=cco, redirecionado_para=destino_teste)
        except Exception as e:
            erro = e
            if not db.eh_lock(e):
                break
    log.critical("E-mail ENVIADO e nao registrado: %s para %s (%s)", assunto, para, mensagem_id)
    raise EnvioNaoRegistrado(mensagem_id, assunto, para) from erro


# --- assinatura de quem envia --------------------------------------------------------------------------------

def _arquivo_assinatura(usuario_id: int) -> Path:
    return arquivos.pasta("assinaturas") / f"usuario-{int(usuario_id)}"


def assinatura(usuario_id: int) -> tuple[bytes, str] | None:
    """(bytes, mime) da imagem da assinatura, ou None."""
    try:
        dados = _arquivo_assinatura(usuario_id).read_bytes()
    except OSError:
        return None
    return (dados, _mime_imagem(dados)) if dados and _mime_imagem(dados) else None


def _mime_imagem(dados: bytes) -> str | None:
    if dados.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if dados.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


# Tipo de cor do PNG -> (amostras por pixel, profundidades validas): cinza, RGB, paleta, cinza+alfa, RGBA.
_PNG_CORES = {0: (1, (1, 2, 4, 8, 16)), 2: (3, (8, 16)), 3: (1, (1, 2, 4, 8)), 4: (2, (8, 16)), 6: (4, (8, 16))}
_ADAM7 = ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))
# Teto da imagem descomprimida (~4000 x 4000 RGBA): assinatura e' pequena, e um PNG de 1 MB que promete uma
# imagem enorme faria o servidor descomprimir gigabytes so' para conferir.
_PNG_MAX_PIXELS_BYTES = 64 * 1024 * 1024


def _png_integro(dados: bytes) -> bool:
    """Percorre os blocos (tamanho e CRC de cada um), exige IHDR no inicio, PLTE antes do IDAT se a imagem e' de
    paleta, IDAT seguidos e IEND no fim, e descomprime o IDAT conferindo que da' exatamente o tamanho que o IHDR
    promete, sem sobra. Arquivo cortado ou com byte trocado falha em algum desses pontos."""
    pos, idat, ihdr, plte, fim, idat_fechado = 8, [], None, False, False, False
    while pos < len(dados):
        if pos + 12 > len(dados):
            return False
        tamanho, tipo = struct.unpack(">I4s", dados[pos:pos + 8])
        corpo = dados[pos + 8:pos + 8 + tamanho]
        if len(corpo) != tamanho or pos + 12 + tamanho > len(dados):
            return False
        (crc,) = struct.unpack(">I", dados[pos + 8 + tamanho:pos + 12 + tamanho])
        if zlib.crc32(tipo + corpo) != crc:
            return False
        if ihdr is None and tipo != b"IHDR":
            return False
        if tipo == b"IHDR":
            if pos != 8:
                return False
            ihdr = corpo
        elif tipo == b"PLTE":
            plte = True
        elif tipo == b"IDAT":
            if idat_fechado:
                return False
            idat.append(corpo)
        elif tipo == b"IEND":
            if tamanho or pos + 12 != len(dados):      # IEND vazio e no fim do arquivo, sem nada depois
                return False
            fim = True
            break
        if idat and tipo != b"IDAT":
            idat_fechado = True
        pos += 12 + tamanho
    if not fim or ihdr is None or len(ihdr) != 13 or not idat:
        return False
    largura, altura, prof, cor, _, _, entrelacado = struct.unpack(">IIBBBBB", ihdr)
    if (not largura or not altura or cor not in _PNG_CORES or prof not in _PNG_CORES[cor][1]
            or entrelacado not in (0, 1) or (cor == 3 and not plte)):
        return False
    bits = _PNG_CORES[cor][0] * prof
    passos = _ADAM7 if entrelacado else ((0, 0, 1, 1),)
    esperado = 0
    for x0, y0, dx, dy in passos:
        w, h = (largura - x0 + dx - 1) // dx, (altura - y0 + dy - 1) // dy
        if w and h:
            esperado += h * (1 + (w * bits + 7) // 8)
    if esperado > _PNG_MAX_PIXELS_BYTES:
        raise ValueError("Imagem da assinatura grande demais: reduza as dimensões e suba de novo")
    d, total, entrada = zlib.decompressobj(), 0, b"".join(idat)
    try:
        while entrada and not d.eof and total <= esperado:   # em pedacos: so' conta, nada fica na memoria
            total += len(d.decompress(entrada, 1 << 20))
            entrada = d.unconsumed_tail
    except zlib.error:
        return False
    return d.eof and not d.unused_data and total == esperado


def _jpg_integro(dados: bytes) -> bool:
    """Percorre o arquivo inteiro ate' o marcador de fim (EOI): segmentos com tamanho, quadro (SOF) valido antes
    da primeira varredura (SOS), dados de cada varredura (com `FF 00`, RSTn e preenchimento) e os segmentos entre
    varreduras (JPG progressivo). So' vale o EOI que e' marcador de verdade, depois de tudo completo; JPG cortado
    para no meio de um segmento ou da varredura. Nao decodifica a imagem: byte trocado dentro dos dados da
    varredura nao e' detectado."""
    pos, n, quadro, varredura = 2, len(dados), False, False
    while pos < n:
        if dados[pos] != 0xFF:
            if not varredura:
                return False
            pos = dados.find(b"\xff", pos)             # dados da varredura: so' interessa o proximo FF
            if pos == -1:
                return False
            continue
        if pos + 1 >= n:
            return False
        marcador = dados[pos + 1]
        if marcador == 0xFF:                           # preenchimento
            pos += 1
            continue
        if marcador == 0xD9:                           # EOI
            return quadro and varredura
        if marcador == 0x00 or 0xD0 <= marcador <= 0xD7:   # FF 00 e RSTn: so' dentro da varredura
            if not varredura:
                return False
            pos += 2
            continue
        if marcador == 0x01 or (marcador == 0xD8 and not varredura):   # TEM e SOI: sem tamanho
            pos += 2
            continue
        if pos + 4 > n:
            return False
        (tamanho,) = struct.unpack(">H", dados[pos + 2:pos + 4])
        if tamanho < 2 or pos + 2 + tamanho > n:
            return False
        if 0xC0 <= marcador <= 0xCF and marcador not in (0xC4, 0xC8, 0xCC):
            corpo = dados[pos + 4:pos + 2 + tamanho]
            if len(corpo) < 6:
                return False
            precisao, altura, largura, componentes = struct.unpack(">BHHB", corpo[:6])
            if (tamanho != 8 + 3 * componentes or not precisao or not altura or not largura
                    or not componentes):
                return False
            quadro = True
        elif marcador == 0xDA:
            if not quadro:
                return False
            varredura = True
        pos += 2 + tamanho
    return False


def gravar_assinatura(conn, usuario_id: int, dados: bytes) -> None:
    mime = _mime_imagem(dados)
    if not mime:
        raise ValueError("A assinatura tem que ser uma imagem PNG ou JPG")
    if len(dados) > ASSINATURA_MAX:
        raise ValueError("Imagem da assinatura acima de 1 MB")
    if not (_png_integro(dados) if mime == "image/png" else _jpg_integro(dados)):
        raise ValueError("A imagem da assinatura está incompleta ou corrompida. Salve a imagem de novo e "
                         "suba outra vez.")
    # temporario + rename (#441): o backup le a pasta sem trava, e o nome nao e' o sha256 (nada confere o conteudo);
    # `write_bytes` direto truncaria a assinatura antes de escrever, e o backup poderia guardar a metade
    destino = _arquivo_assinatura(usuario_id)
    _limpar_temporarios_de_assinatura(destino.parent)
    tmp = destino.with_name(f"{destino.name}.{os.getpid()}-{secrets.token_hex(4)}.tmp")
    try:
        tmp.write_bytes(dados)
        _evento_com_retentativa(conn, usuario_id, {"tamanho": len(dados), "sha256": hashlib.sha256(dados).hexdigest()},
                                lambda: os.replace(tmp, destino), GRAVAR_ASSINATURA_OCUPADA)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


# `usuario-<id>.<pid>-<aleatorio>.tmp`: so' o temporario que `gravar_assinatura` cria
_TMP_ASSINATURA = re.compile(r"usuario-\d+\.\d+-[0-9a-f]{8}\.tmp")
_TMP_ASSINATURA_VELHO_SEG = 3600
GRAVAR_ASSINATURA_OCUPADA = "Não foi possível gravar a assinatura agora; tente de novo"
_TENTATIVAS_TROCA = (0.1, 0.2, 0.4, 0.8)    # ~1,5 s no total, so' com o arquivo ocupado


def _limpar_temporarios_de_assinatura(pasta: Path) -> None:
    """Sobra de gravacao interrompida (processo morto entre escrever e renomear): ninguem mais a renomeia."""
    agora = time.time()
    for sobra in pasta.glob("usuario-*.tmp"):
        try:
            if _TMP_ASSINATURA.fullmatch(sobra.name) and agora - sobra.stat().st_mtime > _TMP_ASSINATURA_VELHO_SEG:
                sobra.unlink(missing_ok=True)
        except OSError:
            pass                # aberto por outra gravacao (ou ja' saiu): nao e' sobra


REMOVER_ASSINATURA_OCUPADA = "Não foi possível tirar a assinatura agora; tente de novo"


def _evento_com_retentativa(conn, usuario_id: int, depois: dict, mexer, recusa: str) -> None:
    """Evento `correio.assinatura` e mudanca no arquivo (`mexer`) na mesma transacao. `os.replace`/`unlink` sobre a
    assinatura que o backup esta' lendo falha com PermissionError no Windows (arquivo aberto): a transacao inteira e'
    desfeita (o rollback solta a trava de escrita do banco) e so' entao se espera para tentar de novo (#479: dormir
    dentro dela seguraria todas as outras gravacoes). O que persiste vira ValueError em portugues (422)."""
    for espera in (*_TENTATIVAS_TROCA, None):
        try:
            with db.mutacao(conn):
                auditoria.registrar(conn, usuario_id, "correio.assinatura", "usuario", usuario_id, None, depois)
                mexer()
            return
        except PermissionError:
            if espera is None:
                raise ValueError(recusa) from None
            time.sleep(espera)


def remover_assinatura(conn, usuario_id: int) -> None:
    arquivo = _arquivo_assinatura(usuario_id)
    if not arquivo.exists():
        return
    # missing_ok: outra remocao simultanea ja' tirou, nao e' erro
    _evento_com_retentativa(conn, usuario_id, {"removida": True}, lambda: arquivo.unlink(missing_ok=True),
                            REMOVER_ASSINATURA_OCUPADA)


# --- contatos para os destinatarios --------------------------------------------------------------------------

def _contatos_locais(conn, usuario_id: int) -> dict[str, str | None]:
    """email -> nome, do que a dashboard ja' conhece: usuarios, fiscais, faturamento das entidades, enderecos dos
    orgaos e das obras, e quem ja' recebeu e-mail pelo sistema."""
    out: dict[str, str | None] = {}

    def por(email, nome=None):
        e = (email or "").strip().lower()
        if _EMAIL.fullmatch(e) and (e not in out or (nome and not out[e])):
            out[e] = nome or out.get(e)

    for r in conn.execute("SELECT nome, email FROM usuarios WHERE ativo=1"):
        por(r["email"], r["nome"])
    for r in conn.execute("SELECT nome, email FROM contrato_fiscais WHERE email IS NOT NULL"):
        por(r["email"], r["nome"])
    textos = [r[0] for r in conn.execute("SELECT regras FROM orgaos WHERE regras IS NOT NULL")]
    textos += [r[0] for r in conn.execute("SELECT emails_faturamento FROM entidades WHERE emails_faturamento IS NOT NULL")]
    textos += [r[0] for r in conn.execute("SELECT destinatarios_extras FROM contratos WHERE destinatarios_extras IS NOT NULL")]
    textos += [r[0] for r in conn.execute("SELECT copia_extras FROM contratos WHERE copia_extras IS NOT NULL")]
    textos += [x for r in conn.execute("SELECT para, copia FROM envios") for x in r if x]
    textos += [r[0] for r in conn.execute("SELECT cco FROM envios WHERE usuario_id=? AND cco IS NOT NULL",
                                          (usuario_id,))]          # copia oculta de outra pessoa nao vaza
    for t in textos:
        for e in _EMAIL.findall(t):
            por(e)
    return out


def _diretorio(usuario_id: int, q: str, todos: bool) -> list[dict]:
    """Pessoas (/me/people) e usuarios da empresa (/users) pelo Graph. Sem a permissao (conta conectada antes
    de 2026-09-25) ou fora do ar: lista vazia, e ficam as sugestoes do cadastro."""
    cfg = configuracao()
    if cfg["simulador"] or not cfg["client_id"] or not conectado(usuario_id):
        return []
    c = ClienteCorreio(graph.Token(cfg["tenant"], cfg["client_id"], arquivo_token(usuario_id), ESCOPOS_DIRETORIO))
    out = []
    try:
        if q:
            r = c._json("GET", "/me/people?" + urllib.parse.urlencode({"$search": f'"{q}"', "$top": "10"}))
            for p in r.get("value", []):
                for e in p.get("scoredEmailAddresses") or []:
                    out.append({"nome": p.get("displayName"), "email": (e.get("address") or "").lower()})
        filtro = {"$select": "displayName,mail", "$top": "200" if todos else "10", "$orderby": "displayName"}
        if q:
            filtro["$search"] = f'"displayName:{q}" OR "mail:{q}"'
        r = c._json("GET", "/users?" + urllib.parse.urlencode(filtro), headers={"ConsistencyLevel": "eventual"})
        out += [{"nome": u.get("displayName"), "email": (u.get("mail") or "").lower()} for u in r.get("value", [])]
    except graph.ErroGraph as e:
        log.info("diretorio Microsoft indisponivel para o usuario %s: %s", usuario_id, e)
    return [x for x in out if _EMAIL.fullmatch(x["email"] or "")]


def contatos(conn, usuario_id: int, q: str = "", todos: bool = False) -> list[dict]:
    """Sugestoes de destinatario: cadastro da dashboard e diretorio Microsoft, sem repetir e-mail."""
    q = (q or "").strip().lower()
    vistos: dict[str, dict] = {}
    for e, nome in _contatos_locais(conn, usuario_id).items():
        if not q or q in e or q in (nome or "").lower():
            vistos[e] = {"nome": nome, "email": e}
    for x in _diretorio(usuario_id, q, todos):
        if x["email"] not in vistos or not vistos[x["email"]]["nome"]:
            vistos[x["email"]] = x
    lista = sorted(vistos.values(), key=lambda x: ((x["nome"] or x["email"]).lower()))
    if q:   # quem comeca com o texto vem primeiro, como no Outlook
        lista.sort(key=lambda x: not ((x["nome"] or "").lower().startswith(q) or x["email"].startswith(q)))
    return lista[:200 if todos else 10]

