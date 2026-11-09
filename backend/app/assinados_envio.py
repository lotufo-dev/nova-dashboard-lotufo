"""Envio dos documentos assinados ao orgao (issue #627; SINFRA).

Depois do boletim do orgao a Lotufo devolve, na mesma conversa da planilha/carta, o pacote da medicao assinado no
DocuSign, o do reajuste do par (o SIGADOC quer um arquivo para cada) e, quando o orgao ressalva, a justificativa de
atraso do cronograma. Dois atos: "Enviar documentos assinados" (o e-mail sai da conta de quem clicou, tipo
`assinados`, com reserva atomica antes, `envio_reserva`) e "Registrar envio dos assinados por fora". Os dois gravam
uma linha em `medicao_assinados_envios` (migracao 080) e o evento de assinatura com o PDF em cada medicao que foi
(execucao e reajuste). Reenvio (pacote corrigido) e' um envio novo, com motivo; o anterior fica no historico.

Os PDFs chegam a cada chamada (previa e envio): nada fica guardado antes do envio. A previa devolve nome, tamanho e
sha256 de cada anexo, e o envio recusa se o que chegou nao for o que a pessoa conferiu.
"""
import datetime
import hashlib

from app import arquivos, auditoria, carta, correio, db, envio_reserva, medicoes, pleitos, tempo
from app.planilha_envio import AnexosMudaram, _conferir_anexos, _contexto, _medicao

TABELA = "medicao_assinados_envios"
TIPO_ENVIO = "assinados"
FAMILIA = "sinfra"
MIN_MOTIVO = 10
MB = 1024 * 1024
# depois do envio da nota ao orgao (protocolo) os assinados ja' foram; cancelada e desistida nao enviam nada
ESTADOS_SEM_ENVIO = ("protocolada", "nf_emitida", "recebida", "cancelada", "desistida")
# o teto do pedido com arquivos (limites.TETO_MULTIPART, 45 MB) menos a folga do multipart: a tela confere a soma
TETO_REGISTRO = 44 * 1024 * 1024
CORPO = "Encaminho, em anexo, os documentos assinados."
CORPO_COM_JUSTIFICATIVA = "Encaminho, em anexo, os documentos assinados e a justificativa de atraso do cronograma."
ROTULO_DOC = {"medicao": "PDF assinado da medição", "reajuste": "PDF assinado do reajuste",
              "justificativa": "justificativa de atraso"}

__all__ = ["AnexosMudaram"]


# --- leitura ---------------------------------------------------------------------------------------

def recusa(conn, m: dict) -> str | None:
    """Por que esta medicao nao envia os documentos assinados (None: envia)."""
    try:
        _, familia, _ = _contexto(conn, m)
    except ValueError as e:
        return str(e)
    if familia != FAMILIA:
        return "Os documentos assinados só vão ao órgão por e-mail na SINFRA"
    nome = medicoes.nome_medicao(m["numero"], m["tipo"])
    if m["estado"] in ("cancelada", "desistida"):
        return f"{nome} está {medicoes.rotulo_estado(m['estado'])}: não envia documentos assinados"
    if not medicoes.tem_boletim(conn, m["id"]):
        return "Registre o boletim do órgão antes da assinatura"
    if m["estado"] in ESTADOS_SEM_ENVIO:
        return (f"{nome} está {medicoes.rotulo_estado(m['estado'])}: os documentos assinados vão antes do envio da "
                "nota")
    return None


def par(conn, m: dict) -> dict | None:
    """A medicao de reajuste de mesmo nº e competencia, quando existe e tambem tem boletim: o PDF assinado dela vai no
    mesmo e-mail, num arquivo separado. A de reajuste nao tem par aqui (vai sozinha)."""
    if m["tipo"] == "reajuste":
        return None
    r = conn.execute("SELECT * FROM medicoes WHERE contrato_id=? AND numero=? AND competencia=? AND tipo='reajuste'",
                     (m["contrato_id"], m["numero"], m["competencia"])).fetchone()
    if r is None or r["estado"] in ESTADOS_SEM_ENVIO or not medicoes.tem_boletim(conn, r["id"]):
        return None
    return dict(r)


