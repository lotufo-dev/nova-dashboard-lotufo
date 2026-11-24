"""Decisoes das licitacoes (fatia 2 da #906, docs/adr/0018): o corte e o que as pessoas decidem pela tela.

Ate' o corte as decisoes sao espelho do radar e nada aqui grava (`Recusa`). O corte e' um ato so', do administrador,
pela linha de comando; dali em diante so' a dashboard grava decisao, e o radar busca (`para_o_radar`). Cada decisao
grava quem fez e quando e sai na auditoria com o que valia antes. Nada se apaga.
"""
import json
import re

from app import auditoria, db, licitacoes, tempo

MOTIVOS_DESCARTE = ("tipo de obra", "local", "valor", "órgão", "outro")
ETAPA_DA_ANALISE = "em_analise"
COMANDO_ANALISAR = "/analisar-edital"
# so' um endereco http(s) inteiro, sem espaco nem quebra de linha: o comando e' colado numa sessao de trabalho, e um
# texto estranho vindo de uma fonte nao pode virar instrucao
_LINK = re.compile(r"https?://[^\s\x00-\x1f\x7f]{1,2000}")

DECISOES_NO_RADAR = "As decisões ainda estão com o radar: o corte das licitações não foi feito"
LICITACAO_INEXISTENTE = "Licitação não encontrada"
JA_FAVORITA = "Esta licitação já é favorita"
JA_DECIDIDA = "Esta licitação acabou de ser decidida por outra pessoa: atualize a página"
NAO_FAVORITA = "Esta licitação não é favorita"
ETAPA_DO_DOSSIE = "A etapa desta licitação vem do dossiê e não se muda pela tela"
ETAPA_INVALIDA = "Escolha a etapa da licitação"
MOTIVO_INVALIDO = "Escolha o motivo do descarte"
FAVORITA_NAO_SE_DESCARTA = "Favorita não se descarta: tire a favorita"
JA_DESCARTADA = "Esta licitação já foi descartada"
NAO_DESCARTADA = "Esta licitação não está descartada"
SEM_MUDANCA_NOVA = "Esta favorita não tem mudança nova"
SEM_LINK = "Esta licitação não tem link de edital: baixe o edital e passe o arquivo ao comando"


class Recusa(Exception):
    """A decisao nao cabe no estado em que a licitacao esta' (a rota responde 409)."""


def _agora() -> str:
    """O carimbo das decisoes, em UTC, no formato do banco: o mesmo relogio que decide o dia da favorita."""
    return tempo.agora_utc().strftime("%Y-%m-%d %H:%M:%S")


# --- o corte ---------------------------------------------------------------------------------------------------

def corte(conn, usuario_id: int, ensaio: bool = False) -> dict:
    """Passa as decisoes do radar para a dashboard. Um ato so': o segundo nao muda a data. `ensaio` nao grava."""
    with db.mutacao(conn):
        feito_em = licitacoes.corte_em(conn)
        passam = {
            "favoritas": conn.execute("SELECT COUNT(*) FROM lic_favoritas WHERE removida_em IS NULL").fetchone()[0],
            "descartadas": conn.execute("SELECT COUNT(*) FROM lic_descartes WHERE desfeito_em IS NULL").fetchone()[0]}
        if feito_em is None and not ensaio:
            conn.execute("UPDATE lic_estado SET corte_em=?, corte_por=? WHERE id=1", (_agora(), usuario_id))
            auditoria.registrar(conn, usuario_id, "licitacoes.corte", "licitacoes", None, None, passam)
        return {"ja_feito_em": feito_em, "ensaio": ensaio, **passam}


def _exigir_corte(conn) -> None:
    if licitacoes.corte_em(conn) is None:
        raise Recusa(DECISOES_NO_RADAR)


# --- as decisoes -------------------------------------------------------------------------------------------------

def _certame(conn, certame_id: int):
    c = conn.execute("SELECT id, chave, dados FROM lic_certames WHERE id=?", (certame_id,)).fetchone()
    if c is None:
        raise LookupError(LICITACAO_INEXISTENTE)
    return c


def _favorita(conn, chave: str):
    return conn.execute("SELECT id, desde, etapa, mudancas_vistas_ate FROM lic_favoritas "
                        "WHERE chave=? AND removida_em IS NULL", (chave,)).fetchone()


def _descarte(conn, chave: str):
    return conn.execute("SELECT id, motivo FROM lic_descartes WHERE chave=? AND desfeito_em IS NULL",
                        (chave,)).fetchone()


