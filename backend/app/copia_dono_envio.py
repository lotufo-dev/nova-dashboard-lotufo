"""Envio por e-mail da copia cifrada do dono (issue #420; plano de protecao da VM, item B3).

Depois de cada copia gerada (`copia_dono`, issue #419), o `.tar.age` vai como anexo ao destinatario do cadastro
(`geral.yaml`, `copia_dono: {para, enviada_por}`), da conta Microsoft do primeiro usuario ativo com um dos logins de
`enviada_por` (`correio.enviar_e_registrar`, como a cobranca de certidoes). Acima do teto do anexo, o arquivo vai em
partes numeradas (`.part01`, `.part02`...), um e-mail por parte, com o sha256 do arquivo inteiro em cada corpo.

Cada e-mail e' uma linha de `copia_dono_envios` (migracao 066), reservada antes de sair (`envio_reserva`). A mesma
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
CABECALHO_AGE = b"age-encryption.org/v1\n"     # o que `pyrage.encrypt` grava no inicio de todo arquivo cifrado


class EnvioNaoConfigurado(ValueError):
    """Nada saiu porque falta cadastro, usuario, conta conectada ou a copia."""


class CopiaInvalida(ValueError):
    """O arquivo com o nome da copia nao e' a copia cifrada que a geracao gravou: nada sai."""


class ParteNaoEnviada(ValueError):
    """Uma parte nao saiu (falha antes do /send); `enviados` e' quantos e-mails desta rodada sairam antes dela,
    de `partes`."""

    def __init__(self, mensagem: str, enviados: int, partes: int):
        super().__init__(mensagem)
        self.enviados, self.partes = enviados, partes


def _conferir_copia(arquivo: Path, dados: bytes, sha: str) -> None:
    """So' sai o que a geracao gravou: arquivo age (nunca um `.tar` em claro com o mesmo nome) e com o sha256 que a
    geracao grava ao lado (`<arquivo>.sha256`). Antes da reserva: a recusa nao deixa rastro."""
    if not dados.startswith(CABECALHO_AGE):
        raise CopiaInvalida("o arquivo da cópia do dono não é um arquivo cifrado (age): nada foi enviado")
    try:
        gravado = (arquivo.parent / f"{arquivo.name}.sha256").read_text(encoding="utf-8").split()
    except (OSError, UnicodeError):
        raise CopiaInvalida("falta o sha256 da cópia do dono gravado ao lado dela: nada foi enviado") from None
    if not gravado or gravado[0].lower() != sha:
        raise CopiaInvalida("a cópia do dono não confere com o sha256 gravado ao lado dela: nada foi enviado")


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
    try:
        correio.cliente(u["id"], u["email"])       # a mesma conferencia do envio, antes de reservar
    except graph.ErroGraph as e:
        if correio.configuracao()["client_id"] and not correio.conectado(u["id"]):
            raise EnvioNaoConfigurado(
                f"a conta Microsoft de {u['email']} não está conectada: conecte em Minha conta") from None
        raise EnvioNaoConfigurado(str(e)) from None
    return u


def _gerada_em(arquivo: Path) -> datetime.datetime:
    """O momento (local) do nome do arquivo; nome fora do padrao: a data do disco."""
    gerada = _carimbo(arquivo.name)
    if gerada:
        return gerada
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


def _soltar(conn, ids: list[int]) -> str:
    """Reservas das partes que nao sairam; chamada de dentro do `except` da falha. Tenta soltar todas, mesmo que
    uma falhe (banco ocupado alem das retentativas), e devolve o aviso das que ficaram presas, para a Saude."""
    presas = 0
    for rid in ids:
        try:
            envio_reserva.liberar_com_retentativa(conn, TABELA, rid)
        except ValueError:
            presas += 1
    if not presas:
        return ""
    quantas = "1 reserva ficou presa" if presas == 1 else f"{presas} reservas ficaram presas"
    return f"; {quantas}: aguarde 15 minutos e libere o envio"


def _ja_teve_rodada(conn, nome: str) -> bool:
    return conn.execute(f"SELECT 1 FROM {TABELA} WHERE arquivo=? LIMIT 1", (nome,)).fetchone() is not None


def _carimbo(nome: str) -> datetime.datetime | None:
    """O momento (local) do nome do arquivo; None fora do padrao."""
    m = _CARIMBO.search(nome)
    return datetime.datetime.strptime(m[1], "%Y%m%d-%H%M%S") if m else None


def _data(nome: str) -> str:
    gerada = _carimbo(nome)
    return f"{gerada:%d/%m/%Y}" if gerada else nome


def _presa(conn):
    """A reserva mais antiga que ja' passou de `envio_reserva.IDADE_MINIMA_LIBERACAO`, de qualquer copia (o arquivo
    pode ja' ter sido apagado): rodada parada. None se nao ha'."""
    return conn.execute(f"SELECT id, arquivo, parte, partes, envio_reservado_em, envio_reservado_por FROM {TABELA} "
                        "WHERE envio_reservado_em <= datetime('now', ?) ORDER BY id LIMIT 1",
                        (f"-{envio_reserva.IDADE_MINIMA_LIBERACAO} minutes",)).fetchone()


