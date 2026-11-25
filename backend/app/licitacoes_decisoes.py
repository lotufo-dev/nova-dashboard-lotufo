"""Decisoes das licitacoes (fatia 2 da #906, docs/adr/0018): o corte e o que as pessoas decidem pela tela.

Ate' o corte as decisoes sao espelho do radar e nada aqui grava (`Recusa`). O corte e' um ato so', do administrador,
pela linha de comando; dali em diante so' a dashboard grava decisao, e o radar busca (`para_o_radar`). Cada decisao
grava quem fez e quando e sai na auditoria com o que valia antes. Nada se apaga.
"""
import datetime
import json
import re

from app import auditoria, db, licitacoes, tempo

MOTIVOS_DESCARTE = ("tipo de obra", "local", "valor", "órgão", "outro")
ETAPA_DA_ANALISE = "em_analise"
COMANDO_ANALISAR = "/analisar-edital"
# so' um endereco http(s) inteiro, escrito com as letras, os digitos e a pontuacao comum de endereco: o comando e'
# colado num terminal, e um texto estranho vindo de uma fonte nao pode virar instrucao. Fica de fora tudo o que um
# terminal interpreta (; | & $ ( ) { } crase, aspas, < > \ ! *), espaco e qualquer caractere que nao seja ASCII
# (inclusive os invisiveis). O link que nao passa vai sem ele, com o aviso de baixar o edital
_LINK = re.compile(r"https?://[A-Za-z0-9._~:/?#@+,=%-]{1,2000}")

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
CORTE_SEM_ESTADO = "O corte não foi gravado: falta a linha de estado das licitações (rode as migrações)"


def motivos_de_descarte() -> list[dict]:
    """Os motivos que a tela oferece ao descartar, na ordem, com o rotulo."""
    return [{"motivo": m, "rotulo": m[0].upper() + m[1:]} for m in MOTIVOS_DESCARTE]


class Recusa(Exception):
    """A decisao nao cabe no estado em que a licitacao esta' (a rota responde 409)."""


class NaoEncontrada(Exception):
    """A licitacao pedida nao existe (a rota responde 404)."""


class ForaDaLista(Exception):
    """O valor mandado nao e' um dos que a decisao aceita: etapa ou motivo (a rota responde 422)."""


class _Ensaio(Exception):
    """Desfaz o que o ensaio do corte gravou para poder contar."""


def _agora() -> str:
    """O carimbo das decisoes, em UTC, no formato do banco: o mesmo relogio que decide o dia da favorita."""
    return tempo.agora_utc().strftime("%Y-%m-%d %H:%M:%S")


# --- o corte ---------------------------------------------------------------------------------------------------

def _ver_as_mudancas_antigas(conn) -> None:
    """No corte, as mudancas com mais de 7 dias de cada favorita ativa entram como vistas: e' a regra que valia ate'
    ali (`licitacoes.MUDANCA_RECENTE`), para a Triagem do dia seguinte ter as mesmas favoritas da vespera. Sem isso
    toda mudanca antiga das favoritas espelhadas do radar viraria "nao vista" de uma vez."""
    recente = (tempo.hoje_local() - datetime.timedelta(days=licitacoes.MUDANCA_RECENTE)).isoformat()
    for f in conn.execute("SELECT f.id, f.desde, f.mudancas_vistas, c.dados FROM lic_favoritas f "
                          "JOIN lic_certames c ON c.chave=f.chave WHERE f.removida_em IS NULL").fetchall():
        antigas = [m["chave"] for m in licitacoes.mudancas(json.loads(f["dados"]), f)
                   if not m["vista"] and m["data"] < recente]
        if antigas:
            conn.execute("UPDATE lic_favoritas SET mudancas_vistas=? WHERE id=?",
                         (json.dumps(sorted(set(json.loads(f["mudancas_vistas"])) | set(antigas))), f["id"]))


def corte(conn, usuario_id: int, ensaio: bool = False) -> dict:
    """Passa as decisoes do radar para a dashboard. Um ato so': o segundo nao muda a data. `ensaio` nao grava: faz
    tudo, conta e desfaz. `pedem_atencao`: quantas favoritas ficam na Triagem depois do corte."""
    rel: dict = {}
    try:
        with db.mutacao(conn):
            feito_em = licitacoes.corte_em(conn)
            passam = {
                "favoritas": conn.execute("SELECT COUNT(*) FROM lic_favoritas WHERE removida_em IS NULL").fetchone()[0],
                "descartadas": conn.execute("SELECT COUNT(*) FROM lic_descartes WHERE desfeito_em IS NULL").fetchone()[0]}
            if feito_em is None:
                _ver_as_mudancas_antigas(conn)
                cur = conn.execute("UPDATE lic_estado SET corte_em=?, corte_por=? WHERE id=1 AND corte_em IS NULL",
                                   (_agora(), usuario_id))
                db.exigir_uma_linha(cur, CORTE_SEM_ESTADO)
                auditoria.registrar(conn, usuario_id, "licitacoes.corte", "licitacoes", None, None, passam)
            rel = {"ja_feito_em": feito_em, "ensaio": ensaio, **passam,
                   "pedem_atencao": len(licitacoes.triagem(conn)["favoritas"])}
            if ensaio and feito_em is None:
                raise _Ensaio
    except _Ensaio:
        pass
    return rel