def limite(regras: dict) -> tuple[int, str]:
    """(bytes, recusa) de cada PDF: o limite por documento do orgao; sem ele, o teto do e-mail."""
    mb = regras.get("limite_mb_por_documento")
    if mb:
        return int(mb * MB), f"PDF acima de {mb} MB, o limite por documento do órgão: divida o arquivo"
    teto = correio.MAX_TOTAL // MB
    return correio.MAX_TOTAL, f"PDF acima de {teto} MB, o limite do e-mail: divida o arquivo"


# Uma linha e' envio de cada medicao cujo PDF foi nela: a execucao (`medicao_id`) e o reajuste do par
# (`reajuste_id`). As conferencias olham todas as medicoes que vao no envio (code-review e revisao da PR #635).
def _onde(ids: list[int]) -> tuple[str, list[int]]:
    marcas = ",".join("?" * len(ids))
    return f"(a.medicao_id IN ({marcas}) OR a.reajuste_id IN ({marcas}))", [*ids, *ids]


def _ids(m: dict, p: dict | None, docs: dict) -> list[int]:
    """As medicoes deste envio: a da pagina e, quando o PDF dele vai, o reajuste do par."""
    return [m["id"], *((p["id"],) if p and docs.get("reajuste") else ())]


def _concluidos(conn, medicao_id: int | list[int]) -> int:
    ids = medicao_id if isinstance(medicao_id, list) else [medicao_id]
    onde, args = _onde(ids)
    return conn.execute(f"SELECT COUNT(*) FROM {TABELA} a WHERE {onde} AND (a.envio_id IS NOT NULL OR "
                        "a.origem='externo')", args).fetchone()[0]


def _reservada(conn, medicao_id: int | list[int]):
    """A linha com o e-mail saindo (ou preso) de uma destas medicoes, como execucao ou como reajuste do par."""
    ids = medicao_id if isinstance(medicao_id, list) else [medicao_id]
    onde, args = _onde(ids)
    return conn.execute(f"SELECT a.id, a.envio_reservado_em, a.envio_reservado_por, u.nome AS reservado_por_nome "
                        f"FROM {TABELA} a LEFT JOIN usuarios u ON u.id=a.envio_reservado_por "
                        f"WHERE {onde} AND a.envio_id IS NULL AND a.envio_reservado_em IS NOT NULL "
                        "ORDER BY a.id DESC LIMIT 1", args).fetchone()


def envios(conn, medicao_id: int) -> list[dict]:
    """Os envios concluidos (pelo sistema e por fora), do 1o ao vigente (o ultimo)."""
    lista = [dict(r) for r in conn.execute(
        f"SELECT a.id, a.origem, a.assinado_em, a.motivo, a.envio_id, a.reajuste_id, a.nome, a.nome_reajuste, "
        f"a.nome_justificativa, v.enviado_em, u.nome AS usuario FROM {TABELA} a LEFT JOIN envios v ON v.id=a.envio_id "
        "LEFT JOIN usuarios u ON u.id=a.usuario_id WHERE (a.medicao_id=? OR a.reajuste_id=?) "
        "AND (a.envio_id IS NOT NULL OR a.origem='externo') ORDER BY a.id", (medicao_id, medicao_id))]
    for i, e in enumerate(lista):
        e["vigente"] = i == len(lista) - 1
    return lista


def _reserva(conn, medicao_id: int) -> dict | None:
    r = _reservada(conn, medicao_id)
    return ({"tabela": TABELA, "id": r["id"], "envio_reservado_em": r["envio_reservado_em"],
             "reservado_por": r["reservado_por_nome"]} if r else None)


def situacao(conn, medicao_id: int) -> dict:
    """O que a tela precisa para oferecer (ou nao) os dois atos."""
    m = _medicao(conn, medicao_id)
    motivo = recusa(conn, m)
    out = {"disponivel": motivo is None, "motivo": motivo, "reajuste": None, "limite": None, "limite_recusa": None,
           "teto_registro": None, "limite_email": correio.MAX_TOTAL,
           "envios": envios(conn, medicao_id), "reserva": _reserva(conn, medicao_id)}
    if motivo is None:
        _, _, regras = _contexto(conn, m)
        p = par(conn, m)
        out["reajuste"] = {"id": p["id"], "numero": p["numero"]} if p else None
        out["limite"], out["limite_recusa"] = limite(regras)
        out["teto_registro"] = TETO_REGISTRO
    return out


# --- conferencia dos PDFs ----------------------------------------------------------------------------