def reserva_presa(conn) -> dict | None:
    """A reserva que a Saude acusa como interrompida, com o que a liberacao precisa (issue #482): a Saude oferece o
    "Liberar envio" a partir dela, sem passar pelo "Reenviar" (que mandaria a copia mais recente de novo)."""
    presa = _presa(conn)
    return None if presa is None else _detalhe_presa(conn, presa)


def pendente(conn, pasta_backups: Path) -> str | None:
    """O que a Saude acusa do envio da copia do dono, lido do banco (vale depois de o servidor reiniciar, quando o
    erro da memoria ja' sumiu). Primeiro, qualquer reserva mais velha que `envio_reserva.IDADE_MINIMA_LIBERACAO`, de
    qualquer copia: envio interrompido (queda no meio da rodada, envio incerto, e-mail sem registro). A rodada em
    curso renova a reserva das partes que faltam a cada parte enviada, entao reserva velha e' rodada parada. Depois,
    a copia mais recente sem rodada completa e sem envio em andamento: nao saiu. None: nada pendente."""
    presa = _presa(conn)
    if presa is not None:
        return f"envio da cópia de {_data(presa['arquivo'])} interrompido: confira os Enviados e libere"
    copias = copia_dono.copias(pasta_backups)
    if not copias:
        return None
    nome = copias[-1].name
    r = conn.execute(
        f"SELECT SUM(envio_reservado_em IS NOT NULL) AS reservadas, "
        f"(SELECT COUNT(*) FROM (SELECT rodada FROM {TABELA} WHERE arquivo=:a GROUP BY rodada "
        f"HAVING COUNT(envio_id) = MAX(partes))) AS completas FROM {TABELA} WHERE arquivo=:a", {"a": nome}).fetchone()
    if r["reservadas"] or r["completas"]:
        return None
    return f"a cópia de {_data(nome)} não saiu por e-mail"


def _detalhe_presa(conn, presa) -> dict:
    """O `detail` do 409 de envio reservado mais a linha, qual parte e o assunto a procurar nos Enviados (#482)."""
    gerada = _carimbo(presa["arquivo"])             # o arquivo pode ja' ter sido apagado: so' o nome
    recusa = envio_reserva.reservado(conn, presa["envio_reservado_em"], presa["envio_reservado_por"])
    return recusa.detalhe() | {"tabela": TABELA, "id": presa["id"], "parte": presa["parte"], "partes": presa["partes"],
                               "assunto": assunto(gerada, presa["parte"], presa["partes"]) if gerada else None}


def _auditar_reenvio(conn, quem: dict, arquivo: Path, depois: dict) -> None:
    """O resultado do "Reenviar", DEPOIS da rodada, num segundo evento (o "iniciado" entrou com a reserva): a falha
    dele nao esconde a do envio."""
    try:
        with db.mutacao(conn):
            auditoria.registrar(conn, quem["id"], "copia_dono.reenviar", "copia_dono", arquivo.name, None, depois)
    except Exception:
        log.exception("auditoria do reenvio da copia do dono %s nao gravada: %s", arquivo.name, depois)


