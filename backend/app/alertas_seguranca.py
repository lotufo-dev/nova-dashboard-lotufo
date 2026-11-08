"""Alertas de seguranca por e-mail ao dono e resumo diario (issue #424; plano de protecao da VM, item B5).

Destinatario e logins de quem envia vem do cadastro (`geral.yaml`, `alertas_seguranca: {para, enviada_por}`, como a
cobranca de certidoes); o e-mail sai da conta Microsoft do primeiro usuario ativo com um desses logins
(`correio.enviar_e_registrar`). Sem cadastro, sem usuario ou sem conta conectada nada sai: fica no log e a Saude mostra
o motivo (`situacao`).

- Alerta imediato: cada item `critico` ou `acao` do bloco Seguranca (`seguranca.itens`) que ainda nao saiu. A rodada
  roda a cada `INTERVALO_SEG`. O que e' "o mesmo item":
  - o problema que continua aberto (protecao das tabelas, cadeia da auditoria, codigo diferente do deploy: a data
    dele so' mora na memoria do processo e muda a cada reinicio) sai uma vez por episodio, pela mensagem; o episodio
    fecha quando o problema some (depois de `CARENCIA_SEG` do processo no ar, para a primeira conferencia rodar);
  - a leitura de arquivos da sentinela, que soma as rodadas, pela identidade do agregado (`identidade`);
  - o resto, pela mensagem na hora de Cuiaba da data: itens iguais na mesma hora vao num e-mail so'.
  Item com data anterior ao marco (a primeira rodada com o cadastro configurado) nao vira e-mail: o primeiro deploy
  nao manda o historico. Depois do marco, o item que nao saiu (conta desconectada, por exemplo) sai quando der,
  enquanto estiver no bloco.
- Resumo diario a partir das 07:00 de Cuiaba, um por dia, mesmo vazio ("Nada a relatar"): os itens das ultimas 24
  horas e os problemas abertos, os dias sem resumo desde o ultimo, o commit em producao, a ultima copia do dono, a
  sentinela e a linha e o hash mais recentes da auditoria, que ancoram a cadeia fora da VM
  (`python -m app.cli auditoria conferir`).

Cada e-mail e' uma linha de `alertas_seguranca_envios` (migracao 071), gravada ANTES do envio, com `chave` unica: o
mesmo e-mail nao sai duas vezes. Falha antes do envio solta a marca e a rodada seguinte (depois de
`ESPERA_FALHA_MIN`) tenta de novo. Envio incerto, sem registro ou interrompido (queda entre a marca e o envio) deixa a
marca e nao se repete sozinho: a Saude acusa ate' uma pessoa conferir os Enviados e registrar o resultado
(`conferir_envio`, pela linha de comando). No modo copia (instalacao nao autorizada) nada roda: o envio ja' e'
recusado la' (`instalacao.exigir_envio`).
"""
import datetime
import json
import logging
import re
import threading
import time
from html import escape

from app import (auditoria, backup, cobranca_certidoes, copia_dono, copia_dono_envio, correio, db, graph,
                 instalacao, integridade, seguranca, sentinela, tempo)

log = logging.getLogger("app.alertas_seguranca")

TABELA = "alertas_seguranca_envios"
TIPO_ENVIO = "alertas_seguranca"
NIVEIS_IMEDIATOS = ("critico", "acao")
HORA_RESUMO = 7
INTERVALO_SEG = 120   # o e-mail sai em ate' 5 minutos com folga
ESPERA_FALHA_MIN = 10
JANELA_RESUMO = datetime.timedelta(hours=24)
# Marca de envio mais velha que isto, sem envio registrado, e' envio parado (o e-mail leva segundos)
PRESA_MIN = 15
# O episodio de um problema aberto so' fecha depois disto do processo no ar: no reinicio, as conferencias (protecao,
# cadeia, codigo) ainda nao rodaram e o bloco vem sem o problema que continua
CARENCIA_SEG = 900
DIAS_SEM_RESUMO_MAX = 7
ASSUNTO_CURTO_MAX = 120
_NIVEL = {"critico": "crítico", "acao": "ação", "atencao": "atenção"}
_CONTROLE = re.compile(r"[\x00-\x1f\x7f]")
_INICIO = time.monotonic()

