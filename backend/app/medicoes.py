"""Medicoes: 4 estados visiveis + excecoes, origem por dado, congelamento no protocolo.

Fase 2: transicoes manuais (importacao); fases 5-6 passam a mover nf_emitida/recebida
por deteccao. Regra de congelamento (spec §5): apos o 1o protocolo (marco externo),
o valor PROTOCOLADO nao muda mais; o ATESTADO segue editavel (glosa).
"""
import calendar
import datetime
import json
import logging
import sqlite3
import unicodedata

from app import auditoria, checklist, db, tempo

log = logging.getLogger(__name__)

# Estado -> estados alcancaveis por mudar_estado. cancelada/desistida so de estados
# nao-finais.
# `protocolada` NAO aparece aqui de proposito: quem promove prevista -> protocolada e'
# registrar_protocolo, que no mesmo passo cria a linha em medicao_protocolos e liga
# `congelada`. Se mudar_estado tambem pudesse faze-lo, existiria medicao "protocolada"
# sem nenhum protocolo e com o valor protocolado ainda editavel -- a invariante de
# congelamento (spec §5) contornavel por uma rota so.
TRANSICOES = {
    "prevista": {"cancelada", "desistida"},
    # Issue #281: entra pela planilha/carta (medicao_planilhas.registrar); a saida a mao e' o cancelamento.
    "planilha_gerada": {"cancelada", "desistida"},
    # Issue #283: entra pelo envio da planilha/carta (medicao_planilhas.registrar_envio_externo); sai como a gerada.
    # Issue #284: com o boletim recebido, a medicao tambem pode ser encerrada a mao
    "planilha_enviada": {"cancelada", "desistida"},
    "boletim_recebido": {"cancelada", "desistida"},
    # Estados do espelho (spec 2026-09-21 §2). espelho_gerado -> espelho_enviado e' do SISTEMA
    # (marcar_espelho_enviado, no ato do envio); -> protocolada e' registrar_protocolo.
    # Issue #359: espelho_enviado -> espelho_gerado tambem e' do SISTEMA, na versao nova do espelho
    # (criar_para_espelho); nao se faz a mao.
    # Bloco 3: a nota (PDF lido ou RM) fecha `nota_emitida` (notas.fechar_se_completa, ou a
    # declaracao com justificativa); o protocolo continua sendo registrar_protocolo.
    "espelho_gerado": {"nota_emitida", "cancelada"},
    "espelho_enviado": {"nota_emitida", "cancelada"},
    "nota_emitida": {"cancelada"},
    # `nf_emitida` deixou de ser alvo: a NF entra pela nota (bloco 3), nao por botao. Fica
    # como ORIGEM ate' o remapeamento do legado zerar as linhas (app/legado.py).
    "protocolada": {"recebida", "cancelada", "desistida"},
    "nf_emitida": {"recebida", "cancelada", "desistida"},
    "recebida": set(),
    "cancelada": set(),
    "desistida": set(),
}
ESTADOS_ESPELHO = ("espelho_gerado", "espelho_enviado")
# Issue #289: a planilha/carta GERADA nao recebe espelho: o boletim (#284) substitui a ponte ao espelho, nao o envio ao
# protocolo (regra de 04/11/2026, depois das decisoes da #284 de 03/11)
PLANILHA_SEM_ENVIO = ("está com a planilha/carta gerada: envie ao protocolo (ou registre o envio por fora) antes de "
                      "gerar o espelho")
PEDIDO_ENVIADO = "O pedido congelou no envio da planilha/carta: não muda à mão"
# Issue #281: estados em que o pedido (valor protocolado) e' o da planilha/carta e so' muda por revisao
ESTADOS_PLANILHA = ("planilha_gerada", "planilha_enviada", "boletim_recebido")
# Issue #284: a medicao que ja' existe antes do espelho; o espelho a leva a `espelho_gerado`. Nas sem boletim, so'
# com "seguir sem boletim" e justificativa (decisao do Leo de 03/11/2026: prevista, planilha gerada ou enviada).
ESTADOS_ANTES_DO_ESPELHO = ("prevista", *ESTADOS_PLANILHA)
ESTADOS_SEM_BOLETIM = ("prevista", "planilha_gerada", "planilha_enviada")
PEDIDO_POR_REVISAO = "Para mudar o pedido, registre uma revisão da planilha/carta"
PEDIDO_DEPOIS_DO_BOLETIM = "O pedido não pode mais ser alterado depois do boletim do órgão"
APROVADO_PELO_BOLETIM = "O aprovado vem do boletim do órgão: para corrigir ou registrar glosa, registre um boletim novo"
# Gate Sol S4 (#281): os estados que recebem protocolo, por extenso. Estes vao a `protocolada` no mesmo passo...
ESTADOS_PROMOVIDOS_PELO_PROTOCOLO = ("prevista", "planilha_gerada", *ESTADOS_ESPELHO, "nota_emitida")
# ...e estes ja' foram protocolados: o protocolo seguinte (novo oficio) so' congela. Os demais sao recusados.
ESTADOS_DE_NOVO_PROTOCOLO = ("protocolada", "nf_emitida")
# B-12 (10/10/2026): mensagem ao usuario com o tipo e o estado por extenso, nunca o codigo ("(execucao)")
ROTULO_TIPO = {"execucao": "execução", "reajuste": "reajuste", "projeto": "projeto"}
ROTULO_ESTADO = {"prevista": "prevista", "planilha_gerada": "com planilha/carta gerada",
                 "planilha_enviada": "com planilha/carta enviada", "boletim_recebido": "com boletim recebido",
                 "espelho_gerado": "com espelho gerado", "espelho_enviado": "com espelho enviado",
                 "nota_emitida": "com nota emitida", "protocolada": "protocolada", "nf_emitida": "lançada no RM",
                 "recebida": "recebida", "cancelada": "cancelada", "desistida": "desistida"}


def nome_medicao(numero, tipo: str) -> str:
    """"Medição 32 de execução" para mensagem de erro."""
    return f"Medição {numero} de {ROTULO_TIPO.get(tipo, tipo)}"


def rotulo_estado(estado: str) -> str:
    return ROTULO_ESTADO.get(estado, estado)
ESTADOS_ANTES_DO_PROTOCOLO = ("prevista", "espelho_gerado", "espelho_enviado", "nota_emitida")
NOTA_NAO_EMITIDA = "Nota fiscal ainda não emitida: protocolar agora pula o faturamento e a nota"

def criar(conn: sqlite3.Connection, usuario_id: int, dados: dict) -> int:
    duplicada = f"{nome_medicao(dados['numero'], dados['tipo'])} já existe neste contrato"
    with db.mutacao(conn):
        ja = conn.execute(
            "SELECT id FROM medicoes WHERE contrato_id=? AND numero=? AND tipo=?",
            (dados["contrato_id"], dados["numero"], dados["tipo"])).fetchone()
        if ja:
            raise ValueError(duplicada)
        # O SELECT acima e' so cortesia (mensagem boa no caso comum). Quem de fato decide e'
        # o UNIQUE (contrato_id, numero, tipo) do schema: entre a leitura e o INSERT outra
        # requisicao pode inserir a mesma medicao. Sem este catch o perdedor da corrida
        # recebia sqlite3.IntegrityError crua dentro do handler -> 500 em vez de 422.
        try:
            cur = conn.execute(
                "INSERT INTO medicoes (contrato_id, numero, tipo, competencia) VALUES (?,?,?,?)",
                (dados["contrato_id"], dados["numero"], dados["tipo"], dados["competencia"]))
        except sqlite3.IntegrityError as e:
            # So a violacao de unicidade vira erro de dominio: FK/CHECK quebrados sao bug
            # nosso e devem continuar subindo como 500 (nao mentir dizendo "ja existe").
            if "UNIQUE" not in str(e).upper():
                raise
            raise ValueError(duplicada) from e
        mid = cur.lastrowid
        auditoria.registrar(conn, usuario_id, "medicao.criar", "medicao", mid, None, dados)
    return mid

def detalhe(conn: sqlite3.Connection, medicao_id: int) -> dict | None:
    r = conn.execute("SELECT * FROM medicoes WHERE id=?", (medicao_id,)).fetchone()
    if r is None:
        return None
    d = dict(r)
    d["diferenca_centavos"] = diferenca(d)      # issue #284: aprovado do boletim menos o pedido
    # Issue #283: `protocolos` e' so' o da nota (o que conta como protocolo nas telas e nos marcos); o nº do SIGA da
    # planilha/carta (etapa 'planilha', migracao 054) vem a' parte
    d["protocolos"] = [dict(p) for p in conn.execute(
        "SELECT * FROM medicao_protocolos WHERE medicao_id=? AND etapa='nota' ORDER BY id", (medicao_id,))]
    p = conn.execute("SELECT data, numero_processo FROM medicao_protocolos WHERE medicao_id=? AND etapa='planilha'",
                     (medicao_id,)).fetchone()
    d["planilha_siga"] = {"data": p["data"], "numero": p["numero_processo"]} if p else None
    # NFs do RM alocadas a esta medicao, com o recebido de cada uma (fase 5). Import local:
    # sincronizacao_rm importa este modulo.
    from app import sincronizacao_rm
    d["notas"] = sincronizacao_rm.notas_da_medicao(conn, medicao_id)
    # Documentos de faturamento do consorcio (NF/NFS-e/FATURA do SharePoint, migracao 017):
    # evidencia por medicao dos consorcios, que faturam fora do RM. So' leitura.
    # Bloco 2: documentos LOCAIS tambem (espelho gerado, evidencia do orgao) -- `arquivo` e
    # `tamanho` preenchidos; os do SharePoint continuam so' com `weblink`.
    d["documentos"] = [dict(x) for x in conn.execute(
        "SELECT id, tipo_doc, nome, numero_nf, consorciada, municipio, weblink, fonte, arquivo, tamanho, "
        "espelho_id FROM medicao_documentos WHERE medicao_id=? ORDER BY tipo_doc, id", (medicao_id,))]
    # Issue #359: o aprovado mudou depois do espelho vigente: a situacao (espelhos.TEXTO_AVISO) ou None (import
    # local: espelhos importa este modulo)
    from app import espelhos
    d["espelho_desatualizado"] = next((x["situacao"] for x in espelhos.desatualizadas(conn, medicao_id=medicao_id)),
                                      None)
    return d

