"""Envio da planilha/carta ao protocolo do orgao (issue #282; spec 2026-10-20 §2.1, passo 2, "E-mail" e "O que
congela"; E3 e D11, decididas em 20/10/2026).

A operacao clica "Enviar para protocolo": o e-mail sai da conta dela (tipo `planilha`), com o oficio assinado, a
planilha zipada e as pecas que o orgao pede na medicao (`orgaos.pecas`, pela natureza), para os enderecos de
protocolo do orgao com as copias do cadastro. Reserva atomica antes do e-mail (`envio_reserva`, tabela
`medicao_planilha_envios` da migracao 053: uma linha por versao enviada). A 1a versao enviada poe a medicao em
`planilha_enviada` (data e origem `sistema`) e congela o pedido no valor DELA; revisao depois do envio e' versao
nova (`medicao_planilhas.revisar`, com motivo), enviada de novo por aqui sem mudar o pedido congelado.
Na MT-PAR nao ha' esse passo: o oficio vai com a nota.

Modulo proprio, ao lado de `medicao_planilhas` (registro e revisao, #281) e de `pleitos` (de onde vem o desenho do
envio). O texto do e-mail e' do cadastro (`cartas.yaml`, chave `planilha`).
"""
import datetime
import hashlib
import io
import zipfile

from app import arquivos, auditoria, carta, correio, db, envio_reserva, espelhos, medicoes, oficios, pleitos, tempo
from app.protocolo import AnexosMudaram     # a mesma recusa (com `codigo`) do envio da nota e do protocolo

TABELA = "medicao_planilha_envios"
TIPO_ENVIO = "planilha"
ESTADOS_ENVIO = ("planilha_gerada", "planilha_enviada")
FAMILIAS_SEM_ENVIO = ("mtpar",)
SEM_ENVIO_MTPAR = "Na MT-PAR não há envio da planilha/carta: o ofício vai com a nota"
MIN_JUSTIFICATIVA = 10
EXTENSOES_PECA = ("pdf", "xlsx")
ROTULO_NATUREZA = {"execucao": "Medição", "projeto": "Projeto", "reajuste": "Reajuste"}
# data fixa dentro do zip: o mesmo arquivo da o mesmo zip (e o mesmo tamanho) na previa e no envio
_DATA_ZIP = (1980, 1, 1, 0, 0, 0)


# --- leitura ---------------------------------------------------------------------------------------

def _medicao(conn, medicao_id: int) -> dict:
    m = conn.execute("SELECT * FROM medicoes WHERE id=?", (medicao_id,)).fetchone()
    if m is None:
        raise ValueError("Medição não encontrada")
    return dict(m)


def _contexto(conn, m: dict) -> tuple[dict, str, dict]:
    """(contrato, familia do orgao, regras do orgao)."""
    c = dict(conn.execute("SELECT * FROM contratos WHERE id=?", (m["contrato_id"],)).fetchone())
    if not c.get("orgao_id"):
        raise ValueError("Contrato sem órgão no cadastro: não há para quem mandar a planilha/carta")
    familia, regras, _ = pleitos._orgao(conn, c)
    return c, familia, regras


def _vigente(conn, medicao_id: int) -> dict | None:
    r = conn.execute("SELECT * FROM medicao_planilhas WHERE medicao_id=? ORDER BY versao DESC LIMIT 1",
                     (medicao_id,)).fetchone()
    return dict(r) if r else None


def _ultima_enviada(conn, m: dict) -> int:
    """A maior versao ja' enviada. Medicao em `planilha_enviada` sem envio pelo sistema (carga do historico, envio
    por fora) tem ao menos a 1a enviada: so' a revisao sai daqui, nunca a mesma planilha/carta de novo."""
    r = conn.execute(f"SELECT MAX(p.versao) FROM {TABELA} e JOIN medicao_planilhas p ON p.id=e.planilha_id "
                     "WHERE e.medicao_id=? AND e.envio_id IS NOT NULL", (m["id"],)).fetchone()[0] or 0
    return max(r, 1) if m["estado"] == "planilha_enviada" else r


