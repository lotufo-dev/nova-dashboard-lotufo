"""Grava no banco a estrutura normalizada do cadastro (spec 2026-09-21 §8).

Uma transacao so' (db.mutacao): qualquer erro desfaz tudo. Idempotente: reaplicar o mesmo
cadastro nao muda nada. `ensaio=True` roda de verdade e desfaz no fim, para o relatorio
mostrar exatamente o que SERIA gravado.
"""
import json
import sqlite3
from pathlib import Path

from app import arquivos, auditoria, contratos, cronograma, db, oficios, reajuste, tempo
from app.cadastro_arquivos import NATUREZAS, TIPOS_ADITIVO, TIPOS_COM_NATUREZA, competencias_do_apostilamento


class _Ensaio(Exception):
    """Sinal interno: desfaz a transacao do ensaio."""


def _rel() -> dict:
    return {"criados": [], "alterados": [], "iguais": 0}


def _json(v) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def _diferencas(antes: dict, depois: dict) -> tuple[dict, dict]:
    chaves = [k for k in depois if antes.get(k) != depois[k]]
    return {k: antes.get(k) for k in chaves}, {k: depois[k] for k in chaves}


def _orgaos(conn, usuario_id, orgaos, rel) -> dict[str, int]:
    ids = {}
    for o in orgaos:
        novo = {"nome": o["nome"], "familia": o["familia"], "regras": _json(o["regras"]), "cnpj": o.get("cnpj")}
        ja = conn.execute("SELECT * FROM orgaos WHERE chave=?", (o["chave"],)).fetchone()
        if ja is None:
            cur = conn.execute("INSERT INTO orgaos (chave, nome, familia, regras, cnpj) VALUES (?,?,?,?,?)",
                               (o["chave"], novo["nome"], novo["familia"], novo["regras"], novo["cnpj"]))
            ids[o["chave"]] = cur.lastrowid
            rel["criados"].append(o["chave"])
            auditoria.registrar(conn, usuario_id, "cadastro.orgao", "orgao", cur.lastrowid, None, novo)
            continue
        ids[o["chave"]] = ja["id"]
        antes, depois = _diferencas(dict(ja), novo)
        if not depois:
            rel["iguais"] += 1
            continue
        conn.execute("UPDATE orgaos SET nome=?, familia=?, regras=?, cnpj=? WHERE id=?",
                     (novo["nome"], novo["familia"], novo["regras"], novo["cnpj"], ja["id"]))
        rel["alterados"].append(o["chave"])
        auditoria.registrar(conn, usuario_id, "cadastro.orgao", "orgao", ja["id"], antes, depois)
    return ids


def _entidades(conn, usuario_id, ents, rel) -> dict[str, int]:
    ids = {}
    for e in ents:
        novo = {"nome": e["nome"], "papel": e["papel"], "chave": e["chave"],
                "coligada_rm": e["coligada_rm"], "sigla_oficio": e["sigla_oficio"],
                "emails_faturamento": _json(e.get("emails_faturamento") or []),
                # bloco 4: nome curto (arquivos do ZIP) e folha propria (regularidade mensal)
                "nome_curto": e.get("nome_curto") or e["nome"],
                "regularidade_propria": 1 if e.get("regularidade_propria") else 0}
        ja = conn.execute("SELECT * FROM entidades WHERE cnpj=?", (e["cnpj"],)).fetchone()
        if ja is None and e["papel"] == "lotufo":
            # A empresa própria é uma só: a que a migração 006 semeia (id 1) é a mesma do cadastro, mesmo com
            # outro CNPJ (cadastro de exemplo num banco vazio). Sem isto nasceria uma segunda "lotufo" e a
            # coligada 1 colidiria. Só vale para a semeada que nenhum cadastro reivindicou ainda (chave nula):
            # depois disso, CNPJ digitado errado volta a ser recusado, e duas "lotufo" no YAML também.
            ja = conn.execute("SELECT * FROM entidades WHERE papel='lotufo' AND chave IS NULL "
                              "ORDER BY id LIMIT 1").fetchone()
            if ja is not None:
                novo["cnpj"] = e["cnpj"]
        if ja is None:
            colunas = ["cnpj", *novo]
            cur = conn.execute(
                f"INSERT INTO entidades ({','.join(colunas)}) VALUES ({','.join('?' * len(colunas))})",
                (e["cnpj"], *novo.values()))
            ids[e["chave"]] = cur.lastrowid
            rel["criados"].append(e["chave"])
            auditoria.registrar(conn, usuario_id, "cadastro.entidade", "entidade", cur.lastrowid,
                                None, {**novo, "cnpj": e["cnpj"]})
            continue
        ids[e["chave"]] = ja["id"]
        antes, depois = _diferencas(dict(ja), novo)
        if not depois:
            rel["iguais"] += 1
            continue
        conn.execute(f"UPDATE entidades SET {', '.join(f'{k}=?' for k in novo)} WHERE id=?",
                     (*novo.values(), ja["id"]))
        rel["alterados"].append(e["chave"])
        auditoria.registrar(conn, usuario_id, "cadastro.entidade", "entidade", ja["id"], antes, depois)
    _consorciadas(conn, usuario_id, ents, ids, rel)
    return ids


def _consorciadas(conn, usuario_id, ents, ids, rel) -> None:
    """Composicao dos consorcios: o conjunto do YAML substitui o do banco (cadastro, nao historico
    financeiro); a mudanca vai para a auditoria com as chaves de antes e de depois."""
    chave_de = {v: k for k, v in ids.items()}
    for e in ents:
        if e.get("papel") != "consorcio":
            continue
        cid = ids[e["chave"]]
        antes = sorted(chave_de.get(r[0], str(r[0])) for r in conn.execute(
            "SELECT consorciada_id FROM entidade_consorciadas WHERE consorcio_id=?", (cid,)))
        depois = sorted(e.get("consorciadas") or [])
        if antes == depois:
            continue
        conn.execute("DELETE FROM entidade_consorciadas WHERE consorcio_id=?", (cid,))
        for ch in depois:
            conn.execute("INSERT INTO entidade_consorciadas (consorcio_id, consorciada_id) VALUES (?,?)",
                         (cid, ids[ch]))
        rel["alterados"].append(f"{e['chave']} (consorciadas)")
        auditoria.registrar(conn, usuario_id, "cadastro.consorciadas", "entidade", cid,
                            {"consorciadas": antes}, {"consorciadas": depois})


def aplicar(conn: sqlite3.Connection, usuario_id: int, cad: dict, ensaio: bool = False,
            commit_hash: str | None = None) -> dict:
    rel = {"orgaos": _rel(), "entidades": _rel(), "contratos": _rel(), "instrumentos": _rel(),
           "pleitos": _rel(), "cronograma": _rel(), "geral": _rel(), "espelho": _rel(), "frc": _rel(),
           "avisos": list(cad.get("avisos", [])), "ensaio": ensaio}
    try:
        with db.mutacao(conn):
            ids_orgao = _orgaos(conn, usuario_id, cad["orgaos"], rel["orgaos"])
            ids_ent = _entidades(conn, usuario_id, cad["entidades"], rel["entidades"])
            for c in cad["contratos"]:
                _contrato(conn, usuario_id, c, ids_orgao, ids_ent, rel)
            _geral(conn, usuario_id, _materializar_geral(cad.get("geral"), ensaio), rel["geral"])
            _espelhos(conn, usuario_id, cad.get("espelho") or [], rel["espelho"], ensaio)
            _frcs(conn, usuario_id, cad.get("frc") or [], rel["frc"], ensaio)
            if ensaio:
                raise _Ensaio()
            resumo = {k: {"criados": len(v["criados"]), "alterados": len(v["alterados"]),
                          "iguais": v["iguais"]}
                      for k, v in rel.items() if isinstance(v, dict)}
            conn.execute("INSERT INTO cadastro_aplicacoes (commit_hash, usuario_id, resumo) VALUES (?,?,?)",
                         (commit_hash, usuario_id, _json(resumo)))
            auditoria.registrar(conn, usuario_id, "cadastro.aplicar", "cadastro", None, None,
                                {"commit": commit_hash, **resumo})
    except _Ensaio:
        pass
    return rel


