"""Licitacoes (issue #908, docs/adr/0018): o que o radar entrega e o que as telas leem.

A dashboard nao le fonte nenhuma. O radar, de fora, manda os certames ja' classificados (tipo de obra, distancia,
nota e motivo das Recomendadas, rotulo de cada mudanca) e fecha a rodada com a lista do que mostra hoje, a situacao
das fontes e, ate' o corte, as favoritas dele. Aqui se grava como veio e se calcula so' o que depende do dia (dias
uteis ate' a sessao, sessao passada) e das decisoes (favorita). Nada se apaga.
"""
import datetime
import json

from app import db, feriados, tempo

ETAPAS = (("acompanhando", "Acompanhando"), ("em_analise", "Em análise"), ("proposta_enviada", "Proposta enviada"),
          ("vencida", "Vencida"), ("perdida", "Perdida"), ("desistida", "Desistida"), ("encerrada", "Encerrada"))
ROTULO_ETAPA = dict(ETAPAS)
ETAPA_PADRAO = "acompanhando"

PRAZO_CRITICO = 5                 # dias uteis ate' o prazo: critico ate' aqui
PRAZO_BREVE = 15                  # vence em breve ate' aqui; e' tambem o corte da Triagem
MUDANCA_RECENTE = 7               # dias corridos em que a mudanca de uma favorita fica na Triagem
HORA_DA_LEITURA = 10              # antes dessa hora (Cuiaba) a leitura de hoje ainda nao e' esperada
FOLGA_FUTURO = datetime.timedelta(minutes=10)

LEITURA_NO_FUTURO = "Data da leitura no futuro: confira o relógio da máquina do radar"
LEITURA_ANTIGA = "Leitura mais antiga que a última gravada"
LEITURA_FORA_DA_FAIXA = "Data da leitura fora da faixa aceita"
ANO_MINIMO_DA_LEITURA = 2020
CHAVE_DESCONHECIDA = "Licitação que a dashboard ainda não recebeu: "

_UM_DIA = datetime.timedelta(days=1)
_COLUNAS = ("resumo", "dados", "uf", "data_sessao", "valor_centavos", "encerrada", "nova", "grande_vulto", "nota")


# --- o que o radar entrega ---------------------------------------------------------------------------------

def estado(conn) -> dict:
    """O que o radar pergunta antes de mandar: o resumo de cada certame gravado e de que lado estao as decisoes."""
    return {"decisoes": "radar", "corte_em": None,
            "resumos": {r["chave"]: r["resumo"] for r in conn.execute("SELECT chave, resumo FROM lic_certames")}}


def gravar_certames(conn, certames: list[dict]) -> dict:
    """Grava os certames novos e os de resumo diferente. O de resumo igual nao muda nada."""
    novos = alterados = 0
    with db.mutacao(conn):
        tem = {r["chave"]: r["resumo"] for r in conn.execute("SELECT chave, resumo FROM lic_certames")}
        for c in certames:
            chave, resumo = c["chave"], c["resumo"]
            if tem.get(chave) == resumo:
                continue
            dados = {k: v for k, v in c.items() if k not in ("chave", "resumo")}
            rec = dados.get("recomendada")
            valores = (resumo, json.dumps(dados, ensure_ascii=False, sort_keys=True), dados["uf"],
                       dados["data_sessao"], dados["valor_centavos"], int(dados["encerrada"]), int(dados["nova"]),
                       int(dados["grande_vulto"]), rec["nota"] if rec else None)
            if chave in tem:
                conn.execute(f"UPDATE lic_certames SET {', '.join(c + '=?' for c in _COLUNAS)}, "
                             "atualizado_em=datetime('now') WHERE chave=?", (*valores, chave))
                alterados += 1
            else:
                conn.execute(f"INSERT INTO lic_certames (chave, {', '.join(_COLUNAS)}) "
                             f"VALUES (?{', ?' * len(_COLUNAS)})", (chave, *valores))
                novos += 1
            tem[chave] = resumo
    return {"recebidos": len(certames), "novos": novos, "alterados": alterados}