def _criar_favorita(conn, usuario_id: int, c, etapa: str | None) -> None:
    """Favorita com o dia de hoje (Cuiaba). Favoritar uma descartada desfaz o descarte."""
    agora = _agora()
    conn.execute("INSERT INTO lic_favoritas (chave, desde, etapa, etapa_em, origem, criada_por, criada_em) "
                 "VALUES (?,?,?,?,'dashboard',?,?)",
                 (c["chave"], tempo.hoje_local().isoformat(), etapa, agora if etapa else None, usuario_id, agora))
    descarte = _descarte(conn, c["chave"])
    if descarte is not None:
        conn.execute("UPDATE lic_descartes SET desfeito_em=?, desfeito_por=? WHERE id=?",
                     (agora, usuario_id, descarte["id"]))
    auditoria.registrar(conn, usuario_id, "licitacoes.favorita", "licitacao", c["id"],
                        {"descartada": descarte["motivo"]} if descarte is not None else None,
                        {"chave": c["chave"], "etapa": etapa})


def favoritar(conn, usuario_id: int, certame_id: int) -> None:
    with db.mutacao(conn):
        _exigir_corte(conn)
        c = _certame(conn, certame_id)
        if _favorita(conn, c["chave"]) is not None:
            raise Recusa(JA_FAVORITA)
        _criar_favorita(conn, usuario_id, c, None)


def remover_favorita(conn, usuario_id: int, certame_id: int) -> None:
    """Tira a favorita: a linha fica, com a data e o autor."""
    with db.mutacao(conn):
        _exigir_corte(conn)
        c = _certame(conn, certame_id)
        fav = _favorita(conn, c["chave"])
        if fav is None:
            raise Recusa(NAO_FAVORITA)
        conn.execute("UPDATE lic_favoritas SET removida_em=?, removida_por=? WHERE id=?",
                     (_agora(), usuario_id, fav["id"]))
        auditoria.registrar(conn, usuario_id, "licitacoes.favorita.remover", "licitacao", c["id"],
                            {"chave": c["chave"], "desde": fav["desde"], "etapa": fav["etapa"]}, None)


def _etapa_do_dossie(c) -> str | None:
    return (json.loads(c["dados"]).get("dossie") or {}).get("etapa")


def mudar_etapa(conn, usuario_id: int, certame_id: int, etapa: str) -> None:
    """Etapa da favorita sem etapa de dossie. Com dossie, a etapa vem dele (pelo radar) e nao se muda aqui."""
    if etapa not in licitacoes.ROTULO_ETAPA:
        raise ValueError(ETAPA_INVALIDA)
    with db.mutacao(conn):
        _exigir_corte(conn)
        c = _certame(conn, certame_id)
        fav = _favorita(conn, c["chave"])
        if fav is None:
            raise Recusa(NAO_FAVORITA)
        if _etapa_do_dossie(c):
            raise Recusa(ETAPA_DO_DOSSIE)
        if fav["etapa"] == etapa:
            return
        conn.execute("UPDATE lic_favoritas SET etapa=?, etapa_em=? WHERE id=?", (etapa, _agora(), fav["id"]))
        auditoria.registrar(conn, usuario_id, "licitacoes.etapa", "licitacao", c["id"],
                            {"etapa": fav["etapa"]}, {"etapa": etapa})


def descartar(conn, usuario_id: int, certame_id: int, motivo: str) -> None:
    if motivo not in MOTIVOS_DESCARTE:
        raise ValueError(MOTIVO_INVALIDO)
    with db.mutacao(conn):
        _exigir_corte(conn)
        c = _certame(conn, certame_id)
        if _favorita(conn, c["chave"]) is not None:
            raise Recusa(FAVORITA_NAO_SE_DESCARTA)
        if _descarte(conn, c["chave"]) is not None:
            raise Recusa(JA_DESCARTADA)
        conn.execute("INSERT INTO lic_descartes (chave, motivo, origem, criado_por, criado_em) "
                     "VALUES (?,?,'dashboard',?,?)", (c["chave"], motivo, usuario_id, _agora()))
        auditoria.registrar(conn, usuario_id, "licitacoes.descarte", "licitacao", c["id"], None,
                            {"chave": c["chave"], "motivo": motivo})