# status do cadastro -> contratos.estado. "em_encerramento" nao e' estado do banco: e'
# 'ativo' com encerramento_iniciado_em preenchido (migracao 018).
_ESTADO = {"ativo": "ativo", "suspenso": "suspenso", "em_encerramento": "ativo", "encerrado": "encerrado"}
_EVENTO = {("ativo", "suspenso"): "suspensao", ("suspenso", "ativo"): "retomada",
           ("ativo", "encerrado"): "encerramento", ("suspenso", "encerrado"): "encerramento"}
_CAMPOS_CONTRATO = ("nome_curto", "orgao", "orgao_id", "entidade_id", "objeto", "municipio", "lei", "cno",
                    "numero_processo", "centro_custo_rm", "valor_original_centavos",
                    "percentual_direito_bp", "execucao_inicio", "execucao_fim", "vigencia_inicio",
                    "vigencia_fim", "sem_reajuste", "encerramento_iniciado_em", "destinatarios_extras",
                    "copia_extras",
                    "estado", "documentos", "objeto_completo", "cno_arquivo", "folga_vigencia_dias",
                    "centros_custo_anteriores_rm", "objeto_carta", "garantia_apolice", "garantia_vigencia_fim",
                    "garantia_arquivo", "indice_reajuste")
_CAMPOS_FISCAL = ("cargo", "tratamento", "portaria")


def _no_disco(pasta: str, caminho: str, ext: str, ensaio: bool) -> str:
    """Copia um arquivo do cadastro para a pasta de dados pelo hash (a producao nao le o checkout).
    No ensaio so' calcula o caminho: nada vai para o disco."""
    dados = Path(caminho).read_bytes()
    if ensaio:
        return f"{pasta}/{arquivos.sha_de(dados)}.{ext}"
    return arquivos.gravar_bytes(pasta, dados, ext)[0]


def _materializar_geral(geral: dict | None, ensaio: bool) -> dict | None:
    """Troca os caminhos do checkout pelos arquivos na pasta de dados: timbre (bloco 5) e modelo do QDOP (bloco 8)."""
    if geral and "qdop" in geral:
        geral = {**geral, "qdop": {"modelo": _no_disco("modelos", geral["qdop"]["modelo_caminho"], "xlsx", ensaio)}}
    if not geral or "cartas" not in geral:
        return geral
    cartas = {**geral["cartas"], "emitentes": {}}
    for chave, e in (geral["cartas"].get("emitentes") or {}).items():
        e = dict(e)
        caminho = e.pop("logo_caminho", None)
        e["logo"] = _no_disco("modelos", caminho, Path(caminho).suffix.lstrip(".").lower(), ensaio) \
            if caminho else None
        cartas["emitentes"][chave] = e
    return {**geral, "cartas": cartas}


def _frcs(conn, usuario_id, lista, rel, ensaio) -> None:
    """frc.yaml -> frc_consorcios (issue #110; antes, semente da migracao 032). O cadastro e' a verdade: outro
    valor atualiza a linha, auditado. Consorcio que sai do frc.yaml fica no banco (as FRCs emitidas apontam para ele)."""
    for f in lista:
        caminho = f["logo_caminho"]
        logo = _no_disco("modelos", caminho, Path(caminho).suffix.lstrip(".").lower(), ensaio) if caminho else None
        novo = {"formulario": f["formulario"], "ultimo_anterior": f["ultimo_anterior"],
                "dados": _json({**f["dados"], "logo": logo})}
        ja = conn.execute("SELECT formulario, ultimo_anterior, dados FROM frc_consorcios WHERE consorcio=?",
                          (f["consorcio"],)).fetchone()
        if ja is None:
            conn.execute("INSERT INTO frc_consorcios (consorcio, formulario, ultimo_anterior, dados) VALUES (?,?,?,?)",
                         (f["consorcio"], novo["formulario"], novo["ultimo_anterior"], novo["dados"]))
            rel["criados"].append(f["consorcio"])
            auditoria.registrar(conn, usuario_id, "cadastro.frc", "frc_consorcio", f["consorcio"], None, novo)
            continue
        antes, depois = _diferencas(dict(ja), novo)
        if not depois:
            rel["iguais"] += 1
            continue
        conn.execute("UPDATE frc_consorcios SET formulario=?, ultimo_anterior=?, dados=?, atualizado_em=datetime('now') "
                     "WHERE consorcio=?", (novo["formulario"], novo["ultimo_anterior"], novo["dados"], f["consorcio"]))
        rel["alterados"].append(f["consorcio"])
        auditoria.registrar(conn, usuario_id, "cadastro.frc", "frc_consorcio", f["consorcio"], antes, depois)


def _indice_das_bases(bases: list[dict]) -> str | None:
    """Texto de contratos.indice_reajuste, derivado das datas-base (issue #397): o indice da base unica; com mais
    de uma, `AAAA-MM: indice (aplica_a)` separadas por "; ". Sem base, nulo."""
    if not bases:
        return None
    if len(bases) == 1:
        return bases[0]["indice"]
    return "; ".join(f"{d['mes']}: {d['indice']}" + (f" ({d['aplica_a']})" if d.get("aplica_a") else "")
                     for d in sorted(bases, key=lambda d: d["mes"]))