def _enviar(conn, arquivo: Path, reenvio_por: dict | None) -> int:
    """Uma rodada de envio do arquivo; devolve quantos e-mails sairam. `reenvio_por` None = envio automatico, que
    nao sai se o arquivo ja' teve rodada. Tudo o que recusa vem antes da reserva; a reserva, antes do e-mail."""
    config = _config(conn)
    usuario = _remetente(conn, config)
    if reenvio_por is None and _ja_teve_rodada(conn, arquivo.name):
        return 0                                    # antes de ler o arquivo; conferido de novo na reserva
    dados = arquivo.read_bytes()
    sha = hashlib.sha256(dados).hexdigest()
    _conferir_copia(arquivo, dados, sha)
    partes = _partes(dados, arquivo.name)
    total = len(partes)
    reservado_por = reenvio_por["id"] if reenvio_por else usuario["id"]
    gerada = _gerada_em(arquivo)                    # antes da reserva: a falha aqui nao deixa nada preso
    with db.mutacao(conn):
        presa = conn.execute(f"SELECT id, arquivo, parte, partes, envio_reservado_em, envio_reservado_por FROM {TABELA} "
                             "WHERE arquivo=? AND envio_reservado_em IS NOT NULL ORDER BY id LIMIT 1",
                             (arquivo.name,)).fetchone()
        if presa is not None:
            recusa = envio_reserva.reservado(conn, presa["envio_reservado_em"], presa["envio_reservado_por"])
            recusa.presa = _detalhe_presa(conn, presa)  # a rota devolve, para a liberacao (/api/envios/liberar)
            raise recusa
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
        if reenvio_por is not None:                 # quem clicou fica antes do e-mail, mesmo que a rodada caia
            auditoria.registrar(conn, reenvio_por["id"], "copia_dono.reenviar", "copia_dono", arquivo.name, None, {
                "rodada": rodada, "partes": total, "resultado": "iniciado", "sha256": sha, "para": config["para"],
                "enviada_por": usuario["email"]})
    enviados, resultado = 0, "nada"
    try:
        for i, (rid, (nome, pedaco)) in enumerate(zip(ids, partes)):
            n = i + 1
            titulo = assunto(gerada, n, total)
            try:
                envio_id = correio.enviar_e_registrar(conn, usuario, TIPO_ENVIO, config["para"], [], titulo,
                                                      corpo(arquivo.name, gerada, len(dados), sha, n, total),
                                                      [(nome, pedaco)])
            except correio.EnvioNaoRegistrado as e:
                e.trava = _soltar(conn, ids[i + 1:])  # esta parte pode ter saido: a reserva dela fica
                raise
            except Exception as e:
                trava = _soltar(conn, ids[i:])      # nada desta parte saiu
                if total == 1 and not trava:
                    raise
                if total == 1:
                    raise ParteNaoEnviada(f"{_motivo(e)}{trava}", 0, total) from e
                anteriores = "; as anteriores saíram" if n > 1 else ""
                raise ParteNaoEnviada(f"parte {n} de {total} não enviada ({_motivo(e)}){anteriores}{trava}", i,
                                      total) from e
            try:
                with correio.depois_do_envio(titulo, config["para"], envio_id), db.mutacao(conn):
                    envio_reserva.liberar(conn, TABELA, rid)
                    conn.execute(f"UPDATE {TABELA} SET envio_id=? WHERE id=?", (envio_id, rid))
                    # a rodada continua viva: as partes que faltam renovam a reserva, para a Saude e a liberacao
                    # manual nao a tomarem por interrompida (rodada de muitas partes passa dos 15 minutos)
                    if ids[i + 1:]:
                        marcas = ",".join("?" * len(ids[i + 1:]))
                        conn.execute(f"UPDATE {TABELA} SET envio_reservado_em=datetime('now') WHERE id IN "
                                     f"({marcas}) AND envio_reservado_em IS NOT NULL", ids[i + 1:])
            except correio.EnvioNaoRegistrado as e:
                e.trava = _soltar(conn, ids[i + 1:])  # esta parte saiu e nao foi marcada: so' a reserva dela fica
                raise
            enviados += 1
        resultado = "completo"
    except correio.EnvioIncerto:
        resultado = "incerto"
        raise
    except correio.EnvioNaoRegistrado:
        resultado = "enviado_sem_registro"
        raise
    except BaseException:
        resultado = "parcial" if enviados else "nada"
        raise
    finally:
        if reenvio_por is not None:
            _auditar_reenvio(conn, reenvio_por, arquivo, {
                "rodada": rodada, "partes": total, "enviados": enviados, "resultado": resultado, "sha256": sha,
                "para": config["para"], "enviada_por": usuario["email"]})
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
    except correio.EnvioIncerto as e:               # a conexao caiu no /send: pode ter saido ou nao
        backup.ESTADO["ultimo_envio_copia_dono_erro"] = (
            f"{agora}: envio incerto: confira os Enviados de quem envia antes de reenviar{getattr(e, 'trava', '')}")
        log.critical("copia do dono %s: envio incerto (%s)", arquivo.name, e)
        raise
    except correio.EnvioNaoRegistrado as e:
        backup.ESTADO["ultimo_envio_copia_dono_erro"] = (
            f"{agora}: o e-mail saiu e o registro falhou; confira os Enviados de quem envia antes de reenviar"
            f"{getattr(e, 'trava', '')}")
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


def enviar_nova(conn, arquivo: Path) -> dict:
    """Envio automatico, logo depois de gerar a copia: `{emails, partes, completo}` (`partes` None quando nada foi
    tentado; `completo` so' com todas as partes enviadas). Falha fica no log e na Saude e nao sobe, menos o e-mail
    que saiu sem registro (EnvioNaoRegistrado): esse sobe, para a rota dizer "NAO envie de novo"."""
    try:
        total = _registrado(conn, arquivo, None)
    except correio.EnvioNaoRegistrado:
        raise
    except ParteNaoEnviada as e:
        return {"emails": e.enviados, "partes": e.partes, "completo": False}
    except Exception:
        return {"emails": 0, "partes": None, "completo": False}
    return {"emails": total, "partes": total or None, "completo": total > 0}


def reenviar(conn, pasta_backups: Path, usuario: dict) -> dict:
    """Botao "Reenviar cópia do dono": a copia mais recente, de novo, inteira. Parte que nao sai levanta
    (ParteNaoEnviada): a rota mostra o motivo, e o que volta aqui e' sempre o envio completo."""
    copias = copia_dono.copias(pasta_backups)
    if not copias:
        raise EnvioNaoConfigurado(SEM_COPIA)
    arquivo = copias[-1]
    total = _registrado(conn, arquivo, usuario)
    return {"arquivo": arquivo.name, "emails": total, "partes": total, "completo": True}


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