def _json_dict(texto) -> dict | None:
    """Gate Sol S1 (10/10/2026): linha antiga de auditoria pode ter JSON torto ou nao-dicionario; None = defeituosa."""
    try:
        d = json.loads(texto or "{}")
    except (ValueError, TypeError):
        return None
    return d if isinstance(d, dict) else None


LOTE_AUDITORIA = 500    # ids por consulta: abaixo do limite de parametros do SQLite


def _linhas_edicoes(conn: sqlite3.Connection, medicao_ids: list[int]) -> list:
    """Gate Sol S2 (10/10/2026): filtra no SQL, pelo indice ix_audit_log_entidade (migracao 036), em lotes."""
    linhas = []
    for i in range(0, len(medicao_ids), LOTE_AUDITORIA):
        lote = [str(x) for x in medicao_ids[i:i + LOTE_AUDITORIA]]
        linhas += conn.execute(
            "SELECT a.id, a.acao, a.entidade_id, a.antes, a.depois, a.criado_em, u.nome FROM audit_log a "
            "LEFT JOIN usuarios u ON u.id=a.usuario_id WHERE a.entidade='medicao' "
            f"AND a.entidade_id IN ({','.join('?' * len(lote))}) "
            "AND a.acao IN ('medicao.valor_protocolado', 'medicao.estado', 'medicao.sem_boletim')", lote).fetchall()
    return sorted(linhas, key=lambda r: r["id"])


def _data_br(iso: str) -> str:
    try:
        return datetime.date.fromisoformat(iso).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return str(iso)


def _eventos_atesto(conn: sqlite3.Connection, ids: list[int], out: dict[int, list[dict]]) -> None:
    """Issue #61: a linha do tempo do atesto vem dos eventos (medicao_atestos, append-only), um por mudanca de
    valor ou de dia (as duas no mesmo evento dao duas linhas). Evento que nao muda nenhum dos dois (carga da
    auditoria antiga) nao vira linha."""
    from app.dinheiro import format_brl
    linhas = []
    for i in range(0, len(ids), LOTE_AUDITORIA):
        lote = ids[i:i + LOTE_AUDITORIA]
        linhas += conn.execute(
            "SELECT e.id, e.medicao_id, e.valor_centavos, e.origem, e.atestado_em, e.criado_em, u.nome FROM medicao_atestos e "
            "LEFT JOIN usuarios u ON u.id=e.usuario_id "
            f"WHERE e.medicao_id IN ({','.join('?' * len(lote))})", lote).fetchall()
    anterior: dict[int, tuple] = {}
    for r in sorted(linhas, key=lambda r: r["id"]):
        mid = r["medicao_id"]
        valor_ant, dia_ant, origem_ant = anterior.get(mid, (None, None, None))
        # Evento sem dia (carga da auditoria antiga) nao apaga o dia que ja' valia
        dia = r["atestado_em"] if r["atestado_em"] is not None else dia_ant
        anterior[mid] = (r["valor_centavos"], dia, r["origem"])
        textos = []
        if valor_ant != r["valor_centavos"]:
            textos.append(f"Atestado definido em {format_brl(r['valor_centavos'])}" if valor_ant is None
                          else f"Atestado alterado de {format_brl(valor_ant)} para {format_brl(r['valor_centavos'])}")
        # O dia que chega junto com o primeiro valor ja' aparece como "Atestada pelo órgão" (linha do tempo da
        # tela); dia posto depois, num atesto que nao tinha, ganha linha propria com autor (gate Sol S1)
        if dia_ant is not None and dia != dia_ant:
            textos.append(f"Data do atesto alterada de {_data_br(dia_ant)} para {_data_br(dia)}")
        elif dia_ant is None and dia is not None and valor_ant is not None:
            textos.append(f"Data do atesto definida em {_data_br(dia)}")
        # So' a origem mudou (ex.: o detectado salvo pela pessoa): e' a confirmacao, com autor (revisor R4).
        # Origem desconhecida (carga da auditoria antiga) nao conta como mudanca.
        if not textos and origem_ant is not None and r["origem"] is not None and r["origem"] != origem_ant:
            textos.append(f"Atestado confirmado em {format_brl(r['valor_centavos'])}")
        for texto in textos:
            out[mid].append({"data": r["criado_em"],
                             "texto": f"{texto} por {r['nome']}" if r["nome"] else f"{texto} pelo sistema"})


def _eventos_assinatura(conn: sqlite3.Connection, ids: list[int], out: dict[int, list[dict]]) -> None:
    """Issue #287: a assinatura no DocuSign e' evento (medicao_assinaturas, append-only), uma linha por registro."""
    for i in range(0, len(ids), LOTE_AUDITORIA):
        lote = ids[i:i + LOTE_AUDITORIA]
        for r in conn.execute(
                "SELECT e.medicao_id, e.envelope, e.assinado_em, e.criado_em, u.nome FROM medicao_assinaturas e "
                "LEFT JOIN usuarios u ON u.id=e.usuario_id "
                f"WHERE e.medicao_id IN ({','.join('?' * len(lote))}) ORDER BY e.id", lote):
            texto = f"Boletim assinado no DocuSign em {_data_br(r['assinado_em'])}"
            if r["envelope"]:
                texto += f" (envelope {r['envelope']})"
            # a data do evento e' a da assinatura (como o atesto), nao a do registro: registrada depois do protocolo,
            # ela nao pode aparecer depois dele
            out[r["medicao_id"]].append({"data": r["assinado_em"],
                                         "texto": f"{texto} por {r['nome']}" if r["nome"] else f"{texto} pelo sistema"})


def registrar_assinatura(conn: sqlite3.Connection, usuario_id: int, medicao_id: int, assinado_em: str,
                         envelope: str | None) -> int:
    """Issue #287: registra que o boletim foi assinado no DocuSign (data e nome do envelope do e-mail de
    conclusao). Evento informativo, sem estado e sem aviso; correcao e' um registro novo."""
    try:
        data = datetime.date.fromisoformat(assinado_em)
    except (TypeError, ValueError):
        raise ValueError("Data da assinatura inválida")
    if data > tempo.hoje_local():
        raise ValueError("A data da assinatura não pode ser futura")
    envelope = (envelope or "").strip() or None
    with db.mutacao(conn):
        if conn.execute("SELECT 1 FROM medicoes WHERE id=?", (medicao_id,)).fetchone() is None:
            raise ValueError("Medição não encontrada")
        if conn.execute("SELECT 1 FROM medicao_assinaturas WHERE medicao_id=? AND assinado_em=? AND envelope IS ?",
                        (medicao_id, data.isoformat(), envelope)).fetchone():
            raise ValueError("Esta assinatura já está registrada")     # duplo clique: o registro não se apaga depois
        cur = conn.execute(
            "INSERT INTO medicao_assinaturas (medicao_id, envelope, assinado_em, origem, usuario_id) "
            "VALUES (?,?,?,'manual',?)", (medicao_id, envelope, data.isoformat(), usuario_id))
        auditoria.registrar(conn, usuario_id, "medicao.assinatura", "medicao", medicao_id, None,
                            {"assinado_em": data.isoformat(), "envelope": envelope})
        return cur.lastrowid


# --- issue #284: boletim do orgao (spec 2026-10-20 §2.1, passo 3; D4) -----------------------------------------
MEIOS_BOLETIM = ("smo", "oficio", "email", "carimbo", "ci", "outro")     # o CHECK de medicao_atestos.meio (042)


def diferenca(m) -> int | None:
    """Aprovado menos pedido; sem um dos dois, nao ha' diferenca."""
    if m["valor_atestado_centavos"] is None or m["valor_protocolado_centavos"] is None:
        return None
    return m["valor_atestado_centavos"] - m["valor_protocolado_centavos"]


def tem_boletim(conn, medicao_id: int) -> bool:
    """O boletim do orgao registrado com o documento (o atesto digitado a mao, sem PDF, nao conta)."""
    return conn.execute("SELECT 1 FROM medicao_atestos WHERE medicao_id=? AND arquivo IS NOT NULL LIMIT 1",
                        (medicao_id,)).fetchone() is not None