def _recusa(conn, m: dict) -> str | None:
    """Por que esta medicao nao envia a planilha/carta agora (None: envia). A ordem e' a do que a tela explica."""
    try:
        _, familia, _ = _contexto(conn, m)
    except ValueError as e:
        return str(e)
    if familia in FAMILIAS_SEM_ENVIO:
        return SEM_ENVIO_MTPAR
    nome = medicoes.nome_medicao(m["numero"], m["tipo"])
    if m["estado"] not in ESTADOS_ENVIO:
        if m["estado"] == "prevista":
            return f"{nome} ainda não tem planilha/carta registrada"
        return (f"{nome} está {medicoes.rotulo_estado(m['estado'])}: a planilha/carta só se envia antes do boletim "
                "do órgão")
    v = _vigente(conn, m["id"])
    if v is None:
        return f"{nome} não tem planilha/carta registrada"
    if v["versao"] <= _ultima_enviada(conn, m):
        return f"A versão {v['versao']} da planilha/carta já foi enviada: para enviar de novo, registre uma revisão"
    return None


def envios(conn, medicao_id: int) -> list[dict]:
    """As versoes ja' enviadas pelo sistema, da 1a a ultima (a linha do tempo da medicao)."""
    return [dict(r) for r in conn.execute(
        f"SELECT e.planilha_id, p.versao, e.numero_oficio, e.envio_id, v.enviado_em, u.nome AS usuario "
        f"FROM {TABELA} e JOIN medicao_planilhas p ON p.id=e.planilha_id JOIN envios v ON v.id=e.envio_id "
        "LEFT JOIN usuarios u ON u.id=v.usuario_id WHERE e.medicao_id=? ORDER BY p.versao", (medicao_id,))]


def _reserva(conn, medicao_id: int) -> dict | None:
    """Envio reservado e nao concluido (em andamento, ou preso depois de uma falha): a tela precisa do id para
    oferecer a liberacao (`POST /api/envios/liberar`), como no protocolo e no pleito."""
    r = conn.execute(f"SELECT e.id, e.envio_reservado_em, u.nome AS reservado_por FROM {TABELA} e "
                     "LEFT JOIN usuarios u ON u.id=e.envio_reservado_por WHERE e.medicao_id=? AND e.envio_id IS NULL "
                     "AND e.envio_reservado_em IS NOT NULL ORDER BY e.id DESC LIMIT 1", (medicao_id,)).fetchone()
    return {"tabela": TABELA, **dict(r)} if r else None


def situacao(conn, medicao_id: int) -> dict:
    """O que a tela precisa para oferecer (ou nao) o botao "Enviar para protocolo"."""
    m = _medicao(conn, medicao_id)
    motivo = _recusa(conn, m)
    try:
        _, _, regras = _contexto(conn, m)
        pedidas = _config_pecas(regras, m["tipo"])
    except ValueError:
        pedidas = []
    return {"disponivel": motivo is None, "motivo": motivo, "envios": envios(conn, medicao_id),
            "reserva": _reserva(conn, medicao_id), "pecas": pecas(conn, medicao_id),
            "pecas_do_orgao": [{"tipo": x["tipo"], "rotulo": x["rotulo"], "exigida": x["exigida"]} for x in pedidas]}


# --- pecas do orgao --------------------------------------------------------------------------------

def _config_pecas(regras: dict, natureza: str) -> list[dict]:
    """As pecas do orgao para esta natureza, sem a `planilha` (a planilha editavel ja' e' a da versao)."""
    out = [{"exigida": False, **x} for x in (regras.get("pecas") or [])]
    return [x for x in out if x["tipo"] != "planilha" and (not x.get("naturezas") or natureza in x["naturezas"])]


def pecas(conn, medicao_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT id, tipo, nome, tamanho, ext, sha256, criado_em FROM medicao_planilha_pecas "
        "WHERE medicao_id=? AND removida_em IS NULL ORDER BY id", (medicao_id,))]