def _utc(dt: datetime.datetime) -> str:
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def fechar_leitura(conn, lido_em: datetime.datetime, chaves: list[str], fontes: list[dict],
                   decisoes: dict | None) -> dict:
    """Fecha a rodada do radar: o que ele lista hoje, a situacao das fontes e, ate' o corte, as favoritas dele.
    Confere tudo antes de gravar: chave que a dashboard nao recebeu recusa o fechamento inteiro."""
    if lido_em.year < ANO_MINIMO_DA_LEITURA:            # antes de qualquer conta com fuso, que estouraria no ano 1
        raise ValueError(LEITURA_FORA_DA_FAIXA)
    if lido_em > tempo.agora_utc() + FOLGA_FUTURO:
        raise ValueError(LEITURA_NO_FUTURO)
    lido = _utc(lido_em)
    listadas = set(chaves)
    favoritas = None if decisoes is None else {f["chave"]: f for f in decisoes.get("favoritas") or []}
    with db.mutacao(conn):
        ultima = conn.execute("SELECT MAX(lido_em) FROM lic_leituras").fetchone()[0]
        if ultima and lido < ultima:
            raise ValueError(LEITURA_ANTIGA)
        gravados = {r["chave"]: r["fora_desde"] for r in conn.execute("SELECT chave, fora_desde FROM lic_certames")}
        for chave in sorted((listadas | set(favoritas or ())) - set(gravados)):
            raise ValueError(CHAVE_DESCONHECIDA + chave)
        saiu = [(lido, k) for k, fora in gravados.items() if fora is None and k not in listadas]
        voltou = [(k,) for k, fora in gravados.items() if fora is not None and k in listadas]
        conn.executemany("UPDATE lic_certames SET fora_desde=? WHERE chave=?", saiu)
        conn.executemany("UPDATE lic_certames SET fora_desde=NULL WHERE chave=?", voltou)
        # a mesma rodada mandada de novo nao cria linha, mas vale o que ela diz agora
        conn.execute("INSERT INTO lic_leituras (lido_em, certames, fontes) VALUES (?,?,?) "
                     "ON CONFLICT(lido_em) DO UPDATE SET certames=excluded.certames, fontes=excluded.fontes",
                     (lido, len(listadas), json.dumps(fontes, ensure_ascii=False)))
        espelhadas = _espelhar_favoritas(conn, favoritas, lido) if favoritas is not None else None
    return {"listados": len(listadas), "fora": len(saiu), "favoritas": espelhadas}


def _espelhar_favoritas(conn, favoritas: dict[str, dict], lido: str) -> int:
    """Ate' o corte as favoritas sao espelho do radar: entra a que falta, a etapa, o dia e o autor acompanham, e a
    que ele nao manda mais sai, com a data. A linha da que saiu fica."""
    ativas = {r["chave"]: r for r in conn.execute(
        "SELECT id, chave, desde, etapa, autor_radar FROM lic_favoritas WHERE removida_em IS NULL AND origem='radar'")}
    for chave, f in favoritas.items():
        desde, etapa, autor = f["desde"], f.get("etapa"), f.get("autor")
        atual = ativas.get(chave)
        if atual is None:
            conn.execute("INSERT INTO lic_favoritas (chave, desde, etapa, etapa_em, origem, autor_radar) "
                         "VALUES (?,?,?,?,'radar',?)", (chave, desde, etapa, lido if etapa else None, autor))
            continue
        if atual["etapa"] != etapa:
            conn.execute("UPDATE lic_favoritas SET etapa=?, etapa_em=? WHERE id=?", (etapa, lido, atual["id"]))
        if (atual["desde"], atual["autor_radar"]) != (desde, autor):
            # tirada e favoritada de novo no radar entre duas rodadas: vale o dia novo
            conn.execute("UPDATE lic_favoritas SET desde=?, autor_radar=? WHERE id=?", (desde, autor, atual["id"]))
    conn.executemany("UPDATE lic_favoritas SET removida_em=? WHERE id=?",
                     [(lido, r["id"]) for chave, r in ativas.items() if chave not in favoritas])
    return len(favoritas)


# --- o que depende do dia ----------------------------------------------------------------------------------

def dias_uteis_ate(hoje: datetime.date, data: datetime.date) -> int:
    """Dias uteis de hoje ate' a data: hoje nao conta, o dia da data conta. No proprio dia, 0; passada, negativo."""
    if data >= hoje:
        return feriados.dias_uteis_entre(hoje + _UM_DIA, data + _UM_DIA)
    return -feriados.dias_uteis_entre(data + _UM_DIA, hoje + _UM_DIA)


def situacao_do_prazo(dias_uteis: int | None, passado: bool = False) -> str | None:
    """Critico ate' 5 dias uteis, vence em breve ate' 15; acima disso, passado ou sem data, sem situacao. Passado se
    decide pela data, nao pelos dias uteis: de sexta para sabado nao ha' dia util nenhum."""
    if dias_uteis is None or passado:
        return None
    return "critico" if dias_uteis <= PRAZO_CRITICO else "breve" if dias_uteis <= PRAZO_BREVE else None


def _dia_util_anterior(d: datetime.date) -> datetime.date:
    d -= _UM_DIA
    while not feriados.dia_util(d):
        d -= _UM_DIA
    return d