def conferir_boletim(conn: sqlite3.Connection, medicao_id: int, dados: dict):
    """Recusas do boletim (ValueError), sem gravar nada: a rota chama ANTES de gravar o PDF, e `registrar_boletim`
    de novo dentro da transacao. Devolve a medicao e o dia do boletim."""
    try:
        dia = datetime.date.fromisoformat(dados["data"])
    except (TypeError, ValueError):
        raise ValueError("Data do boletim inválida")
    if dia > tempo.hoje_local():
        raise ValueError("A data do boletim não pode ser futura")
    if (dados.get("meio") or None) not in (None, *MEIOS_BOLETIM):
        raise ValueError("Meio do boletim inválido")
    if not (dados.get("numero_orgao") or "").strip():
        raise ValueError("Informe o nº do boletim no órgão (processo ou SMO)")    # issue: "valor aprovado, data e nº"
    m = conn.execute("SELECT * FROM medicoes WHERE id=?", (medicao_id,)).fetchone()
    if m is None:
        raise ValueError("Medição não encontrada")
    if m["estado"] in ("cancelada", "desistida"):
        raise ValueError(f"{nome_medicao(m['numero'], m['tipo'])} está {rotulo_estado(m['estado'])}: "
                         "não recebe boletim")
    if m["estado"] == "planilha_gerada":
        # spec §2.1: o boletim vem depois do envio da planilha/carta (pelo sistema ou registrado por fora)
        raise ValueError("Registre o envio da planilha/carta antes do boletim do órgão")
    if m["estado"] == "planilha_enviada":
        # revisor (rodada 4): depois do boletim a revisao nao se envia nem se registra mais, e o espelho espera a
        # revisao registrada ser enviada (conferir_espelho_da_planilha): a medicao ficaria presa em boletim_recebido
        from app import planilha_envio      # import local: planilha_envio importa este modulo
        vigente = conn.execute("SELECT MAX(versao) FROM medicao_planilhas WHERE medicao_id=?",
                               (medicao_id,)).fetchone()[0] or 0
        if vigente > planilha_envio._ultima_enviada(conn, dict(m)):
            raise ValueError("A planilha/carta tem revisão registrada e não enviada: envie ao protocolo (ou registre o "
                             "envio por fora) antes do boletim do órgão")
    return m, dia


def registrar_boletim(conn: sqlite3.Connection, usuario_id: int, medicao_id: int, dados: dict, anexo: dict) -> dict:
    """O boletim do orgao e' um evento de atesto (medicao_atestos, append-only) com o meio, o nº no orgao e o PDF;
    o aprovado vigente (`valor_atestado_centavos`) e' o do ultimo evento. Na planilha/carta enviada a medicao vai a
    `boletim_recebido`; nos estados seguintes e' glosa (evento novo, estado igual). A prevista vai a
    `boletim_recebido` na obra que gera espelho (o passo seguinte); na do fluxo antigo guarda o evento e fica
    prevista, porque o protocolo nao recebe `boletim_recebido`. O pedido nao muda."""
    meio = dados.get("meio") or None
    numero = (dados.get("numero_orgao") or "").strip() or None
    observacao = (dados.get("observacao") or "").strip() or None
    valor = dados["valor_centavos"]
    with db.mutacao(conn):
        m, dia = conferir_boletim(conn, medicao_id, dados)
        atual = m["estado"]
        # Repeticao (clique duplo, pedido atrasado) e' o mesmo boletim de QUALQUER evento ja' gravado, com o mesmo
        # documento, valor, dia, nº, meio e observacao (gate Sol): a repeticao atrasada de A depois da correcao B nao
        # volta o valor; corrigir so' o nº, o meio ou a observacao e' um evento novo. O evento nao se apaga depois.
        if conn.execute("SELECT 1 FROM medicao_atestos WHERE medicao_id=? AND valor_centavos=? AND atestado_em=? "
                        "AND sha256=? AND numero_orgao IS ? AND meio IS ? AND observacao IS ? LIMIT 1",
                        (medicao_id, valor, dia.isoformat(), anexo["sha256"], numero, meio, observacao)).fetchone():
            raise ValueError("Este boletim já está registrado")
        regra_ativa = conn.execute("SELECT 1 FROM espelho_regras WHERE contrato_id=? AND situacao='ativa'",
                                   (m["contrato_id"],)).fetchone() is not None
        novo = ("boletim_recebido" if atual == "planilha_enviada" or (atual == "prevista" and regra_ativa)
                else atual)
        cur = conn.execute(
            "UPDATE medicoes SET valor_atestado_centavos=?, valor_atestado_origem='manual', atestado_em=?, estado=? "
            "WHERE id=? AND estado=?", (valor, dia.isoformat(), novo, medicao_id, atual))
        db.exigir_uma_linha(cur, "Estado da medição mudou concorrentemente; tente novamente")
        aid = conn.execute(
            "INSERT INTO medicao_atestos (medicao_id, valor_centavos, origem, atestado_em, usuario_id, meio, "
            "numero_orgao, arquivo, sha256, observacao) VALUES (?,?,'manual',?,?,?,?,?,?,?)",
            (medicao_id, valor, dia.isoformat(), usuario_id, meio, numero, anexo["arquivo"], anexo["sha256"],
             observacao)).lastrowid
        antes = {"estado": atual, "valor_atestado_centavos": m["valor_atestado_centavos"],
                 "valor_atestado_origem": m["valor_atestado_origem"], "atestado_em": m["atestado_em"]}
        auditoria.registrar(conn, usuario_id, "medicao.valor_atestado", "medicao", medicao_id, antes, {
            "estado": novo, "valor_atestado_centavos": valor, "valor_atestado_origem": "manual",
            "atestado_em": dia.isoformat(), "boletim": {"atesto_id": aid, "meio": meio, "numero_orgao": numero,
                                                       "sha256": anexo["sha256"], "observacao": observacao}})
        pedido = m["valor_protocolado_centavos"]
    return {"id": aid, "estado": novo, "pedido_centavos": pedido, "aprovado_centavos": valor,
            "diferenca_centavos": None if pedido is None else valor - pedido}


def boletins(conn: sqlite3.Connection, medicao_id: int) -> list[dict]:
    """Os boletins registrados (eventos de atesto com meio ou documento), do primeiro ao vigente."""
    return [{**dict(r), "tem_arquivo": bool(r["tem_arquivo"])} for r in conn.execute(
        "SELECT e.id, e.valor_centavos, e.atestado_em, e.meio, e.numero_orgao, e.sha256, e.observacao, e.criado_em, "
        "e.arquivo IS NOT NULL AS tem_arquivo, u.nome AS usuario FROM medicao_atestos e "
        "LEFT JOIN usuarios u ON u.id=e.usuario_id "
        "WHERE e.medicao_id=? AND (e.meio IS NOT NULL OR e.arquivo IS NOT NULL) ORDER BY e.id", (medicao_id,))]


def arquivo_boletim(conn: sqlite3.Connection, medicao_id: int, atesto_id: int) -> dict | None:
    """O PDF de UM boletim, so' se o evento for da medicao pedida."""
    r = conn.execute("SELECT e.arquivo, m.numero FROM medicao_atestos e JOIN medicoes m ON m.id=e.medicao_id "
                     "WHERE e.id=? AND e.medicao_id=?", (atesto_id, medicao_id)).fetchone()
    return dict(r) if r else None


def edicoes_valor(conn: sqlite3.Connection, medicao_ids: list[int]) -> dict[int, list[dict]]:
    """B-02 (10/10/2026): as edicoes de valor da auditoria, por medicao, para a linha do tempo (a tela so' mostrava
    espelho, nota, protocolo e atesto). Gravar o mesmo valor nao vira evento. O atestado vem dos eventos de
    atesto (issue #61), nao da auditoria."""
    from app.dinheiro import format_brl
    rotulo = {"medicao.valor_protocolado": ("valor_protocolado_centavos", "Valor protocolado")}
    out: dict[int, list[dict]] = {i: [] for i in medicao_ids}
    for r in _linhas_edicoes(conn, list(out)):
        if not (r["entidade_id"] or "").isdigit() or int(r["entidade_id"]) not in out:
            continue
        a_d, d_d = _json_dict(r["antes"]), _json_dict(r["depois"])
        if r["acao"] == "medicao.sem_boletim":
            # issue #284: o espelho gerado sem o boletim do orgao, com a justificativa de quem seguiu
            if d_d and d_d.get("justificativa"):
                texto = f"Espelho gerado sem boletim: {d_d['justificativa']}"
                out[int(r["entidade_id"])].append({"data": r["criado_em"],
                                                   "texto": f"{texto} por {r['nome']}" if r["nome"] else f"{texto} pelo sistema"})
            continue
        if r["acao"] == "medicao.estado":
            # Issue #260: cancelamento e desistencia entram na linha do tempo com o motivo (a duplicata cancelada
            # pela carga do historico diz de qual medicao ela e' copia); as outras transicoes ja' tem marco proprio
            if d_d and d_d.get("estado") in ("cancelada", "desistida"):
                texto = f"{'Cancelada' if d_d['estado'] == 'cancelada' else 'Desistida'}" + (
                    f": {d_d['motivo']}" if d_d.get("motivo") else "")
                out[int(r["entidade_id"])].append({"data": r["criado_em"],
                                                   "texto": f"{texto} por {r['nome']}" if r["nome"] else f"{texto} pelo sistema"})
            continue
        col, nome = rotulo[r["acao"]]
        antes, depois = (a_d or {}).get(col), (d_d or {}).get(col)
        if a_d is None or d_d is None or not isinstance(antes, (int, type(None))) or not isinstance(depois, (int, type(None))):
            log.warning("auditoria da medicao %s com antes/depois ilegivel; evento fora da linha do tempo", r["entidade_id"])
            continue
        if depois is None or antes == depois:
            continue
        texto = (f"{nome} definido em {format_brl(depois)}" if antes is None
                 else f"{nome} alterado de {format_brl(antes)} para {format_brl(depois)}")
        out[int(r["entidade_id"])].append({"data": r["criado_em"],
                                           # gate Sol S5 (10/10/2026): sem usuario, a autoria e' do sistema
                                           "texto": f"{texto} por {r['nome']}" if r["nome"] else f"{texto} pelo sistema"})
    _eventos_atesto(conn, list(out), out)
    _eventos_assinatura(conn, list(out), out)
    from app import medicao_planilhas     # issue #283: o envio da planilha/carta (import local: ele importa este)
    medicao_planilhas.eventos_envio(conn, list(out), out)
    for eventos in out.values():
        eventos.sort(key=lambda e: e["data"] or "")      # estavel: no mesmo segundo, o protocolado vem antes
    return out


