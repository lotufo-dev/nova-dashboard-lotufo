"""Alertas de seguranca por e-mail ao dono e resumo diario (issue #424; plano de protecao da VM, item B5).

Destinatario e logins de quem envia vem do cadastro (`geral.yaml`, `alertas_seguranca: {para, enviada_por}`, como a
cobranca de certidoes); o e-mail sai da conta Microsoft do primeiro usuario ativo com um desses logins
(`correio.enviar_e_registrar`). Sem cadastro, sem usuario ou sem conta conectada nada sai: fica no log e a Saude mostra
o motivo (`situacao`).

- Alerta imediato: cada item `critico` ou `acao` do bloco Seguranca (`seguranca.itens`) que ainda nao saiu. Itens
  iguais na mesma hora (de Cuiaba) vao num e-mail so'. A rodada roda a cada `INTERVALO_SEG`.
- Resumo diario a partir das 07:00 de Cuiaba, um por dia, mesmo vazio ("Nada a relatar"): os itens das ultimas 24
  horas (e os `critico` que continuam abertos), o commit em producao, a ultima copia do dono, a sentinela e a linha e
  o hash mais recentes da auditoria, que ancoram a cadeia fora da VM (`python -m app.cli auditoria conferir`).

Cada e-mail e' uma linha de `alertas_seguranca_envios` (migracao 071), gravada ANTES do envio, com `chave` unica: o
mesmo e-mail nao sai duas vezes. Falha antes do envio solta a marca e a rodada seguinte (depois de
`ESPERA_FALHA_MIN`) tenta de novo; envio incerto ou sem registro deixa a marca e nao se repete sozinho. No modo copia
(instalacao nao autorizada) nada roda: o envio ja' e' recusado la' (`instalacao.exigir_envio`).
"""
import datetime
import json
import logging
import re
import threading
import time
from html import escape

from app import (backup, cobranca_certidoes, copia_dono, copia_dono_envio, correio, db, graph, instalacao,
                 integridade, seguranca, sentinela, tempo)

log = logging.getLogger("app.alertas_seguranca")

TABELA = "alertas_seguranca_envios"
TIPO_ENVIO = "alertas_seguranca"
NIVEIS_IMEDIATOS = ("critico", "acao")
HORA_RESUMO = 7
INTERVALO_SEG = 60
ESPERA_FALHA_MIN = 10
JANELA_RESUMO = datetime.timedelta(hours=24)
# envio incerto mais velho que isto sai da Saude: o e-mail de alerta nao se repete e a tela nao fica acusando para sempre
PRESA_NA_SAUDE = datetime.timedelta(hours=24)
ASSUNTO_CURTO_MAX = 120
_NIVEL = {"critico": "crítico", "acao": "ação", "atencao": "atenção"}
# O item de leitura da sentinela soma as quantidades das rodadas da mesma hora (`seguranca._sentinela`): a mensagem
# cresce, o item e' o mesmo
_QUANTIDADE = re.compile(r", \d+ arquivos?$")

SEM_CADASTRO = "nada sai: falta o destinatário no cadastro"
SEM_REMETENTE = "nada sai: falta quem envia no cadastro"
SEM_USUARIO = "nada sai: nenhum usuário ativo é quem envia; corrija o cadastro"
SERVICO_NAO_CONFIGURADO = "nada sai: o envio de e-mail não está configurado neste servidor"

# O que a Saude mostra do ultimo envio (`erro`) e quando ele falhou (`falhou_em`, UTC), da memoria do processo
ESTADO: dict = {"erro": None, "falhou_em": None}


class NaoConfigurado(ValueError):
    """Falta cadastro, usuario ou conta conectada: nada sai."""


def _config(conn) -> dict:
    r = conn.execute("SELECT valor FROM cadastro_geral WHERE chave='alertas_seguranca'").fetchone()
    try:
        config = json.loads(r["valor"]) if r else None
    except ValueError:
        config = None
    if not isinstance(config, dict) or not config.get("para"):
        raise NaoConfigurado(SEM_CADASTRO)
    if not config.get("enviada_por"):
        raise NaoConfigurado(SEM_REMETENTE)
    return config


def _remetente(conn, config: dict) -> dict:
    """O usuario de `enviada_por` com a conta pronta para enviar (a mesma conferencia do envio)."""
    u = cobranca_certidoes._usuario(conn, config["enviada_por"])
    if u is None:
        raise NaoConfigurado(SEM_USUARIO)
    try:
        correio.cliente(u["id"], u["email"])
    except (graph.ErroGraph, RuntimeError):
        if not correio.configuracao()["client_id"]:
            raise NaoConfigurado(SERVICO_NAO_CONFIGURADO) from None
        if not correio.conectado(u["id"]):
            raise NaoConfigurado(f"nada sai: a conta Microsoft de {u['email']} não está conectada; conecte em "
                                 "Minha conta") from None
        raise NaoConfigurado(f"nada sai: a conta Microsoft de {u['email']} não pôde ser usada; reconecte em "
                             "Minha conta") from None
    return u