SEM_CADASTRO = "nada sai: falta o destinatário no cadastro"
SEM_REMETENTE = "nada sai: falta quem envia no cadastro"
SEM_USUARIO = "nada sai: nenhum usuário ativo é quem envia; corrija o cadastro"
SAIU_SEM_REGISTRO = "Este e-mail saiu (sem registro): não registre que ele não saiu"
SERVICO_NAO_CONFIGURADO = "nada sai: o envio de e-mail não está configurado neste servidor"

# O que a Saude mostra do ultimo envio (`erro`) e quando ele falhou (`falhou_em`, UTC), da memoria do processo
ESTADO: dict = {"erro": None, "falhou_em": None}
# As linhas que deram envio incerto ou sem registro neste processo: a Saude as acusa na hora, sem esperar `PRESA_MIN`
_INCERTOS: set[int] = set()
# As linhas cujo e-mail SAIU com certeza e cuja marcacao falhou (banco ocupado): cada rodada tenta grava-las como
# saidas; enquanto isso a Saude as mostra como "saiu sem registro" e `conferir_envio` recusa "nao saiu". O banco
# guarda o mesmo estado em `envio_saiu_sem_registro_em` (issue #588), que vale fora deste processo; a memoria cobre
# so' o caso em que nem essa gravacao passou
_SAIRAM: set[int] = set()


class NaoConfigurado(ValueError):
    """Falta cadastro, usuario ou conta conectada: nada sai. `conectar`: a tela leva a Minha conta."""

    def __init__(self, mensagem: str, conectar: bool = False):
        super().__init__(mensagem)
        self.conectar = conectar


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
            raise NaoConfigurado(f"nada sai: a conta Microsoft de {u['email']} não está conectada",
                                 conectar=True) from None
        raise NaoConfigurado(f"nada sai: a conta Microsoft de {u['email']} não pôde ser usada; reconecte",
                             conectar=True) from None
    return u


def _local(data_iso: str) -> datetime.datetime:
    return tempo.para_local(datetime.datetime.fromisoformat(data_iso))


def _linha(item: dict) -> str:
    return f"- {item['mensagem']} ({_NIVEL.get(item['nivel'], item['nivel'])}), em {_local(item['data']):%d/%m/%Y %H:%M}"


def _html(linhas: list[str]) -> str:
    return "".join(f"<p>{escape(x)}</p>" if x else "<p>&nbsp;</p>" for x in linhas)


def assunto_alerta(mensagem: str) -> str:
    mensagem = " ".join(_CONTROLE.sub(" ", mensagem).split())      # assunto numa linha so'
    curta = mensagem if len(mensagem) <= ASSUNTO_CURTO_MAX else mensagem[:ASSUNTO_CURTO_MAX - 1] + "…"
    return f"Dashboard Lotufo: alerta de segurança: {curta}"


def assunto_resumo(dia: datetime.date) -> str:
    return f"Dashboard Lotufo: resumo de segurança de {dia:%d/%m/%Y}"


def _marco(conn, agora: datetime.datetime) -> datetime.datetime:
    """O momento em que os alertas comecaram a valer: gravado na primeira rodada com o cadastro configurado."""
    with db.mutacao(conn):
        conn.execute(f"INSERT OR IGNORE INTO {TABELA} (chave, tipo, assunto, criado_em) VALUES ('marco', 'marco', '', ?)",
                     (seguranca._carimbo(agora),))
    r = conn.execute(f"SELECT criado_em FROM {TABELA} WHERE chave='marco'").fetchone()
    return datetime.datetime.fromisoformat(r[0]).replace(tzinfo=datetime.timezone.utc)


