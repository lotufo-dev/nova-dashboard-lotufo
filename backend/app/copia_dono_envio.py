"""Envio por e-mail da copia cifrada do dono (issue #420; plano de protecao da VM, item B3).

Depois de cada copia gerada (`copia_dono`, issue #419), o `.tar.age` vai como anexo ao destinatario do cadastro
(`geral.yaml`, `copia_dono: {para, enviada_por}`), da conta Microsoft do primeiro usuario ativo com um dos logins de
`enviada_por` (`correio.enviar_e_registrar`, como a cobranca de certidoes). Acima do teto do anexo, o arquivo vai em
partes numeradas (`.part01`, `.part02`...), um e-mail por parte, com o sha256 do arquivo inteiro em cada corpo.

Cada e-mail e' uma linha de `copia_dono_envios` (migracao 064), reservada antes de sair (`envio_reserva`). A mesma
copia sai uma vez so' sozinha (rodada 1); de novo, so' pelo "Reenviar cópia do dono" (rodadas 2, 3...). Sem
cadastro, sem usuario ou sem conta conectada nada sai: fica no log e em `backup.ESTADO` (a Saude mostra).
"""
import datetime
import hashlib
import html
import json
import logging
import re
from pathlib import Path

from app import auditoria, backup, cobranca_certidoes, copia_dono, correio, db, envio_reserva, graph, tempo

log = logging.getLogger("app.copia_dono_envio")

TABELA = "copia_dono_envios"
TIPO_ENVIO = "copia_dono"
# A parte e a assinatura de quem envia (ate' 1 MB, embutida no corpo) cabem juntas no teto do e-mail.
TAMANHO_PARTE = correio.MAX_TOTAL - correio.ASSINATURA_MAX
INSTRUCAO = "Abre só com a chave do dono; instruções no runbook, seção Cópia do dono."
SEM_CADASTRO = "destinatário da cópia do dono não configurado no cadastro (geral.yaml, copia_dono)"
SEM_COPIA = "Nenhuma cópia do dono gerada ainda"
_CARIMBO = re.compile(r"dashboard-dono-(\d{8}-\d{6})\.tar\.age$")


class EnvioNaoConfigurado(ValueError):
    """Nada saiu porque falta cadastro, usuario, conta conectada ou a copia."""


class ParteNaoEnviada(ValueError):
    """Uma parte nao saiu (falha antes do /send); `enviados` e' quantos e-mails desta rodada sairam antes dela."""

    def __init__(self, mensagem: str, enviados: int):
        super().__init__(mensagem)
        self.enviados = enviados


def _config(conn) -> dict:
    r = conn.execute("SELECT valor FROM cadastro_geral WHERE chave='copia_dono'").fetchone()
    if r is None:
        raise EnvioNaoConfigurado(SEM_CADASTRO)
    return json.loads(r["valor"])


def _remetente(conn, config: dict) -> dict:
    """O usuario de `enviada_por` e a conta dele pronta para enviar; senao, nada sai."""
    u = cobranca_certidoes._usuario(conn, config["enviada_por"])
    if u is None:
        raise EnvioNaoConfigurado("nenhum usuário ativo com um login de copia_dono.enviada_por (geral.yaml)")
    cfg = correio.configuracao()
    if not cfg["simulador"]:
        if not cfg["client_id"]:
            raise EnvioNaoConfigurado("Microsoft 365 não configurado neste servidor (DASH_GRAPH_CLIENT_ID)")
        if not correio.conectado(u["id"]):
            raise EnvioNaoConfigurado(f"a conta Microsoft de {u['email']} não está conectada: conecte em Minha conta")
    return u


def _gerada_em(arquivo: Path) -> datetime.datetime:
    """O momento (local) do nome do arquivo; nome fora do padrao: a data do disco."""
    m = _CARIMBO.search(arquivo.name)
    if m:
        return datetime.datetime.strptime(m[1], "%Y%m%d-%H%M%S")
    mtime = datetime.datetime.fromtimestamp(arquivo.stat().st_mtime, datetime.timezone.utc)
    return tempo.para_local(mtime).replace(tzinfo=None)