def _local(data_iso: str) -> datetime.datetime:
    return tempo.para_local(datetime.datetime.fromisoformat(data_iso))


def _linha(item: dict) -> str:
    return f"- {item['mensagem']} ({_NIVEL.get(item['nivel'], item['nivel'])}), em {_local(item['data']):%d/%m/%Y %H:%M}"


def _html(linhas: list[str]) -> str:
    return "".join(f"<p>{escape(x)}</p>" if x else "<p>&nbsp;</p>" for x in linhas)


def assunto_alerta(mensagem: str) -> str:
    curta = mensagem if len(mensagem) <= ASSUNTO_CURTO_MAX else mensagem[:ASSUNTO_CURTO_MAX - 1] + "…"
    return f"Dashboard Lotufo: alerta de segurança: {curta}"


def assunto_resumo(dia: datetime.date) -> str:
    return f"Dashboard Lotufo: resumo de segurança de {dia:%d/%m/%Y}"


def _grupos(itens: list[dict]) -> dict[str, list[dict]]:
    """Itens imediatos agrupados: mesma mensagem (sem a quantidade da sentinela) na mesma hora de Cuiaba."""
    grupos: dict[str, list[dict]] = {}
    for i in sorted(itens, key=lambda i: i["data"]):
        if i["nivel"] not in NIVEIS_IMEDIATOS:
            continue
        chave = f"alerta {_local(i['data']):%Y-%m-%d %H} {_QUANTIDADE.sub('', i['mensagem'])}"
        grupos.setdefault(chave, []).append(i)
    return grupos


def _ja_saiu(conn, chave: str) -> bool:
    """A linha existe e saiu ou esta' marcada (envio em curso, incerto ou sem registro)."""
    r = conn.execute(f"SELECT envio_id, envio_reservado_em FROM {TABELA} WHERE chave=?", (chave,)).fetchone()
    return r is not None and (r["envio_id"] is not None or r["envio_reservado_em"] is not None)


def _reservar(conn, chave: str, tipo: str, assunto: str, usuario_id: int) -> int | None:
    """Grava a linha (ou marca a que falhou antes) ANTES do e-mail; None se ja' saiu ou esta' marcada."""
    with db.mutacao(conn):
        r = conn.execute(f"SELECT id, envio_id, envio_reservado_em FROM {TABELA} WHERE chave=?", (chave,)).fetchone()
        if r is None:
            return conn.execute(
                f"INSERT INTO {TABELA} (chave, tipo, assunto, envio_reservado_em, envio_reservado_por) "
                "VALUES (?,?,?,datetime('now'),?)", (chave, tipo, assunto, usuario_id)).lastrowid
        if r["envio_id"] is not None or r["envio_reservado_em"] is not None:
            return None
        conn.execute(f"UPDATE {TABELA} SET envio_reservado_em=datetime('now'), envio_reservado_por=?, assunto=? "
                     "WHERE id=?", (usuario_id, assunto, r["id"]))
        return r["id"]


def _soltar(conn, rid: int) -> None:
    try:
        with db.mutacao(conn):
            conn.execute(f"UPDATE {TABELA} SET envio_reservado_em=NULL, envio_reservado_por=NULL WHERE id=?", (rid,))
    except Exception:
        log.exception("alerta de seguranca nao enviado e a marca %s nao foi solta", rid)


def _enviar(conn, usuario: dict, para: list[str], chave: str, tipo: str, assunto: str, corpo: str,
            agora: datetime.datetime) -> bool:
    """Um e-mail registrado antes de sair. False: nao saiu (ou saiu incerto), e a rodada para aqui."""
    rid = _reservar(conn, chave, tipo, assunto, usuario["id"])
    if rid is None:
        return True
    try:
        envio_id = correio.enviar_e_registrar(conn, usuario, TIPO_ENVIO, para, [], assunto, corpo, [])
    except correio.EnvioNaoRegistrado as e:          # inclui o incerto: a marca fica, nada se repete sozinho
        ESTADO["erro"] = (f"envio incerto às {tempo.para_local(agora):%H:%M} ({assunto}); confira os Enviados de "
                          "quem envia")
        ESTADO["falhou_em"] = agora
        log.critical("alerta de seguranca: envio incerto ou sem registro (%s): %s", assunto, e)
        return False
    except Exception as e:
        _soltar(conn, rid)
        ESTADO["erro"] = f"o último envio falhou ({copia_dono_envio.motivo(e)})"
        ESTADO["falhou_em"] = agora
        log.warning("alerta de seguranca nao enviado (%s): %s", assunto, e)
        return False
    try:
        with correio.depois_do_envio(assunto, para, envio_id), db.mutacao(conn):
            conn.execute(f"UPDATE {TABELA} SET envio_id=?, envio_reservado_em=NULL, envio_reservado_por=NULL "
                         "WHERE id=?", (envio_id, rid))
    except correio.EnvioNaoRegistrado:
        log.critical("alerta de seguranca enviado e nao marcado (%s): a marca fica", assunto)
    ESTADO["erro"] = None
    ESTADO["falhou_em"] = None
    return True