def _persistentes() -> set[str]:
    """As mensagens dos problemas que continuam abertos: a conferencia de hora em hora e a do codigo em producao."""
    return {i["mensagem"] for i in seguranca._conferencia + integridade.itens() if i["nivel"] in NIVEIS_IMEDIATOS}


def _grupos(itens: list[dict], persistentes: set[str], marco: datetime.datetime) -> dict[str, dict]:
    """`{chave do grupo: {itens, aberto}}`. `aberto`: a mensagem do problema aberto (a chave sai no envio)."""
    grupos: dict[str, dict] = {}
    for i in sorted(itens, key=lambda i: i["data"]):
        if i["nivel"] not in NIVEIS_IMEDIATOS:
            continue
        if i["mensagem"] in persistentes:
            grupos.setdefault(f"aberto {i['mensagem']}", {"itens": [], "aberto": i["mensagem"]})["itens"].append(i)
            continue
        if datetime.datetime.fromisoformat(i["data"]) < marco:
            continue
        chave = (f"alerta {i['identidade']}" if i.get("identidade")
                 else f"alerta {_local(i['data']):%Y-%m-%d %H} {i['mensagem']}")
        grupos.setdefault(chave, {"itens": [], "aberto": None})["itens"].append(i)
    return grupos


def _saiu_ou_marcada(r) -> bool:
    return r is not None and (r["envio_id"] is not None or r["envio_reservado_em"] is not None
                              or r["envio_conferido_em"] is not None)


def _ja_saiu(conn, chave: str) -> bool:
    """A linha existe e saiu, esta' marcada (envio em curso, incerto ou parado) ou foi conferida como saida."""
    return _saiu_ou_marcada(conn.execute(
        f"SELECT envio_id, envio_reservado_em, envio_conferido_em FROM {TABELA} WHERE chave=?", (chave,)).fetchone())


def _chave_do_episodio(conn, mensagem: str, agora: datetime.datetime) -> str | None:
    """A chave do e-mail do problema aberto: None se o episodio aberto ja' saiu (ou esta' marcado); a do episodio
    aberto que ainda nao saiu (falha antes do envio); ou uma nova."""
    r = conn.execute(f"SELECT chave, envio_id, envio_reservado_em, envio_conferido_em FROM {TABELA} WHERE tipo='alerta' "
                     "AND mensagem=? AND problema_resolvido_em IS NULL ORDER BY id DESC LIMIT 1", (mensagem,)).fetchone()
    if r is None:
        return f"aberto {seguranca._carimbo(agora)} {mensagem}"
    return None if _saiu_ou_marcada(r) else r["chave"]


def _fechar_episodios(conn, persistentes: set[str]) -> None:
    """O problema que sumiu fecha o episodio: se voltar, sai de novo. O do codigo em producao so' fecha quando a
    conferencia diz que esta' igual ao deploy: falha passageira do git (`integridade.ERRO`, nivel atencao) tira o item
    do bloco sem que a diferenca tenha sumido."""
    if time.monotonic() - _INICIO < CARENCIA_SEG:
        return
    codigo_ok = integridade.ESTADO is not None and integridade.ESTADO.get("estado") == integridade.OK
    abertos = [r[0] for r in conn.execute(f"SELECT id, mensagem FROM {TABELA} WHERE tipo='alerta' AND mensagem IS NOT "
                                          "NULL AND problema_resolvido_em IS NULL")
               if r[1] not in persistentes and (codigo_ok or not r[1].startswith(integridade.TITULO_DIFERENTE))]
    if abertos:
        with db.mutacao(conn):
            conn.executemany(f"UPDATE {TABELA} SET problema_resolvido_em=datetime('now') WHERE id=?",
                             [(i,) for i in abertos])