def _partes(dados: bytes, nome: str) -> list[tuple[str, bytes]]:
    if len(dados) <= TAMANHO_PARTE:
        return [(nome, dados)]
    pedacos = [dados[i:i + TAMANHO_PARTE] for i in range(0, len(dados), TAMANHO_PARTE)]
    return [(f"{nome}.part{n:02d}", p) for n, p in enumerate(pedacos, start=1)]


def _tamanho(n: int) -> str:
    em_bytes = f"{n:,}".replace(",", ".") + " bytes"
    if n < 1024 * 1024:
        return em_bytes
    return f"{n / 1024 / 1024:.1f}".replace(".", ",") + f" MB ({em_bytes})"


def assunto(gerada: datetime.datetime, parte: int, partes: int) -> str:
    base = f"Dashboard Lotufo: cópia cifrada de {gerada:%d/%m/%Y}"
    return base if partes == 1 else f"{base} (parte {parte} de {partes})"


def corpo(nome: str, gerada: datetime.datetime, tamanho: int, sha: str, parte: int, partes: int) -> str:
    linhas = [f"Cópia cifrada da Dashboard Lotufo de {gerada:%d/%m/%Y} às {gerada:%H:%M}.",
              f"Arquivo: {nome}", f"Tamanho: {_tamanho(tamanho)}", f"sha256 do arquivo inteiro: {sha}"]
    if partes > 1:
        linhas.append(f"Parte {parte} de {partes}: junte as {partes} partes, em ordem, num arquivo só antes de "
                      "conferir o sha256.")
    linhas.append(INSTRUCAO)
    return "".join(f"<p>{html.escape(l)}</p>" for l in linhas)


def _soltar(conn, ids: list[int]) -> None:
    """Reservas das partes que nao sairam; chamada de dentro do `except` da falha."""
    for rid in ids:
        envio_reserva.liberar_com_retentativa(conn, TABELA, rid)


def _enviar(conn, arquivo: Path, reenvio_por: dict | None) -> int:
    """Uma rodada de envio do arquivo; devolve quantos e-mails sairam. `reenvio_por` None = envio automatico, que
    nao sai se o arquivo ja' teve rodada. Tudo o que recusa vem antes da reserva; a reserva, antes do e-mail."""
    config = _config(conn)
    usuario = _remetente(conn, config)
    dados = arquivo.read_bytes()
    sha = hashlib.sha256(dados).hexdigest()
    partes = _partes(dados, arquivo.name)
    total = len(partes)
    reservado_por = reenvio_por["id"] if reenvio_por else usuario["id"]
    with db.mutacao(conn):
        presa = conn.execute(f"SELECT envio_reservado_em, envio_reservado_por FROM {TABELA} WHERE arquivo=? "
                             "AND envio_reservado_em IS NOT NULL ORDER BY id LIMIT 1", (arquivo.name,)).fetchone()
        if presa is not None:
            raise envio_reserva.reservado(conn, presa["envio_reservado_em"], presa["envio_reservado_por"])
        ultima = conn.execute(f"SELECT MAX(rodada) FROM {TABELA} WHERE arquivo=?", (arquivo.name,)).fetchone()[0]
        if ultima is not None and reenvio_por is None:
            return 0                                # a mesma copia nao sai duas vezes sozinha
        rodada = (ultima or 0) + 1
        ids = []
        for n in range(1, total + 1):
            ids.append(conn.execute(
                f"INSERT INTO {TABELA} (arquivo, sha256, tamanho, rodada, parte, partes) VALUES (?,?,?,?,?,?)",
                (arquivo.name, sha, len(dados), rodada, n, total)).lastrowid)
            envio_reserva.reservar(conn, TABELA, ids[-1], reservado_por, None)
        if reenvio_por is not None:
            auditoria.registrar(conn, reenvio_por["id"], "copia_dono.reenviar", "copia_dono", arquivo.name, None,
                                {"rodada": rodada, "partes": total, "sha256": sha, "para": config["para"],
                                 "enviada_por": usuario["email"]})
    gerada = _gerada_em(arquivo)
    for i, (rid, (nome, pedaco)) in enumerate(zip(ids, partes)):
        n = i + 1
        titulo = assunto(gerada, n, total)
        try:
            envio_id = correio.enviar_e_registrar(conn, usuario, TIPO_ENVIO, config["para"], [], titulo,
                                                  corpo(arquivo.name, gerada, len(dados), sha, n, total),
                                                  [(nome, pedaco)])
        except correio.EnvioNaoRegistrado:
            _soltar(conn, ids[i + 1:])              # esta parte pode ter saido: a reserva dela fica
            raise
        except Exception as e:
            _soltar(conn, ids[i:])                  # nada desta parte saiu
            if total == 1:
                raise
            anteriores = "; as anteriores saíram" if n > 1 else ""
            raise ParteNaoEnviada(f"parte {n} de {total} não enviada ({_motivo(e)}){anteriores}", i) from e
        with correio.depois_do_envio(titulo, config["para"], envio_id), db.mutacao(conn):
            envio_reserva.liberar(conn, TABELA, rid)
            conn.execute(f"UPDATE {TABELA} SET envio_id=? WHERE id=?", (envio_id, rid))
    return total