def _pecas_com_arquivo(conn, medicao_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM medicao_planilha_pecas WHERE medicao_id=? AND removida_em IS NULL ORDER BY id", (medicao_id,))]


def _editavel(conn, m: dict) -> dict:
    """As pecas so' mudam enquanto a planilha/carta pode ser enviada (fora da MT-PAR, antes do boletim)."""
    _, familia, regras = _contexto(conn, m)
    if familia in FAMILIAS_SEM_ENVIO:
        raise ValueError(SEM_ENVIO_MTPAR)
    if m["estado"] not in ESTADOS_ENVIO:
        raise ValueError(f"{medicoes.nome_medicao(m['numero'], m['tipo'])} está "
                         f"{medicoes.rotulo_estado(m['estado'])}: as peças da planilha/carta não mudam mais")
    # com o e-mail saindo (ou preso), as pecas nao mudam: o que vai e' o que foi lido sob a reserva (gate Sol S5)
    r = conn.execute(f"SELECT envio_reservado_em, envio_reservado_por FROM {TABELA} WHERE medicao_id=? "
                     "AND envio_id IS NULL AND envio_reservado_em IS NOT NULL LIMIT 1", (m["id"],)).fetchone()
    if r is not None:
        raise envio_reserva.reservado(conn, r["envio_reservado_em"], r["envio_reservado_por"])
    return regras


def adicionar_peca(conn, usuario_id: int, medicao_id: int, tipo: str, nome: str, dados: bytes, ext: str) -> int:
    if ext not in EXTENSOES_PECA:
        raise ValueError("A peça é um PDF ou uma planilha .xlsx")
    m = _medicao(conn, medicao_id)
    regras = _editavel(conn, m)
    pedidas = {x["tipo"]: x["rotulo"] for x in _config_pecas(regras, m["tipo"])}
    if tipo not in pedidas:
        raise ValueError("O órgão não pede esta peça nesta medição" +
                         (f": use {', '.join(pedidas.values())}" if pedidas else ""))
    rel, sha = arquivos.gravar_bytes("planilhas", dados, ext)
    with db.mutacao(conn):
        _editavel(conn, _medicao(conn, medicao_id))       # de novo sob o lock: o estado pode ter mudado no meio
        peca_id = conn.execute(
            "INSERT INTO medicao_planilha_pecas (medicao_id, tipo, nome, arquivo, sha256, tamanho, ext, usuario_id) "
            "VALUES (?,?,?,?,?,?,?,?)", (medicao_id, tipo, nome, rel, sha, len(dados), ext, usuario_id)).lastrowid
        auditoria.registrar(conn, usuario_id, "medicao.planilha_peca", "medicao", medicao_id, None,
                            {"peca_id": peca_id, "tipo": tipo, "nome": nome, "sha256": sha})
    return peca_id


def remover_peca(conn, usuario_id: int, medicao_id: int, peca_id: int) -> None:
    with db.mutacao(conn):
        _editavel(conn, _medicao(conn, medicao_id))
        p = conn.execute("SELECT tipo, nome, sha256 FROM medicao_planilha_pecas WHERE id=? AND medicao_id=? "
                         "AND removida_em IS NULL", (peca_id, medicao_id)).fetchone()
        if p is None:
            raise ValueError("Peça não encontrada")
        conn.execute("UPDATE medicao_planilha_pecas SET removida_em=datetime('now') WHERE id=?", (peca_id,))
        auditoria.registrar(conn, usuario_id, "medicao.planilha_peca", "medicao", medicao_id, dict(p),
                            {"peca_id": peca_id, "removida": True})


# --- previa ----------------------------------------------------------------------------------------

def _oficio(conn, c: dict, numero_oficio: str, hoje: datetime.date) -> str:
    """O numero do oficio CT, digitado (o contador da empresa vive fora do sistema), normalizado como no protocolo."""
    sigla = conn.execute("SELECT sigla_oficio FROM entidades WHERE id=?",
                         (c["entidade_id"],)).fetchone()["sigla_oficio"] if c.get("entidade_id") else "LT"
    return oficios.canonico(numero_oficio or "", sigla, hoje.year)


def _revisao(versao: int) -> str:
    return f" - Rev{versao - 1:02d}" if versao > 1 else ""


def _base(c: dict, m: dict, versao: int) -> str:
    """`{obra} - {nº}ª Medição ({MM.AAAA})`, o mesmo miolo do nome do pacote do protocolo (spec 2026-09-21 §4.4)."""
    comp = f"{m['competencia'][5:7]}.{m['competencia'][:4]}"
    # obra sem nome curto cai no nº do instrumento ("045/2025"): a barra viraria pasta dentro do zip
    obra = pleitos._obra(c).replace("/", "-").replace("\\", "-")
    return f"{obra} - {m['numero']:02d}ª {ROTULO_NATUREZA[m['tipo']]} ({comp}){_revisao(versao)}"


def _zip(nome: str, dados: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        info = zipfile.ZipInfo(nome, date_time=_DATA_ZIP)
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info, dados)
    return buf.getvalue()


def _anexos(conn, c: dict, m: dict, v: dict, oficio: str) -> list[tuple[str, bytes, str]]:
    """(nome, bytes, origem): o oficio assinado, a planilha zipada e as pecas anexadas, nessa ordem."""
    base = _base(c, m, v["versao"])
    ext = v["arquivo_planilha"].rsplit(".", 1)[-1]
    out = [(f"{oficio} - {base}.pdf", arquivos.caminho_seguro(v["arquivo"]).read_bytes(), "oficio"),
           (f"Planilha - {base}.zip",
            _zip(f"Planilha - {base}.{ext}", arquivos.caminho_seguro(v["arquivo_planilha"]).read_bytes()), "planilha")]
    out += [(p["nome"], arquivos.caminho_seguro(p["arquivo"]).read_bytes(), "pecas")
            for p in _pecas_com_arquivo(conn, m["id"])]
    return out


def _lista_anexos(regras: dict, m: dict, anexos: list[tuple[str, bytes, str]], tipos: set[str]) -> str:
    """"ofício, planilha editável e memória de cálculo da medição": so' o que vai (regra do envio ao orgao)."""
    itens = [{"oficio": "ofício", "planilha": "planilha editável"}[o] for _, _, o in anexos if o != "pecas"]
    itens += [x["rotulo"][:1].lower() + x["rotulo"][1:] for x in _config_pecas(regras, m["tipo"]) if x["tipo"] in tipos]
    return itens[0] if len(itens) == 1 else ", ".join(itens[:-1]) + " e " + itens[-1]


def _textos(conn, familia: str) -> dict:
    t = carta.config(conn).get("planilha")
    if not t:
        raise ValueError("Textos do e-mail da planilha/carta não carregados: inclua `planilha` em cartas.yaml e rode "
                         "`cadastro aplicar`")
    return {k: t.get(f"{k}_{familia}") or t.get(k) or "" for k in ("email_assunto", "email_corpo")}


def _campos(c: dict, m: dict, v: dict, oficio: str, lista_anexos: str) -> dict:
    ini, fim = (datetime.date.fromisoformat(x) for x in (v["periodo_inicio"], v["periodo_fim"]))
    mes, ano = m["competencia"][5:7], m["competencia"][:4]
    return {"oficio": oficio, "medicao": medicoes.titulo(m), "numero": f"{m['numero']}ª",
            "competencia": f"{mes}/{ano}", "competencia_sublinhada": f"{mes}_{ano}",
            "periodo": f"{ini:%d/%m/%Y} a {fim:%d/%m/%Y}", "instrumento": c.get("numero_instrumento") or "",
            "obra": pleitos._obra(c), "saudacao": espelhos.saudacao(), "revisao": _revisao(v["versao"]),
            "lista_anexos": lista_anexos}


def previa(conn, medicao_id: int, numero_oficio: str, remetente: str | None = None,
           hoje: datetime.date | None = None) -> dict:
    """Destinatarios, assunto, corpo e anexos sugeridos (a pessoa confere e pode editar o texto antes de enviar)."""
    hoje = hoje or tempo.hoje_local()
    m = _medicao(conn, medicao_id)
    motivo = _recusa(conn, m)
    if motivo:
        raise ValueError(motivo)
    c, familia, regras = _contexto(conn, m)
    textos = _textos(conn, familia)
    v = _vigente(conn, medicao_id)
    oficio = _oficio(conn, c, numero_oficio, hoje)
    anexos = _anexos(conn, c, m, v, oficio)
    presentes = {p["tipo"] for p in pecas(conn, medicao_id)}
    campos = _campos(c, m, v, oficio, _lista_anexos(regras, m, anexos, presentes))
    para, copia = pleitos._destinatarios(conn, regras, c, hoje)     # protocolo do orgao, fiscal e as copias
    if remetente:       # o e-mail de login e a conta do Outlook (podem ser diferentes), como no protocolo
        fora = {remetente.lower()} | correio.contas_do_usuario(conn, remetente)
        copia = [x for x in copia if x.lower() not in fora]
    total = sum(len(b) for _, b, _ in anexos)
    pend = [{"codigo": "peca", "mensagem": f"Falta a peça que o órgão exige: {x['rotulo']}"}
            for x in _config_pecas(regras, m["tipo"]) if x["exigida"] and x["tipo"] not in presentes]
    if total > correio.MAX_TOTAL:
        pend.append({"codigo": "tamanho", "mensagem": f"Anexos somam {total // (1024 * 1024)} MB, acima do limite "
                                                      f"do e-mail ({correio.MAX_TOTAL // (1024 * 1024)} MB)"})
    return {"medicao_id": medicao_id, "planilha_id": v["id"], "versao": v["versao"], "numero_oficio": oficio,
            "para": para, "copia": copia, "assunto": carta.preencher(textos["email_assunto"], campos).strip(),
            "corpo": carta.preencher(textos["email_corpo"], campos).strip(),
            "anexos": [{"nome": n, "tamanho": len(b), "sha256": hashlib.sha256(b).hexdigest(), "origem": o}
                       for n, b, o in anexos], "total": total,
            "limite": correio.MAX_TOTAL, "pendencias": pend}


def _conferir_anexos(conferidos: list[dict], atuais: list[dict]) -> None:
    """Nome, tamanho e conteudo (sha256): a peca trocada por outra de mesmo nome e tamanho tambem recusa (gate Sol S5)."""
    def chave(lista):
        return sorted((a["nome"], a["tamanho"], a["sha256"]) for a in lista)
    if chave(conferidos) != chave(atuais):
        raise AnexosMudaram("Os anexos mudaram depois da prévia: abra a prévia de novo para conferir o que vai no "
                            "e-mail")


# --- envio -----------------------------------------------------------------------------------------

def enviar(conn, usuario: dict, medicao_id: int, numero_oficio: str, para: list[str], copia: list[str], assunto: str,
           corpo: str, anexos_previa: list[dict], justificativa: str | None = None, cco: list[str] | None = None,
           hoje: datetime.date | None = None) -> int:
    """`anexos_previa` (nome, tamanho e sha256) e' obrigatorio, como no envio da nota (gate Sol S1, PR #141): o e-mail leva
    o que a pessoa conferiu na previa, e nada sai sem essa conferencia."""
    hoje = hoje or tempo.hoje_local()
    # Tudo o que recusa vem ANTES do e-mail (que nao se desfaz).
    pv = previa(conn, medicao_id, numero_oficio, hoje=hoje)
    para = [x.strip() for x in para if x.strip()]
    if not para:
        raise ValueError("Informe ao menos um destinatário")
    if pv["total"] > correio.MAX_TOTAL:
        raise ValueError("Anexos acima do limite do e-mail")
    _conferir_anexos(anexos_previa, pv["anexos"])
    justificativa = (justificativa or "").strip() or None
    if pv["pendencias"] and len(justificativa or "") < MIN_JUSTIFICATIVA:
        raise ValueError(f"{len(pv['pendencias'])} pendência(s) na prévia: informe a justificativa "
                         f"(ao menos {MIN_JUSTIFICATIVA} caracteres) para enviar assim")
    # Reserva atomica antes do e-mail: dois cliques simultaneos mandam um e-mail so'. A condicao da reserva
    # (envio_reserva._CONDICAO) confere, no mesmo UPDATE, que a versao ainda e' a vigente e a medicao ainda envia.
    with db.mutacao(conn):
        conn.execute(f"INSERT OR IGNORE INTO {TABELA} (medicao_id, planilha_id) VALUES (?,?)",
                     (medicao_id, pv["planilha_id"]))
        linha = conn.execute(f"SELECT id FROM {TABELA} WHERE planilha_id=?", (pv["planilha_id"],)).fetchone()
        envio_reserva.reservar(conn, TABELA, linha["id"], usuario["id"], None)
    rid = linha["id"]
    try:
        # o que vai e' lido de novo depois da reserva: peca anexada ou removida desde a previa recusa aqui
        m = _medicao(conn, medicao_id)
        c, _, _ = _contexto(conn, m)
        v = conn.execute("SELECT * FROM medicao_planilhas WHERE id=?", (pv["planilha_id"],)).fetchone()
        rotulados = _anexos(conn, c, m, dict(v), pv["numero_oficio"])
        _conferir_anexos([{"nome": n, "tamanho": len(b), "sha256": hashlib.sha256(b).hexdigest()}
                          for n, b, _ in rotulados], pv["anexos"])
        envio_id = correio.enviar_e_registrar(conn, usuario, TIPO_ENVIO, para, [x.strip() for x in copia if x.strip()],
                                              assunto, pleitos._html(corpo), [(n, b) for n, b, _ in rotulados],
                                              cco=cco)
    except correio.EnvioNaoRegistrado:
        raise                                       # o e-mail saiu: a reserva fica e segura a repeticao
    except Exception:
        envio_reserva.liberar_com_retentativa(conn, TABELA, rid)    # nada saiu: destrava e sobe o erro
        raise
    # O e-mail ja' saiu: daqui para baixo nada recusa. Medicao que mudou de estado no meio (cancelada por outra
    # pessoa) nao desfaz o registro do envio: fica anotada na auditoria.
    with correio.depois_do_envio(assunto, para, envio_id), db.mutacao(conn):
        envio_reserva.liberar(conn, TABELA, rid)
        conn.execute(f"UPDATE {TABELA} SET envio_id=?, numero_oficio=?, justificativa=? WHERE id=?",
                     (envio_id, pv["numero_oficio"], justificativa, rid))
        conn.execute("INSERT OR IGNORE INTO envio_medicoes (envio_id, medicao_id) VALUES (?,?)", (envio_id, medicao_id))
        m = _medicao(conn, medicao_id)
        antes = {k: m[k] for k in ("estado", "valor_protocolado_centavos", "periodo_inicio", "periodo_fim",
                                   "planilha_enviada_em", "planilha_envio_origem")}
        # 1a versao enviada: o pedido congela no valor DELA (revisao registrada durante o e-mail nao entra). Congela
        # pelo estado (medicoes.definir_valor recusa o pedido em planilha/carta), nao por `congelada`: esse marcador
        # tambem congela o valor original do contrato, e a spec 2026-10-20 §2.1 so' congela o PEDIDO (revisor R3)
        primeira = conn.execute(
            "UPDATE medicoes SET estado='planilha_enviada', planilha_enviada_em=?, planilha_envio_origem='sistema', "
            "valor_protocolado_centavos=?, valor_protocolado_origem='manual', periodo_inicio=?, "
            "periodo_fim=? WHERE id=? AND estado='planilha_gerada'",
            (hoje.isoformat(), v["valor_pedido_centavos"], v["periodo_inicio"], v["periodo_fim"], medicao_id)).rowcount
        depois = {"envio_id": envio_id, "versao": v["versao"], "planilha_id": v["id"],
                  "numero_oficio": pv["numero_oficio"], "pendencias": pv["pendencias"], "justificativa": justificativa}
        if primeira:
            depois |= {"estado": "planilha_enviada", "planilha_enviada_em": hoje.isoformat(),
                       "planilha_envio_origem": "sistema",
                       "valor_protocolado_centavos": v["valor_pedido_centavos"],
                       "periodo_inicio": v["periodo_inicio"], "periodo_fim": v["periodo_fim"]}
        elif m["estado"] != "planilha_enviada":
            depois["nao_marcada"] = f"medição {medicoes.rotulo_estado(m['estado'])} durante o envio"
        auditoria.registrar(conn, usuario["id"], "medicao.planilha_envio", "medicao", medicao_id, antes, depois)
    return envio_id
