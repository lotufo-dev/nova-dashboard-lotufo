"""Medicoes: 4 estados visiveis + excecoes, origem por dado, congelamento no protocolo.

Fase 2: transicoes manuais (importacao); fases 5-6 passam a mover nf_emitida/recebida
por deteccao. Regra de congelamento (spec §5): apos o 1o protocolo (marco externo),
o valor PROTOCOLADO nao muda mais; o ATESTADO segue editavel (glosa).
"""
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
    # Estados do espelho (spec 2026-09-21 §2). espelho_gerado -> espelho_enviado e' do SISTEMA
    # (marcar_espelho_enviado, no ato do envio); -> protocolada e' registrar_protocolo.
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
# B-12 (10/10/2026): mensagem ao usuario com o tipo e o estado por extenso, nunca o codigo ("(execucao)")
ROTULO_TIPO = {"execucao": "execução", "reajuste": "reajuste", "projeto": "projeto"}
ROTULO_ESTADO = {"prevista": "prevista", "espelho_gerado": "com espelho gerado", "espelho_enviado": "com espelho enviado",
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
    d["protocolos"] = [dict(p) for p in conn.execute(
        "SELECT * FROM medicao_protocolos WHERE medicao_id=? ORDER BY id", (medicao_id,))]
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
            "AND a.acao = 'medicao.valor_protocolado'", lote).fetchall()
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
        col, nome = rotulo[r["acao"]]
        a_d, d_d = _json_dict(r["antes"]), _json_dict(r["depois"])
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
                     " AND COALESCE(valor_protocolado_origem, '') <> 'espelho'")
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
        sem_nota = exige_nota and atual in ("prevista", *ESTADOS_ESPELHO)
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
        if atual in ("prevista", *ESTADOS_ESPELHO, "nota_emitida"):
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


def criar_para_espelho(conn, usuario_id: int, contrato_id: int, numero: int, tipo: str,
                       competencia: str, valor_centavos: int) -> int:
    """A medicao nasce ao gerar o espelho (spec §2). Gerar de novo atualiza o valor enquanto a
    medicao nao foi protocolada; depois disso correcao e' fora do escopo (nao ha' glosa pos-protocolo)."""
    with db.mutacao(conn):
        ja = conn.execute("SELECT id, estado, valor_protocolado_centavos FROM medicoes "
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
        if ja["estado"] not in ESTADOS_ESPELHO:
            raise ValueError(f"{nome_medicao(numero, tipo)} já está {rotulo_estado(ja['estado'])}: o espelho não pode ser "
                             "gerado de novo depois de protocolada")
        cur = conn.execute("UPDATE medicoes SET valor_protocolado_centavos=?, valor_protocolado_origem='espelho', "
                           "competencia=? WHERE id=? AND estado IN ('espelho_gerado','espelho_enviado')",
                           (valor_centavos, competencia, ja["id"]))
        db.exigir_uma_linha(cur, "Estado da medição mudou concorrentemente; tente novamente")
        auditoria.registrar(conn, usuario_id, "medicao.valor_protocolado", "medicao", ja["id"],
                            {"valor_protocolado_centavos": ja["valor_protocolado_centavos"]},
                            {"valor_protocolado_centavos": valor_centavos, "valor_protocolado_origem": "espelho"})
        return ja["id"]


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


PROXIMO_PASSO = {"espelho_gerado": "enviar ao faturamento", "espelho_enviado": "anexar as notas",
                 "nota_emitida": "protocolar", "protocolada": "aguardando pagamento",
                 "nf_emitida": "aguardando pagamento"}


def em_andamento(conn, contrato_id: int | None = None, estado: str | None = None) -> list[dict]:
    """Medicoes entre o espelho e o pagamento, com o proximo passo e a data do ultimo marco."""
    sql = ("SELECT m.*, c.nome_curto, c.numero_instrumento, "
           "(SELECT MAX(p.data) FROM medicao_protocolos p WHERE p.medicao_id=m.id) AS protocolado_em "
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
        marcos = [d.isoformat() for d in map(_dia, (r["espelho_em"], r["nota_emitida_em"], r["protocolado_em"])) if d]
        criado = _dia(r["criado_em"])
        out.append({"id": r["id"], "contrato_id": r["contrato_id"],
                    "obra": r["nome_curto"] or r["numero_instrumento"], "numero": r["numero"], "tipo": r["tipo"],
                    "titulo": titulo(r), "competencia": r["competencia"], "estado": r["estado"],
                    "valor_centavos": r["valor_protocolado_centavos"], "proximo_passo": PROXIMO_PASSO[r["estado"]],
                    "desde": max(marcos) if marcos else (criado.isoformat() if criado else ""),
                    # os marcos crus, para quem precisa do marco da SITUACAO e nao do mais recente (resumo abaixo)
                    "espelho_em": r["espelho_em"], "nota_emitida_em": r["nota_emitida_em"],
                    "protocolado_em": r["protocolado_em"]})
    return out


# --- pagina Medicoes com abas (09/10/2026, prototipo aprovado pelo Leo) ---------------------------------
# Estado -> situacao, que e' a aba da pagina. As chaves sao as do PROXIMO_PASSO: "em andamento" continua sendo um
# lugar so' (o teste confere). `nf_emitida` e' o legado do bloco 3 (o remapeamento leva a zero) e espera o orgao
# como a protocolada. `prevista` (criada pelo cronograma, sem espelho) fica de fora DE PROPOSITO: a obra com so'
# uma prevista esta' "sem medicao aberta" (decisao do Leo).
SITUACAO = {"espelho_gerado": "faturamento", "espelho_enviado": "aguardando-nota", "nota_emitida": "enviar-nota",
            "protocolada": "aguardando-pagamento", "nf_emitida": "aguardando-pagamento"}
ORDEM_SITUACAO = ("faturamento", "aguardando-nota", "enviar-nota", "aguardando-pagamento")

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

    def marco(m: dict) -> datetime.date | None:
        if m["estado"] == "espelho_gerado":
            return _dia(espelho_de.get(m["id"])) or _dia(m["espelho_em"])
        if m["estado"] == "espelho_enviado":
            return _dia(envio_de.get(m["id"]))
        if m["estado"] == "nota_emitida":
            return _dia(m["nota_emitida_em"])
        return _dia(m["protocolado_em"])

    grupos: dict[tuple, list[dict]] = {}
    for m in em_andamento(conn):
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
    prevista_de: dict[int, int] = {}
    for r in conn.execute("SELECT contrato_id, id FROM medicoes WHERE estado='prevista' "
                          "ORDER BY competencia, numero, id"):
        prevista_de.setdefault(r["contrato_id"], r["id"])
    ativas = sorted((o for o in obras.values() if o["estado"] == "ativo"), key=lambda o: _chave_nome(o["obra"]))
    lista_obras = [{"contrato_id": o["id"], "obra": o["obra"], "contratante": o["contratante"],
                    "orgao_sub": o["orgao_sub"], "aberta": o["id"] in abertas, "prevista_id": prevista_de.get(o["id"]),
                    # A-21 (10/10/2026): a obra em encerramento segue na lista (mede a final), mas a tela nao a
                    # conta como "obra ativa" (a definicao de `avisos.ativos`, a do Inicio)
                    "encerramento": bool(o["encerramento_iniciado_em"])}
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