def _motivo(e: BaseException) -> str:
    if isinstance(e, (ValueError, graph.ErroGraph, correio.EnvioNaoRegistrado)):
        return str(e)
    return backup._motivo(e)


def _registrado(conn, arquivo: Path, reenvio_por: dict | None) -> int:
    """`_enviar` + `backup.ESTADO` (o que a Saude mostra) + log."""
    agora = tempo.para_local(tempo.agora_utc()).isoformat(timespec="seconds")
    try:
        enviados = _enviar(conn, arquivo, reenvio_por)
    except envio_reserva.EnvioEmAndamento:
        raise                                       # outro envio da mesma copia esta' saindo: nao e' falha
    except correio.EnvioNaoRegistrado as e:
        backup.ESTADO["ultimo_envio_copia_dono_erro"] = (
            f"{agora}: o e-mail saiu e o registro falhou; confira os Enviados de quem envia antes de reenviar")
        log.critical("copia do dono %s: e-mail enviado e nao registrado (%s)", arquivo.name, e)
        raise
    except Exception as e:
        backup.ESTADO["ultimo_envio_copia_dono_erro"] = f"{agora}: {_motivo(e)}"
        log.warning("copia do dono %s nao enviada: %s", arquivo.name, _motivo(e), exc_info=not isinstance(
            e, (EnvioNaoConfigurado, ParteNaoEnviada)))
        raise
    if enviados:
        backup.ESTADO["ultimo_envio_copia_dono"] = agora
        backup.ESTADO["ultimo_envio_copia_dono_erro"] = None
    return enviados


def enviar_nova(conn, arquivo: Path) -> int:
    """Envio automatico, logo depois de gerar a copia. Falha fica no log e na Saude e nao sobe, menos o e-mail que
    saiu sem registro (EnvioNaoRegistrado): esse sobe, para a rota dizer "NAO envie de novo"."""
    try:
        return _registrado(conn, arquivo, None)
    except correio.EnvioNaoRegistrado:
        raise
    except ParteNaoEnviada as e:
        return e.enviados
    except Exception:
        return 0


def reenviar(conn, pasta_backups: Path, usuario: dict) -> dict:
    """Botao "Reenviar cópia do dono": a copia mais recente, de novo, inteira."""
    copias = copia_dono.copias(pasta_backups)
    if not copias:
        raise EnvioNaoConfigurado(SEM_COPIA)
    arquivo = copias[-1]
    return {"arquivo": arquivo.name, "emails": _registrado(conn, arquivo, usuario)}


def rodada_semanal(raiz: Path, pasta_backups: Path) -> None:
    """A rodada semanal da copia (chamada pelo backup) e o envio da copia que ela gerou."""
    destino = copia_dono.rodada_semanal(raiz, pasta_backups)
    if destino is None:
        return
    conn = db.get_conn()
    try:
        enviar_nova(conn, destino)
    finally:
        conn.close()