def listar(conn: sqlite3.Connection, contrato_id: int) -> list[dict]:
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM medicoes WHERE contrato_id=? ORDER BY tipo, numero", (contrato_id,))]
    return [detalhe(conn, i) for i in ids]

def definir_valor(conn, usuario_id: int, medicao_id: int, campo: str, centavos: int, origem: str,
                  data: str | None = None) -> None:
    # fail-closed: `campo` vira NOME DE COLUNA no UPDATE abaixo. Um `assert` some com
    # `python -O` e o identificador passaria cru -- valida sempre, com erro de dominio.
    if campo not in ("protocolado", "atestado"):
        raise ValueError(f"Campo inválido: {campo}")
    # `data` e' o dia do ATESTO (fase 3,5, spec §6): o protocolado tem a data no proprio
    # protocolo, entao aceitar uma aqui seria gravar um marco que nao existe.
    if data is not None and campo != "atestado":
        raise ValueError("Data só acompanha o valor atestado (o protocolado tem a data do protocolo)")
    with db.mutacao(conn):
        m = detalhe(conn, medicao_id)
        # Cancelada/desistida sao encerramentos: NENHUM dos dois campos muda mais. `congelada`
        # nao cobria isso -- quem cancela antes do 1o protocolo fica com congelada=0, e o
        # atestado nem passa pela guarda de congelamento (segue editavel de proposito, glosa).
        # `recebida` NAO entra aqui: la o atestado continua editavel (spec §5) e o protocolado
        # ja e' barrado pelo congelamento.
        if m["estado"] in ("cancelada", "desistida"):
            raise ValueError(f"Medição em estado final ({m['estado']}) não recebe valores")
        # Congelamento barra ALTERACAO do protocolado, nao o primeiro preenchimento: uma
        # medicao protocolada pela deteccao (fase 6) ou registrada sem valor (pendencia
        # "protocolada sem valor" do painel) ainda precisa receber o valor do oficio uma
        # vez. Com valor ja' gravado, correcao e' reapresentacao (evento novo).
        if campo == "protocolado" and m["congelada"] and m["valor_protocolado_centavos"] is not None:
            raise ValueError("Medição congelada: valor protocolado não pode mais mudar (registre reapresentação)")
        # Valor que veio do espelho so' muda gerando o espelho de novo, em estado nenhum a mao
        # (testes de quebra 10/10/2026, A-16): a 631 virou R$ 1,00 depois da nota e nada avisou.
        if campo == "protocolado" and m["valor_protocolado_origem"] == "espelho":
            raise ValueError("O valor desta medição vem do espelho: para mudar, gere o espelho de novo")
        # Issue #281: da planilha/carta ao boletim, o pedido so' muda por versao nova (com motivo)
        if campo == "protocolado" and m["estado"] in ESTADOS_PLANILHA:
            # depois do boletim nem a revisao e' aceita: so' orienta a revisao onde ela existe (gate Sol, rodada 2)
            raise ValueError(PEDIDO_DEPOIS_DO_BOLETIM if m["estado"] == "boletim_recebido" else PEDIDO_POR_REVISAO)
        # Issue #289 (PR #382): enviada a planilha/carta, o pedido nao muda a mao em estado nenhum (o espelho leva a
        # medicao a `espelho_gerado`, fora de ESTADOS_PLANILHA)
        if campo == "protocolado" and m["planilha_enviada_em"]:
            raise ValueError(PEDIDO_ENVIADO)
        # Issue #284: o espelho leva a medicao da planilha/carta adiante sem trocar o pedido; dali em diante ele
        # tambem nao muda a mao (congela no envio da planilha, spec §2.1)
        if campo == "protocolado" and conn.execute("SELECT 1 FROM medicao_planilhas WHERE medicao_id=? LIMIT 1",
                                                   (medicao_id,)).fetchone():
            raise ValueError("O pedido vem da planilha/carta e não se altera à mão")
        # Issue #284 (gate Sol): com boletim registrado, o aprovado so' muda por boletim novo (com o documento);
        # o atesto digitado ficaria fora da lista de boletins e o espelho sairia por ele
        if campo == "atestado" and tem_boletim(conn, medicao_id):
            raise ValueError(APROVADO_PELO_BOLETIM)
        col_v, col_o = f"valor_{campo}_centavos", f"valor_{campo}_origem"
        antes = {col_v: m[col_v], col_o: m[col_o]}
        extra_sql, extra_par = "", []
        if campo == "atestado":
            # Sem data nova, a anterior FICA (COALESCE): corrigir o valor da glosa nao
            # apaga o dia em que o orgao atestou.
            antes["atestado_em"] = m["atestado_em"]
            extra_sql, extra_par = ", atestado_em=COALESCE(?, atestado_em)", [data]
        # As condicoes fecham a janela entre a leitura acima e o UPDATE: outro usuario pode
        # protocolar (congelando) ou cancelar/desistir nesse meio-tempo, e o valor entraria numa
        # medicao ja congelada / ja encerrada. `congelada=0` so no caminho `protocolado` -- o
        # atestado e editavel enquanto a medicao vive (glosa, spec §5).
        cond = " AND estado NOT IN ('cancelada','desistida')"
        if campo == "protocolado":
            cond += (" AND (congelada=0 OR valor_protocolado_centavos IS NULL)"
                     " AND COALESCE(valor_protocolado_origem, '') <> 'espelho' AND planilha_enviada_em IS NULL"
                     f" AND estado NOT IN ({','.join(repr(e) for e in ESTADOS_PLANILHA)})")
        cur = conn.execute(f"UPDATE medicoes SET {col_v}=?, {col_o}=?{extra_sql} WHERE id=?{cond}",
                           (centavos, origem, *extra_par, medicao_id))
        db.exigir_uma_linha(cur, "Medição congelada ou encerrada concorrentemente: o valor não pôde ser "
                                 "gravado (se houve reapresentação, registre o novo protocolo)")
        depois = {col_v: centavos, col_o: origem}
        if campo == "atestado":
            # O que FICOU gravado (COALESCE), como no motivo de mudar_estado.
            depois["atestado_em"] = data if data is not None else m["atestado_em"]
            # Issue #61 (decisao do Leo, 15/10/2026): cada mudanca de atesto e' um evento append-only, com autor e
            # data; a coluna acima e' o vigente (o ultimo evento). Regravar o mesmo atesto nao vira evento.
            # A origem entra (revisor R3): confirmar um atesto detectado, sem mudar valor nem dia, e' ato com autor
            if (centavos, origem, depois["atestado_em"]) != (m[col_v], m[col_o], m["atestado_em"]):
                conn.execute("INSERT INTO medicao_atestos (medicao_id, valor_centavos, origem, atestado_em, usuario_id) "
                             "VALUES (?,?,?,?,?)", (medicao_id, centavos, origem, depois["atestado_em"], usuario_id))
        auditoria.registrar(conn, usuario_id, f"medicao.valor_{campo}", "medicao", medicao_id,
                            antes, depois)

