"""Cobranca de certidao por e-mail (plano 2026-10-09; regra da issue #665, decisao do dono de 10/11/2026).

No maximo um e-mail por dia util (segunda a sexta, fora feriado de `feriados.py`), na primeira rodada a partir das
08:00 (Cuiaba), so' com a lista "Renovar agora" (`documentos.renovar_agora`: certidao vencida, nunca anexada ou que
vence ate' o proximo protocolo previsto). Lista vazia nao gera e-mail. O dia e' reservado em
`cobranca_certidoes_envios` ANTES de o e-mail sair (motivo `renovar AAAA-MM-DD`), entao reinicio do servidor ou duas
rodadas juntas nao repetem; a reserva so' e' desfeita quando o e-mail com certeza nao saiu.

Destinatario e logins de quem envia vem do cadastro (geral.yaml, `cobranca_certidoes`, issue #110); sem eles, ou sem
conta Microsoft conectada, so' registra no log. `listas` continua servindo a tela Inicio e nao decide mais o e-mail.
"""
import datetime
import json
import logging
import threading
import time
from html import escape

from app import correio, db, documentos, entidades, feriados, graph, tempo

log = logging.getLogger("app.cobranca_certidoes")

INICIO = 8
DIAS_VENCENDO = 15
INTERVALO_SEG = 600


def listas(conn, hoje: datetime.date) -> tuple[list[dict], list[dict]]:
    """(vencidas, vencendo em ate' 15 dias) das certidoes exigidas pelos contratos ativos."""
    cert, _, _, _ = documentos._exigidos_ativos(conn)
    vencidas, vencendo = [], []
    for eid in sorted(cert):
        e = entidades.detalhe(conn, eid)
        if e is None or not e["ativo"]:
            continue
        for t in sorted(cert[eid].values(), key=lambda t: t["id"]):
            s = documentos.situacao(conn, eid, t, hoje)
            linha = {"entidade_id": eid, "entidade": e.get("nome_curto") or e["nome"], "tipo_id": t["id"],
                     "tipo": t["nome"], "validade": (s["certidao"] or {}).get("validade"),
                     "link": t.get("link_emissao"), "dias": s["dias"]}
            if s["situacao"] == "vencida":
                vencidas.append(linha)
            elif s["situacao"] in ("ok", "vencendo") and s["dias"] <= DIAS_VENCENDO:
                vencendo.append(linha)
    return vencidas, vencendo


def _data(iso: str) -> str:
    return datetime.date.fromisoformat(iso[:10]).strftime("%d/%m/%Y")


def _corpo(itens: list[dict]) -> str:
    linhas = ["Certidões a renovar para o próximo protocolo:", ""]
    for x in itens:
        if x["situacao"] == "faltando":
            estado = "nunca anexada"
        elif x["situacao"] == "vencida":
            estado = f"vencida em {_data(x['validade'])}"
        else:
            estado = f"vence em {_data(x['validade'])}"
        linhas.append(f"- {x['entidade']} — {x['tipo']} — {estado}"
                      + (f" — próximo protocolo previsto para {_data(x['proximo_protocolo'])}"
                         if x["proximo_protocolo"] else "")
                      + (f" — emitir em: {x['link_emissao']}" if x["link_emissao"] else ""))
    return "".join(f"<p>{escape(l)}</p>" if l else "<p>&nbsp;</p>" for l in linhas)


def _config(conn) -> dict | None:
    r = conn.execute("SELECT valor FROM cadastro_geral WHERE chave='cobranca_certidoes'").fetchone()
    return json.loads(r["valor"]) if r else None


def _usuario(conn, logins: list[str]) -> dict | None:
    marcas = ",".join("?" * len(logins))
    r = conn.execute(f"SELECT id, email FROM usuarios WHERE ativo=1 AND lower(email) IN ({marcas}) ORDER BY id LIMIT 1",
                     logins).fetchone()
    return {"id": r["id"], "email": r["email"]} if r else None


def _motivo(dia: datetime.date) -> str:
    return f"renovar {dia.isoformat()}"


def _ja_saiu(conn, motivo: str) -> bool:
    return conn.execute("SELECT 1 FROM cobranca_certidoes_envios WHERE motivo=? LIMIT 1", (motivo,)).fetchone() is not None


def _reservar(conn, motivo: str, itens: list[dict]) -> bool:
    """Marca o dia como cobrado antes de o e-mail sair. A conferencia e a gravacao vao na mesma transacao de escrita
    (BEGIN IMMEDIATE): de duas rodadas juntas, so' uma reserva."""
    with db.mutacao(conn):
        if _ja_saiu(conn, motivo):
            return False
        conn.executemany("INSERT INTO cobranca_certidoes_envios (certidao_tipo, entidade_id, motivo) VALUES (?,?,?)",
                         [(x["tipo_id"], x["entidade_id"], motivo) for x in itens])
    return True


def _liberar(conn, motivo: str) -> None:
    with db.mutacao(conn):
        conn.execute("DELETE FROM cobranca_certidoes_envios WHERE motivo=?", (motivo,))


def _enviar(conn, motivo: str, assunto: str, corpo: str, itens: list[dict]) -> bool:
    config = _config(conn)
    if config is None:
        log.warning("cobranca de certidoes sem destinatario no cadastro (geral.yaml): %s", assunto)
        return False
    usuario = _usuario(conn, config["enviada_por"])
    if usuario is None:
        log.warning("cobranca de certidoes sem usuario ativo com o login do cadastro: %s", assunto)
        return False
    if not _reservar(conn, motivo, itens):
        return False
    try:
        correio.enviar_e_registrar(conn, usuario, "cobranca_certidoes", config["para"], [], assunto, corpo, [])
    except correio.EnvioNaoRegistrado as e:
        # O e-mail saiu (ou pode ter saido) sem registro: a reserva fica, para o dia nao ganhar um segundo e-mail.
        log.error("cobranca de certidoes sem registro do envio, nao sera repetida hoje (%s): %s", assunto, e)
        return False
    except (graph.ErroGraph, RuntimeError) as e:
        _liberar(conn, motivo)                                      # com certeza nao saiu: a proxima rodada tenta
        log.warning("cobranca de certidoes nao enviada (%s): %s", assunto, e)
        return False
    except BaseException:
        _liberar(conn, motivo)                                      # recusa antes do envio (ex.: instalacao)
        raise
    return True


def rodada(conn, agora_local: datetime.datetime) -> list[str]:
    """Uma passada do job, com a data e a hora locais de quem chama; devolve os assuntos enviados (um ou nenhum)."""
    hoje = agora_local.date()
    if agora_local.hour < INICIO or not feriados.dia_util(hoje):
        return []
    motivo = _motivo(hoje)
    if _ja_saiu(conn, motivo):                                      # um por dia; o controle esta' no banco
        return []
    itens = documentos.renovar_agora(conn, hoje)
    if not itens:
        return []
    assunto = f"Certidões a renovar ({len(itens)})"
    return [assunto] if _enviar(conn, motivo, assunto, _corpo(itens), itens) else []


def agendar(intervalo_seg: int = INTERVALO_SEG) -> threading.Thread:
    def loop():
        while True:
            try:
                conn = db.get_conn()
                try:
                    rodada(conn, tempo.para_local(tempo.agora_utc()))
                finally:
                    conn.close()
            except Exception:
                log.exception("rodada da cobranca de certidoes falhou")
            time.sleep(intervalo_seg)

    t = threading.Thread(target=loop, name="cobranca-certidoes", daemon=True)
    t.start()
    return t