def _contrato(conn, usuario_id, c, ids_orgao, ids_ent, rel) -> int:
    nome_orgao = conn.execute("SELECT nome FROM orgaos WHERE id=?", (ids_orgao[c["orgao"]],)).fetchone()[0]
    ja = conn.execute("SELECT * FROM contratos WHERE numero_instrumento=?",
                      (c["numero_instrumento"],)).fetchone()
    # Bloco 7: medicao final marcada na operacao preserva o encerramento mesmo com o YAML em `ativo`.
    tem_final = ja is not None and conn.execute(
        "SELECT 1 FROM medicoes WHERE contrato_id=? AND final=1 LIMIT 1", (ja["id"],)).fetchone() is not None
    if c["status"] == "em_encerramento":
        enc = c["status_desde"]
    elif ja is not None and (c["status"] == "encerrado" or tem_final):
        enc = ja["encerramento_iniciado_em"]
        if tem_final and c["status"] == "ativo":
            rel["avisos"].append(f"{c['nome_curto']}: medição final marcada na operação; atualize o YAML "
                                 f"para status em_encerramento")
    else:
        enc = None
    novo = {"nome_curto": c["nome_curto"], "orgao": nome_orgao, "orgao_id": ids_orgao[c["orgao"]],
            "entidade_id": ids_ent[c["entidade"]], "objeto": c["objeto"], "municipio": c["municipio"],
            "lei": c["lei"], "cno": c["cno"], "numero_processo": c["numero_processo"],
            "centro_custo_rm": c["centro_custo_rm"],
            "valor_original_centavos": c["valor_original_centavos"],
            "percentual_direito_bp": c["percentual_direito_bp"],
            "execucao_inicio": c["execucao_inicio"], "execucao_fim": c["execucao_fim"],
            "vigencia_inicio": c["vigencia_inicio"], "vigencia_fim": c["vigencia_fim"],
            "sem_reajuste": 1 if c["sem_reajuste"] else 0, "encerramento_iniciado_em": enc,
            "destinatarios_extras": _json(c["destinatarios_extras"]),
            "copia_extras": _json(c["copia_extras"]) if c.get("copia_extras") else None,
            "estado": _ESTADO[c["status"]],
            "documentos": _json(c["documentos"]) if c.get("documentos") else None,
            "objeto_completo": c.get("objeto_completo"),
            "cno_arquivo": _no_disco("anexos", c["cno_caminho"], "pdf", rel["ensaio"]) if c.get("cno_caminho")
            else None,
            "folga_vigencia_dias": c.get("folga_vigencia_dias"),
            "centros_custo_anteriores_rm": _json(c["centros_custo_anteriores_rm"])
            if c.get("centros_custo_anteriores_rm") else None,
            "objeto_carta": c.get("objeto_carta"),
            # issue #65: garantia (apolice, fim da vigencia, PDF)
            "garantia_apolice": c.get("garantia_apolice"), "garantia_vigencia_fim": c.get("garantia_vigencia_fim"),
            "garantia_arquivo": _no_disco("anexos", c["garantia_caminho"], "pdf", rel["ensaio"])
            if c.get("garantia_caminho") else None,
            "indice_reajuste": _indice_das_bases(c["datas_base"])}
    mudou = False
    if ja is None:
        colunas = ["numero_instrumento", *_CAMPOS_CONTRATO]
        cur = conn.execute(
            f"INSERT INTO contratos ({','.join(colunas)}) VALUES ({','.join('?' * len(colunas))})",
            [c["numero_instrumento"], *[novo[k] for k in _CAMPOS_CONTRATO]])
        cid = cur.lastrowid
        mudou = True
        rel["contratos"]["criados"].append(c["nome_curto"])
        auditoria.registrar(conn, usuario_id, "cadastro.contrato", "contrato", cid, None,
                            {"numero_instrumento": c["numero_instrumento"], **novo})
    else:
        cid = ja["id"]
        antes, depois = _diferencas(dict(ja), novo)
        if "valor_original_centavos" in depois and conn.execute(
                "SELECT 1 FROM medicoes WHERE contrato_id=? AND congelada=1 LIMIT 1", (cid,)).fetchone():
            raise ValueError(f"{c['nome_curto']}: o valor original não muda com medição congelada; "
                             "a alteração de valor entra como instrumento")
        if depois:
            sets = ", ".join(f"{k}=?" for k in depois)
            conn.execute(f"UPDATE contratos SET {sets} WHERE id=?", [*depois.values(), cid])
            if "estado" in depois:
                tipo = _EVENTO.get((antes["estado"], depois["estado"]))
                if tipo is None:
                    raise ValueError(f"{c['nome_curto']}: mudança de estado não prevista: "
                                     f"{antes['estado']} → {depois['estado']}")
                conn.execute("INSERT INTO contrato_eventos (contrato_id, tipo, data, observacao) "
                             "VALUES (?,?,?,?)",
                             (cid, tipo, c["status_desde"] or tempo.hoje_local().isoformat(),
                              "Cadastro versionado"))
            mudou = True
            auditoria.registrar(conn, usuario_id, "cadastro.contrato", "contrato", cid, antes, depois)

    # Datas-base: o cadastro e' a verdade (configuracao, nao historico financeiro).
    atuais = {r["mes"]: {"indice": r["indice"], "aplica_a": r["aplica_a"]} for r in conn.execute(
        "SELECT mes, indice, aplica_a FROM contrato_datas_base WHERE contrato_id=?", (cid,))}
    desejadas = {d["mes"]: {"indice": d["indice"], "aplica_a": d.get("aplica_a") or ""} for d in c["datas_base"]}
    if atuais != desejadas:
        conn.execute("DELETE FROM contrato_datas_base WHERE contrato_id=?", (cid,))
        conn.executemany("INSERT INTO contrato_datas_base (contrato_id, mes, indice, aplica_a) VALUES (?,?,?,?)",
                         [(cid, m, v["indice"], v["aplica_a"]) for m, v in sorted(desejadas.items())])
        mudou = True
        auditoria.registrar(conn, usuario_id, "cadastro.datas_base", "contrato", cid, atuais, desejadas)

    # Fiscais: historico. So' acrescenta; o fiscal vigente e' o de `desde` mais recente.
    for f in c["fiscais"]:
        cur = conn.execute("INSERT OR IGNORE INTO contrato_fiscais (contrato_id, nome, email, desde) "
                           "VALUES (?,?,?,?)", (cid, f["nome"], f["email"], f["desde"]))
        if cur.rowcount:
            mudou = True
            auditoria.registrar(conn, usuario_id, "cadastro.fiscal", "contrato", cid, None, f)
        # Bloco 5: cargo, tratamento e portaria sao descricao do fiscal (vao na carta) e podem ser corrigidos.
        linha = conn.execute("SELECT id, cargo, tratamento, portaria FROM contrato_fiscais "
                             "WHERE contrato_id=? AND email=? AND desde=?", (cid, f["email"], f["desde"])).fetchone()
        antes_f = {k: linha[k] for k in _CAMPOS_FISCAL}
        depois_f = {k: f.get(k) for k in _CAMPOS_FISCAL}
        if antes_f != depois_f:
            conn.execute("UPDATE contrato_fiscais SET cargo=?, tratamento=?, portaria=? WHERE id=?",
                         (depois_f["cargo"], depois_f["tratamento"], depois_f["portaria"], linha["id"]))
            mudou = True
            auditoria.registrar(conn, usuario_id, "cadastro.fiscal", "contrato", cid, antes_f,
                                {"email": f["email"], **depois_f})

    if ja is not None:
        if mudou:
            rel["contratos"]["alterados"].append(c["nome_curto"])
        else:
            rel["contratos"]["iguais"] += 1
    _instrumentos(conn, usuario_id, cid, c, rel["instrumentos"])
    _pleitos_anteriores(conn, usuario_id, cid, c, rel["pleitos"], rel["avisos"])
    _apostilamentos_de_reajuste(conn, usuario_id, cid, c, rel["pleitos"])
    _aditivos_de_reajuste(conn, usuario_id, cid, c, rel["pleitos"], rel["avisos"])
    _cronograma(conn, usuario_id, cid, c, rel["cronograma"], rel["avisos"])
    return cid


def _cronograma(conn, usuario_id, contrato_id, c, rel, avisos) -> None:
    """Issue #256: uma `cronograma_versoes` por entrada do YAML, com criado_em = data do documento.

    So' acrescenta. Versao aplicada nao muda nem some (correcao e' versao nova, com outra chave); as
    versoes sem linha no cadastro (manuais e a carga de 04/09/2026) ficam na linha do tempo e sao superadas
    pela primeira versao de documento posterior (cronograma.previsto_efetivo); a unica mudanca nelas e' o
    `superada_em` que `cronograma_superadas` grava (issue #395)."""
    nome = c["nome_curto"]
    do_cadastro = {v["chave"] for v in c.get("cronograma") or []}
    for r in conn.execute("SELECT chave FROM cronograma_versoes_cadastro WHERE contrato_id=?", (contrato_id,)):
        if r["chave"] not in do_cadastro:
            raise ValueError(f"{nome}: a versão de cronograma {r['chave']} já foi aplicada e sumiu do cadastro; "
                             "versão aplicada não se apaga (correção é versão nova, com outra chave)")
    # Ordem do documento: o numero das versoes segue a linha do tempo. Nao ha empate: a validacao recusa duas
    # versoes do cadastro com a mesma data (gate Sol, PR #311).
    ordenadas = sorted(enumerate(c.get("cronograma") or []), key=lambda par: (par[1]["data"], par[0]))
    criadas: list[tuple[int, str]] = []
    for _, v in ordenadas:
        rotulo = f"{nome}/{v['chave']} ({'/'.join(reversed(v['data'].split('-')))})"   # DD/MM/AAAA
        itens = sorted(v["itens"])
        ja = conn.execute("SELECT * FROM cronograma_versoes_cadastro WHERE contrato_id=? AND chave=?",
                          (contrato_id, v["chave"])).fetchone()
        if ja is None:
            numero = cronograma.nova_versao(conn, usuario_id, contrato_id, itens, "manual",
                                            data_documento=v["data"])
            vid = conn.execute("SELECT id FROM cronograma_versoes WHERE contrato_id=? AND numero=?",
                               (contrato_id, numero)).fetchone()[0]
            conn.execute("INSERT INTO cronograma_versoes_cadastro (versao_id, contrato_id, chave, origem, "
                         "data_documento, instrumento) VALUES (?,?,?,?,?,?)",
                         (vid, contrato_id, v["chave"], v["origem"], v["data"], v["instrumento"]))
            auditoria.registrar(conn, usuario_id, "cadastro.cronograma", "contrato", contrato_id, None,
                                {"chave": v["chave"], "versao": numero, "origem": v["origem"],
                                 "data_documento": v["data"], "instrumento": v["instrumento"]})
            rel["criados"].append(rotulo)
            criadas.append((numero, rotulo))
            continue
        gravado = {"origem": ja["origem"], "data": ja["data_documento"], "instrumento": ja["instrumento"],
                   "itens": [tuple(r) for r in conn.execute(
                       "SELECT competencia, valor_previsto_centavos FROM cronograma_itens WHERE versao_id=? "
                       "ORDER BY competencia", (ja["versao_id"],))]}
        novo = {"origem": v["origem"], "data": v["data"], "instrumento": v["instrumento"], "itens": itens}
        mudou = [k for k in novo if gravado[k] != novo[k]]
        if mudou:
            raise ValueError(f"{rotulo}: versão de cronograma já aplicada não pode ser alterada "
                             f"({', '.join(mudou)}); registre uma versão nova, com outra chave")
        rel["iguais"] += 1
    superou = _cronograma_superadas(conn, usuario_id, contrato_id, c, rel)
    # code-review (#395): superar sem versao nova pode deixar a obra sem cronograma vigente (curva S vazia)
    if superou and cronograma.vigente(conn, contrato_id) is None:
        avisos.append(f"{nome}: com a versão superada, a obra ficou sem cronograma vigente (sem previsto na "
                      "curva S); inclua a versão do documento em `cronograma`")
    # A versao de documento anterior a uma ja gravada (a carga de 04/09/2026, uma publicada na tela) entra
    # ANTES dela na linha do tempo e nao muda o futuro: quem aplica precisa saber.
    if criadas:
        numero, rotulo = criadas[-1]     # a de documento mais recente desta aplicacao
        vig = cronograma.vigente(conn, contrato_id)["numero"]
        if numero != vig:
            avisos.append(f"{rotulo}: versão aplicada, mas não é a vigente (há versão {vig} com data "
                          "posterior); ela só vale para os meses até a data dessa versão")