def conferir(conn, medicao_id: int, docs: dict) -> tuple[dict, dict, dict, dict | None]:
    """Recusas (ValueError) do que chegou, sem gravar nada. `docs`: {"medicao": (nome, bytes), "reajuste": ... ou
    None, "justificativa": ... ou None}. Devolve (medicao, contrato, regras, par)."""
    m = _medicao(conn, medicao_id)
    motivo = recusa(conn, m)
    if motivo:
        raise ValueError(motivo)
    c, _, regras = _contexto(conn, m)
    if not docs.get("medicao"):
        raise ValueError("Anexe o PDF assinado da medição")
    p = par(conn, m)
    if docs.get("reajuste") and p is None:
        raise ValueError("Esta medição não tem reajuste com boletim para receber o PDF assinado")
    teto, recusa_teto = limite(regras)
    for chave in ("medicao", "reajuste", "justificativa"):
        if docs.get(chave) and len(docs[chave][1]) > teto:
            raise ValueError(recusa_teto)
    return m, c, regras, p


def _anexos(docs: dict) -> list[tuple[str, bytes, str]]:
    """(nome, bytes, origem): o da medicao, o do reajuste e a justificativa, nessa ordem, com nomes unicos."""
    usados: set[str] = set()
    out = []
    for chave in ("medicao", "reajuste", "justificativa"):
        if docs.get(chave):
            nome, dados = docs[chave]
            nome = (nome or f"{chave}.pdf").replace("/", "-").replace("\\", "-")[-200:]
            out.append((pleitos._nome_unico(nome, usados), dados, chave))
    return out


# --- previa ----------------------------------------------------------------------------------------

def _ids_da_planilha(conn, m: dict) -> list[int]:
    """A medicao e, na de reajuste, a execucao (ou projeto) de mesmo nº e competencia: a planilha/carta do reajuste
    vai com a dela (#590)."""
    if m["tipo"] != "reajuste":
        return [m["id"]]
    return [m["id"], *(r[0] for r in conn.execute(
        "SELECT id FROM medicoes WHERE contrato_id=? AND numero=? AND competencia=? AND tipo<>'reajuste'",
        (m["contrato_id"], m["numero"], m["competencia"])))]


def _assunto(conn, c: dict, m: dict) -> str:
    """"RE: " + o assunto do ultimo envio da planilha/carta pelo sistema; foi por fora, o assunto do modelo do orgao."""
    ids = _ids_da_planilha(conn, m)
    r = conn.execute("SELECT v.assunto FROM medicao_planilha_envios e JOIN envios v ON v.id=e.envio_id "
                     f"WHERE e.medicao_id IN ({','.join('?' * len(ids))}) ORDER BY v.enviado_em DESC, v.id DESC LIMIT 1",
                     ids).fetchone()
    if r and r["assunto"]:
        base = r["assunto"]
    else:
        base = _assunto_do_modelo(conn, c, m)
    return base if base.upper().startswith("RE:") else f"RE: {base}"


def _assunto_do_modelo(conn, c: dict, m: dict) -> str:
    from app import planilha_envio
    obra = pleitos._obra(c)
    reserva = f"{medicoes.titulo(m)} - {c.get('numero_instrumento') or ''} - {obra}".replace(" -  - ", " - ")
    try:
        modelo = planilha_envio._textos(conn, FAMILIA)["email_assunto"]
    except ValueError:
        return reserva
    if not modelo:
        return reserva
    v = planilha_envio._vigente(conn, m["id"])
    mes, ano = m["competencia"][5:7], m["competencia"][:4]
    periodo = ""
    if v and v.get("periodo_inicio") and v.get("periodo_fim"):
        ini, fim = (datetime.date.fromisoformat(x) for x in (v["periodo_inicio"], v["periodo_fim"]))
        periodo = f"{ini:%d/%m/%Y} a {fim:%d/%m/%Y}"
    campos = {"oficio": "", "medicao": medicoes.titulo(m), "numero": f"{m['numero']}ª", "competencia": f"{mes}/{ano}",
              "competencia_sublinhada": f"{mes}_{ano}", "periodo": periodo,
              "instrumento": c.get("numero_instrumento") or "", "obra": obra, "saudacao": "",
              "revisao": "", "lista_anexos": ""}
    # sem o nº do oficio (a planilha/carta foi por fora), o separador que ficaria solto no comeco sai
    return carta.preencher(modelo, campos).strip().lstrip("-– ").strip() or reserva