def leitura(conn) -> dict:
    """A ultima leitura do radar e se ela esta' atrasada: e' de antes do dia esperado, que e' hoje, se hoje e' dia
    util e ja' passou da hora da leitura, ou o dia util anterior."""
    r = conn.execute("SELECT lido_em, fontes FROM lic_leituras ORDER BY lido_em DESC LIMIT 1").fetchone()
    agora = tempo.para_local(tempo.agora_utc())
    hoje = agora.date()
    esperado = hoje if feriados.dia_util(hoje) and agora.hour >= HORA_DA_LEITURA else _dia_util_anterior(hoje)
    if r is None:
        return {"lido_em": None, "atrasada": True, "fontes_com_problema": 0}
    lido = tempo.para_local(datetime.datetime.fromisoformat(r["lido_em"])).date()
    return {"lido_em": tempo.iso_utc(r["lido_em"]), "atrasada": lido < esperado,
            "fontes_com_problema": sum(1 for f in json.loads(r["fontes"]) if f.get("problema"))}


# --- as linhas das telas -----------------------------------------------------------------------------------

_DA_LINHA = ("orgao", "sigla_orgao", "grupo_orgao", "orgao_de_interesse", "esfera", "municipio", "uf", "cidade", "km", "edital",
             "modalidade", "objeto", "tipo_obra", "valor_centavos", "valor_rotulo", "situacao", "data_publicacao",
             "data_sessao", "hora_sessao", "primeira_vez", "link", "portal", "fontes", "recomendada")


def _data(texto: str | None) -> datetime.date | None:
    return datetime.date.fromisoformat(texto) if texto else None


def _prazos(dados: dict, hoje: datetime.date) -> list[dict]:
    """Os prazos da favorita, em ordem de data: os do dossie, quando ha', e a sessao, que nunca falta (o dossie
    pode vir sem prazo nenhum, ou sem a sessao)."""
    brutos = list((dados.get("dossie") or {}).get("prazos") or [])
    if dados.get("data_sessao") and not any(p["codigo"] == "sessao" for p in brutos):
        brutos.append({"codigo": "sessao", "rotulo": "Sessão", "data": dados["data_sessao"],
                       "hora": dados.get("hora_sessao"), "aviso": ""})
    prazos = []
    for p in sorted(brutos, key=lambda p: (p["data"], p.get("hora") or "99:99")):
        data = _data(p["data"])
        du, passado = dias_uteis_ate(hoje, data), data < hoje
        prazos.append({**p, "dias_uteis": du, "passado": passado, "situacao": situacao_do_prazo(du, passado)})
    return prazos


def _favorita(fav, dados: dict, hoje: datetime.date, encerrada: bool) -> dict:
    dossie = dados.get("dossie")
    etapa = (dossie or {}).get("etapa") or fav["etapa"] or ETAPA_PADRAO
    prazos = _prazos(dados, hoje)
    if encerrada:                                       # licitacao encerrada nao tem prazo correndo
        prazos = [{**p, "situacao": None} for p in prazos]
    mudancas = [{"data": h["data"], "texto": h["texto"], "rotulo": h["rotulo"]}
                for h in dados.get("historico") or [] if h.get("rotulo") and h["data"] >= fav["desde"]]
    mudancas.sort(key=lambda m: m["data"], reverse=True)
    return {"desde": fav["desde"], "etapa": etapa, "etapa_rotulo": ROTULO_ETAPA[etapa],
            "etapa_do_dossie": bool(dossie and dossie.get("etapa")), "dossie": (dossie or {}).get("pasta"),
            "selos": (dossie or {}).get("selos") or [],
            "prazos": prazos, "proximo_prazo": next((p for p in prazos if not p["passado"]), None),
            "mudancas": mudancas}


def _linha(row, hoje: datetime.date, fav=None) -> dict:
    """A licitacao como as telas a mostram: o que o radar mandou, o que depende do dia e, na favorita, a etapa, os
    prazos e as mudancas. Uma funcao so' para a Triagem e para as Favoritas."""
    dados = json.loads(row["dados"])
    sessao = _data(dados.get("data_sessao"))
    du = dias_uteis_ate(hoje, sessao) if sessao else None
    encerrada = bool(dados["encerrada"]) or (sessao is not None and sessao < hoje)   # pela data: ver situacao_do_prazo
    linha = {"chave": row["chave"], **{k: dados.get(k) for k in _DA_LINHA}, "dias_uteis": du,
             "prazo": None if encerrada else situacao_do_prazo(du), "encerrada": encerrada, "favorita": None}
    if fav is not None:
        linha["favorita"] = _favorita(fav, dados, hoje, encerrada)
    return linha