def _cronograma_superadas(conn, usuario_id, contrato_id, c, rel) -> bool:
    """Issue #395: `cronograma_superadas` marca `superada_em` nas versoes ja gravadas sem linha no cadastro.

    Irreversivel pelo YAML: tirar o numero da lista nao "dessupera" (nada aqui volta a NULL). Versao do cadastro nao
    se supera assim: correcao e' versao nova. Roda depois das versoes do YAML, para o aviso de vigente ja' ver a
    linha do tempo sem a superada. Devolve se superou alguma nesta aplicacao."""
    nome = c["nome_curto"]
    superou = False
    for numero in c.get("cronograma_superadas") or []:
        v = conn.execute("SELECT v.id, v.superada_em, k.chave FROM cronograma_versoes v "
                         "LEFT JOIN cronograma_versoes_cadastro k ON k.versao_id = v.id "
                         "WHERE v.contrato_id=? AND v.numero=?", (contrato_id, numero)).fetchone()
        if v is None:
            raise ValueError(f"{nome}: cronograma_superadas: a versão {numero} não existe neste contrato")
        if v["chave"] is not None:
            raise ValueError(f"{nome}: cronograma_superadas: a versão {numero} veio do cadastro (chave "
                             f"{v['chave']}) e não se supera; correção é versão nova, com outra chave")
        if v["superada_em"] is not None:
            rel["iguais"] += 1
            continue
        quando = conn.execute("SELECT datetime('now')").fetchone()[0]
        conn.execute("UPDATE cronograma_versoes SET superada_em=? WHERE id=?", (quando, v["id"]))
        auditoria.registrar(conn, usuario_id, "cadastro.cronograma_superada", "contrato", contrato_id, None,
                            {"versao": numero, "superada_em": quando})
        rel["alterados"].append(f"{nome}: versão {numero} superada")
        superou = True
    return superou


# o que o YAML diz de um pleito anterior, a coluna em que ele foi gravado e o nome no aviso do que difere
_CAMPOS_PLEITO = (("data", "enviado_em", "data"), ("dias", "dias", "dias"), ("ciclo", "ciclo", "ciclo"),
                  ("valor_centavos", "valor_centavos", "valor"), ("objeto", "objeto", "objeto"))


def _pleitos_anteriores(conn, usuario_id, contrato_id, c, rel, avisos) -> None:
    """Bloco 7: pleitos enviados antes do sistema viram `pleitos` de origem 'cadastro', ja' enviados.
    So' acrescenta (a chave e' contrato + tipo + oficio). Pleito ja' gravado com outro dado no YAML continua como
    esta' e vira aviso; data e oficio se corrigem com `corrige` (issue #399, `_corrigir_pleito`)."""
    sigla = conn.execute("SELECT e.sigla_oficio FROM contratos k JOIN entidades e ON e.id=k.entidade_id "
                         "WHERE k.id=?", (contrato_id,)).fetchone()
    sigla = sigla[0] if sigla else "LT"
    # issue #399: o pleito corrigido sai da lista; escrito de outro jeito (CT/001, 1) a validacao do arquivo nao o ve
    corrigidos = [(p["tipo"], *_alvo_escrito(p, sigla), p["data_base"] or "")
                  for p in c.get("pleitos_anteriores") or [] if p.get("corrige")]
    for p in c.get("pleitos_anteriores") or []:
        canon = oficios.canonico(p["oficio"], sigla, int(p["data"][:4]))
        if p.get("corrige"):
            _corrigir_pleito(conn, usuario_id, contrato_id, c, p, canon, sigla, rel, avisos)
            continue
        if any(t == p["tipo"] and b == (p["data_base"] or "") and _bate(canon, alvo, exato)
               for t, alvo, exato, b in corrigidos):
            raise ValueError(f"{c['nome_curto']}: o pleito {canon} ({p['tipo']}) é corrigido por outro item; tire-o "
                             "da lista (o item com corrige o substitui)")
        cur = conn.execute(
            "INSERT OR IGNORE INTO pleitos (contrato_id, tipo, origem, data_base_mes, ciclo, dias, numero_oficio, "
            "situacao, enviado_em, usuario_id, valor_centavos, objeto) "
            "VALUES (?,?, 'cadastro', ?,?,?,?, 'enviado', ?,?,?,?)",
            (contrato_id, p["tipo"], p["data_base"], p["ciclo"], p["dias"], canon, p["data"], usuario_id,
             p.get("valor_centavos"), p.get("objeto")))   # issue #398: o pedido de valor
        rotulo = f"{c['nome_curto']}/{p['tipo']} {canon}"
        if cur.rowcount:
            rel["criados"].append(rotulo)
            auditoria.registrar(conn, usuario_id, "cadastro.pleito", "pleito", cur.lastrowid, None,
                                {**p, "numero_oficio": canon})
        else:
            rel["iguais"] += 1
            gravado = conn.execute(
                "SELECT enviado_em, dias, ciclo, valor_centavos, objeto FROM pleitos WHERE contrato_id=? AND tipo=? "
                "AND numero_oficio=? AND COALESCE(data_base_mes, '')=COALESCE(?, '') AND origem='cadastro'",
                (contrato_id, p["tipo"], canon, p["data_base"])).fetchone()
            difere = [nome for chave, coluna, nome in _CAMPOS_PLEITO
                      if gravado is not None and p.get(chave) != gravado[coluna]]
            if difere:
                avisos.append(f"{rotulo}: {', '.join(difere)} no YAML difere do gravado; o gravado fica "
                              "(para corrigir a data ou o ofício, use corrige: {oficio, data})")


def _br(iso: str) -> str:
    return "/".join(reversed(iso[:10].split("-")))


def _alvo_escrito(p: dict, sigla: str) -> tuple[str, bool]:
    """O oficio gravado que `corrige` aponta, e se ele e' exato. Exato quando o ano esta' escrito no oficio ou vem
    `corrige.data` (o ano dela). Sem os dois, o ano nao se sabe (gate Sol, PR #411): vale so' o numero, e o pleito
    gravado e' procurado entre os existentes (`_alvo_gravado`)."""
    alvo = p["corrige"]
    canon = oficios.canonico(alvo["oficio"], sigla, int((alvo["data"] or p["data"])[:4]))
    if alvo["data"] or oficios._ANO.search(alvo["oficio"]):
        return canon, True
    return canon.rsplit("-", 1)[0] + "-", False


def _bate(numero: str | None, alvo: str, exato: bool) -> bool:
    return numero == alvo if exato else bool(numero) and numero.startswith(alvo) and len(numero) == len(alvo) + 4