def previa(conn, medicao_id: int, docs: dict, remetente: str | None = None,
           hoje: datetime.date | None = None) -> dict:
    """Destinatarios, assunto, corpo e anexos sugeridos (a pessoa confere e pode editar o texto antes de enviar)."""
    hoje = hoje or tempo.hoje_local()
    m, c, regras, p = conferir(conn, medicao_id, docs)
    anexos = _anexos(docs)
    para, copia = pleitos._destinatarios(conn, regras, c, hoje)     # os mesmos do envio da planilha/carta
    if remetente:
        fora = {remetente.lower()} | correio.contas_do_usuario(conn, remetente)
        copia = [x for x in copia if x.lower() not in fora]
    total = sum(len(b) for _, b, _ in anexos)
    pend = []
    if total > correio.MAX_TOTAL:
        pend.append({"codigo": "tamanho", "mensagem": f"Anexos somam {total // MB} MB, acima do limite do e-mail "
                                                      f"({correio.MAX_TOTAL // MB} MB)"})
    anteriores = _concluidos(conn, _ids(m, p, docs))
    return {"medicao_id": medicao_id, "para": para, "copia": copia, "assunto": _assunto(conn, c, m),
            "corpo": CORPO_COM_JUSTIFICATIVA if docs.get("justificativa") else CORPO,
            "anexos": [{"nome": n, "tamanho": len(b), "sha256": hashlib.sha256(b).hexdigest(), "origem": o}
                       for n, b, o in anexos], "total": total, "limite": correio.MAX_TOTAL, "pendencias": pend,
            "reajuste": {"id": p["id"], "numero": p["numero"]} if p else None,
            "reenvio": anteriores > 0, "anteriores": anteriores}


# --- gravacao --------------------------------------------------------------------------------------

def _gravar_pdfs(docs: dict) -> dict:
    """Grava os PDFs pelo hash (antes da reserva: o que sobrar de um envio recusado tem o nome do proprio hash e e'
    reaproveitado no proximo, como em api_medicoes._gravar_e_registrar) e le o envelope do DocuSign de cada um."""
    out = {}
    for nome, dados, chave in _anexos(docs):      # o nome do anexo que vai no e-mail (unico, sem barra)
        rel, sha = arquivos.gravar_bytes("assinados", dados, "pdf")
        out[chave] = {"nome": nome, "arquivo": rel, "sha256": sha,
                      "envelope": medicoes.envelope_do_pdf(dados) if chave != "justificativa" else None}
    return out


def _inserir(conn, usuario_id: int, m: dict, p: dict | None, gravados: dict, origem: str, data: str,
             motivo: str | None, anteriores: int, eml: str | None = None) -> int:
    reaj = gravados.get("reajuste") or {}
    just = gravados.get("justificativa") or {}
    return conn.execute(
        f"INSERT INTO {TABELA} (medicao_id, reajuste_id, origem, assinado_em, arquivo, sha256, nome, arquivo_reajuste, "
        "sha256_reajuste, nome_reajuste, arquivo_justificativa, sha256_justificativa, nome_justificativa, eml, motivo, "
        "anteriores, usuario_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (m["id"], p["id"] if p and reaj else None, origem, data, gravados["medicao"]["arquivo"],
         gravados["medicao"]["sha256"], gravados["medicao"]["nome"], reaj.get("arquivo"), reaj.get("sha256"),
         reaj.get("nome"), just.get("arquivo"), just.get("sha256"), just.get("nome"), eml, motivo, anteriores,
         usuario_id)).lastrowid


def _assinaturas(conn, usuario_id: int, m: dict, p: dict | None, gravados: dict, data: str, origem: str,
                 linha_id: int, envio_id: int | None) -> None:
    """Um evento de assinatura por medicao que foi (a execucao e, quando o PDF dele foi, o reajuste)."""
    alvos = [(m["id"], gravados["medicao"])]
    if p and gravados.get("reajuste"):
        alvos.append((p["id"], gravados["reajuste"]))
    for mid, g in alvos:
        medicoes.gravar_assinatura(conn, usuario_id, mid, data, g["envelope"], g["arquivo"], g["sha256"],
                                   envio_id, origem, linha_id)