def _reservar(conn, chave: str, tipo: str, assunto: str, usuario_id: int, mensagem: str | None = None) -> int | None:
    """Grava a linha (ou marca a que falhou antes) ANTES do e-mail; None se ja' saiu ou esta' marcada."""
    with db.mutacao(conn):
        r = conn.execute(f"SELECT id, envio_id, envio_reservado_em, envio_conferido_em FROM {TABELA} WHERE chave=?",
                         (chave,)).fetchone()
        if r is None:
            return conn.execute(
                f"INSERT INTO {TABELA} (chave, tipo, assunto, mensagem, envio_reservado_em, envio_reservado_por) "
                "VALUES (?,?,?,?,datetime('now'),?)", (chave, tipo, assunto, mensagem, usuario_id)).lastrowid
        if _saiu_ou_marcada(r):
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


def _gravar_saiu_sem_registro(conn, rid: int) -> None:
    """O e-mail saiu e o registro do envio falhou: grava isso na linha, numa transacao propria (a linha de comando,
    em outro processo, le' daqui para recusar "nao saiu"). Falha fica no log; a proxima rodada tenta de novo."""
    try:
        with db.mutacao(conn):
            conn.execute(f"UPDATE {TABELA} SET envio_saiu_sem_registro_em=datetime('now') WHERE id=? "
                         "AND envio_saiu_sem_registro_em IS NULL", (rid,))
    except Exception:
        log.exception("alerta de seguranca %s ENVIADO e a marca de saida sem registro nao foi gravada", rid)


def _sairam(conn) -> set[int]:
    """As linhas que sairam sem registro e ainda nao foram marcadas como saidas: as deste processo e as do banco."""
    return _SAIRAM | {r[0] for r in conn.execute(
        f"SELECT id FROM {TABELA} WHERE envio_saiu_sem_registro_em IS NOT NULL AND envio_id IS NULL "
        "AND envio_conferido_em IS NULL")}


def _marcar_saida(conn, rid: int, envio_id: int | None = None) -> bool:
    """O e-mail saiu: grava (o envio, quando registrado, ou a conferencia) e solta a marca. False se nao gravou: a
    linha fica em `_SAIRAM` e a proxima rodada tenta de novo."""
    try:
        with db.mutacao(conn):
            if envio_id is not None:
                conn.execute(f"UPDATE {TABELA} SET envio_id=?, envio_reservado_em=NULL, envio_reservado_por=NULL "
                             "WHERE id=?", (envio_id, rid))
            else:
                conn.execute(f"UPDATE {TABELA} SET envio_conferido_em=datetime('now'), envio_reservado_em=NULL, "
                             "envio_reservado_por=NULL WHERE id=?", (rid,))
    except Exception:
        log.exception("alerta de seguranca %s ENVIADO e nao marcado", rid)
        _SAIRAM.add(rid)
        return False
    _SAIRAM.discard(rid)
    return True


def _enviar(conn, usuario: dict, para: list[str], chave: str, tipo: str, assunto: str, corpo: str,
            agora: datetime.datetime, mensagem: str | None = None) -> bool:
    """Um e-mail registrado antes de sair. False: nao saiu (ou saiu incerto), e a rodada para aqui."""
    rid = _reservar(conn, chave, tipo, assunto, usuario["id"], mensagem)
    if rid is None:
        return True
    try:
        envio_id = correio.enviar_e_registrar(conn, usuario, TIPO_ENVIO, para, [], assunto, corpo, [])
    except correio.EnvioIncerto as e:                # pode ter saido ou nao: a marca fica, nada se repete sozinho
        _INCERTOS.add(rid)                           # a Saude le a marca do banco (`situacao`)
        ESTADO["falhou_em"] = agora
        log.critical("alerta de seguranca: envio incerto (%s): %s", assunto, e)
        return False
    except correio.EnvioNaoRegistrado as e:          # SAIU com certeza; so' o registro do envio falhou
        log.critical("alerta de seguranca: enviado e sem registro (%s): %s", assunto, e)
        ESTADO["falhou_em"] = agora                  # banco ocupado: a rodada para e espera
        _SAIRAM.add(rid)                             # ate' gravar, ao menos este processo sabe que saiu
        _gravar_saiu_sem_registro(conn, rid)
        _marcar_saida(conn, rid)
        return False
    except Exception as e:
        _soltar(conn, rid)
        ESTADO["erro"] = f"o último envio falhou ({copia_dono_envio.motivo(e)})"
        ESTADO["falhou_em"] = agora
        log.warning("alerta de seguranca nao enviado (%s): %s", assunto, e)
        return False
    _marcar_saida(conn, rid, envio_id)
    ESTADO["erro"] = None
    ESTADO["falhou_em"] = None
    return True