def _corrigir_pleito(conn, usuario_id, contrato_id, c, p, canon, sigla, rel, avisos) -> None:
    """Issue #399: `corrige: {oficio, data?}` troca `enviado_em` e `numero_oficio` de um pleito do cadastro ja' gravado
    (a carta real, nao a copia sem protocolo). Pleito da tela nao se corrige pelo YAML. Com a data trocada, a ligacao ao
    termo e' desfeita aqui e refeita pela data nova em `_apostilamentos_de_reajuste`, que roda logo depois; o prazo se
    le' da data."""
    alvo = p["corrige"]
    nome = c["nome_curto"]
    escrito, exato = _alvo_escrito(p, sigla)
    mostra = escrito if exato else f"{escrito}<ano>"

    def achar(numero, so_cadastro=False):
        filtro = "AND origem='cadastro' " if so_cadastro else "AND situacao<>'descartado' "
        return conn.execute("SELECT * FROM pleitos WHERE contrato_id=? AND tipo=? AND numero_oficio=? "
                            f"AND COALESCE(data_base_mes, '')=COALESCE(?, '') {filtro}"
                            "ORDER BY origem='cadastro' DESC, id LIMIT 1",
                            (contrato_id, p["tipo"], numero, p["data_base"])).fetchone()

    # reaplicacao (gate Sol, PR #411): o pleito esta' com o oficio e a data novos E a auditoria mostra que foi esta
    # correcao que o levou ate' la' (oficio e, se dita, data de antes), mesmo que a tela tenha usado o numero antigo
    novo = achar(canon, so_cadastro=True)
    if novo is not None and (novo["enviado_em"] or "")[:10] == p["data"]:
        for antes_txt, depois_txt in conn.execute(
                "SELECT antes, depois FROM audit_log WHERE acao='cadastro.pleito' AND entidade='pleito' "
                "AND entidade_id=? AND antes IS NOT NULL ORDER BY id DESC", (str(novo["id"]),)):
            antes, depois = json.loads(antes_txt), json.loads(depois_txt or "{}")
            if (_bate(antes.get("numero_oficio", depois.get("numero_oficio", canon)), escrito, exato)
                    and (not alvo["data"] or (antes.get("enviado_em") or p["data"])[:10] == alvo["data"])
                    and depois.get("numero_oficio", canon) == canon
                    and (depois.get("enviado_em") or p["data"])[:10] == p["data"]):
                _mesmo_ciclo(novo, p, nome)        # gate Sol, rodada 2: o "igual" nao engole ciclo trocado no YAML
                rel["iguais"] += 1
                _avisa_diferencas(novo, p, f"{nome}/{p['tipo']} {canon}", avisos)
                return
    if exato:
        g = achar(escrito)
    else:
        # sem ano: o pleito gravado com esse numero, se for um so' (o de outro ano nao se corrige por engano)
        achados = [r for r in conn.execute(
            "SELECT * FROM pleitos WHERE contrato_id=? AND tipo=? AND COALESCE(data_base_mes, '')=COALESCE(?, '') "
            "AND situacao<>'descartado' ORDER BY id", (contrato_id, p["tipo"], p["data_base"]))
            if _bate(r["numero_oficio"], escrito, False)]
        if len(achados) > 1:
            raise ValueError(f"{nome}: há mais de um pleito {mostra} ({p['tipo']}): "
                             f"{', '.join(r['numero_oficio'] for r in achados)}; escreva o ano em corrige.oficio "
                             "ou diga corrige.data")
        g = achados[0] if achados else None
    if g is None:
        raise ValueError(f"{nome}: pleito {mostra} ({p['tipo']}) a corrigir não existe no banco (num banco montado "
                         "do zero, tire o corrige do item)")
    canon_antigo = g["numero_oficio"]
    if g["origem"] != "cadastro":
        raise ValueError(f"{nome}: o pleito {canon_antigo} ({p['tipo']}) foi criado pela tela e não se corrige "
                         "pelo cadastro")
    _mesmo_ciclo(g, p, nome)
    gravada = (g["enviado_em"] or "")[:10]
    if alvo["data"] and gravada != alvo["data"]:
        raise ValueError(f"{nome}: o pleito {canon_antigo} ({p['tipo']}) está gravado com a data {_br(gravada)}, "
                         f"não {_br(alvo['data'])}")
    if gravada == p["data"] and canon_antigo == canon:
        # gate Sol, rodada 2: sem a auditoria desta correcao, nao ha' o que corrigir; o `corrige` sobra no YAML
        raise ValueError(f"{nome}: o pleito {canon_antigo} ({p['tipo']}) já está com a data {_br(gravada)} e esse "
                         "ofício, sem correção registrada; tire o corrige do item")
    if canon != canon_antigo and (achar(canon) is not None or achar(canon, so_cadastro=True) is not None):
        raise ValueError(f"{nome}: já existe pleito {canon} ({p['tipo']}); a correção de {canon_antigo} "
                         "repetiria o ofício")
    data_mudou = gravada != p["data"]
    # so' a data muda a ligacao ao termo; trocar so' o oficio mantem o termo que atende o pleito
    chave = None if data_mudou else g["instrumento_chave"]
    antes = {"enviado_em": g["enviado_em"], "numero_oficio": canon_antigo, "instrumento_chave": g["instrumento_chave"]}
    depois = {"enviado_em": p["data"], "numero_oficio": canon, "instrumento_chave": chave}
    conn.execute("UPDATE pleitos SET enviado_em=?, numero_oficio=?, instrumento_chave=? WHERE id=?",
                 (p["data"], canon, chave, g["id"]))
    a, d = _diferencas(antes, depois)
    auditoria.registrar(conn, usuario_id, "cadastro.pleito", "pleito", g["id"], a, d)
    if data_mudou and p["tipo"] == "reajuste":
        # revisor e gate Sol (PR #411): a data nova pode mudar qual pleito do ciclo o termo atende. Desliga os outros
        # pleitos do mesmo ciclo e `_apostilamentos_de_reajuste` religa todos pela regra de sempre (o ultimo enviado
        # ate' a data do termo), chegando ao mesmo estado de uma aplicacao do zero
        for o in conn.execute("SELECT id, instrumento_chave FROM pleitos WHERE contrato_id=? AND tipo='reajuste' "
                              "AND data_base_mes=? AND ciclo=? AND instrumento_chave IS NOT NULL AND id<>?",
                              (contrato_id, g["data_base_mes"], g["ciclo"], g["id"])).fetchall():
            conn.execute("UPDATE pleitos SET instrumento_chave=NULL WHERE id=?", (o["id"],))
            auditoria.registrar(conn, usuario_id, "cadastro.pleito_atendido", "pleito", o["id"],
                                {"instrumento_chave": o["instrumento_chave"]}, {"instrumento_chave": None})
    mudancas = []
    if data_mudou:
        mudancas.append(f"data {_br(gravada)} → {_br(p['data'])}")
    if canon != canon_antigo:
        mudancas.append(f"ofício {canon_antigo} → {canon}")
    rel["alterados"].append(f"{nome}/{p['tipo']}: pleito {canon_antigo}: {', '.join(mudancas)}")
    _avisa_diferencas(g, p, f"{nome}/{p['tipo']} {canon}", avisos)


def _mesmo_ciclo(gravado, p, nome) -> None:
    if p["tipo"] == "reajuste" and gravado["ciclo"] != p["ciclo"]:
        raise ValueError(f"{nome}: o pleito {gravado['numero_oficio']} (reajuste) está gravado no ciclo "
                         f"{gravado['ciclo']}, não {p['ciclo']}; corrige troca só a data e o ofício")


def _avisa_diferencas(gravado, p, rotulo, avisos) -> None:
    """Revisor e gate Sol (PR #411): o que `corrige` nao troca (dias, valor, objeto) e difere do gravado vira o mesmo
    aviso do pleito sem `corrige` (#398); o ciclo diferente ja' parou antes."""
    difere = [nome for chave, coluna, nome in _CAMPOS_PLEITO
              if chave not in ("data", "ciclo") and p.get(chave) != gravado[coluna]]
    if difere:
        avisos.append(f"{rotulo}: {', '.join(difere)} no YAML difere do gravado; o gravado fica "
                      "(corrige troca só a data e o ofício)")