def _data(conn, ids: list[int], assinado_em: str | None, hoje: datetime.date) -> str:
    """A data vale para cada medicao do envio: nao vem antes do boletim de nenhuma delas (revisao da PR #635)."""
    for mid in ids:
        data = medicoes.conferir_data_assinatura(conn, mid, assinado_em or hoje.isoformat()).isoformat()
    return data


def _conferir_motivo(conn, ids: list[int], motivo: str | None) -> int:
    anteriores = _concluidos(conn, ids)
    if anteriores and len(motivo or "") < MIN_MOTIVO:
        raise ValueError(f"Os documentos assinados já foram enviados: informe o motivo do reenvio (ao menos "
                         f"{MIN_MOTIVO} caracteres)")
    return anteriores


def _conferir_anteriores(conn, ids: list[int], vistos: int | None) -> None:
    """Outro envio concluido depois da previa (revisao da PR #635): 409, antes de pedir o motivo que a tela de quem
    abriu a previa de um primeiro envio nem mostra."""
    if vistos is not None and _concluidos(conn, ids) != vistos:
        raise envio_reserva.EnvioEmAndamento(
            "Outro envio dos documentos assinados terminou depois da sua prévia: confira a linha do tempo e abra a "
            "prévia de novo antes de enviar", "ENVIO_CONCLUIDO_NO_MEIO")


def _sem_reserva_ativa(conn, ids: list[int]) -> None:
    r = _reservada(conn, ids)
    if r is not None:
        raise envio_reserva.reservado(conn, r["envio_reservado_em"], r["envio_reservado_por"])


def enviar(conn, usuario: dict, medicao_id: int, docs: dict, para: list[str], copia: list[str], assunto: str,
           corpo: str, anexos_previa: list[dict], motivo: str | None = None, assinado_em: str | None = None,
           cco: list[str] | None = None, hoje: datetime.date | None = None, anteriores_vistos: int | None = None) -> int:
    """`anexos_previa` (nome, tamanho e sha256) e' obrigatorio: o e-mail leva o que a pessoa conferiu na previa.
    `anteriores_vistos`: os envios concluidos que a previa mostrou; outro envio concluido desde entao recusa (409)."""
    hoje = hoje or tempo.hoje_local()
    # Tudo o que recusa vem ANTES do e-mail (que nao se desfaz).
    pv = previa(conn, medicao_id, docs, hoje=hoje)
    para = [x.strip() for x in para if x.strip()]
    if not para:
        raise ValueError("Informe ao menos um destinatário")
    if pv["total"] > correio.MAX_TOTAL:
        raise ValueError("Anexos acima do limite do e-mail")
    _conferir_anexos(anexos_previa, pv["anexos"])
    motivo = (motivo or "").strip() or None
    m, _, _, p = conferir(conn, medicao_id, docs)
    ids = _ids(m, p, docs)
    data = _data(conn, ids, assinado_em, hoje)
    _conferir_anteriores(conn, ids, anteriores_vistos)
    _conferir_motivo(conn, ids, motivo)
    gravados = _gravar_pdfs(docs)
    anexos = [(n, b) for n, b, _ in _anexos(docs)]
    # Reserva atomica antes do e-mail: dois cliques simultaneos mandam um e-mail so'. Tudo sob o mesmo BEGIN IMMEDIATE:
    # outro envio reservado (409), outro envio concluido desde a previa (o reenvio pede motivo) e o estado.
    with db.mutacao(conn):
        m, _, _, p = conferir(conn, medicao_id, docs)
        ids = _ids(m, p, docs)
        _data(conn, ids, data, hoje)
        _sem_reserva_ativa(conn, ids)
        _conferir_anteriores(conn, ids, anteriores_vistos)
        anteriores = _conferir_motivo(conn, ids, motivo)
        rid = _inserir(conn, usuario["id"], m, p, gravados, "sistema", data, motivo, anteriores)
        envio_reserva.reservar(conn, TABELA, rid, usuario["id"], None)
    try:
        envio_id = correio.enviar_e_registrar(conn, usuario, TIPO_ENVIO, para, [x.strip() for x in copia if x.strip()],
                                              assunto, pleitos._html(corpo), anexos, cco=cco)
    except correio.EnvioNaoRegistrado:
        raise                                       # o e-mail saiu: a reserva fica e segura a repeticao
    except Exception:
        envio_reserva.liberar_com_retentativa(conn, TABELA, rid)    # nada saiu: destrava e sobe o erro
        raise
    # O e-mail ja' saiu: daqui para baixo nada recusa.
    with correio.depois_do_envio(assunto, para, envio_id), db.mutacao(conn):
        envio_reserva.liberar(conn, TABELA, rid)
        conn.execute(f"UPDATE {TABELA} SET envio_id=? WHERE id=?", (envio_id, rid))
        for mid in (m["id"], *((p["id"],) if p and gravados.get("reajuste") else ())):
            conn.execute("INSERT OR IGNORE INTO envio_medicoes (envio_id, medicao_id) VALUES (?,?)", (envio_id, mid))
        _assinaturas(conn, usuario["id"], m, p, gravados, data, "sistema", rid, envio_id)
        auditoria.registrar(conn, usuario["id"], "medicao.assinados_envio", "medicao", medicao_id, None,
                            {"envio_id": envio_id, "assinados_envio_id": rid, "origem": "sistema", "assinado_em": data,
                             "motivo": motivo, "anteriores": anteriores,
                             "anexos": [a["nome"] for a in pv["anexos"]]})
    return envio_id