def _linhas_das_favoritas(conn, hoje: datetime.date) -> list[dict]:
    """As favoritas ativas: as em aberto primeiro, pela sessao mais proxima; as encerradas depois."""
    linhas = [_linha(r, hoje, r) for r in conn.execute(
        "SELECT c.chave, c.dados, f.desde, f.etapa FROM lic_favoritas f JOIN lic_certames c ON c.chave=f.chave "
        "WHERE f.removida_em IS NULL")]
    linhas.sort(key=lambda l: (l["encerrada"], l["dias_uteis"] if l["dias_uteis"] is not None else 9999,
                               -(l["valor_centavos"] or 0), l["chave"]))
    return linhas


def favoritas(conn) -> dict:
    with db.leitura(conn):
        return {"leitura": leitura(conn), "favoritas": _linhas_das_favoritas(conn, tempo.hoje_local())}


def _pede_atencao(linha: dict, hoje: datetime.date) -> bool:
    """A favorita em aberto entra na Triagem com prazo em ate' 15 dias uteis ou com mudanca nos ultimos 7 dias."""
    if linha["encerrada"]:
        return False
    fav = linha["favorita"]
    corte = (hoje - datetime.timedelta(days=MUDANCA_RECENTE)).isoformat()
    proximo = fav["proximo_prazo"]
    return (proximo is not None and proximo["dias_uteis"] <= PRAZO_BREVE) or any(
        m["data"] >= corte for m in fav["mudancas"])


def _novas_desde(conn, novas: list[dict]) -> dict | None:
    """Quantas das novas apareceram depois do ultimo dia de leitura anterior ao da ultima (o radar le mais de uma
    vez por dia: a rodada da tarde nao pode zerar a conta da manha); sem leitura em dia anterior, nada."""
    def dia(lido_em: str) -> str:
        return tempo.para_local(datetime.datetime.fromisoformat(lido_em)).date().isoformat()
    ultima = conn.execute("SELECT MAX(lido_em) FROM lic_leituras").fetchone()[0]
    if ultima is None:
        return None
    # a ultima leitura de antes da meia-noite (de Cuiaba) do dia da ultima: por consulta, e nao pelas N ultimas
    # linhas, que num dia de muitas rodadas sao todas do mesmo dia
    anterior = conn.execute("SELECT MAX(lido_em) FROM lic_leituras WHERE lido_em < ?",
                            (tempo.inicio_do_dia_utc(dia(ultima)),)).fetchone()[0]
    if anterior is None:
        return None
    desde = dia(anterior)
    return {"desde": desde, "quantas": sum(1 for l in novas if (l["primeira_vez"] or "") > desde)}


def triagem(conn) -> dict:
    """O que pede decisao agora: as favoritas com prazo chegando ou mudanca recente e as recomendadas que ainda nao
    sao favoritas. As contagens do alto saem das mesmas linhas."""
    with db.leitura(conn):
        hoje = tempo.hoje_local()
        favs = _linhas_das_favoritas(conn, hoje)
        chaves_favoritas = {l["chave"] for l in favs}
        listadas = [(r["nova"], _linha(r, hoje)) for r in conn.execute(
            "SELECT chave, dados, nova FROM lic_certames WHERE fora_desde IS NULL AND (nova=1 OR nota IS NOT NULL)")]
        abertas = [(nova, l) for nova, l in listadas if not l["encerrada"]]
        recomendadas = [l for _, l in abertas if l["recomendada"] and l["chave"] not in chaves_favoritas]
        recomendadas.sort(key=lambda l: (-l["recomendada"]["nota"], -(l["valor_centavos"] or 0),
                                         l["recomendada"]["km"] if l["recomendada"]["km"] is not None else 9999,
                                         l["dias_uteis"] if l["dias_uteis"] is not None else 9999, l["chave"]))
        atencao = [l for l in favs if _pede_atencao(l, hoje)]
        atencao.sort(key=lambda l: (l["favorita"]["proximo_prazo"] or {}).get("dias_uteis", 9999))
        novas = [l for nova, l in abertas if nova]
        por_orgao: dict[str, int] = {}
        for l in novas:
            if l["orgao_de_interesse"]:
                por_orgao[l["grupo_orgao"]] = por_orgao.get(l["grupo_orgao"], 0) + 1
        return {"leitura": leitura(conn),
                "contagens": {"recomendadas": len(recomendadas), "favoritas": len(favs), "novas": len(novas),
                              "novas_desde": _novas_desde(conn, novas),
                              "por_orgao": [{"orgao": o, "novas": n} for o, n in sorted(por_orgao.items())]},
                "favoritas": atencao, "recomendadas": recomendadas}