def registrar_protocolo(conn, usuario_id: int, medicao_id: int, data: str,
                        numero_oficio, numero_processo, origem: str,
                        apesar_das_pendencias: bool = False,
                        justificativa: str | None = None,
                        protocolo_id: int | None = None,
                        exige_nota: bool = False) -> tuple[int, dict | None]:
    """Protocolo com o checklist de certidoes acoplado (fase 3,5).

    O veredito (`checklist.pronto_para_protocolar`) e' lido DENTRO da transacao, sob o
    BEGIN IMMEDIATE: uma leitura antes do envelope podia ficar obsoleta entre a
    conferencia e a gravacao (certidao revogada, tipo tornado aplicavel), e a ressalva
    auditada nao descreveria as pendencias do instante do commit. Com pendencia, o
    protocolo so' passa se o operador assumiu (`apesar_das_pendencias`) E justificou;
    a ressalva -- pendencias + justificativa -- vai inteira para a auditoria.

    `exige_nota` (A-09, 10/10/2026): so' a rota do protocolo feito fora liga. Envio pelo sistema, envio por
    fora e carga legada tambem gravam origem "manual"/"aceito" e ja' chegam assumidos com justificativa propria.
    """
    with db.mutacao(conn):
        m = detalhe(conn, medicao_id)
        atual = m["estado"]
        if atual in ("cancelada", "desistida", "recebida"):
            raise ValueError(f"Medição em estado final ({atual}) não recebe protocolo")
        if atual not in (*ESTADOS_PROMOVIDOS_PELO_PROTOCOLO, *ESTADOS_DE_NOVO_PROTOCOLO):
            # Gate Sol S4 (#281): planilha enviada e boletim recebido congelariam o pedido sem mudar o estado
            raise ValueError(f"Medição {rotulo_estado(atual)} não recebe protocolo")
        if exige_nota and atual == "nota_emitida":
            # Issue #188: o protocolo registrado a mao tambem espera a outra metade onde o orgao junta medicao e
            # reajuste (conferido aqui, sob o mesmo lock da gravacao)
            from app import notas_envio      # import local: notas_envio importa protocolo, que importa este modulo
            notas_envio.recusar_se_espera(conn, m)
        # Bloco 4: a exigencia depende da natureza (medicao/projeto x reajuste) e inclui consorciadas.
        ck = checklist.pronto_para_protocolar(conn, m["contrato_id"], m["tipo"])
        itens_pendentes = [i for i in ck["itens"] if i["situacao"] == "pendente"]
        # Uma empresa so': o nome do documento basta (e a ressalva gravada fica como antes). Mais de
        # uma (consorcio): "Rivoli: CRF/FGTS", senao a pendencia nao diz de quem e'.
        varias = len({i["entidade_id"] for i in itens_pendentes}) > 1
        pendentes = [f"{i['entidade']}: {i['tipo']}" if varias else i["tipo"] for i in itens_pendentes]
        motivos = []
        if pendentes:
            motivos.append(f"{len(pendentes)} {'documento' if len(pendentes) == 1 else 'documentos'} sem validade "
                           f"hoje ({', '.join(pendentes)})")
        # A-09 (testes de quebra 10/10/2026): o protocolo registrado a mao antes da nota pulava faturamento,
        # nota e envio sem pedir nada. Vira pendencia da MESMA lista: so' passa assumida e justificada.
        # Gate Sol S3: na ressalva, `pendencias` traz tudo e `certidoes_pendentes` so' as certidoes.
        sem_nota = exige_nota and atual in ("prevista", "planilha_gerada", *ESTADOS_ESPELHO)   # #281: planilha
        pendencias = [*pendentes, NOTA_NAO_EMITIDA] if sem_nota else list(pendentes)
        if sem_nota:
            motivos.append(NOTA_NAO_EMITIDA)
        ressalva = None
        if pendencias:
            if not apesar_das_pendencias:
                acao = "Anexe em Documentos ou registre" if itens_pendentes else "Registre"
                raise ValueError(f"Protocolo travado: {'; '.join(motivos)}. {acao} o protocolo apesar das "
                                 f"pendências, com justificativa.")
            # Gate Sol S6 (10/10/2026): o mesmo minimo para qualquer pendencia, certidao ou nota.
            from app.protocolo import MIN_JUSTIFICATIVA  # aqui: protocolo importa medicoes no topo
            if len((justificativa or "").strip()) < MIN_JUSTIFICATIVA:
                raise ValueError(f"Protocolar com pendência exige justificativa "
                                 f"(ao menos {MIN_JUSTIFICATIVA} caracteres)")
            ressalva = {"pendencias": pendencias, "certidoes_pendentes": pendentes,
                        "justificativa": justificativa.strip()}
        # UPDATE condicional ao estado LIDO (padrao da fase 1, contratos.mudar_estado): entre o
        # SELECT e o UPDATE outro usuario pode cancelar/mover a medicao. Sem a condicao, o
        # perdedor da corrida sobrescreveria um estado final. Vem ANTES do INSERT para nao
        # deixar protocolo orfao na transacao quando a corrida e perdida.
        if atual in ESTADOS_PROMOVIDOS_PELO_PROTOCOLO:
            upd = conn.execute(
                "UPDATE medicoes SET estado='protocolada', congelada=1 WHERE id=? AND estado=?",
                (medicao_id, atual))
        else:
            upd = conn.execute("UPDATE medicoes SET congelada=1 WHERE id=? AND estado=?",
                               (medicao_id, atual))
        db.exigir_uma_linha(upd, "Estado da medição mudou concorrentemente; tente novamente")
        # Bloco 5: `protocolo_id` liga ao protocolo feito pelo sistema (e, por ele, ao e-mail enviado).
        cur = conn.execute(
            "INSERT INTO medicao_protocolos (medicao_id, data, numero_oficio, numero_processo, origem, protocolo_id) "
            "VALUES (?,?,?,?,?,?)", (medicao_id, data, numero_oficio, numero_processo, origem, protocolo_id))
        depois = {"data": data, "numero_oficio": numero_oficio,
                  "numero_processo": numero_processo, "origem": origem}
        if protocolo_id is not None:
            depois["protocolo_id"] = protocolo_id
        if ressalva:
            depois["ressalva"] = ressalva
        auditoria.registrar(conn, usuario_id, "medicao.protocolo", "medicao", medicao_id, None, depois)
    # A ressalva volta ao chamador para a rota devolve-la (a tela mostra o que ficou
    # registrado); `None` quando nao houve pendencia.
    return cur.lastrowid, ressalva

# Estado -> coluna que guarda a DATA do marco (spec §6: Emitido = emissao da NF,
# Recebido = baixa). Os encerramentos por excecao nao tem eixo de indicador.
COLUNA_DATA = {"nota_emitida": "nota_emitida_em", "nf_emitida": "nf_emitida_em", "recebida": "recebida_em"}


def mudar_estado(conn, usuario_id: int, medicao_id: int, novo: str, motivo: str | None,
                 data: str | None = None, origem: str | None = None) -> None:
    """`origem` (issue #203): quem o servidor sabe que fez a transicao ("manual" pela rota de estado, "corte" pelo
    comando do corte), gravada na auditoria; quem digita o motivo nao a controla."""
    if data is not None and novo not in COLUNA_DATA:
        raise ValueError(f"O estado {novo} não tem data de marco (só nota emitida, lançada no RM e recebida)")
    with db.mutacao(conn):
        m = detalhe(conn, medicao_id)
        atual = m["estado"]
        motivo_antes = m["motivo_represamento"]
        if novo not in TRANSICOES.get(atual, set()):
            dica = ""
            if atual == "prevista" and novo == "protocolada":
                dica = " (protocolar é pelo registro de protocolo, que congela o valor)"
            raise ValueError(f"Transição inválida: {atual} → {novo}{dica}")
        # COALESCE: motivo=None PRESERVA o motivo anterior em vez de apaga-lo (uma transicao
        # sem motivo novo nao e' um pedido de esquecer o antigo).
        # `AND estado=?`: a transicao so vale a partir do estado que foi validado. Se outro
        # usuario mudou o estado nesse meio-tempo, rowcount=0 e o perdedor recebe erro em vez
        # de sobrescrever (padrao da fase 1, contratos.mudar_estado).
        col_data = COLUNA_DATA.get(novo)
        if data is not None:
            # Ordem dos marcos (spec §6): NF nao sai antes do ultimo protocolo, e a baixa
            # nao vem antes da NF. So' compara com data CONHECIDA -- marco anterior sem
            # data nao inventa restricao.
            if novo == "nf_emitida":
                ultimo = max((p["data"] for p in m["protocolos"]), default=None)
                if ultimo and data < ultimo:
                    raise ValueError(f"Data da NF ({data}) anterior ao último protocolo ({ultimo})")
            elif novo == "recebida" and m["nf_emitida_em"] and data < m["nf_emitida_em"]:
                raise ValueError(f"Data da baixa ({data}) anterior à emissão da NF ({m['nf_emitida_em']})")
            elif novo == "recebida" and m["nota_emitida_em"] and data < m["nota_emitida_em"]:
                raise ValueError(f"Data da baixa ({data}) anterior à emissão da nota ({m['nota_emitida_em']})")
            # `nota_emitida` nao tem checagem de ordem: a nota vem ANTES do protocolo (spec §2).
        extra_sql = f", {col_data}=?" if col_data else ""
        extra_par = [data] if col_data else []
        cur = conn.execute(
            "UPDATE medicoes SET estado=?, motivo_represamento=COALESCE(?, motivo_represamento)"
            f"{extra_sql} WHERE id=? AND estado=?", (novo, motivo, *extra_par, medicao_id, atual))
        db.exigir_uma_linha(cur, "Estado da medição mudou concorrentemente; tente novamente")
        # A auditoria registra o que FICOU GRAVADO, nao o parametro recebido: com motivo=None,
        # auditar depois={"motivo": None} descreveria um apagamento que o COALESCE nao fez --
        # numa cadeia append-only, a versao auditada tem que casar com a persistida.
        motivo_final = motivo if motivo is not None else motivo_antes
        depois = {"estado": novo, "motivo": motivo_final}
        if col_data:
            depois[col_data] = data
        if origem is not None:
            depois["origem"] = origem
        auditoria.registrar(conn, usuario_id, "medicao.estado", "medicao", medicao_id,
                            {"estado": atual, "motivo": motivo_antes}, depois)


def valor_travado(m) -> tuple[int, str] | None:
    """Issue #284: o valor que o espelho tem de usar, (centavos, fonte): o aprovado do boletim (vigente = ultimo
    evento), senao o pedido (planilha/carta ou valor registrado a mao). O valor que o proprio espelho gravou nao
    trava: ele e' o digitado e muda gerando de novo."""
    if m["valor_atestado_centavos"] is not None:
        return m["valor_atestado_centavos"], "aprovado"
    if m["valor_protocolado_centavos"] is not None and m["valor_protocolado_origem"] != "espelho":
        return m["valor_protocolado_centavos"], "pedido"
    return None


def conferir_espelho_da_planilha(conn, ja: dict, numero: int, tipo: str, competencia: str) -> None:
    """Issue #289: a medicao da planilha/carta so' recebe espelho depois do envio ao orgao, sem revisao registrada
    e ainda nao enviada e na competencia dela. O VALOR nao e' conferido aqui: desde a #284 o espelho usa o aprovado do
    boletim, senao o pedido (espelhos._calcular, valor travado). `ja` traz id, estado, competencia e
    planilha_enviada_em."""
    if ja["estado"] == "planilha_gerada":
        raise ValueError(f"{nome_medicao(numero, tipo)} {PLANILHA_SEM_ENVIO}")
    if not ja.get("planilha_enviada_em"):
        return
    # uma versao saindo pelo sistema (reserva ativa) segura o espelho: o e-mail ainda vai registrar o envio dela
    if conn.execute("SELECT 1 FROM medicao_planilha_envios WHERE medicao_id=? AND envio_id IS NULL "
                    "AND envio_reservado_em IS NOT NULL", (ja["id"],)).fetchone() is not None:
        raise ValueError(f"A planilha/carta da {nome_medicao(numero, tipo)} está sendo enviada ao protocolo: aguarde "
                         "o envio terminar (ou libere o envio preso) antes de gerar o espelho")
    # revisao registrada e ainda nao enviada (rodada extra, PR #382): o espelho a levaria a `espelho_gerado`, onde ela
    # nao sai mais por caminho nenhum. A vigente tem de ser a ultima enviada (pelo sistema ou por fora).
    if ja["estado"] in ("planilha_enviada", "boletim_recebido"):
        from app import planilha_envio      # import local: planilha_envio importa este modulo
        vigente = conn.execute("SELECT MAX(versao) FROM medicao_planilhas WHERE medicao_id=?",
                               (ja["id"],)).fetchone()[0] or 0
        # com o boletim recebido a planilha/carta tambem ja' foi enviada (ao menos a 1a versao)
        if vigente > planilha_envio._ultima_enviada(conn, {"id": ja["id"], "estado": "planilha_enviada"}):
            raise ValueError(f"A {nome_medicao(numero, tipo)} tem revisão da planilha/carta registrada e não enviada: "
                             "envie ao protocolo (ou registre o envio por fora) antes de gerar o espelho")
    if ja["competencia"] != competencia:
        raise ValueError(f"{nome_medicao(numero, tipo)} tem a planilha/carta da competência "
                         f"{ja['competencia'][5:7]}/{ja['competencia'][:4]}: gere o espelho nessa competência")