def _corpo_alerta(itens: list[dict]) -> str:
    return _html(["Alerta de segurança da Dashboard Lotufo:", "", *[_linha(i) for i in itens], "",
                  "Detalhes em Administração > Saúde."])


def _auditoria(conn) -> tuple[int, int | None, str | None]:
    total = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    r = conn.execute("SELECT id, hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    return total, (r["id"] if r else None), (r["hash"] if r else None)


def corpo_resumo(conn, agora: datetime.datetime) -> str:
    """Itens das ultimas 24 horas (e os `critico` que continuam: problema aberto nao some do resumo) ou "Nada a
    relatar", mais o que ancora o estado da VM."""
    dia = tempo.para_local(agora).date()
    desde = agora - JANELA_RESUMO
    itens = [i for i in seguranca.itens(conn, agora)
             if i["nivel"] == "critico" or datetime.datetime.fromisoformat(i["data"]) >= desde]
    linhas = [f"Resumo de segurança da Dashboard Lotufo de {dia:%d/%m/%Y} (últimas 24 horas).", ""]
    linhas += [_linha(i) for i in itens] if itens else ["Nada a relatar."]
    linhas += ["", f"Commit em produção: {integridade.commit_atual() or 'não identificado'}"]
    ultima = copia_dono.ultima_copia(backup.pasta_local())
    if ultima is not None:
        linhas.append(f"Última cópia do dono: {tempo.para_local(ultima):%d/%m/%Y %H:%M}")
    s = sentinela.situacao()
    linhas.append("Sentinela: ativa" if s.get("roda") else f"Sentinela: {s.get('mensagem') or 'não roda'}")
    total, linha, hash_ = _auditoria(conn)
    if linha is None:
        linhas.append("Auditoria: 0 linhas")
    else:
        linhas += [f"Auditoria: {total} linhas; última linha {linha}, hash {hash_}",
                   f"Para conferir: python -m app.cli auditoria conferir --linha {linha} --hash {hash_}"]
    return _html(linhas)


def rodada(conn, agora: datetime.datetime | None = None) -> list[str]:
    """Uma passada do job; devolve os assuntos enviados."""
    agora = agora or tempo.agora_utc()
    if not instalacao.ligada():
        return []
    try:
        config = _config(conn)
        usuario = _remetente(conn, config)
    except NaoConfigurado as e:
        if ESTADO["erro"] != str(e):
            log.warning("alertas de seguranca: %s", e)
        ESTADO["erro"] = str(e)
        return []
    if (ESTADO["erro"] or "").startswith("nada sai:"):
        ESTADO["erro"] = None                       # o cadastro ou a conta foram corrigidos
    falhou = ESTADO["falhou_em"]
    if falhou is not None and agora - falhou < datetime.timedelta(minutes=ESPERA_FALHA_MIN):
        return []
    enviados = []
    for chave, itens in _grupos(seguranca.itens(conn, agora)).items():
        if _ja_saiu(conn, chave):
            continue
        assunto = assunto_alerta(itens[-1]["mensagem"])
        if not _enviar(conn, usuario, config["para"], chave, "alerta", assunto, _corpo_alerta(itens), agora):
            return enviados
        enviados.append(assunto)
    local = tempo.para_local(agora)
    chave = f"resumo {local.date().isoformat()}"
    if local.hour >= HORA_RESUMO and not _ja_saiu(conn, chave):
        assunto = assunto_resumo(local.date())
        if _enviar(conn, usuario, config["para"], chave, "resumo", assunto, corpo_resumo(conn, agora), agora):
            enviados.append(assunto)
    return enviados


def situacao(conn) -> str | None:
    """O que a Saude mostra: por que nada sai (lido agora do cadastro e da conta), o envio incerto das ultimas 24
    horas ou a falha do ultimo envio. None: tudo certo (ou modo copia, em que o envio ja' e' recusado)."""
    if not instalacao.ligada():
        return None
    try:
        _remetente(conn, _config(conn))
    except NaoConfigurado as e:
        return str(e)
    presa = conn.execute(f"SELECT assunto, envio_reservado_em FROM {TABELA} WHERE envio_id IS NULL "
                         "AND envio_reservado_em <= datetime('now', '-15 minutes') AND envio_reservado_em >= "
                         "datetime('now', ?) ORDER BY id LIMIT 1",
                         (f"-{int(PRESA_NA_SAUDE.total_seconds())} seconds",)).fetchone()
    if presa is not None:
        return f"envio incerto ({presa['assunto']}); confira os Enviados de quem envia"
    return ESTADO["erro"]


def agendar(intervalo_seg: int = INTERVALO_SEG) -> threading.Thread:
    def loop():
        while True:
            try:
                conn = db.get_conn()
                try:
                    rodada(conn)
                finally:
                    conn.close()
            except Exception:                       # a thread nunca morre; a proxima rodada tenta de novo
                log.exception("rodada dos alertas de seguranca falhou")
            time.sleep(intervalo_seg)

    t = threading.Thread(target=loop, name="alertas-seguranca", daemon=True)
    t.start()
    return t