def _corpo_alerta(itens: list[dict]) -> str:
    return _html(["Alerta de segurança da Dashboard Lotufo:", "", *[_linha(i) for i in itens], "",
                  "Detalhes em Administração > Saúde."])


def _auditoria(conn) -> tuple[int, int | None, str | None]:
    """Total de linhas e a ultima (id e hash), numa leitura so'."""
    r = conn.execute("SELECT (SELECT COUNT(*) FROM audit_log) AS total, "
                     "(SELECT id FROM audit_log ORDER BY id DESC LIMIT 1) AS id, "
                     "(SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1) AS hash").fetchone()
    return r["total"], r["id"], r["hash"]


def _sentinela(conn) -> str:
    """A situacao da sentinela: nao roda neste ambiente, ou quando ela leu o log pela ultima vez (o ponto de leitura
    so' muda quando a rodada avanca no log, o que acontece a cada rodada numa VM com o log ativo)."""
    s = sentinela.situacao()
    if not s.get("roda"):
        return s.get("mensagem") or sentinela.NAO_RODA
    r = conn.execute("SELECT atualizado_em FROM sentinela_ponto WHERE id = 1").fetchone()
    if r is None:
        return "Sentinela: nenhuma leitura do log registrada"
    return f"Sentinela: última leitura do log em {tempo.para_local(datetime.datetime.fromisoformat(r[0])):%d/%m/%Y %H:%M}"


def _dias_sem_resumo(conn, dia: datetime.date) -> str | None:
    """Os dias entre o ultimo resumo que saiu e hoje sem resumo (servidor parado, envio que falhou)."""
    ultimo = conn.execute(f"SELECT MAX(chave) FROM {TABELA} WHERE tipo='resumo' AND chave < ? AND "
                          "(envio_id IS NOT NULL OR envio_conferido_em IS NOT NULL)", (f"resumo {dia}",)).fetchone()[0]
    if ultimo is None:
        return None
    primeiro = datetime.date.fromisoformat(ultimo.split()[1]) + datetime.timedelta(days=1)
    faltam = [primeiro + datetime.timedelta(days=n) for n in range((dia - primeiro).days)]
    if not faltam:
        return None
    if len(faltam) > DIAS_SEM_RESUMO_MAX:
        return f"Sem resumo desde {faltam[0]:%d/%m/%Y} ({len(faltam)} dias)"
    return "Sem resumo em: " + ", ".join(f"{d:%d/%m/%Y}" for d in faltam)


