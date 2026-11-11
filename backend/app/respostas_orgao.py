"""Respostas do orgao lidas da conversa da planilha/carta enviada (issue #644, regra decidida em 10/11/2026).

O sistema le SO' a conversa que ele mesmo enviou. Aqui se decide QUAIS conversas: as dos envios da planilha/carta
(`medicao_planilha_envios`) feitos pela propria pessoa logada, com a conversa gravada (`envios.conversa_id`), de
medicoes ainda abertas. A leitura usa a conta Microsoft dela (`correio.cliente`) e so' acontece quando a tela dela
chama (ao entrar e a cada 5 minutos): nao ha' job, nao ha' conta de servico e nada e' lido para quem nao envia.
Como o Graph e' consultado mora em `correio.py` (`consulta_da_conversa`).

Cada mensagem da conversa que nao e' de quem enviou vira uma linha em `medicao_respostas_orgao`: remetente, data e
hora, assunto, trecho inicial (ate' 500 caracteres) e nomes dos anexos. O corpo inteiro e os anexos nao sao gravados.
"""
import json
import logging

from app import auditoria, correio, db, graph

log = logging.getLogger("app.respostas_orgao")

TRECHO_MAX = 500
ESTADOS_FECHADOS = ("recebida", "cancelada", "desistida")
_CAMPOS = "id, medicao_id, envio_id, remetente, remetente_nome, recebida_em, assunto, trecho, anexos, criado_em"


def _linha(r) -> dict:
    d = dict(r)
    try:
        d["anexos"] = [str(x) for x in json.loads(d["anexos"] or "[]")]
    except ValueError:
        d["anexos"] = []
    return d


def da_medicao(conn, medicao_id: int) -> list[dict]:
    """As respostas registradas da medicao, da mais nova para a mais antiga."""
    return [_linha(r) for r in conn.execute(
        f"SELECT {_CAMPOS} FROM medicao_respostas_orgao WHERE medicao_id=? ORDER BY recebida_em DESC, id DESC",
        (medicao_id,))]


def conversas_a_ler(conn, usuario_id: int) -> list[dict]:
    """Os envios cuja conversa a pessoa logada pode ler: os DELA, da planilha/carta, com conversa gravada, de medicao
    que nao foi recebida, cancelada nem desistida."""
    marcas = ",".join("?" * len(ESTADOS_FECHADOS))
    return [dict(r) for r in conn.execute(
        "SELECT e.id AS envio_id, e.conversa_id, e.remetente, pe.medicao_id FROM medicao_planilha_envios pe "
        "JOIN envios e ON e.id=pe.envio_id JOIN medicoes m ON m.id=pe.medicao_id "
        "WHERE e.usuario_id=? AND e.conversa_id IS NOT NULL AND e.conversa_id<>'' "
        f"AND m.estado NOT IN ({marcas}) ORDER BY e.id", (usuario_id, *ESTADOS_FECHADOS))]


def _pode_ler(usuario_id: int) -> bool:
    cfg = correio.configuracao()
    return bool(cfg["simulador"]) or bool(cfg["client_id"] and correio.conectado(usuario_id))


def ler(conn, usuario: dict) -> list[dict]:
    """Le as conversas de `conversas_a_ler` e registra as respostas novas; devolve as registradas agora. Sem conta
    Microsoft conectada, sem envio a ler ou com o Graph fora do ar: lista vazia, sem erro (a tela chama sozinha)."""
    if not _pode_ler(usuario["id"]):
        return []
    envios = conversas_a_ler(conn, usuario["id"])
    if not envios:
        return []
    try:
        c = correio.cliente(usuario["id"], usuario.get("email", ""))
    except graph.ErroGraph as e:
        log.info("leitura das respostas indisponivel para o usuario %s: %s", usuario["id"], e)
        return []
    proprias = {(usuario.get("email") or "").lower()} | correio.contas_do_usuario(conn, usuario.get("email") or "")
    novas = []
    for envio in envios:
        try:
            mensagens = c.mensagens_da_conversa(envio["conversa_id"])
        except (graph.ErroGraph, ValueError) as e:
            log.info("conversa do envio %s nao foi lida: %s", envio["envio_id"], e)
            if isinstance(e, graph.ErroGraph) and e.status is None:
                break       # sem resposta do Graph (rede, token): nao insiste nas outras conversas; a tela chama de novo
            continue
        for msg in mensagens:
            de = msg["de"]
            if (not msg["id"] or not de or not msg["recebida_em"] or de in proprias
                    or de == (envio["remetente"] or "").lower()):
                continue
            if conn.execute("SELECT 1 FROM medicao_respostas_orgao WHERE mensagem_id=?", (msg["id"],)).fetchone():
                continue
            try:
                anexos = c.anexos_da_mensagem(msg)
            except (graph.ErroGraph, ValueError) as e:      # fica para a proxima leitura, com os nomes
                log.info("anexos da resposta do envio %s nao foram lidos: %s", envio["envio_id"], e)
                continue
            trecho = " ".join(msg["texto"].split())[:TRECHO_MAX]
            with db.mutacao(conn):
                cur = conn.execute(
                    "INSERT OR IGNORE INTO medicao_respostas_orgao (medicao_id, envio_id, mensagem_id, remetente, "
                    "remetente_nome, recebida_em, assunto, trecho, anexos, lida_por) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (envio["medicao_id"], envio["envio_id"], msg["id"], de, msg["nome"], msg["recebida_em"],
                     msg["assunto"][:300], trecho, json.dumps(anexos, ensure_ascii=False), usuario["id"]))
                if not cur.rowcount:        # outra leitura registrou no meio: a mesma mensagem nao entra duas vezes
                    continue
                auditoria.registrar(conn, usuario["id"], "medicao.resposta_orgao", "medicao", envio["medicao_id"],
                                    None, {"resposta_id": cur.lastrowid, "envio_id": envio["envio_id"],
                                           "mensagem_id": msg["id"], "remetente": de,
                                           "recebida_em": msg["recebida_em"], "assunto": msg["assunto"][:300],
                                           "anexos": anexos})
                rid = cur.lastrowid
            novas.append(_linha(conn.execute(f"SELECT {_CAMPOS} FROM medicao_respostas_orgao WHERE id=?",
                                             (rid,)).fetchone()))
    return novas