def criar_para_espelho(conn, usuario_id: int, contrato_id: int, numero: int, tipo: str,
                       competencia: str, valor_centavos: int) -> int:
    """A medicao nasce ao gerar o espelho (spec §2). Gerar de novo atualiza o valor enquanto a
    medicao nao foi protocolada; depois disso correcao e' fora do escopo (nao ha' glosa pos-protocolo).
    Issue #284: a medicao que ja' existe antes do espelho (prevista, planilha/carta, boletim) vai a `espelho_gerado`
    sem trocar o pedido; com valor travado (aprovado ou pedido), o pedido nunca e' sobrescrito pelo espelho."""
    with db.mutacao(conn):
        ja = conn.execute("SELECT id, estado, competencia, valor_protocolado_centavos, valor_protocolado_origem, "
                          "valor_atestado_centavos, planilha_enviada_em FROM medicoes "
                          "WHERE contrato_id=? AND numero=? AND tipo=?", (contrato_id, numero, tipo)).fetchone()
        if ja is None:
            cur = conn.execute(
                "INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, "
                "valor_protocolado_centavos, valor_protocolado_origem) VALUES (?,?,?,?,'espelho_gerado',?,'espelho')",
                (contrato_id, numero, tipo, competencia, valor_centavos))
            auditoria.registrar(conn, usuario_id, "medicao.criar", "medicao", cur.lastrowid, None,
                                {"numero": numero, "tipo": tipo, "competencia": competencia,
                                 "estado": "espelho_gerado", "valor_protocolado_centavos": valor_centavos})
            return cur.lastrowid
        # Issue #289: a planilha/carta so' recebe espelho enviada, sem revisao pendente e na competencia dela (a
        # protocolada em diante cai na recusa de baixo)
        if ja["estado"] in (*ESTADOS_ANTES_DO_ESPELHO, *ESTADOS_ESPELHO):
            conferir_espelho_da_planilha(conn, dict(ja), numero, tipo, competencia)
        if ja["estado"] in ESTADOS_ANTES_DO_ESPELHO:
            # o pedido fica; sem pedido (prevista vazia), o valor do espelho entra como o de hoje
            pedido = ja["valor_protocolado_centavos"]
            novo = {"estado": "espelho_gerado", "competencia": competencia,
                    "valor_protocolado_centavos": valor_centavos if pedido is None else pedido,
                    "valor_protocolado_origem": "espelho" if pedido is None else ja["valor_protocolado_origem"]}
            cur = conn.execute(
                "UPDATE medicoes SET estado='espelho_gerado', competencia=?, valor_protocolado_centavos=?, "
                "valor_protocolado_origem=? WHERE id=? AND estado=?",
                (competencia, novo["valor_protocolado_centavos"], novo["valor_protocolado_origem"], ja["id"],
                 ja["estado"]))
            db.exigir_uma_linha(cur, "Estado da medição mudou concorrentemente; tente novamente")
            auditoria.registrar(conn, usuario_id, "medicao.estado", "medicao", ja["id"],
                                {k: ja[k] for k in novo}, {**novo, "valor_do_espelho_centavos": valor_centavos})
            if pedido is None:
                # o valor novo tem o evento proprio, como na medicao que nasce no espelho (linha do tempo)
                auditoria.registrar(conn, usuario_id, "medicao.valor_protocolado", "medicao", ja["id"],
                                    {"valor_protocolado_centavos": None},
                                    {"valor_protocolado_centavos": valor_centavos, "valor_protocolado_origem": "espelho"})
            return ja["id"]
        if ja["estado"] not in ESTADOS_ESPELHO:
            raise ValueError(f"{nome_medicao(numero, tipo)} já está {rotulo_estado(ja['estado'])}: o espelho não pode ser "
                             "gerado de novo depois de protocolada")
        # Issue #359 (decisao do Leo de 03/11/2026): a versao nova volta a medicao a `espelho_gerado` ate' o envio
        # dela ao faturamento (marcar_espelho_enviado): a tela volta a pedir o envio, em vez de esperar a nota
        if valor_travado(ja) is not None:
            # o valor do espelho e' o travado (conferido em espelhos._calcular); o pedido nao muda
            cur = conn.execute("UPDATE medicoes SET competencia=?, estado='espelho_gerado' WHERE id=? AND estado=?",
                               (competencia, ja["id"], ja["estado"]))
            db.exigir_uma_linha(cur, "Estado da medição mudou concorrentemente; tente novamente")
            _registrar_volta_a_gerado(conn, usuario_id, ja)
            return ja["id"]
        cur = conn.execute("UPDATE medicoes SET valor_protocolado_centavos=?, valor_protocolado_origem='espelho', "
                           "competencia=?, estado='espelho_gerado' WHERE id=? AND estado=?",
                           (valor_centavos, competencia, ja["id"], ja["estado"]))
        db.exigir_uma_linha(cur, "Estado da medição mudou concorrentemente; tente novamente")
        _registrar_volta_a_gerado(conn, usuario_id, ja)
        auditoria.registrar(conn, usuario_id, "medicao.valor_protocolado", "medicao", ja["id"],
                            {"valor_protocolado_centavos": ja["valor_protocolado_centavos"]},
                            {"valor_protocolado_centavos": valor_centavos, "valor_protocolado_origem": "espelho"})
        return ja["id"]


def _registrar_volta_a_gerado(conn, usuario_id: int, ja) -> None:
    """A auditoria da volta de `espelho_enviado` a `espelho_gerado` pela versao nova do espelho (issue #359)."""
    if ja["estado"] == "espelho_enviado":
        auditoria.registrar(conn, usuario_id, "medicao.estado", "medicao", ja["id"], {"estado": "espelho_enviado"},
                            {"estado": "espelho_gerado", "motivo": "versão nova do espelho"})


def marcar_espelho_enviado(conn, usuario_id: int, medicao_id: int) -> None:
    """Transicao do SISTEMA no ato do envio ao faturamento. Ja' enviado: nada a fazer."""
    with db.mutacao(conn):
        cur = conn.execute("UPDATE medicoes SET estado='espelho_enviado' WHERE id=? AND estado='espelho_gerado'",
                           (medicao_id,))
        if cur.rowcount == 1:
            auditoria.registrar(conn, usuario_id, "medicao.estado", "medicao", medicao_id,
                                {"estado": "espelho_gerado"}, {"estado": "espelho_enviado"})


# --- bloco 6: lista de medicoes em andamento (spec §10.2) -------------------------------------------

def titulo(m: dict) -> str:
    """"23ª Medição", "Reajuste da 23ª Medição", "3ª Medição de Projeto" (era `protocolo.titulo`)."""
    if m["tipo"] == "reajuste":
        return f"Reajuste da {m['numero']}ª Medição"
    return f"{m['numero']}ª Medição" + (" de Projeto" if m["tipo"] == "projeto" else "")


PROXIMO_PASSO = {"planilha_gerada": "enviar a planilha/carta", "planilha_enviada": "registrar o boletim",
                 "boletim_recebido": "gerar o espelho", "espelho_gerado": "enviar ao faturamento", "espelho_enviado": "anexar as notas",
                 "nota_emitida": "protocolar", "protocolada": "aguardando pagamento",
                 "nf_emitida": "aguardando pagamento"}