def corpo_resumo(conn, agora: datetime.datetime) -> str:
    """Itens das ultimas 24 horas e os problemas que continuam abertos (a conferencia de hora em hora e a do codigo em
    producao, que guardam a data em que foram vistos primeiro) ou "Nada a relatar", mais o que ancora o estado da VM."""
    dia = tempo.para_local(agora).date()
    desde = agora - JANELA_RESUMO
    itens = [i for i in seguranca.itens(conn, agora) if datetime.datetime.fromisoformat(i["data"]) >= desde]
    abertos = [i for i in seguranca._conferencia + integridade.itens() if i["nivel"] == "critico" and i not in itens]
    itens = sorted(itens + abertos, key=lambda i: i["data"], reverse=True)
    linhas = [f"Resumo de segurança da Dashboard Lotufo de {dia:%d/%m/%Y} (últimas 24 horas).", ""]
    linhas += [_linha(i) for i in itens] if itens else ["Nada a relatar."]
    linhas.append("")
    faltam = _dias_sem_resumo(conn, dia)
    if faltam:
        linhas.append(faltam)
    linhas.append(f"Commit em produção: {integridade.commit_atual() or 'não identificado'}")
    ultima = copia_dono.ultima_copia(backup.pasta_local())
    linhas.append(f"Última cópia do dono: {tempo.para_local(ultima):%d/%m/%Y %H:%M}" if ultima is not None
                  else "Última cópia do dono: nenhuma encontrada")
    linhas.append(_sentinela(conn))
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
        marco = _marco(conn, agora)
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
    for rid in sorted(_sairam(conn)):               # saiu e nao foi marcado: tenta de novo antes de tudo
        if rid in _SAIRAM:
            _gravar_saiu_sem_registro(conn, rid)
        if not _marcar_saida(conn, rid):
            return []
    persistentes = _persistentes()
    _fechar_episodios(conn, persistentes)
    enviados = []
    for chave, g in _grupos(seguranca.itens(conn, agora), persistentes, marco).items():
        if g["aberto"] is not None:
            chave = _chave_do_episodio(conn, g["aberto"], agora)
            if chave is None:
                continue
        elif _ja_saiu(conn, chave):
            continue
        itens = g["itens"]
        assunto = assunto_alerta(itens[-1]["mensagem"])
        if not _enviar(conn, usuario, config["para"], chave, "alerta", assunto, _corpo_alerta(itens), agora,
                       g["aberto"]):
            return enviados
        enviados.append(assunto)
    local = tempo.para_local(agora)
    chave = f"resumo {local.date().isoformat()}"
    if local.hour >= HORA_RESUMO and not _ja_saiu(conn, chave):
        assunto = assunto_resumo(local.date())
        if _enviar(conn, usuario, config["para"], chave, "resumo", assunto, corpo_resumo(conn, agora), agora):
            enviados.append(assunto)
    return enviados


def _paradas(conn) -> list:
    """Marcas de envio paradas (mais de `PRESA_MIN`, ou incertas neste processo; sem envio registrado e sem
    conferencia), sem prazo: ficam na Saude ate' uma pessoa registrar o resultado."""
    return [r for r in conn.execute(
        f"SELECT id, assunto, envio_reservado_em <= datetime('now', ?) AS velha FROM {TABELA} WHERE envio_id IS NULL "
        "AND envio_conferido_em IS NULL AND envio_saiu_sem_registro_em IS NULL AND envio_reservado_em IS NOT NULL "
        "ORDER BY id", (f"-{PRESA_MIN} minutes",))
        if r["id"] not in _SAIRAM and (r["velha"] or r["id"] in _INCERTOS)]


def situacao(conn) -> dict:
    """O que a Saude mostra: `{erro, conectar}`. `erro`: por que nada sai (lido agora do cadastro e da conta), os
    e-mails que podem nao ter saido e a falha do ultimo envio; None quando esta' tudo certo (ou no modo copia, em que
    o envio ja' e' recusado). `conectar`: a conta Microsoft de quem envia precisa ser conectada (Minha conta)."""
    if not instalacao.ligada():
        return {"erro": None, "conectar": False}
    partes, conectar = [], False
    try:
        _remetente(conn, _config(conn))
    except NaoConfigurado as e:
        partes.append(str(e))
        conectar = e.conectar
    for r in _paradas(conn):
        partes.append(f"o e-mail nº {r['id']} pode não ter saído ({r['assunto']}); confira os Enviados de quem envia "
                      "e registre o resultado no servidor")
    for rid in sorted(_sairam(conn)):
        partes.append(f"o e-mail nº {rid} saiu sem registro; não registre que ele não saiu")
    if not partes and ESTADO["erro"]:
        partes.append(ESTADO["erro"])
    return {"erro": "; ".join(partes) or None, "conectar": conectar}