def _exigir_corte(conn) -> None:
    if licitacoes.corte_em(conn) is None:
        raise Recusa(DECISOES_NO_RADAR)


# --- as decisoes -------------------------------------------------------------------------------------------------

def _certame(conn, certame_id: int):
    c = conn.execute("SELECT id, chave, dados FROM lic_certames WHERE id=?", (certame_id,)).fetchone()
    if c is None:
        raise NaoEncontrada(LICITACAO_INEXISTENTE)
    return c


def _favorita(conn, chave: str):
    return conn.execute("SELECT id, desde, etapa, mudancas_vistas FROM lic_favoritas "
                        "WHERE chave=? AND removida_em IS NULL", (chave,)).fetchone()


def _descarte(conn, chave: str):
    return conn.execute("SELECT id, motivo FROM lic_descartes WHERE chave=? AND desfeito_em IS NULL",
                        (chave,)).fetchone()


def _criar_favorita(conn, usuario_id: int, c, etapa: str | None) -> None:
    """Favorita com o dia de hoje (Cuiaba). As mudancas que a licitacao ja' tem nesse momento entram como vistas:
    quem favorita acabou de olhar para ela, e a favorita nao cai na Triagem na mesma hora. Favoritar uma descartada
    desfaz o descarte."""
    agora, hoje = _agora(), tempo.hoje_local().isoformat()
    vistas = sorted({m["chave"] for m in licitacoes.mudancas(json.loads(c["dados"]),
                                                             {"desde": hoje, "mudancas_vistas": "[]"})})
    conn.execute("INSERT INTO lic_favoritas (chave, desde, etapa, etapa_em, origem, criada_por, criada_em, "
                 "mudancas_vistas) VALUES (?,?,?,?,'dashboard',?,?,?)",
                 (c["chave"], hoje, etapa, agora if etapa else None, usuario_id, agora, json.dumps(vistas)))
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
    with db.mutacao(conn):
        _exigir_corte(conn)                             # antes de tudo: sem o corte a resposta e' sempre a mesma
        if etapa not in licitacoes.ROTULO_ETAPA:
            raise ForaDaLista(ETAPA_INVALIDA)
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
    with db.mutacao(conn):
        _exigir_corte(conn)
        if motivo not in MOTIVOS_DESCARTE:
            raise ForaDaLista(MOTIVO_INVALIDO)
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


def marcar_mudancas_vistas(conn, usuario_id: int, certame_id: int, chaves: list[str]) -> None:
    """Marca como vistas as mudancas que a tela mostrou (`chaves`): entram na lista so' as que sao mudancas desta
    favorita e ainda nao estavam vistas. A mudanca que chegou depois de a tela ser lida continua nao vista."""
    with db.mutacao(conn):
        _exigir_corte(conn)
        c = _certame(conn, certame_id)
        fav = _favorita(conn, c["chave"])
        if fav is None:
            raise Recusa(NAO_FAVORITA)
        pedidas = set(chaves)
        novas = {m["chave"] for m in licitacoes.mudancas(json.loads(c["dados"]), fav)
                 if not m["vista"] and m["chave"] in pedidas}
        if not novas:
            raise Recusa(SEM_MUDANCA_NOVA)
        antes = json.loads(fav["mudancas_vistas"])
        depois = sorted(set(antes) | novas)
        conn.execute("UPDATE lic_favoritas SET mudancas_vistas=? WHERE id=?", (json.dumps(depois), fav["id"]))
        auditoria.registrar(conn, usuario_id, "licitacoes.mudancas_vistas", "licitacao", c["id"],
                            {"vistas": antes}, {"vistas": depois})


# --- o que o radar busca depois do corte ---------------------------------------------------------------------------

def para_o_radar(conn) -> dict:
    """As decisoes em vigor, para o radar juntar os repetidos e avisar por e-mail como sempre fez. Um retrato so':
    a decisao gravada no meio das consultas nao poe a mesma chave nas duas listas, nem em nenhuma."""
    with db.leitura(conn):
        favoritas = [{"chave": r["chave"], "desde": r["desde"], "etapa": r["etapa"], "autor": r["nome"] or r["autor_radar"]}
                     for r in conn.execute(
                         "SELECT f.chave, f.desde, f.etapa, f.autor_radar, u.nome FROM lic_favoritas f "
                         "LEFT JOIN usuarios u ON u.id=f.criada_por WHERE f.removida_em IS NULL ORDER BY f.id")]
        descartadas = [{"chave": r["chave"], "motivo": r["motivo"], "quando": tempo.iso_utc(r["criado_em"]),
                        "autor": r["nome"] or r["autor_radar"]}
                       for r in conn.execute(
                           "SELECT d.chave, d.motivo, d.criado_em, d.autor_radar, u.nome FROM lic_descartes d "
                           "LEFT JOIN usuarios u ON u.id=d.criado_por WHERE d.desfeito_em IS NULL ORDER BY d.id")]
        cortado = licitacoes.corte_em(conn)
        return {"corte_em": tempo.iso_utc(cortado) if cortado else None,
                "favoritas": favoritas, "descartadas": descartadas}