def _apostilamentos_de_reajuste(conn, usuario_id, contrato_id, c, rel) -> None:
    """Issue #271 (spec 2026-10-20 §2.2): cada competencia do apostilamento vira uma `reajuste_previsoes` de origem
    'apostilamento' (uma vez por instrumento: reaplicar nao duplica), e o ultimo pleito enviado do mesmo ciclo
    recebe `instrumento_chave`. Roda depois dos instrumentos e dos pleitos anteriores, entao o pleito que entra no
    cadastro depois do termo tambem e' ligado.

    Qual termo vale nao depende desta ordem: e' a leitura (reajuste._termo_vale) que tira o termo corrigido e da'
    precedencia pela data do documento; as previsoes do termo corrigido ficam no historico. A ordem (corrigido antes
    da correcao) serve ao pleito: a correcao herda o pleito ligado a qualquer termo da cadeia que ela corrige; so' o
    termo sem pleito herdado procura, pela data, o ultimo pleito enviado do ciclo ainda sem termo."""
    aps = [i for i in c["instrumentos"] if i["tipo"] == "apostilamento_reajuste"]
    if not aps:
        return
    por_chave = {i["chave"]: i for i in aps}
    ordenados = [i for _, i in sorted(enumerate(aps), key=lambda par: (par[1]["data"], par[0]))]
    ordem: list[dict] = []

    def poe(inst, caminho=()):
        if inst in ordem or inst["chave"] in caminho:
            return
        alvo = por_chave.get(inst["corrige"] or "")
        if alvo is not None:
            poe(alvo, (*caminho, inst["chave"]))
        ordem.append(inst)

    for inst in ordenados:
        poe(inst)

    def corrigidos(inst) -> set[str]:
        """Os termos que este corrige, direta ou indiretamente (correcao de correcao)."""
        out, k = set(), inst["corrige"]
        while k and k not in out:
            out.add(k)
            k = (por_chave.get(k) or {}).get("corrige")
        return out

    def ligar(p, inst) -> None:
        conn.execute("UPDATE pleitos SET instrumento_chave=? WHERE id=?", (inst["chave"], p["id"]))
        auditoria.registrar(conn, usuario_id, "cadastro.pleito_atendido", "pleito", p["id"],
                            {"instrumento_chave": p["instrumento_chave"]}, {"instrumento_chave": inst["chave"]})
        rel["alterados"].append(f"{c['nome_curto']}/reajuste {p['numero_oficio']}: atendido por {inst['chave']}")

    corrigidos_por_outro = {i["corrige"] for i in aps if i["corrige"]}
    bases = [d["mes"] for d in c["datas_base"]]

    def base_ciclo(inst) -> tuple:
        guardada = conn.execute("SELECT data_base_mes FROM instrumentos WHERE contrato_id=? AND chave=?",
                                (contrato_id, inst["chave"])).fetchone()[0]
        # termo ja' aplicado (gate Sol, PR #317): segue na base guardada quando foi aplicado, mesmo que o contrato
        # tenha ganhado ou trocado de data-base depois; o termo novo sem base nem chega aqui (_base_do_termo_novo)
        return (reajuste.base_do_termo(inst["dados"], guardada, bases[0] if len(bases) == 1 else None),
                reajuste.ciclo_do_apostilamento(inst["dados"], inst["data"]))

    for inst in ordem:
        dados = inst["dados"]
        iid = conn.execute("SELECT id FROM instrumentos WHERE contrato_id=? AND chave=?",
                           (contrato_id, inst["chave"])).fetchone()[0]
        base, ciclo = base_ciclo(inst)
        comps = competencias_do_apostilamento(dados)
        if comps and (base is None or ciclo is None):
            # nada de ignorar competencia em silencio: o validar so' avisa (nao sabe o que ja' foi aplicado)
            raise ValueError(f"{c['nome_curto']}/{inst['chave']}: apostilamento com competências sem data-base ou "
                             "ciclo determinável; diga data_base e ciclo no termo")
        # a correcao herda o pleito do termo que corrige (a cadeia inteira); a busca por data e' so' do termo original
        cadeia = corrigidos(inst)
        da_cadeia = conn.execute(
            f"SELECT id, instrumento_chave, numero_oficio, data_base_mes, ciclo FROM pleitos WHERE contrato_id=? "
            f"AND tipo='reajuste' AND instrumento_chave IN ({','.join('?' * len(cadeia))}) ORDER BY id",
            (contrato_id, *cadeia)).fetchall() if cadeia else []
        # so' herda o pleito do mesmo ciclo e data-base; o de outro ciclo fica sem termo (o termo dele foi corrigido)
        herdados = [p for p in da_cadeia if (p["data_base_mes"], p["ciclo"]) == (base, ciclo)]
        mesmos = {p["id"] for p in herdados}
        for p in da_cadeia:
            if p["id"] in mesmos:
                ligar(p, inst)
            else:
                conn.execute("UPDATE pleitos SET instrumento_chave=NULL WHERE id=?", (p["id"],))
                auditoria.registrar(conn, usuario_id, "cadastro.pleito_atendido", "pleito", p["id"],
                                    {"instrumento_chave": p["instrumento_chave"]}, {"instrumento_chave": None})
                rel["alterados"].append(f"{c['nome_curto']}/reajuste {p['numero_oficio']}: sem termo "
                                        f"({inst['chave']} corrige {p['instrumento_chave']} para outro ciclo)")
        if base is None or ciclo is None:
            continue
        if comps and not conn.execute("SELECT 1 FROM reajuste_previsoes WHERE instrumento_id=? LIMIT 1",
                                      (iid,)).fetchone():
            conn.executemany(
                "INSERT INTO reajuste_previsoes (contrato_id, data_base_mes, ciclo, competencia, "
                "valor_previsto_centavos, origem, instrumento_id, usuario_id) VALUES (?,?,?,?,?, 'apostilamento', ?,?)",
                [(contrato_id, base, ciclo, x["competencia"], x["valor_centavos"], iid, usuario_id) for x in comps])
            auditoria.registrar(conn, usuario_id, "cadastro.reajuste_previsoes", "instrumento", iid, None,
                                {"chave": inst["chave"], "data_base_mes": base, "ciclo": ciclo, "competencias": comps})
        # termo corrigido nao atende pleito nenhum (senao cada aplicar o religaria e a correcao o desligaria)
        if inst["chave"] in corrigidos_por_outro or herdados or conn.execute("SELECT 1 FROM pleitos WHERE contrato_id=? AND instrumento_chave=? LIMIT 1",
                                    (contrato_id, inst["chave"])).fetchone():
            continue
        # o pleito que o termo atendeu foi enviado ate' a data do termo (reemissao posterior ainda espera o dela). A
        # correcao atende o pleito que o termo original atendeu: conta a data do termo mais antigo da cadeia no mesmo
        # ciclo e data-base, e nao a dela (revisor e gate Sol, PR #411: sem isso a reemissao entre as datas dos dois
        # termos aparecia atendida quando a ligacao herdada se perdia)
        data_termo = min([inst["data"], *(por_chave[k]["data"] for k in cadeia
                                          if k in por_chave and base_ciclo(por_chave[k]) == (base, ciclo))])
        p = conn.execute("SELECT id, instrumento_chave, numero_oficio FROM pleitos WHERE contrato_id=? "
                         "AND tipo='reajuste' AND data_base_mes=? AND ciclo=? AND situacao='enviado' "
                         "AND date(enviado_em) <= date(?) ORDER BY enviado_em DESC, id DESC LIMIT 1",
                         (contrato_id, base, ciclo, data_termo)).fetchone()
        if p is not None and p["instrumento_chave"] is None:
            ligar(p, inst)