def _data_do_envio(conn, ids: list[int], enviado_em: str) -> str:
    """As recusas da data da assinatura (o evento grava esta data), com o nome do campo da tela."""
    try:
        return _data(conn, ids, enviado_em, tempo.hoje_local())
    except ValueError as e:
        raise ValueError(str(e).replace("Data da assinatura", "Data do envio")
                         .replace("data da assinatura", "data do envio")) from None


def registrar_por_fora(conn, usuario_id: int, medicao_id: int, docs: dict, enviado_em: str,
                       eml: tuple[str, bytes] | None = None, motivo: str | None = None) -> int:
    """"Registrar envio dos assinados por fora": data (nao futura, nao anterior ao boletim), o PDF assinado, os
    opcionais e o .eml (com a mesma conferencia do envio por fora da planilha/carta). Sem e-mail."""
    from app import notas_envio       # import local: notas_envio importa protocolo, que importa medicoes
    m, _, _, p = conferir(conn, medicao_id, docs)
    data = _data_do_envio(conn, _ids(m, p, docs), enviado_em)
    if eml:
        if len(eml[1]) > notas_envio.TETO_EML:
            raise ValueError("Arquivo .eml acima de 25 MB")
        if not notas_envio._e_email(eml[1]):
            raise ValueError(notas_envio.NAO_E_EML)
    motivo = (motivo or "").strip() or None
    gravados = _gravar_pdfs(docs)
    rel_eml = arquivos.gravar_bytes("evidencias", eml[1], "eml")[0] if eml else None
    with db.mutacao(conn):
        m, _, _, p = conferir(conn, medicao_id, docs)
        ids = _ids(m, p, docs)
        _data_do_envio(conn, ids, data)
        # o que esta' saindo pelo sistema (reserva ativa) nao se registra por fora: seriam dois envios
        if _reservada(conn, ids) is not None:
            raise ValueError("Os documentos assinados estão sendo enviados pelo sistema: aguarde o envio terminar (ou "
                             "libere o envio preso) antes de registrar o envio por fora")
        # clique duplo, ou a repeticao depois de uma resposta que se perdeu: o registro nao se apaga depois
        if conn.execute(f"SELECT 1 FROM {TABELA} WHERE medicao_id=? AND origem='externo' AND sha256=? "
                        "AND assinado_em=?", (medicao_id, gravados["medicao"]["sha256"], data)).fetchone():
            raise ValueError("Este envio dos documentos assinados já está registrado")
        anteriores = _concluidos(conn, ids)
        rid = _inserir(conn, usuario_id, m, p, gravados, "externo", data, motivo, anteriores, rel_eml)
        _assinaturas(conn, usuario_id, m, p, gravados, data, "externo", rid, None)
        auditoria.registrar(conn, usuario_id, "medicao.assinados_envio", "medicao", medicao_id, None,
                            {"assinados_envio_id": rid, "origem": "externo", "enviado_em": data, "eml": rel_eml,
                             "motivo": motivo, "anteriores": anteriores,
                             "anexos": [g["nome"] for g in gravados.values()]})
    return rid