def desfazer_descarte(conn, usuario_id: int, certame_id: int) -> None:
    with db.mutacao(conn):
        _exigir_corte(conn)
        c = _certame(conn, certame_id)
        descarte = _descarte(conn, c["chave"])
        if descarte is None:
            raise Recusa(NAO_DESCARTADA)
        conn.execute("UPDATE lic_descartes SET desfeito_em=?, desfeito_por=? WHERE id=?",
                     (_agora(), usuario_id, descarte["id"]))
        auditoria.registrar(conn, usuario_id, "licitacoes.descarte.desfazer", "licitacao", c["id"],
                            {"chave": c["chave"], "motivo": descarte["motivo"]}, None)


def analisar(conn, usuario_id: int, certame_id: int) -> dict:
    """Pede a analise do edital: favorita, se ainda nao e'; sem etapa de dossie, poe em "Em analise"; devolve o
    comando para colar na sessao de analise. A analise em si acontece fora da dashboard."""
    with db.mutacao(conn):
        _exigir_corte(conn)
        c = _certame(conn, certame_id)
        do_dossie = _etapa_do_dossie(c)
        fav = _favorita(conn, c["chave"])
        favoritou = fav is None
        if favoritou:
            _criar_favorita(conn, usuario_id, c, None if do_dossie else ETAPA_DA_ANALISE)
        elif not do_dossie and fav["etapa"] != ETAPA_DA_ANALISE:
            conn.execute("UPDATE lic_favoritas SET etapa=?, etapa_em=? WHERE id=?",
                         (ETAPA_DA_ANALISE, _agora(), fav["id"]))
            auditoria.registrar(conn, usuario_id, "licitacoes.etapa", "licitacao", c["id"],
                                {"etapa": fav["etapa"]}, {"etapa": ETAPA_DA_ANALISE})
    link = (json.loads(c["dados"]).get("link") or "").strip()
    tem_link = bool(_LINK.fullmatch(link))
    return {"favoritou": favoritou, "comando": f"{COMANDO_ANALISAR} {link}" if tem_link else COMANDO_ANALISAR,
            "aviso": None if tem_link else SEM_LINK}


def marcar_mudancas_vistas(conn, usuario_id: int, certame_id: int) -> None:
    """Grava a data da mudanca mais recente da favorita: as mudancas ate' ela deixam de po-la na Triagem."""
    with db.mutacao(conn):
        _exigir_corte(conn)
        c = _certame(conn, certame_id)
        fav = _favorita(conn, c["chave"])
        if fav is None:
            raise Recusa(NAO_FAVORITA)
        novas = [m["data"] for m in licitacoes.mudancas(json.loads(c["dados"]), fav) if not m["vista"]]
        if not novas:
            raise Recusa(SEM_MUDANCA_NOVA)
        conn.execute("UPDATE lic_favoritas SET mudancas_vistas_ate=? WHERE id=?", (max(novas), fav["id"]))
        auditoria.registrar(conn, usuario_id, "licitacoes.mudancas_vistas", "licitacao", c["id"],
                            {"ate": fav["mudancas_vistas_ate"]}, {"ate": max(novas)})


# --- o que o radar busca depois do corte ---------------------------------------------------------------------------

def para_o_radar(conn) -> dict:
    """As decisoes em vigor, para o radar juntar os repetidos e avisar por e-mail como sempre fez."""
    favoritas = [{"chave": r["chave"], "desde": r["desde"], "etapa": r["etapa"], "autor": r["nome"] or r["autor_radar"]}
                 for r in conn.execute(
                     "SELECT f.chave, f.desde, f.etapa, f.autor_radar, u.nome FROM lic_favoritas f "
                     "LEFT JOIN usuarios u ON u.id=f.criada_por WHERE f.removida_em IS NULL ORDER BY f.id")]
    descartadas = [{"chave": r["chave"], "motivo": r["motivo"], "quando": tempo.iso_utc(r["criado_em"]),
                    "autor": r["nome"] or r["autor_radar"]}
                   for r in conn.execute(
                       "SELECT d.chave, d.motivo, d.criado_em, d.autor_radar, u.nome FROM lic_descartes d "
                       "LEFT JOIN usuarios u ON u.id=d.criado_por WHERE d.desfeito_em IS NULL ORDER BY d.id")]
    return {"corte_em": tempo.iso_utc(licitacoes.corte_em(conn)) if licitacoes.corte_em(conn) else None,
            "favoritas": favoritas, "descartadas": descartadas}