def _aditivos_de_reajuste(conn, usuario_id, contrato_id, c, rel, avisos) -> None:
    """Issue #390: na SES o reajuste sai por termo aditivo de valor (`natureza: reajuste`). Como o apostilamento, o
    aditivo atende o ultimo pleito de reajuste enviado ate' a data dele, na data-base e no ciclo que ele guarda
    (`reajuste.base_e_ciclo_do_aditivo`, migracao 058: o declarado, senao o do ultimo aniversario antes da
    assinatura), e o pleito recebe `instrumento_chave`.

    A ligacao se confere a cada aplicar (gate Sol, rodada 2, PR #407): se o destino mudou (o `ciclo` declarado depois
    da primeira aplicacao), a ligacao antiga sai, auditada, e a nova entra; sem pleito no destino, a antiga sai com
    aviso. Aditivo sem base determinavel (duas bases, nada declarado) nao se liga nem se desliga: o validar avisa."""
    bases = [d["mes"] for d in c["datas_base"]]
    unica = bases[0] if len(bases) == 1 else None
    nome = c["nome_curto"]

    def religar(p, antes, depois) -> None:
        conn.execute("UPDATE pleitos SET instrumento_chave=? WHERE id=?", (depois, p["id"]))
        auditoria.registrar(conn, usuario_id, "cadastro.pleito_atendido", "pleito", p["id"],
                            {"instrumento_chave": antes}, {"instrumento_chave": depois})

    for inst in sorted((i for i in c["instrumentos"] if i["tipo"] in TIPOS_COM_NATUREZA), key=lambda i: i["data"]):
        # o que vale e' o gravado (aditivo assinado, nao cancelado, de reajuste, com a base e o ciclo da 058)
        r = conn.execute(f"SELECT * FROM aditivos WHERE contrato_id=? AND chave_cadastro=? "
                         f"AND {reajuste.ADITIVO_DE_REAJUSTE}", (contrato_id, inst["chave"])).fetchone()
        if r is None:
            continue
        base, ciclo = reajuste.base_e_ciclo_do_aditivo(r, unica)
        if base is None:
            continue
        destino = None
        if ciclo is not None:
            p = conn.execute("SELECT id, instrumento_chave, numero_oficio FROM pleitos WHERE contrato_id=? "
                             "AND tipo='reajuste' AND data_base_mes=? AND ciclo=? AND situacao='enviado' "
                             "AND date(enviado_em) <= date(?) ORDER BY enviado_em DESC, id DESC LIMIT 1",
                             (contrato_id, base, ciclo, inst["data"])).fetchone()
            if p is not None and p["instrumento_chave"] in (None, inst["chave"]):
                destino = p
        for p in conn.execute("SELECT id, numero_oficio FROM pleitos WHERE contrato_id=? AND instrumento_chave=?",
                              (contrato_id, inst["chave"])).fetchall():
            if destino is not None and p["id"] == destino["id"]:
                continue
            religar(p, inst["chave"], None)
            rel["alterados"].append(f"{nome}/reajuste {p['numero_oficio']}: sem termo ({inst['chave']} atende o "
                                    f"ciclo {ciclo})")
            if destino is None:
                avisos.append(f"{nome}/{inst['chave']}: o aditivo de reajuste atende o ciclo {ciclo} e não há pleito "
                              f"desse ciclo enviado até a assinatura; a ligação ao pleito {p['numero_oficio']} saiu")
        if destino is not None and destino["instrumento_chave"] is None:
            religar(destino, None, inst["chave"])
            rel["alterados"].append(f"{nome}/reajuste {destino['numero_oficio']}: atendido por {inst['chave']}")


# O que torna um aditivo o que ele e': nao muda depois de aplicado (correcao e' instrumento
# novo). Numero, objeto, forma e ordinal sao descricao e podem ser corrigidos. A natureza (#262) aceita so' a
# primeira classificacao de um aditivo sem natureza (NULL) e trava depois (ver `_aditivo`).
_IMUTAVEL_ADITIVO = ("tipo", "delta_valor_centavos", "nova_execucao_fim", "nova_vigencia_fim",
                     "data_assinatura")


def _instrumentos(conn, usuario_id, contrato_id, c, rel) -> None:
    nome = c["nome_curto"]
    do_cadastro = {i["chave"] for i in c["instrumentos"]}
    # chave -> True se foi aplicada em `aditivos`, False se em `instrumentos`
    aplicadas = {r["chave_cadastro"]: True for r in conn.execute(
        "SELECT chave_cadastro FROM aditivos WHERE contrato_id=? AND chave_cadastro IS NOT NULL",
        (contrato_id,))} | {r["chave"]: False for r in conn.execute(
            "SELECT chave FROM instrumentos WHERE contrato_id=?", (contrato_id,))}
    for chave in aplicadas:
        if chave not in do_cadastro:
            raise ValueError(f"{nome}: o instrumento {chave} já foi aplicado e sumiu do cadastro; "
                             "instrumento aplicado não se apaga (correção é instrumento novo)")
    for inst in c["instrumentos"]:
        # Trocar o tipo para a outra tabela gravaria uma segunda linha com a mesma chave.
        if aplicadas.get(inst["chave"], inst["tipo"] in TIPOS_ADITIVO) != (inst["tipo"] in TIPOS_ADITIVO):
            raise ValueError(f"{nome}/{inst['chave']}: instrumento já aplicado não pode ser alterado "
                             f"(tipo → {inst['tipo']}); registre um instrumento novo com `corrige`")

    # Ordem cronologica (empate: ordem do arquivo): o retrato valor_anterior/valor_novo de
    # cada aditivo depende dos que vieram antes.
    ordenados = sorted(enumerate(c["instrumentos"]), key=lambda par: (par[1]["data"], par[0]))
    for _, inst in ordenados:
        rotulo = f"{nome}/{inst['chave']}"
        if inst["tipo"] in TIPOS_ADITIVO:
            _aditivo(conn, usuario_id, contrato_id, inst, rotulo, rel)
        else:
            _outro(conn, usuario_id, contrato_id, inst, rotulo, rel)