def _ainda_sai(conn, id_: int) -> bool | None:
    """Depois de "nao saiu": a linha vai sair de novo? True: o resumo de hoje, ou o alerta cujo item continua no bloco.
    False: resumo de dia passado, episodio fechado ou item que ja' saiu do bloco. None: problema aberto, que depende
    da conferencia do servidor (este processo, o da linha de comando, nao a ve)."""
    r = conn.execute(f"SELECT chave, tipo, mensagem, problema_resolvido_em FROM {TABELA} WHERE id=?", (id_,)).fetchone()
    agora = tempo.agora_utc()
    if r["tipo"] == "resumo":
        return r["chave"] == f"resumo {tempo.para_local(agora).date().isoformat()}"
    if r["mensagem"] is not None:
        return None if r["problema_resolvido_em"] is None else False
    m = conn.execute(f"SELECT criado_em FROM {TABELA} WHERE chave='marco'").fetchone()
    marco = (datetime.datetime.fromisoformat(m[0]).replace(tzinfo=datetime.timezone.utc) if m
             else datetime.datetime.min.replace(tzinfo=datetime.timezone.utc))
    return r["chave"] in _grupos(seguranca.itens(conn, agora), set(), marco)


def conferir_envio(conn, usuario_id: int, id_: int, saiu: bool) -> bool | None:
    """Uma pessoa conferiu os Enviados de quem envia e registra o resultado do e-mail parado (`_paradas`): saiu (fica
    como enviado, nao se repete) ou nao saiu (a marca solta e a proxima rodada manda, se o item continuar). Auditado.
    Devolve, no "nao saiu", se o e-mail vai sair de novo (`_ainda_sai`); no "saiu", None. O e-mail que saiu com
    certeza e ficou sem registro (`envio_saiu_sem_registro_em` no banco, ou `_SAIRAM` quando nem isso gravou) nao
    aceita "nao saiu"."""
    if not saiu and id_ in _SAIRAM:
        raise ValueError(SAIU_SEM_REGISTRO)
    with db.mutacao(conn):
        r = conn.execute(f"SELECT assunto, envio_id, envio_reservado_em, envio_conferido_em, envio_saiu_sem_registro_em, "
                         f"envio_reservado_em <= datetime('now', ?) AS parada FROM {TABELA} WHERE id=?",
                         (f"-{PRESA_MIN} minutes", id_)).fetchone()
        if r is None or r["envio_id"] is not None or r["envio_conferido_em"] is not None or r["envio_reservado_em"] is None:
            raise ValueError("Este e-mail não está parado")
        if not saiu and r["envio_saiu_sem_registro_em"] is not None:
            raise ValueError(SAIU_SEM_REGISTRO)
        if not r["parada"]:
            raise ValueError(f"Envio iniciado há menos de {PRESA_MIN} minutos: pode ainda estar saindo")
        if saiu:
            conn.execute(f"UPDATE {TABELA} SET envio_conferido_em=datetime('now'), envio_conferido_por=?, "
                         "envio_reservado_em=NULL, envio_reservado_por=NULL WHERE id=?", (usuario_id, id_))
        else:
            conn.execute(f"UPDATE {TABELA} SET envio_reservado_em=NULL, envio_reservado_por=NULL WHERE id=?", (id_,))
        auditoria.registrar(conn, usuario_id, "seguranca.alerta_envio_conferido", "alerta_seguranca_envio", id_, None,
                            {"assunto": r["assunto"], "saiu": saiu})
    _SAIRAM.discard(id_)
    return None if saiu else _ainda_sai(conn, id_)


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