def em_andamento(conn, contrato_id: int | None = None, estado: str | None = None) -> list[dict]:
    """Medicoes entre o espelho e o pagamento, com o proximo passo e a data do ultimo marco."""
    sql = ("SELECT m.*, c.nome_curto, c.numero_instrumento, "
           "(SELECT MAX(p.data) FROM medicao_protocolos p WHERE p.medicao_id=m.id AND p.etapa='nota') AS protocolado_em "
           "FROM medicoes m JOIN contratos c ON c.id=m.contrato_id "
           f"WHERE m.estado IN ({','.join('?' * len(PROXIMO_PASSO))})")
    args: list = list(PROXIMO_PASSO)
    if contrato_id is not None:
        sql += " AND m.contrato_id=?"
        args.append(contrato_id)
    if estado is not None:
        sql += " AND m.estado=?"
        args.append(estado)
    out = []
    for r in conn.execute(sql + " ORDER BY c.nome_curto, c.id, m.numero DESC, m.tipo", args):
        # dia de Cuiaba (`_dia`) nos marcos e no criado_em: carimbo UTC das 20h as 24h cairia no dia seguinte
        brutos = [r["espelho_em"], r["nota_emitida_em"], r["protocolado_em"]]
        # marcos do motor so' no estado deles: atesto/glosa posterior numa medicao adiante nao rebaixa o "desde"
        if r["estado"] == "planilha_enviada":
            brutos.append(r["planilha_enviada_em"])
        if r["estado"] == "boletim_recebido":
            brutos.append(r["atestado_em"])
        marcos = [d.isoformat() for d in map(_dia, brutos) if d]
        criado = _dia(r["criado_em"])
        out.append({"id": r["id"], "contrato_id": r["contrato_id"],
                    "obra": r["nome_curto"] or r["numero_instrumento"], "numero": r["numero"], "tipo": r["tipo"],
                    "titulo": titulo(r), "competencia": r["competencia"], "estado": r["estado"],
                    # #284: o valor da linha e' o que vale para a nota (aprovado, senao pedido), em todo estado
                    "valor_centavos": (valor_travado(r) or (r["valor_protocolado_centavos"],))[0],
                    "proximo_passo": PROXIMO_PASSO[r["estado"]],
                    "desde": max(marcos) if marcos else (criado.isoformat() if criado else ""),
                    # os marcos crus, para quem precisa do marco da SITUACAO e nao do mais recente (resumo abaixo)
                    "espelho_em": r["espelho_em"], "nota_emitida_em": r["nota_emitida_em"],
                    "protocolado_em": r["protocolado_em"], "planilha_enviada_em": r["planilha_enviada_em"],
                    "atestado_em": r["atestado_em"]})
    return out


# --- pagina Medicoes com abas (09/10/2026, prototipo aprovado pelo Leo) ---------------------------------
# Estado -> situacao, que e' a aba da pagina. As chaves sao as do PROXIMO_PASSO: "em andamento" continua sendo um
# lugar so' (o teste confere). `nf_emitida` e' o legado do bloco 3 (o remapeamento leva a zero) e espera o orgao
# como a protocolada. `prevista` (criada pelo cronograma, sem espelho) fica de fora DE PROPOSITO: a obra com so'
# uma prevista esta' "sem medicao aberta" (decisao do Leo).
SITUACAO = {"planilha_gerada": "planilha-gerada", "planilha_enviada": "planilha-enviada",
            "boletim_recebido": "boletim-recebido", "espelho_gerado": "faturamento", "espelho_enviado": "aguardando-nota", "nota_emitida": "enviar-nota",
            "protocolada": "aguardando-pagamento", "nf_emitida": "aguardando-pagamento"}
ORDEM_SITUACAO = ("planilha-gerada", "planilha-enviada", "boletim-recebido", "faturamento", "aguardando-nota", "enviar-nota", "aguardando-pagamento")

# Sigla curta do contratante pela chave do orgao no cadastro (orgaos.chave). A SINFRA sai da familia, com a
# superintendencia ao lado; o que nao estiver aqui aparece com o nome do cadastro, sem sigla inventada.
SIGLA_ORGAO = {"mtpar": "MTPAR", "ses-mt": "SES-MT", "pref-cuiaba": "Pref. Cuiabá", "pref-vg": "Pref. Várzea Grande",
               "rota-do-oeste": "Rota do Oeste"}


def contratante(familia: str | None, chave: str | None, nome: str | None, orgao_texto: str | None) -> tuple[str, str | None]:
    """(sigla, sub-orgao): ("SINFRA", "SUEF II"), ("MTPAR", None). O cadastro escreve "SINFRA - SUEF II" e
    "SINFRA - SUPU (Pavimentação Urbana)": a superintendencia e' o que vem depois do traco, sem o parentese.
    Contrato sem orgao no cadastro (anterior ao bloco 1) fica com o texto livre do proprio contrato."""
    if familia == "sinfra":
        sub = (nome or "").split(" - ", 1)[1].split(" (")[0].strip() if " - " in (nome or "") else ""
        return "SINFRA", sub or None
    if chave in SIGLA_ORGAO:
        return SIGLA_ORGAO[chave], None
    return nome or orgao_texto or "sem contratante", None


def _dia(valor: str | None) -> datetime.date | None:
    """Data do negocio (Cuiaba). So' a data ("2026-10-08": nota, protocolo) ja' e' do negocio; carimbo com hora
    (criado_em do espelho, enviado_em do e-mail) e' UTC do SQLite e vira o dia local (app/tempo.py)."""
    if not valor:
        return None
    try:
        if len(valor) <= 10:
            return datetime.date.fromisoformat(valor)
        return tempo.para_local(datetime.datetime.fromisoformat(valor.replace("Z", ""))).date()
    except ValueError:
        return None