def _aditivo(conn, usuario_id, contrato_id, inst, rotulo, rel) -> None:
    novo = {"tipo": TIPOS_ADITIVO[inst["tipo"]], "delta_valor_centavos": inst["delta_valor_centavos"],
            "nova_execucao_fim": inst["nova_execucao_fim"], "nova_vigencia_fim": inst["nova_vigencia_fim"],
            "data_assinatura": inst["data"], "numero": inst["numero"], "objeto": inst["objeto"],
            "forma": "apostilamento" if inst["tipo"].startswith("apostilamento") else "termo_aditivo",
            "ordinal": inst.get("ordinal"),
            # None = nao classificado (conta como execucao); so' o que o YAML declara e' gravado
            "natureza": inst.get("natureza")}
    # Issue #390 (rodada 2, PR #407; migracao 058): o aditivo de reajuste guarda a base (a declarada, senao a unica de
    # agora) e o ciclo declarado; o motor do reajuste le daqui, nao do YAML
    reaj, d = inst.get("natureza") == "reajuste", inst["dados"]
    bases = [r[0] for r in conn.execute("SELECT mes FROM contrato_datas_base WHERE contrato_id=?", (contrato_id,))]
    declarada = d.get("data_base") if reaj else None
    novo["data_base_mes"] = (declarada or (bases[0] if len(bases) == 1 else None)) if reaj else None
    novo["ciclo_reajuste"] = int(str(d["ciclo"])[:4]) if reaj and d.get("ciclo") is not None else None
    ja = conn.execute("SELECT * FROM aditivos WHERE contrato_id=? AND chave_cadastro=?",
                      (contrato_id, inst["chave"])).fetchone()
    if ja is None:
        # #262 (gate Sol): o NULL e' so' do legado. Aditivo de valor novo sem natureza voltaria a inflar o saldo.
        if inst["tipo"] in TIPOS_COM_NATUREZA and novo["delta_valor_centavos"] and novo["natureza"] is None:
            raise ValueError(f"{rotulo}: aditivo de valor novo precisa de `natureza` "
                             f"({' ou '.join(NATUREZAS)}): o reajuste fica fora do saldo")
        anterior = contratos.vigente(conn, contrato_id)["valor_vigente_centavos"]
        cur = conn.execute(
            """INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, nova_vigencia_fim,
                   nova_execucao_fim, status, data_assinatura, numero, objeto, forma, chave_cadastro,
                   valor_anterior_centavos, valor_novo_centavos, assinado_por, observacao, ordinal, natureza,
                   data_base_mes, ciclo_reajuste)
               VALUES (?,?,?,?,?,'assinado',?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (contrato_id, novo["tipo"], novo["delta_valor_centavos"], novo["nova_vigencia_fim"],
             novo["nova_execucao_fim"], novo["data_assinatura"], novo["numero"], novo["objeto"],
             novo["forma"], inst["chave"], anterior, anterior + novo["delta_valor_centavos"], usuario_id,
             f"Corrige {inst['corrige']}" if inst["corrige"] else None, novo["ordinal"], novo["natureza"],
             novo["data_base_mes"], novo["ciclo_reajuste"]))
        rel["criados"].append(rotulo)
        auditoria.registrar(conn, usuario_id, "cadastro.instrumento", "aditivo", cur.lastrowid, None,
                            {"chave": inst["chave"], **novo})
        return
    for campo in _IMUTAVEL_ADITIVO:
        # A carga legada gravou o agregado como tipo 'valor' sem datas: comparar so' o que o
        # cadastro declara de diferente do que esta' gravado.
        if ja[campo] != novo[campo]:
            raise ValueError(f"{rotulo}: instrumento já aplicado não pode ser alterado "
                             f"({campo}: {ja[campo]!r} → {novo[campo]!r}); registre um instrumento novo "
                             "com `corrige`")
    # #262: a natureza se classifica UMA vez. O aditivo sem classificacao (NULL: aplicado antes da 046, ou sem o
    # campo no YAML) aceita a primeira, auditada; depois trava como os imutaveis -- inclusive apagar o campo.
    if ja["natureza"] is not None and ja["natureza"] != novo["natureza"]:
        raise ValueError(f"{rotulo}: instrumento já aplicado não pode ser alterado "
                         f"(natureza: {ja['natureza']!r} → {novo['natureza']!r}); registre um instrumento novo "
                         "com `corrige`")
    campos = {k: novo[k] for k in ("numero", "objeto", "forma", "ordinal", "natureza")}
    # base e ciclo do aditivo de reajuste (migracao 058): como a natureza, o NULL (aplicado antes da 058, ou sem
    # declaracao) aceita o primeiro valor, auditado, e trava depois. A base guardada so' muda por declaracao diferente
    # (erro); sem declaracao, segue a guardada mesmo que o contrato ganhe outra base (como a 055 no apostilamento).
    for campo, declarado in (("data_base_mes", declarada), ("ciclo_reajuste", novo["ciclo_reajuste"])):
        if ja[campo] is None:
            if novo[campo] is not None:
                campos[campo] = novo[campo]
        elif (campo == "ciclo_reajuste" or declarado is not None) and declarado != ja[campo]:
            raise ValueError(f"{rotulo}: instrumento já aplicado não pode ser alterado "
                             f"({campo}: {ja[campo]!r} → {declarado!r}); registre um instrumento novo com `corrige`")
    antes, depois = _diferencas(dict(ja), campos)
    if not depois:
        rel["iguais"] += 1
        return
    sets = ", ".join(f"{k}=?" for k in depois)
    conn.execute(f"UPDATE aditivos SET {sets} WHERE id=?", [*depois.values(), ja["id"]])
    rel["alterados"].append(rotulo)
    auditoria.registrar(conn, usuario_id, "cadastro.instrumento", "aditivo", ja["id"], antes, depois)


def _base_do_termo_novo(conn, contrato_id, inst, rotulo) -> str:
    """A data-base que o apostilamento de reajuste novo guarda (migracao 055): a dele, senao a base unica do contrato
    agora (as datas-base deste aplicar ja' estao gravadas). Termo sem base ou ciclo determinavel e' recusado, com ou
    sem competencias (gate Sol, rodada 3, PR #317): gravado, ele seria imutavel, tiraria do ciclo o termo que corrige
    e nunca fecharia ciclo nenhum."""
    bases = [r[0] for r in conn.execute("SELECT mes FROM contrato_datas_base WHERE contrato_id=?", (contrato_id,))]
    base = reajuste.base_do_termo(inst["dados"], None, bases[0] if len(bases) == 1 else None)
    if base is None or reajuste.ciclo_do_apostilamento(inst["dados"], inst["data"]) is None:
        raise ValueError(f"{rotulo}: apostilamento de reajuste sem data-base ou ciclo determinável; "
                         "diga data_base e ciclo no termo")
    return base


def _outro(conn, usuario_id, contrato_id, inst, rotulo, rel) -> None:
    novo = {"tipo": inst["tipo"], "numero": inst["numero"], "data": inst["data"],
            "dados": _json({**inst["dados"], "objeto": inst["objeto"], "corrige": inst["corrige"]})}
    ja = conn.execute("SELECT * FROM instrumentos WHERE contrato_id=? AND chave=?",
                      (contrato_id, inst["chave"])).fetchone()
    if ja is None:
        base = _base_do_termo_novo(conn, contrato_id, inst, rotulo) if inst["tipo"] == "apostilamento_reajuste" else None
        cur = conn.execute("INSERT INTO instrumentos (contrato_id, chave, tipo, numero, data, dados, pdf, data_base_mes) "
                           "VALUES (?,?,?,?,?,?,?,?)", (contrato_id, inst["chave"], novo["tipo"], novo["numero"],
                                                        novo["data"], novo["dados"], inst["pdf"], base))
        rel["criados"].append(rotulo)
        auditoria.registrar(conn, usuario_id, "cadastro.instrumento", "instrumento", cur.lastrowid, None,
                            {"chave": inst["chave"], **novo})
        return
    for campo in ("tipo", "numero", "data", "dados"):
        if ja[campo] != novo[campo]:
            raise ValueError(f"{rotulo}: instrumento já aplicado não pode ser alterado ({campo}); "
                             "registre um instrumento novo com `corrige`")
    if ja["pdf"] != inst["pdf"]:
        conn.execute("UPDATE instrumentos SET pdf=? WHERE id=?", (inst["pdf"], ja["id"]))
        rel["alterados"].append(rotulo)
        auditoria.registrar(conn, usuario_id, "cadastro.instrumento", "instrumento", ja["id"],
                            {"pdf": ja["pdf"]}, {"pdf": inst["pdf"]})
        return
    rel["iguais"] += 1


# --- geral.yaml e regra do espelho (bloco 2) ------------------------------------------------

def pasta_modelos() -> Path:
    """Modelos Word copiados pelo hash: a producao nao le o checkout em tempo de execucao."""
    p = db.db_path().parent / "modelos"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _geral(conn, usuario_id, geral, rel) -> None:
    if not geral:
        return
    for chave, valor in geral.items():
        novo = _json(valor)
        ja = conn.execute("SELECT valor FROM cadastro_geral WHERE chave=?", (chave,)).fetchone()
        if ja is None:
            conn.execute("INSERT INTO cadastro_geral (chave, valor) VALUES (?,?)", (chave, novo))
            rel["criados"].append(chave)
            auditoria.registrar(conn, usuario_id, "cadastro.geral", "cadastro_geral", chave, None, valor)
        elif ja["valor"] != novo:
            conn.execute("UPDATE cadastro_geral SET valor=?, atualizado_em=datetime('now') WHERE chave=?",
                         (novo, chave))
            rel["alterados"].append(chave)
            auditoria.registrar(conn, usuario_id, "cadastro.geral", "cadastro_geral", chave,
                                json.loads(ja["valor"]), valor)
        else:
            rel["iguais"] += 1


def _espelhos(conn, usuario_id, lista, rel, ensaio) -> None:
    for e in lista:
        cid = conn.execute("SELECT id FROM contratos WHERE nome_curto=?", (e["contrato"],)).fetchone()
        if cid is None:
            raise ValueError(f"espelho/{e['slug']}.yaml: contrato {e['contrato']!r} não está no banco")
        cid = cid[0]
        modelos = {k: {"arquivo": f"modelos/{m['sha256']}.docx", "sha256": m["sha256"]}
                   for k, m in e["modelos"].items()}
        novo = {"situacao": e["situacao"], "regra": _json(e["regra"]), "modelos": _json(modelos),
                "sha256": e["sha256"]}
        ja = conn.execute("SELECT * FROM espelho_regras WHERE contrato_id=?", (cid,)).fetchone()
        antes = depois = {}
        if ja is not None:
            antes, depois = _diferencas(dict(ja), novo)
            if not depois:
                rel["iguais"] += 1
                continue
        if not ensaio:
            from app import arquivos
            for m in e["modelos"].values():
                # copia pelo hash, reconferindo o que ja' existe (arquivo truncado ou trocado a mao)
                arquivos.gravar_bytes("modelos", Path(m["caminho"]).read_bytes(), "docx")
        if ja is None:
            conn.execute("INSERT INTO espelho_regras (contrato_id, situacao, regra, modelos, sha256) "
                         "VALUES (?,?,?,?,?)",
                         (cid, novo["situacao"], novo["regra"], novo["modelos"], novo["sha256"]))
            rel["criados"].append(e["contrato"])
            auditoria.registrar(conn, usuario_id, "cadastro.espelho", "contrato", cid, None,
                                {"situacao": e["situacao"], "sha256": e["sha256"], "modelos": modelos})
            continue
        conn.execute("UPDATE espelho_regras SET situacao=?, regra=?, modelos=?, sha256=?, "
                     "atualizado_em=datetime('now') WHERE contrato_id=?",
                     (novo["situacao"], novo["regra"], novo["modelos"], novo["sha256"], cid))
        rel["alterados"].append(e["contrato"])
        # a regra em si nao vai para a auditoria (JSON grande); o hash a identifica
        resumo_antes = {k: v for k, v in antes.items() if k != "regra"}
        resumo_depois = {k: v for k, v in depois.items() if k != "regra"}
        if "regra" in depois:
            resumo_antes["regra_sha256"], resumo_depois["regra_sha256"] = ja["sha256"], e["sha256"]
        auditoria.registrar(conn, usuario_id, "cadastro.espelho", "contrato", cid, resumo_antes, resumo_depois)