def resumo(conn, hoje: datetime.date | None = None) -> dict:
    """Pagina Medicoes (abas): contagem por situacao, as medicoes em andamento e as obras ativas.

    "Parada ha'" conta do marco da SITUACAO ATUAL, nunca do criado_em (lancar a medicao nao e' marco de nada):
    enviar ao faturamento = o espelho vigente gerado; aguardando nota = o e-mail ao faturamento; enviar nota = a
    emissao da nota; aguardando pagamento = o envio ao orgao (o protocolo). Sem marco, `dias` nulo ("—").

    Medicao e reajuste da mesma obra, numero e competencia, na mesma situacao, viram UMA linha ("24ª Medição +
    Reajuste") com o valor somado e o marco mais antigo dos dois; o resto (projeto, reajuste em outra situacao)
    fica em linha propria, com o titulo de sempre."""
    hoje = hoje or tempo.hoje_local()
    obras = {r["id"]: dict(r) for r in conn.execute(
        "SELECT c.id, c.estado, COALESCE(c.nome_curto, c.numero_instrumento) AS obra, c.orgao AS orgao_texto, "
        "c.encerramento_iniciado_em, o.familia, o.chave, o.nome FROM contratos c LEFT JOIN orgaos o ON o.id=c.orgao_id")}
    for o in obras.values():
        o["contratante"], o["orgao_sub"] = contratante(o["familia"], o["chave"], o["nome"], o["orgao_texto"])
    # marcos que a tabela medicoes nao guarda: o espelho VIGENTE (o substituido nao conta) e o e-mail do envio
    espelho_de = dict(conn.execute(
        "SELECT em.medicao_id, MAX(e.criado_em) FROM espelho_medicoes em JOIN espelhos e ON e.id=em.espelho_id "
        "WHERE e.situacao='vigente' GROUP BY em.medicao_id").fetchall())
    envio_de = dict(conn.execute(
        "SELECT en.medicao_id, MAX(v.enviado_em) FROM envio_medicoes en JOIN envios v ON v.id=en.envio_id "
        "GROUP BY en.medicao_id").fetchall())

    planilha_de = dict(conn.execute("SELECT medicao_id, MIN(criado_em) FROM medicao_planilhas GROUP BY medicao_id").fetchall())

    def marco(m: dict) -> datetime.date | None:
        # os tres estados do motor (spec motores §2.1): o marco e' o do proprio estado
        if m["estado"] == "planilha_gerada":
            return _dia(planilha_de.get(m["id"]))
        if m["estado"] == "planilha_enviada":
            return _dia(m["planilha_enviada_em"])
        if m["estado"] == "boletim_recebido":
            return _dia(m["atestado_em"])
        if m["estado"] == "espelho_gerado":
            return _dia(espelho_de.get(m["id"])) or _dia(m["espelho_em"])
        if m["estado"] == "espelho_enviado":
            return _dia(envio_de.get(m["id"]))
        if m["estado"] == "nota_emitida":
            return _dia(m["nota_emitida_em"])
        return _dia(m["protocolado_em"])

    grupos: dict[tuple, list[dict]] = {}
    andamento = em_andamento(conn)
    for m in andamento:
        grupos.setdefault((m["contrato_id"], m["numero"], m["competencia"], SITUACAO[m["estado"]]), []).append(m)
    linhas = []
    for (cid, _numero, _comp, situacao), ms in grupos.items():
        tipos = {m["tipo"]: m for m in ms}
        # (contrato, numero, tipo) e' UNIQUE: no grupo ha' no maximo uma de cada tipo
        par = [tipos["execucao"], tipos["reajuste"]] if {"execucao", "reajuste"} <= set(tipos) else []
        partes = ([par] if par else []) + [[m] for m in ms if m not in par]
        for p in partes:
            principal = p[0]
            datas = [d for d in (marco(m) for m in p) if d]
            valores = [m["valor_centavos"] for m in p if m["valor_centavos"] is not None]
            d = min(datas) if datas else None
            o = obras.get(cid, {})
            linhas.append({
                "situacao": situacao, "contrato_id": cid, "obra": principal["obra"],
                "contratante": o.get("contratante"), "orgao_sub": o.get("orgao_sub"),
                "medicao_id": principal["id"], "medicao_ids": [m["id"] for m in p],
                "numero": principal["numero"], "competencia": principal["competencia"],
                "titulo": f"{principal['titulo']} + Reajuste" if len(p) == 2 else principal["titulo"],
                "proximo_passo": principal["proximo_passo"],
                "valor_centavos": sum(valores) if valores else None,
                "marco": d.isoformat() if d else None, "dias": (hoje - d).days if d else None})
    linhas.sort(key=lambda x: (ORDEM_SITUACAO.index(x["situacao"]), _chave_nome(x["obra"]), x["contrato_id"],
                               -x["numero"], x["titulo"]))

    abertas = {x["contrato_id"] for x in linhas}
    # #151 (15/10/2026): a janela "Iniciar processo" mostra a medicao aberta (id, numero e passo), a prevista (numero e
    # competencia) e a ultima de cada serie. Serie de execucao = execucao + reajuste (o reajuste acompanha o numero);
    # a de Projeto so' existe na obra que ja' teve uma medicao de Projeto.
    prevista_serie: dict[tuple[int, bool], dict] = {}
    teve_projeto: set[int] = set()
    for r in conn.execute("SELECT contrato_id, id, numero, tipo, competencia FROM medicoes WHERE estado='prevista' "
                          "AND tipo IN ('execucao','projeto') ORDER BY competencia, numero, id"):
        # a prevista de reajuste (lancada a mao) nao e' a da serie: abriria o reajuste no lugar da execucao
        chave = (r["contrato_id"], r["tipo"] == "projeto")
        if chave not in prevista_serie:   # a mais antiga da serie
            prevista_serie[chave] = {"id": r["id"], "numero": r["numero"], "competencia": r["competencia"]}
        if chave[1]:
            teve_projeto.add(r["contrato_id"])
    aberta_de: dict[tuple[int, bool], dict] = {}
    for m in andamento:
        chave = (m["contrato_id"], m["tipo"] == "projeto")
        atual = aberta_de.get(chave)
        # a de execucao vence o reajuste do mesmo numero; entre numeros, a maior
        if atual is None or (m["numero"], m["tipo"] == "execucao") > (atual["numero"], atual["tipo"] == "execucao"):
            aberta_de[chave] = m
    ultima_serie: dict[tuple[int, bool], dict] = {}
    for r in conn.execute("SELECT contrato_id, numero, tipo, competencia FROM medicoes "
                          "WHERE estado NOT IN ('prevista', 'cancelada', 'desistida') ORDER BY numero, id"):
        if r["tipo"] == "reajuste":
            continue
        projeto = r["tipo"] == "projeto"
        if projeto:
            teve_projeto.add(r["contrato_id"])
        ultima_serie[(r["contrato_id"], projeto)] = {"numero": r["numero"], "competencia": r["competencia"]}

    def serie(cid: int, projeto: bool) -> dict:
        m = aberta_de.get((cid, projeto))
        p = prevista_serie.get((cid, projeto))
        return {"prevista_id": p["id"] if p else None, "prevista_numero": p["numero"] if p else None,
                "prevista_competencia": p["competencia"] if p else None,
                "aberta_id": m["id"] if m else None, "aberta_numero": m["numero"] if m else None,
                "aberta_passo": m["proximo_passo"] if m else None, "ultima": ultima_serie.get((cid, projeto))}

    prevista_de: dict[int, int] = {}
    prevista_dados: dict[int, dict] = {}   # a MESMA medicao de prevista_de: o rotulo e o link da aba nao divergem
    for r in conn.execute("SELECT contrato_id, id, numero, tipo, competencia FROM medicoes WHERE estado='prevista' "
                          "AND tipo IN ('execucao','projeto') ORDER BY competencia, tipo='projeto', numero, id"):
        if r["contrato_id"] not in prevista_de:
            prevista_de[r["contrato_id"]] = r["id"]
            prevista_dados[r["contrato_id"]] = {"numero": r["numero"], "tipo": r["tipo"], "competencia": r["competencia"]}
    # #154: ultima medicao de execucao ou projeto (o reajuste repete o numero da execucao; a prevista, a cancelada e
    # a desistida nao contam), com o tipo. Execucao e projeto sao series de numeracao PROPRIAS: a proxima e' a
    # prevista, ou a seguinte ao maior numero da serie de execucao (a cancelada tambem ocupa o numero); so' a obra
    # que nao tem execucao segue a serie de projeto.
    ultima_de: dict[int, dict] = {}
    for r in conn.execute("SELECT contrato_id, numero, tipo, competencia FROM medicoes WHERE tipo IN ('execucao','projeto') "
                          "AND estado NOT IN ('prevista','cancelada','desistida') ORDER BY competencia DESC, numero DESC"):
        ultima_de.setdefault(r["contrato_id"], {"numero": r["numero"], "tipo": r["tipo"], "competencia": r["competencia"]})
    maior = {(r[0], r[1]): r[2] for r in conn.execute(
        "SELECT contrato_id, tipo, MAX(numero) FROM medicoes WHERE tipo IN ('execucao','projeto') GROUP BY contrato_id, tipo")}

    def proxima(cid: int) -> tuple[int, str]:
        if cid in prevista_dados:
            p = prevista_dados[cid]
            return p["numero"], "projeto" if p["tipo"] == "projeto" else "execucao"
        if (cid, "execucao") in maior or (cid, "projeto") not in maior:
            return maior.get((cid, "execucao"), 0) + 1, "execucao"
        return maior[(cid, "projeto")] + 1, "projeto"

    def ha_dias(competencia: str) -> int:
        """Dias desde o FIM da competencia; competencia ainda em curso: 0 ("hoje"), como no prototipo."""
        ano, mes = int(competencia[:4]), int(competencia[5:7])
        return max(0, (hoje - datetime.date(ano, mes, calendar.monthrange(ano, mes)[1])).days)
    ativas = sorted((o for o in obras.values() if o["estado"] == "ativo"), key=lambda o: _chave_nome(o["obra"]))
    lista_obras = [{"contrato_id": o["id"], "obra": o["obra"], "contratante": o["contratante"],
                    "orgao_sub": o["orgao_sub"], "aberta": o["id"] in abertas,
                    "prevista_id": prevista_de.get(o["id"]),
                    # #151: cada serie no seu bloco; o `prevista_id` e a `ultima` de fora sao os da aba Sem medicao (#154)
                    "execucao": serie(o["id"], False),
                    "projeto": serie(o["id"], True) if o["id"] in teve_projeto or (o["id"], True) in aberta_de else None,
                    # A-21 (10/10/2026): a obra em encerramento segue na lista (mede a final), mas a tela nao a
                    # conta como "obra ativa" (a definicao de `avisos.ativos`, a do Inicio)
                    "encerramento": bool(o["encerramento_iniciado_em"]),
                    "ultima": ultima_de.get(o["id"]),
                    "ha_dias": ha_dias(ultima_de[o["id"]]["competencia"]) if o["id"] in ultima_de else None,
                    "prevista": prevista_dados.get(o["id"]),
                    "proxima": proxima(o["id"])[0], "proxima_tipo": proxima(o["id"])[1]}
                   for o in ativas]
    contagens = {"sem-medicao": sum(1 for o in lista_obras if not o["aberta"])}
    for s in ORDEM_SITUACAO:
        contagens[s] = sum(1 for x in linhas if x["situacao"] == s)
    # N-01 (10/10/2026): a aba abre a tabela de notas enviadas (`notas_envio.aguardando_pagamento`, uma linha por
    # medicao protocolada); contar as linhas daqui (o par medicao + reajuste vira uma) dava outro numero
    contagens["aguardando-pagamento"] = conn.execute(
        "SELECT COUNT(*) FROM medicoes WHERE estado='protocolada'").fetchone()[0]
    return {"hoje": hoje.isoformat(), "contagens": contagens, "linhas": linhas, "obras": lista_obras}


def _chave_nome(nome: str | None) -> str:
    """Ordem alfabetica sem acento e sem caixa ("Estações" junto de "Estacoes", "5 Bairros" antes de "Alta")."""
    return unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode().casefold()


# --- bloco 7: medicao final (spec §2, §7.4) ---------------------------------------------------------

def marcar_final(conn, usuario_id: int, medicao_id: int, data: str) -> None:
    """A medicao final poe o contrato em encerramento (se ainda nao estava), com auditoria nos dois."""
    with db.mutacao(conn):
        m = detalhe(conn, medicao_id)
        if m is None:
            raise ValueError("Medição não encontrada")
        if m["estado"] in ("cancelada", "desistida"):
            raise ValueError(f"Medição {m['estado']} não pode ser a final")
        conn.execute("UPDATE medicoes SET final=1, final_em=? WHERE id=?", (data, medicao_id))
        conn.execute("UPDATE contratos SET encerramento_iniciado_em=COALESCE(encerramento_iniciado_em, ?) WHERE id=?",
                     (data, m["contrato_id"]))
        auditoria.registrar(conn, usuario_id, "medicao.final", "medicao", medicao_id, {"final": m.get("final")},
                            {"final": 1, "final_em": data})
        auditoria.registrar(conn, usuario_id, "contrato.encerramento", "contrato", m["contrato_id"], None,
                            {"encerramento_iniciado_em": data, "por": "medicao_final", "medicao_id": medicao_id})


def desmarcar_final(conn, usuario_id: int, medicao_id: int, motivo: str) -> None:
    """Desfaz a marcacao com motivo; o encerramento so' sai se nenhuma outra medicao do contrato for final."""
    if not (motivo or "").strip():
        raise ValueError("Informe o motivo para desmarcar a medição final")
    with db.mutacao(conn):
        m = detalhe(conn, medicao_id)
        if m is None or not m.get("final"):
            raise ValueError("Esta medição não está marcada como final")
        conn.execute("UPDATE medicoes SET final=0, final_em=NULL WHERE id=?", (medicao_id,))
        auditoria.registrar(conn, usuario_id, "medicao.final", "medicao", medicao_id,
                            {"final": 1, "final_em": m.get("final_em")}, {"final": 0, "motivo": motivo.strip()})
        outra = conn.execute("SELECT 1 FROM medicoes WHERE contrato_id=? AND final=1 LIMIT 1",
                             (m["contrato_id"],)).fetchone()
        if outra is None:
            antes = conn.execute("SELECT encerramento_iniciado_em FROM contratos WHERE id=?",
                                 (m["contrato_id"],)).fetchone()[0]
            conn.execute("UPDATE contratos SET encerramento_iniciado_em=NULL WHERE id=?", (m["contrato_id"],))
            auditoria.registrar(conn, usuario_id, "contrato.encerramento", "contrato", m["contrato_id"],
                                {"encerramento_iniciado_em": antes},
                                {"encerramento_iniciado_em": None, "motivo": motivo.strip(), "medicao_id": medicao_id})
