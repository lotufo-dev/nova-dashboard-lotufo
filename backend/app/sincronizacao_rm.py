"""Sincronizacao RM -> dashboard (fase 5): NFs, baixas, casamento e recebimentos.

Uma rodada (`sincronizar`) faz, nesta ordem:

1. Busca as duas consultas (rede) ANTES de abrir a transacao -- o lock de escrita do
   SQLite nunca espera o RM.
2. UPSERT idempotente de NFs (`notas_fiscais`) e baixas (`baixas`) pela chave externa
   estavel (coligada + IDMOV / IDLAN). Rodar duas vezes nao muda nada.
3. NF que ficou cancelada no RM tem a alocacao DESFEITA (marcada, auditada); a medicao
   nao volta de estado sozinha -- aparece na reconciliacao para um humano decidir.
   Bloco 3: NF que ja' entrou pelo PDF (mesma coligada e numero, emissao ou valor iguais)
   nao vira linha nova -- a linha do PDF e' preenchida e CONFIRMADA (ou marcada divergente).
   Issue #71: o admin desfaz a' mao um vinculo errado (`desalocar`, com motivo); essa NF nao casa mais sozinha.
4. Casamento NF -> medicao (spec §4 e §7.1), do mais forte para o mais fraco, so' entre
   medicoes em andamento que ainda faltam nota e NAO sao legado (nascidas do espelho ou de
   competencia >= COMPETENCIA_CORTE_RM):
   a. `CAMPOLIVRE1` no formato instituido "<instrumento> - <nº>[ <tipo>]": chave forte,
      auto-aplica (origem `detectado`, confianca 1.0).
   b. valor EXATO de uma saida esperada do espelho vigente, unica entre as candidatas (na obra
      do centro de custo, ou na carteira inteira quando o centro nao mapeia: NF da Lotufo ao
      orgao em obra de consorcio) -> auto-aplica `saida_espelho` (0.95).
   O CODCCUSTO da NF estreita as candidatas a' obra certa (o contrato com aquele centro,
   quando ha' exatamente um na coligada). COM esse alvo:
   c. valor exato unico dentro da obra -> auto-aplica `centro_custo_valor` (0.9).
   d. par de NFs do mesmo centro e dia que soma o valor de UMA medicao (padrao MT-388:
      cada medicao sai em duas notas) -> auto-aplica as DUAS, `centro_custo_soma_dia` (0.9).
   e. candidatos proximos (ate' 5%) DENTRO da obra -> sem alocacao, so' log (bloco 9: a fila de sugestoes saiu;
      quem resolve e' o botao "vincular nota" da medicao).
   SEM alvo: se a coligada cadastra centros (Lotufo) e o desta NF nao mapeia, silencio --
   nao casar por valor na coligada inteira (seria coincidencia com outra obra). Coligada
   sem centro cadastrado (consorcio, ja' isolada 1:1) mantem o antigo: exato unico -> 0.8
   `valor_exato`; proximos ate' 5% -> log, sem alocacao. Sem candidato -> so' reconciliacao.
   Alocar nao muda o estado de `protocolada`; em medicao nascida do espelho fecha `nota_emitida`
   quando nao falta nota.
5. Recebimentos: medicao `protocolada` cujas NFs alocadas DA COLIGADA DA ENTIDADE DO CONTRATO
   ja' tem baixa (status 1, 3 ou 4) cobrindo o titulo vira `recebida`, com a maior data de
   baixa. Issue #35: titulo pago ate' R$ 1,00 a menos tambem fecha, com a diferenca auditada em
   `medicao.recebida_com_diferenca`. Parcial fica visivel no detalhe da medicao (recebido por NF), sem mudar de estado.

Toda decisao (alocar, desfazer, mudar estado) e' auditada com usuario NULL = sistema.
As linhas de NF/baixa nao entram na cadeia (espelho de outro sistema, ver migracao 012).
"""
import itertools
import json
import logging
import re
import sqlite3
import threading
import time

from app import auditoria, db, medicoes, rm, tempo

log = logging.getLogger("app.rm")

# Baixas que contam como recebido (RM: 1 baixado, 3 por acordo, 4 parcial). 0 aberto e
# 2 cancelado ficam fora.
STATUS_RECEBIDO = (1, 3, 4)
# Tolerancia para propor candidato (nao para auto-aplicar): 5% do valor da NF.
TOLERANCIA_CANDIDATO = 0.05
INTERVALO_SEG = 3600
# Uma rodada `running` mais nova que isto bloqueia outra (thread agendada x disparo
# manual x segundo processo). Mais velha que isto e' rodada morta (crash) e e' expirada.
PRAZO_RODADA_SEG = 30 * 60

# Ultima rodada, para o health e para o carimbo de frescor das telas.
ESTADO: dict = {"configurado": False, "ultima_sincronizacao": None, "ultimo_erro": None,
                "em_andamento": False}

# "IC 082/2025 - 12", "CT-271-LT-2026 - 12ª", "IC 082/2025 - 3 REAJ", "IC 082/2025 / 3 PROJ".
# O instrumento e' tudo antes do separador " - " (ou " / "); o numero vem depois; o
# sufixo opcional diz a serie (execucao e' o padrao).
_CAMPO_LIVRE = re.compile(
    r"^\s*(?P<instrumento>.+?)\s+[-–/]\s+(?:med(?:i[cç][aã]o)?\.?\s*)?(?P<numero>\d{1,3})\s*[ªa°º]?"
    r"(?:\s+(?P<tipo>reaj\w*|proj\w*|exec\w*))?\s*$", re.IGNORECASE)
_TIPO_POR_PREFIXO = {"reaj": "reajuste", "proj": "projeto", "exec": "execucao"}


def _normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", (texto or "").strip()).upper()


def interpretar_campo_livre(texto) -> tuple[str, int, str] | None:
    """'IC 082/2025 - 12 REAJ' -> ('IC 082/2025', 12, 'reajuste'); fora do formato -> None."""
    if not texto:
        return None
    m = _CAMPO_LIVRE.match(str(texto))
    if not m:
        return None
    tipo = "execucao"
    if m.group("tipo"):
        tipo = _TIPO_POR_PREFIXO[m.group("tipo")[:4].lower()]
    return _normalizar(m.group("instrumento")), int(m.group("numero")), tipo


# ------------------------------------------------------------------ upserts

def _numero_int(numero) -> int | None:
    """'000002260' -> 2260; texto com letra ou vazio -> None (nunca casa por numero)."""
    s = str(numero or "").strip()
    return int(s) if s.isdigit() else None


def _confirmar_nota_do_pdf(conn, coligada: int, idmov: int, numero_int, emissao, valor: int, linha: dict,
                           situacao: str) -> int | None:
    """A nota ja' entrou pelo PDF (idmov NULL, mesma coligada e numero, emissao OU valor iguais): preenche com
    o RM e confirma (bloco 3, decisao 1). Devolve o id, ou None quando nao ha' linha do PDF para esta NF.
    A emissao lida do PDF (data do portal) nao e' sobrescrita: nos pares reais e' a mesma do RM."""
    if numero_int is None:
        return None
    cands = conn.execute("""SELECT id, valor_pdf_centavos FROM notas_fiscais WHERE coligada=? AND idmov IS NULL
                            AND numero_int=? AND (emissao=? OR valor_centavos=?)""",
                         (coligada, numero_int, emissao, valor)).fetchall()
    if len(cands) != 1:
        return None
    r = cands[0]
    conf = "confirmada" if r["valor_pdf_centavos"] == valor else "divergente"
    conn.execute("""UPDATE notas_fiscais SET idmov=?, numero=?, serie=?, emissao=COALESCE(emissao, ?), valor_centavos=?,
                    codtmv=?, status_rm=?, campo_livre1=?, centro_custo=?, tomador=?, situacao=?,
                    confirmacao=?, confirmada_em=datetime('now'), ultimo_visto_em=datetime('now') WHERE id=?""",
                 (idmov, str(linha.get("NUMEROMOV") or ""), linha.get("SERIE"), emissao, valor, linha.get("CODTMV"),
                  linha.get("STATUS"), linha.get("CAMPOLIVRE1"), linha.get("CODCCUSTO"), linha.get("TOMADOR"),
                  situacao, conf, r["id"]))
    auditoria.registrar(conn, None, "nota.confirmacao", "nota_fiscal", r["id"], None,
                        {"origem": "RM depois do PDF", "idmov": idmov, "confirmacao": conf, "valor_rm": valor,
                         "valor_pdf": r["valor_pdf_centavos"]})
    return r["id"]


def _upsert_nf(conn, linha: dict) -> int:
    coligada, idmov = int(linha["CODCOLIGADA"]), int(linha["IDMOV"])
    situacao = "cancelada" if str(linha.get("STATUS", "")).upper() == "C" else "ativa"
    numero = str(linha.get("NUMEROMOV") or "")
    if conn.execute("SELECT 1 FROM notas_fiscais WHERE coligada=? AND idmov=?", (coligada, idmov)).fetchone() is None:
        nid = _confirmar_nota_do_pdf(conn, coligada, idmov, _numero_int(numero), rm.data(linha.get("DATAEMISSAO")),
                                     rm.centavos(linha.get("VALORBRUTO")), linha, situacao)
        if nid is not None:
            return nid
    conn.execute("""
        INSERT INTO notas_fiscais (coligada, idmov, numero, numero_int, serie, emissao, valor_centavos, codtmv,
                                   status_rm, campo_livre1, centro_custo, tomador, situacao)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (coligada, idmov) WHERE idmov IS NOT NULL DO UPDATE SET
            numero=excluded.numero, numero_int=excluded.numero_int, serie=excluded.serie, emissao=excluded.emissao,
            valor_centavos=excluded.valor_centavos, codtmv=excluded.codtmv,
            status_rm=excluded.status_rm, campo_livre1=excluded.campo_livre1,
            centro_custo=excluded.centro_custo, tomador=excluded.tomador, situacao=excluded.situacao,
            confirmacao=CASE WHEN notas_fiscais.valor_pdf_centavos IS NULL THEN notas_fiscais.confirmacao
                             WHEN notas_fiscais.valor_pdf_centavos=excluded.valor_centavos THEN 'confirmada'
                             ELSE 'divergente' END,
            ultimo_visto_em=datetime('now')""",
        (coligada, idmov, numero, _numero_int(numero), linha.get("SERIE"),
         rm.data(linha.get("DATAEMISSAO")), rm.centavos(linha.get("VALORBRUTO")),
         linha.get("CODTMV"), linha.get("STATUS"), linha.get("CAMPOLIVRE1"),
         linha.get("CODCCUSTO"), linha.get("TOMADOR"), situacao))
    return conn.execute("SELECT id FROM notas_fiscais WHERE coligada=? AND idmov=?",
                        (coligada, idmov)).fetchone()[0]


def _upsert_baixa(conn, linha: dict) -> None:
    coligada, idlan = int(linha["CODCOLIGADA"]), int(linha["IDLAN"])
    idmov = linha.get("IDMOV")
    nota_id = None
    if idmov is not None:
        r = conn.execute("SELECT id FROM notas_fiscais WHERE coligada=? AND idmov=?",
                         (coligada, int(idmov))).fetchone()
        nota_id = r["id"] if r else None
    bruta = linha.get("DATABAIXA")
    conn.execute("""
        INSERT INTO baixas (coligada, idlan, nota_id, idmov, numero_documento, valor_original_centavos,
                            valor_baixado_centavos, status_lan, data_baixa, data_baixa_bruta)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (coligada, idlan) DO UPDATE SET
            nota_id=excluded.nota_id, idmov=excluded.idmov, numero_documento=excluded.numero_documento,
            valor_original_centavos=excluded.valor_original_centavos,
            valor_baixado_centavos=excluded.valor_baixado_centavos, status_lan=excluded.status_lan,
            data_baixa=excluded.data_baixa, data_baixa_bruta=excluded.data_baixa_bruta,
            ultimo_visto_em=datetime('now')""",
        (coligada, idlan, nota_id, idmov, linha.get("NUMERODOCUMENTO"),
         rm.centavos(linha.get("VALORORIGINAL")), rm.centavos(linha.get("VALORBAIXADO")),
         int(linha.get("STATUSLAN") or 0), rm.data(bruta), str(bruta) if bruta is not None else None))


# --------------------------------------------------------------- alocacoes

def alocar(conn, usuario_id, nota_id: int, medicao_id: int, origem: str, confianca: float | None,
           regra: str) -> int:
    """Liga a NF a' medicao. Bloco 3: nao move mais `protocolada -> nf_emitida`; em medicao nascida
    do espelho fecha `nota_emitida` quando nao falta nota (notas.fechar_se_completa).

    Reentrante em db.mutacao. Recusa NF cancelada, medicao encerrada e alocacao repetida.
    """
    from app import notas   # import local: notas importa este modulo
    with db.mutacao(conn):
        nf = conn.execute("SELECT * FROM notas_fiscais WHERE id=?", (nota_id,)).fetchone()
        if nf is None:
            raise ValueError("Nota fiscal não encontrada")
        if nf["situacao"] != "ativa":
            raise ValueError(f"Nota fiscal {nf['numero']} está {nf['situacao']} no RM")
        m = medicoes.detalhe(conn, medicao_id)
        if m is None:
            raise ValueError("Medição não encontrada")
        if m["estado"] in ("cancelada", "desistida", "recebida"):
            raise ValueError(f"Medição em estado {m['estado']} não recebe NF")
        if conn.execute("SELECT 1 FROM nf_alocacoes WHERE nota_id=? AND desfeita_em IS NULL",
                        (nota_id,)).fetchone():
            raise ValueError(f"Nota fiscal {nf['numero']} já está alocada a uma medição")
        cur = conn.execute(
            "INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, confianca, regra) "
            "VALUES (?,?,?,?,?,?)", (medicao_id, nota_id, nf["valor_centavos"], origem, confianca, regra))
        auditoria.registrar(conn, usuario_id, "nf.alocar", "medicao", medicao_id, None,
                            {"nota_id": nota_id, "nf": f"{nf['numero']}/{nf['serie'] or ''}",
                             "coligada": nf["coligada"], "valor_centavos": nf["valor_centavos"],
                             "origem": origem, "confianca": confianca, "regra": regra})
        notas.fechar_se_completa(conn, usuario_id, medicao_id)
        return cur.lastrowid


def _desfazer_alocacoes_de_nf_cancelada(conn, nota_id: int, numero: str) -> int:
    n = 0
    for a in conn.execute("SELECT * FROM nf_alocacoes WHERE nota_id=? AND desfeita_em IS NULL", (nota_id,)):
        conn.execute("UPDATE nf_alocacoes SET desfeita_em=datetime('now'), motivo_desfazer=? WHERE id=?",
                     ("NF cancelada no RM", a["id"]))
        auditoria.registrar(conn, None, "nf.desalocar", "medicao", a["medicao_id"],
                            {"nota_id": nota_id}, {"motivo": "NF cancelada no RM", "nf": numero})
        n += 1
    return n


# Prefixo do motivo de quem desfez o vinculo a' mao: o casador nao volta a casar sozinho essa NF.
MOTIVO_A_MAO = "Desfeita à mão: "
# NF com vinculo desfeito a' mao (usar com o id da nota em `{nota}` e o parametro MOTIVO_A_MAO + "%"): o mesmo
# filtro no casamento direto e na irma da soma do dia.
_SQL_DESFEITA_A_MAO = ("EXISTS (SELECT 1 FROM nf_alocacoes d WHERE d.nota_id={nota} AND d.desfeita_em IS NOT NULL "
                       "AND d.motivo_desfazer LIKE ?)")


def desalocar(conn, usuario_id, medicao_id: int, alocacao_id: int, motivo: str) -> None:
    """Issue #71: o admin desfaz um vinculo NF <-> medicao errado, com motivo. Marca (nunca apaga), audita com
    quem fez, e a medicao nao volta de estado sozinha (como na NF cancelada: a reconciliacao a mostra). A NF
    desvinculada a' mao sai do casamento automatico; volta a uma medicao so' pelo PDF anexado nela."""
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValueError("Informe o motivo para desfazer o vínculo da nota")
    with db.mutacao(conn):
        a = conn.execute("""SELECT a.*, n.numero, n.serie, n.coligada, n.documento_id, m.estado FROM nf_alocacoes a
                            JOIN notas_fiscais n ON n.id=a.nota_id JOIN medicoes m ON m.id=a.medicao_id
                            WHERE a.id=? AND a.medicao_id=?""", (alocacao_id, medicao_id)).fetchone()
        if a is None:
            raise ValueError("Vínculo da nota com esta medição não encontrado")
        if a["desfeita_em"] is not None:
            raise ValueError(f"O vínculo da nota {a['numero']} já foi desfeito")
        # Como em `alocar`: medicao encerrada nao recebe NF, entao tirar a nota dela nao teria volta.
        if a["estado"] in ("cancelada", "desistida", "recebida"):
            raise ValueError(f"Medição em estado {a['estado']} não tem o vínculo da nota desfeito")
        # O PDF anexado nesta medicao seguiria no envio ao orgao e na FRC: desfazer o vinculo nao o tira dali.
        if a["documento_id"] is not None and conn.execute(
                "SELECT 1 FROM medicao_documentos WHERE id=? AND medicao_id=?", (a["documento_id"], medicao_id)).fetchone():
            raise ValueError(f"A nota {a['numero']} veio do PDF anexado nesta medição; desfazer o vínculo "
                             "não tira o PDF do envio ao órgão")
        from app import notas    # import local: notas importa este modulo
        faltavam = notas.faltam(conn, medicao_id)
        texto = MOTIVO_A_MAO + motivo
        if conn.execute("UPDATE nf_alocacoes SET desfeita_em=datetime('now'), motivo_desfazer=? "
                        "WHERE id=? AND desfeita_em IS NULL", (texto, alocacao_id)).rowcount != 1:
            raise ValueError(f"O vínculo da nota {a['numero']} já foi desfeito")
        # Revisor R1/R4 (PR #202): em `nota_emitida` a medicao ja' passou da espera da nota; tirar a nota que atendia
        # uma saida (a falta aumenta) ou a ultima nota a faria protocolar sem a ressalva "nota nao emitida" (A-09).
        # A nota a mais, que nao atende saida nenhuma (medicao declarada completa), sai normalmente.
        if a["estado"] == "nota_emitida":
            if (notas.faltam(conn, medicao_id) > faltavam
                    or not conn.execute("SELECT 1 FROM nf_alocacoes WHERE medicao_id=? AND desfeita_em IS NULL",
                                        (medicao_id,)).fetchone()):
                raise ValueError(f"Medição com nota emitida ficaria faltando nota: anexe antes a nota certa e depois "
                                 f"desfaça o vínculo da nota {a['numero']}")
        auditoria.registrar(conn, usuario_id, "nf.desalocar", "medicao", medicao_id,
                            {"alocacao_id": alocacao_id, "nota_id": a["nota_id"], "nf": f"{a['numero']}/{a['serie'] or ''}",
                             "coligada": a["coligada"], "valor_centavos": a["valor_alocado_centavos"],
                             "origem": a["origem"], "regra": a["regra"], "estado_medicao": a["estado"]},
                            {"motivo": texto})


def notas_da_medicao(conn, medicao_id: int) -> list[dict]:
    """NFs alocadas (vigentes) com o recebido de cada uma -- para o detalhe da medicao."""
    out = []
    for r in conn.execute("""
            SELECT a.id AS alocacao_id, a.valor_alocado_centavos, a.origem, a.confianca, a.regra,
                   n.id AS nota_id, n.coligada, n.idmov, n.numero, n.serie, n.emissao, n.valor_centavos, n.situacao,
                   n.origem AS origem_nota, n.confirmacao, n.documento_id, n.valor_pdf_centavos, n.conferencia,
                   n.justificativa, n.leitura, n.municipio
            FROM nf_alocacoes a JOIN notas_fiscais n ON n.id=a.nota_id
            WHERE a.medicao_id=? AND a.desfeita_em IS NULL ORDER BY n.emissao, n.id""", (medicao_id,)):
        d = dict(r)
        d["conferencia"] = json.loads(d["conferencia"] or "[]")
        d["recebido_centavos"], d["devido_centavos"], d["recebido_em"] = _recebido_da_nota(conn, r["nota_id"])
        out.append(d)
    return out


def _recebido_da_nota(conn, nota_id: int) -> tuple[int, int, str | None]:
    """(recebido, devido, ultima_data) para uma NF.

    `devido` e' o valor dos TITULOS no RM (`valor_original` dos lancamentos a receber), que
    nascem no LIQUIDO -- bruto da NF menos as retencoes (ISS/INSS/IRRF) que nunca passam
    pelo titulo. Comparar o recebido com o bruto da NF nunca fecha (o recebido e' ~92%);
    o certo e' comparar com os titulos. Cada linha de `baixas` e' UM titulo (chave unica
    coligada+idlan), entao `devido` SOMA o `valor_original` de todos os titulos da nota
    (uma NF partida em dois lancamentos so' esta' recebida quando os dois entram); titulo
    cancelado (status 2) nao conta como devido nem como recebido."""
    recebido, devido, ultima = 0, 0, None
    for b in conn.execute("SELECT valor_original_centavos, valor_baixado_centavos, data_baixa, status_lan "
                          "FROM baixas WHERE nota_id=?", (nota_id,)):
        if b["status_lan"] == 2:               # cancelado: fora
            continue
        devido += b["valor_original_centavos"] or 0
        if b["status_lan"] in STATUS_RECEBIDO:
            recebido += b["valor_baixado_centavos"]
            if b["data_baixa"] and (ultima is None or b["data_baixa"] > ultima):
                ultima = b["data_baixa"]
    return recebido, devido, ultima


# --------------------------------------------------------------- casamento

# Medicao candidata ao casamento: nasceu do espelho, OU e' de competencia posterior a' carga do legado.
# As 422 medicoes que o remapeamento devolve a `protocolada` sem NF ficam FORA: 24 meses de NFs contra
# elas seria o cenario das 29 sugestoes de 2026-09-04 (backlog), com 422 alvos.
COMPETENCIA_CORTE_RM = "2026-07"
ESTADOS_CANDIDATOS = ("espelho_gerado", "espelho_enviado", "nota_emitida", "protocolada")


def _candidatas(conn, coligada: int, cache: dict | None = None) -> list[dict]:
    """Medicoes em andamento que ainda FALTAM nota: (a) dos contratos da entidade desta coligada; (b) para a
    coligada da Lotufo, tambem as de contratos de CONSORCIO cujo espelho espera nota da Lotufo (a NFS-e da
    Lotufo ao orgao fica na coligada 1, centro 5.001.x, e o contrato e' do consorcio). Cada uma traz
    `esperadas` (valores das saidas do espelho sem nota; vazio sem espelho). Calculado uma vez por coligada
    por rodada (`cache`, limpo a cada alocacao)."""
    if cache is not None and coligada in cache:
        return cache[coligada]
    from app import notas
    marcas = ",".join("?" * len(ESTADOS_CANDIDATOS))
    linhas = conn.execute(f"""
        SELECT m.*, c.numero_instrumento, c.orgao, e.coligada_rm AS coligada_contrato,
               COALESCE(m.valor_atestado_centavos, m.valor_protocolado_centavos) AS valor
        FROM medicoes m JOIN contratos c ON c.id=m.contrato_id
        JOIN entidades e ON e.id=COALESCE(c.entidade_id, 1)
        WHERE m.estado IN ({marcas})
          AND (m.valor_protocolado_origem='espelho' OR m.competencia >= ?)
          AND (e.coligada_rm=? OR EXISTS (SELECT 1 FROM espelho_medicoes em WHERE em.medicao_id=m.id))
        ORDER BY c.numero_instrumento, m.tipo, m.numero""", (*ESTADOS_CANDIDATOS, COMPETENCIA_CORTE_RM, coligada)).fetchall()
    out = []
    for r in linhas:
        d = dict(r)
        esp = notas.esperadas(conn, r["id"])
        d["esperadas"] = [e["valor"] for e in esp if e["nota_id"] is None]
        if esp and notas.coligada_esperada(conn, r["id"]) == coligada:
            # lado da Lotufo: entra enquanto alguma saida esperada estiver sem nota
            if not d["esperadas"]:
                continue
        elif d["coligada_contrato"] == coligada:
            # lado da entidade do contrato (consorcio: a fatura, valor cheio; obra propria sem espelho: a NF):
            # entra enquanto nao tiver nota desta coligada
            d["esperadas"] = []
            if conn.execute("""SELECT 1 FROM nf_alocacoes a JOIN notas_fiscais n ON n.id=a.nota_id
                               WHERE a.medicao_id=? AND a.desfeita_em IS NULL AND n.coligada=?""",
                            (r["id"], coligada)).fetchone():
                continue
        else:
            continue
        out.append(d)
    if cache is not None:
        cache[coligada] = out
    return out


def _contrato_por_centro_custo(conn, coligada: int, centro_custo) -> int | None:
    """Contrato apontado pelo centro de custo da NF, so' quando ha' EXATAMENTE UM dentro
    da coligada.

    E' a chave que desambigua a Lotufo (uma entidade, muitos contratos): o CODCCUSTO da
    NF diz de qual obra ela e'. Centro nao cadastrado, ou repetido entre contratos, nao
    estreita -- devolve None e o casamento cai no comportamento por coligada (que ja'
    basta para consorcio, onde a coligada isola a obra). O codigo do RM e' comparado
    aparado nas duas pontas; espaco a mais no cadastro nao deveria furar a chave."""
    cc = (centro_custo or "").strip()
    if not cc:
        return None
    achados = [r["id"] for r in conn.execute("""
        SELECT c.id FROM contratos c
        JOIN entidades e ON e.id=COALESCE(c.entidade_id, 1)
        WHERE e.coligada_rm=? AND c.centro_custo_rm IS NOT NULL AND TRIM(c.centro_custo_rm)=?""",
        (coligada, cc))]
    return achados[0] if len(achados) == 1 else None


def _por_campo_livre(conn, nf) -> int | None:
    """Medicao apontada pelo CAMPOLIVRE1, so' entre contratos da entidade DESTA coligada
    e so' quando ha' exatamente uma (instrumento repetido entre entidades nao casa
    sozinho -- gate Sol da fase 5)."""
    chave = interpretar_campo_livre(nf["campo_livre1"])
    if chave is None:
        return None
    instrumento, numero, tipo = chave
    achadas = [r["id"] for r in conn.execute("""
            SELECT m.id, c.numero_instrumento FROM medicoes m
            JOIN contratos c ON c.id=m.contrato_id
            JOIN entidades e ON e.id=COALESCE(c.entidade_id, 1)
            WHERE e.coligada_rm=? AND m.numero=? AND m.tipo=?
              AND m.estado IN ('espelho_gerado','espelho_enviado','nota_emitida','protocolada','nf_emitida')
            ORDER BY m.id""", (nf["coligada"], numero, tipo))
               if _normalizar(r["numero_instrumento"]) == instrumento]
    return achadas[0] if len(achadas) == 1 else None


def _coligadas_com_centro(conn) -> set:
    """Coligadas cuja entidade tem ao menos UM contrato com centro de custo cadastrado.

    Calculado uma vez por rodada. E' o gatilho do modo estrito: nessas coligadas (a
    Lotufo, hoje) uma NF cujo centro NAO mapeia para contrato nao cai no casamento por
    valor da coligada inteira -- ficaria a merce de coincidencia de valor com medicao de
    outra obra. Consorcio nao tem centro cadastrado (a coligada ja' isola a obra), entao
    fica de fora e mantem o comportamento antigo."""
    return {r[0] for r in conn.execute("""
        SELECT DISTINCT e.coligada_rm FROM contratos c
        JOIN entidades e ON e.id=COALESCE(c.entidade_id, 1)
        WHERE c.centro_custo_rm IS NOT NULL AND TRIM(c.centro_custo_rm) <> ''
          AND e.coligada_rm IS NOT NULL""")}


def _casar_soma_dia(conn, nf, candidatas) -> tuple[int, int] | None:
    """PAR de NFs do mesmo centro e dia que soma o valor de UMA medicao candidata.

    Devolve (medicao_id, id_da_irma) so' quando o casamento e' inequivoco INDEPENDENTE da
    ordem de processamento; qualquer ambiguidade devolve None (fica sem alocacao). E' o
    padrao da MT-388: cada medicao sai em duas notas do mesmo dia, entao o valor cheio da
    medicao nunca aparece numa nota so'. Cap de 2 de proposito -- nos dados reais (24
    meses) todo casamento por soma e' par; trio, se surgir, vira decisao humana.

    Duas travas contra dependencia de ordem (gate Sol 2026-09-09):
    - UNICIDADE GLOBAL: no centro/dia inteiro, exatamente UM par fecha aquela medicao (nao
      basta ser unico entre os pares que contem esta NF: dois pares disjuntos podem fechar
      a mesma medicao, e ai' quem ganha dependeria de quem foi processado primeiro).
    - ELEGIBILIDADE: uma irma so' entra num par se NAO tiver destino proprio mais forte
      (campo livre valido, ou valor que casa exato com uma medicao candidata) -- senao o
      par a roubaria de um casamento individual que valeria mais."""
    if not nf["emissao"]:
        return None
    grupo = conn.execute("""
        SELECT id, valor_centavos, campo_livre1 FROM notas_fiscais
        WHERE coligada=? AND centro_custo IS NOT NULL AND TRIM(centro_custo)=TRIM(?)
          AND emissao=? AND situacao='ativa'
          AND NOT EXISTS (SELECT 1 FROM nf_alocacoes a WHERE a.nota_id=notas_fiscais.id AND a.desfeita_em IS NULL)
          AND NOT """ + _SQL_DESFEITA_A_MAO.format(nota="notas_fiscais.id"),
        (nf["coligada"], nf["centro_custo"] or "", nf["emissao"], MOTIVO_A_MAO + "%")).fetchall()
    # valor -> medicoes candidatas com aquele valor (a obra ja' esta' estreitada em cands)
    med_por_valor: dict = {}
    for m in candidatas:
        if m["valor"] is not None:
            med_por_valor.setdefault(m["valor"], set()).add(m["id"])

    def elegivel(r) -> bool:
        return (interpretar_campo_livre(r["campo_livre1"]) is None
                and r["valor_centavos"] not in med_por_valor)

    if not elegivel(nf):
        return None
    eleg = [r for r in grupo if elegivel(r)]
    pares_por_med: dict = {}   # medicao_id -> lista de frozenset({id_a, id_b})
    for a, b in itertools.combinations(eleg, 2):
        meds = med_por_valor.get(a["valor_centavos"] + b["valor_centavos"])
        if meds and len(meds) == 1:
            pares_por_med.setdefault(next(iter(meds)), []).append(frozenset((a["id"], b["id"])))
    achados = [(mid, next(iter(pares[0] - {nf["id"]})))
               for mid, pares in pares_por_med.items()
               if len(pares) == 1 and nf["id"] in pares[0]]
    return achados[0] if len(achados) == 1 else None


def _casar(conn, nota_id: int, coligadas_com_centro: set, cache: dict | None = None) -> str | None:
    """Tenta alocar a NF; devolve 'alocada', 'ambigua' ou None. `cache` = candidatas por coligada da
    rodada (limpo aqui a cada alocacao, porque a medicao alocada pode deixar de faltar nota)."""
    cache = {} if cache is None else cache
    nf = conn.execute("SELECT * FROM notas_fiscais WHERE id=?", (nota_id,)).fetchone()
    if nf["situacao"] != "ativa":
        return None
    if conn.execute("SELECT 1 FROM nf_alocacoes WHERE nota_id=? AND desfeita_em IS NULL", (nota_id,)).fetchone():
        return None
    # Issue #71: vinculo desfeito a' mao e' decisao humana -- o casador nao a desfaz na rodada seguinte.
    if conn.execute("SELECT " + _SQL_DESFEITA_A_MAO.format(nota="?"), (nota_id, MOTIVO_A_MAO + "%")).fetchone()[0]:
        return None

    def _aloca(mid, confianca, regra, irma=None):
        alocar(conn, None, nota_id, mid, "detectado", confianca, regra)
        if irma is not None:
            alocar(conn, None, irma, mid, "detectado", confianca, regra)
        cache.pop(nf["coligada"], None)
        return "alocada"

    mid = _por_campo_livre(conn, nf)
    if mid is not None:
        return _aloca(mid, 1.0, "campo_livre1")
    candidatas = _candidatas(conn, nf["coligada"], cache)
    alvo = _contrato_por_centro_custo(conn, nf["coligada"], nf["centro_custo"])
    # Bloco 3: saida esperada do espelho com o valor EXATO da NF -- chave mais forte depois do campo
    # livre. Com centro mapeado, dentro da obra; sem centro (NF Lotufo -> orgao em obra de consorcio,
    # centro 5.001.x), na carteira inteira: o valor da cota e' praticamente unico.
    universo = [m for m in candidatas if m["contrato_id"] == alvo] if alvo is not None else candidatas
    por_saida = [m for m in universo if nf["valor_centavos"] in m["esperadas"]]
    if len(por_saida) == 1:
        return _aloca(por_saida[0]["id"], 0.95, "saida_espelho")
    # Centro de custo estreita as candidatas a' obra certa antes do valor desempatar.
    if alvo is not None:
        candidatas = [m for m in candidatas if m["contrato_id"] == alvo]
        exatas = [m for m in candidatas if m["valor"] == nf["valor_centavos"]]
        if len(exatas) == 1:
            # Centro + valor exato: a obra tambem bate; a auditoria registra a regra.
            return _aloca(exatas[0]["id"], 0.9, "centro_custo_valor")
        par = _casar_soma_dia(conn, nf, candidatas)
        if par is not None:
            medicao_id, irma_id = par
            # As DUAS notas do par sao alocadas AQUI (N:N, cada uma pelo seu valor). Deixar
            # a irma para o loop nao funciona: a medicao alocada deixa de faltar nota e nao
            # apareceria mais em _candidatas.
            return _aloca(medicao_id, 0.9, "centro_custo_soma_dia", irma=irma_id)
    elif nf["coligada"] in coligadas_com_centro:
        # Modo estrito: a coligada cadastra centros, mas o desta NF nao mapeia (imobilizado,
        # NF de cota ao consorcio, obra fora do escopo). Nao casar por valor na coligada
        # inteira -- seria coincidencia com medicao de outra obra. Silencio, sem ruido.
        return None
    else:
        # Consorcio (sem centro cadastrado): comportamento antigo -- a coligada ja' isola.
        exatas = [m for m in candidatas if m["valor"] == nf["valor_centavos"]]
        if len(exatas) == 1:
            return _aloca(exatas[0]["id"], 0.8, "valor_exato")
    tol = nf["valor_centavos"] * TOLERANCIA_CANDIDATO
    proximas = [m for m in candidatas if m["valor"] is not None and abs(m["valor"] - nf["valor_centavos"]) <= tol]
    if not proximas:
        return None
    # Bloco 9 (decisao 3): NF com mais de uma medicao candidata nao vira mais sugestao. Fica sem alocacao e
    # registrada em log; o PDF da nota anexado na medicao casa pelo numero, e o aviso "nota ausente do RM"
    # cobre a medicao que ficou sem nota. (O "Vincular nota do RM" manual saiu em 2026-09-25.)
    log.info("NF %s/%s da coligada %s (R$ %.2f) com %d medicoes candidatas: sem alocacao automatica",
             nf["numero"], nf["serie"] or "", nf["coligada"], nf["valor_centavos"] / 100, len(proximas))
    return "ambigua"


# ------------------------------------------------------------ recebimentos

def _falta_por_titulo(conn, nota_id: int, aberto_inteiro: bool = False) -> int | None:
    """Issue #35: o que falta pagar na nota, titulo a titulo (max(0, original - baixado) dos titulos nao
    cancelados): pagamento a mais num titulo (juros) nao compensa a falta de outro. None quando algum titulo
    nao tem baixa nenhuma (aberto nao e' "pago com diferenca").
    Issue #253: com `aberto_inteiro`, o titulo sem baixa entra pelo valor original inteiro em vez de dar None
    (o a receber e o aviso da Saude querem quanto falta, nao se a nota fecha com diferenca)."""
    falta = 0
    for b in conn.execute("SELECT status_lan, valor_original_centavos, valor_baixado_centavos FROM baixas "
                          "WHERE nota_id=? AND status_lan<>2", (nota_id,)):
        baixado = (b["valor_baixado_centavos"] or 0) if b["status_lan"] in STATUS_RECEBIDO else 0
        if baixado <= 0 and not aberto_inteiro:
            return None
        falta += max(0, (b["valor_original_centavos"] or 0) - baixado)
    return falta


def _recebimentos(conn, medicao_ids: list[int] | None = None) -> int:
    """`medicao_ids`: so' essas (a carga do historico, issue #259, fecha as que acabou de criar sem mexer nas outras)."""
    from app import diretoria   # import local: diretoria importa este modulo
    tolerancia = diretoria.TOLERANCIA_CENTAVOS
    n = 0
    if medicao_ids == []:
        return 0                        # "IN ()" nem e' SQL valido
    filtro = f" AND m.id IN ({','.join('?' * len(medicao_ids))})" if medicao_ids is not None else ""
    for m in conn.execute("""SELECT m.id, e.coligada_rm,
                                    COALESCE(m.valor_atestado_centavos, m.valor_protocolado_centavos) AS valor
                             FROM medicoes m JOIN contratos c ON c.id=m.contrato_id
                             JOIN entidades e ON e.id=COALESCE(c.entidade_id, 1)
                             WHERE m.estado IN ('protocolada','nf_emitida')""" + filtro, medicao_ids or ()).fetchall():
        # Bloco 3 (decisao 13 do plano): so' as notas da COLIGADA DA ENTIDADE DO CONTRATO decidem o
        # recebimento. Em obra de consorcio a medicao tambem tem a NFS-e da Lotufo ao orgao
        # (coligada 1, cota, titulo que o consorcio repassa depois): ela nao segura a medicao.
        notas = [x for x in notas_da_medicao(conn, m["id"]) if x["coligada"] == m["coligada_rm"]]
        if not notas:
            continue
        # Gate Sol S1 (PR #202): vinculo desfeito a' mao pode ter levado parte do faturamento (medicao em duas
        # notas). Ai' so' fecha sozinha se as notas que ficaram cobrem o valor da medicao.
        if m["valor"] is None or sum(x["valor_alocado_centavos"] for x in notas) < m["valor"]:
            if conn.execute("SELECT 1 FROM nf_alocacoes WHERE medicao_id=? AND desfeita_em IS NOT NULL "
                            "AND motivo_desfazer LIKE ?", (m["id"], MOTIVO_A_MAO + "%")).fetchone():
                continue
        # Recebida quando os TITULOS de CADA NF alocada estao quitados (cada um pelo seu valor liquido; ver
        # issue #251 abaixo). Comparar com o bruto da NF nunca fechava por causa das retencoes. NF sem titulo
        # (devido=0: titulo ainda nao existe ou foi cancelado) segura a medicao -- nao da' para concluir
        # recebimento do que nao tem lancamento a receber.
        if not all(x["situacao"] == "ativa" and x["devido_centavos"] > 0 for x in notas):
            continue
        curtas = []
        # Issue #251: quitada e' falta ZERO titulo a titulo, nao o total da nota (recebido >= devido): juros
        # num titulo nao quitam outro titulo aberto da mesma nota. Falta zero ja' implica recebido >= devido.
        faltas = [(x, _falta_por_titulo(conn, x["nota_id"])) for x in notas]
        if not all(f == 0 for _, f in faltas):
            # Issue #35 (decisao do Leo, 19/10/2026): medicao paga ate' R$ 1,00 abaixo, SOMANDO a falta de
            # todas as notas dela, fecha como recebida; sem percentual. A falta e' contada titulo a titulo
            # (juros num titulo nao cobrem outro) e todo titulo precisa de baixa. A diferenca vai para a
            # auditoria como evento proprio.
            if any(f is None for _, f in faltas) or sum(f for _, f in faltas) > tolerancia:
                continue
            curtas = [{"nota_id": x["nota_id"], "numero": x["numero"], "devido_centavos": x["devido_centavos"],
                       "recebido_centavos": x["recebido_centavos"], "diferenca_centavos": f}
                      for x, f in faltas if f > 0]
        datas = [x["recebido_em"] for x in notas if x["recebido_em"]]
        with db.mutacao(conn):
            medicoes.mudar_estado(conn, None, m["id"], "recebida", None, max(datas) if datas else None)
            if curtas:
                auditoria.registrar(conn, None, "medicao.recebida_com_diferenca", "medicao", m["id"], None,
                                    {"diferenca_centavos": sum(c["diferenca_centavos"] for c in curtas),
                                     "tolerancia_centavos": tolerancia, "notas": curtas})
        n += 1
    return n


# ------------------------------------------------------------------ rodada

class RodadaEmAndamento(Exception):
    """Outra rodada segura a trava no banco (thread agendada, outro pedido, outro processo)."""


def sincronizar(conn: sqlite3.Connection, cliente, disparo: str = "manual") -> dict:
    # TRAVA NO BANCO, nao em memoria: a linha `running` e' a exclusao mutua entre a thread
    # agendada, o disparo manual e um segundo processo. Rodada morta (crash sem terminar)
    # expira pelo prazo e e' marcada como falha, senao travaria para sempre.
    with db.mutacao(conn):
        conn.execute("""UPDATE rm_sincronizacoes SET estado='failed', terminado_em=datetime('now'),
                        erro='rodada expirada sem terminar (processo caiu?)'
                        WHERE estado='running' AND iniciado_em < datetime('now', ?)""",
                     (f"-{PRAZO_RODADA_SEG} seconds",))
        if conn.execute("SELECT 1 FROM rm_sincronizacoes WHERE estado='running' LIMIT 1").fetchone():
            raise RodadaEmAndamento("Já há uma sincronização em andamento")
        cur = conn.execute("INSERT INTO rm_sincronizacoes (disparo) VALUES (?)", (disparo,))
        rodada_id = cur.lastrowid
    ESTADO["em_andamento"] = True
    try:
        # Rede primeiro, sem lock de escrita.
        nfs = cliente.consultar(rm.CONSULTA_NF)
        baixas = cliente.consultar(rm.CONSULTA_BAIXA)
        resumo = {"nfs": 0, "baixas": 0, "alocacoes": 0, "sugestoes": 0, "recebimentos": 0}
        with db.mutacao(conn):
            ids = []
            for linha in nfs:
                nid = _upsert_nf(conn, linha)
                ids.append(nid)
                resumo["nfs"] += 1
            for linha in baixas:
                _upsert_baixa(conn, linha)
                resumo["baixas"] += 1
            # Uma vez por rodada: quais coligadas cadastram centro (gatilho do modo estrito) e as
            # candidatas por coligada (cache, limpo a cada alocacao).
            coligadas_com_centro = _coligadas_com_centro(conn)
            cache: dict = {}
            for nid in ids:
                nf = conn.execute("SELECT situacao, numero FROM notas_fiscais WHERE id=?", (nid,)).fetchone()
                if nf["situacao"] != "ativa":
                    _desfazer_alocacoes_de_nf_cancelada(conn, nid, nf["numero"])
                    continue
                r = _casar(conn, nid, coligadas_com_centro, cache)
                if r == "alocada":
                    resumo["alocacoes"] += 1
                elif r == "ambigua":           # coluna `sugestoes` da rodada conta as NFs ambiguas
                    resumo["sugestoes"] += 1
            resumo["recebimentos"] = _recebimentos(conn)
            conn.execute("""UPDATE rm_sincronizacoes SET estado='success', terminado_em=datetime('now'),
                            nfs=?, baixas=?, alocacoes=?, sugestoes=?, recebimentos=? WHERE id=?""",
                         (resumo["nfs"], resumo["baixas"], resumo["alocacoes"], resumo["sugestoes"],
                          resumo["recebimentos"], rodada_id))
            auditoria.registrar(conn, None, "rm.sincronizacao", "rm_sincronizacao", rodada_id, None,
                                {"disparo": disparo, **resumo})
        ESTADO["ultima_sincronizacao"] = tempo.para_local(tempo.agora_utc()).isoformat(timespec="seconds")
        ESTADO["ultimo_erro"] = None
        return {"id": rodada_id, "estado": "success", **resumo}
    except Exception as e:
        # Mensagem sem segredo (ErroRM ja e' assim); falha de dado tambem fica registrada.
        msg = str(e)[:500]
        log.exception("sincronizacao do RM falhou (rodada %s)", rodada_id)
        with db.mutacao(conn):
            conn.execute("UPDATE rm_sincronizacoes SET estado='failed', terminado_em=datetime('now'), erro=? WHERE id=?",
                         (msg, rodada_id))
        ESTADO["ultimo_erro"] = msg
        return {"id": rodada_id, "estado": "failed", "erro": msg}
    finally:
        ESTADO["em_andamento"] = False


def rodadas(conn, limite: int = 10) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM rm_sincronizacoes ORDER BY id DESC LIMIT ?", (limite,))]


PAGINA_NFS_SEM_MEDICAO = 200
PAGINA_DESFEITAS = 50


def _pagina(conn, sql_de: str, chave: tuple[str, ...], cursor: tuple | None, tamanho: int) -> tuple[list[dict], bool]:
    """Uma pagina por cursor (keyset): as linhas depois de `cursor` na ordem `chave` (cada coluna DESC), e se ha'
    mais. A chave tem de ser imutavel: pelo cursor, e nao pela posicao, a lista nao repete nem pula linha quando a
    sincronizacao a muda entre uma pagina e outra."""
    onde, params = ("", ()) if cursor is None else (
        f" AND ({', '.join(chave)}) < ({', '.join('?' * len(chave))})", cursor)
    linhas = [dict(r) for r in conn.execute(
        f"{sql_de}{onde} ORDER BY {', '.join(c + ' DESC' for c in chave)} LIMIT ?", (*params, tamanho + 1))]
    return linhas[:tamanho], len(linhas) > tamanho


def reconciliacao(conn, nfs_apos: int | None = None, desfeitas_apos: int | None = None) -> dict:
    """RM x dashboard (spec §7 tela 8): o que esta' de um lado so'.

    #22: as NFs sem medicao e as alocacoes desfeitas vem em paginas (200 e 50), depois da ultima linha que a tela
    ja' tem, com o total exato em `totais` e `ha_mais`; as outras duas listas vem inteiras. O cursor e' so' o que
    nao muda: as NFs paginam pelo id (das que chegaram por ultimo as mais antigas; a sincronizacao regrava a
    emissao, e paginar por ela pularia ou repetiria NF), e a tela as ordena pela emissao no que ja' chegou; as
    desfeitas, por (desfeita_em, id), que nao mudam depois de gravados. Desfeita que nao existe e' ValueError.

    Tudo e' lido num retrato so' do banco (uma transacao de leitura): a lista e o total nao se desencontram se a
    sincronizacao gravar no meio."""
    if conn.in_transaction:
        return _reconciliacao(conn, nfs_apos, desfeitas_apos)
    conn.execute("BEGIN")
    try:
        return _reconciliacao(conn, nfs_apos, desfeitas_apos)
    finally:
        conn.rollback()   # so' leitura: nada a gravar


def _recebidas_sem_baixa(conn) -> list[dict]:
    """Issue #203: medicao recebida a mao (`conciliacao.recebidas_a_mao`) com nota ligada cujo titulo o RM ainda
    mostra em aberto. O registro manual vale (a nota sai do a receber); esta lista e' o aviso de que o RM nao tem a
    baixa. Uma linha por nota (nota partida entre duas medicoes aparece uma vez, na primeira), so' as da coligada
    da entidade do contrato (as que decidem o recebimento) e com mais que a tolerancia em aberto, a mesma regra do
    a receber; o valor e' o que falta do titulo, cheio."""
    from app import conciliacao, diretoria   # import local: os dois importam este modulo
    a_mao = conciliacao.recebidas_a_mao(conn)
    if not a_mao:
        return []
    out, vistas = [], set()
    for r in conn.execute("""
            SELECT m.id AS medicao_id, m.contrato_id, c.numero_instrumento, m.numero, m.tipo, m.competencia,
                   m.recebida_em, n.id AS nota_id, n.numero AS numero_nf, n.serie
            FROM medicoes m JOIN contratos c ON c.id=m.contrato_id JOIN entidades e ON e.id=COALESCE(c.entidade_id, 1)
            JOIN nf_alocacoes a ON a.medicao_id=m.id AND a.desfeita_em IS NULL
            JOIN notas_fiscais n ON n.id=a.nota_id AND n.situacao='ativa' AND n.coligada=e.coligada_rm
            WHERE m.estado='recebida'
            ORDER BY c.numero_instrumento, m.numero, m.id, n.id"""):
        if r["medicao_id"] not in a_mao or r["nota_id"] in vistas:
            continue
        vistas.add(r["nota_id"])
        falta = _falta_por_titulo(conn, r["nota_id"], aberto_inteiro=True)   # titulo a titulo (#253)
        if falta > diretoria.TOLERANCIA_CENTAVOS:
            out.append({**dict(r), "falta_centavos": falta})
    return out


def _reconciliacao(conn, nfs_apos: int | None, desfeitas_apos: int | None) -> dict:
    de_nfs = """
        FROM notas_fiscais n
        WHERE n.situacao='ativa'
          AND n.coligada IN (SELECT coligada_rm FROM entidades WHERE coligada_rm IS NOT NULL)
          AND NOT EXISTS (SELECT 1 FROM nf_alocacoes a WHERE a.nota_id=n.id AND a.desfeita_em IS NULL)"""
    nfs_sem_medicao, mais_nfs = _pagina(conn, f"SELECT n.* {de_nfs}", ("n.id",),
                                        None if nfs_apos is None else (nfs_apos,), PAGINA_NFS_SEM_MEDICAO)
    total_nfs = conn.execute(f"SELECT COUNT(*) {de_nfs}").fetchone()[0]
    medicoes_sem_nf = [dict(r) for r in conn.execute("""
        SELECT m.id AS medicao_id, m.contrato_id, c.numero_instrumento, c.orgao, m.numero, m.tipo,
               m.competencia, m.estado, COALESCE(m.valor_atestado_centavos, m.valor_protocolado_centavos) AS valor_centavos
        FROM medicoes m JOIN contratos c ON c.id=m.contrato_id
        WHERE (m.estado IN ('nota_emitida','nf_emitida','recebida')
               OR EXISTS (SELECT 1 FROM nf_alocacoes d WHERE d.medicao_id=m.id AND d.desfeita_em IS NOT NULL))
          AND NOT EXISTS (SELECT 1 FROM nf_alocacoes a WHERE a.medicao_id=m.id AND a.desfeita_em IS NULL)
        ORDER BY c.numero_instrumento, m.numero""")]
    divergencias = []
    for r in conn.execute("""
            SELECT m.id AS medicao_id, m.contrato_id, c.numero_instrumento, m.numero, m.tipo, m.competencia,
                   COALESCE(m.valor_atestado_centavos, m.valor_protocolado_centavos) AS valor_centavos,
                   SUM(a.valor_alocado_centavos) AS alocado_centavos
            FROM medicoes m JOIN contratos c ON c.id=m.contrato_id
            JOIN nf_alocacoes a ON a.medicao_id=m.id AND a.desfeita_em IS NULL
            GROUP BY m.id"""):
        if r["valor_centavos"] is not None and r["alocado_centavos"] != r["valor_centavos"]:
            divergencias.append(dict(r))
    de_desfeitas = """
        FROM nf_alocacoes a JOIN notas_fiscais n ON n.id=a.nota_id
        JOIN medicoes m ON m.id=a.medicao_id JOIN contratos c ON c.id=m.contrato_id
        WHERE a.desfeita_em IS NOT NULL"""
    cursor_desfeitas = None
    if desfeitas_apos is not None:
        cursor_desfeitas = conn.execute("SELECT desfeita_em, id FROM nf_alocacoes WHERE id=? AND desfeita_em IS NOT NULL",
                                        (desfeitas_apos,)).fetchone()
        if cursor_desfeitas is None:
            raise ValueError(f"Alocação desfeita {desfeitas_apos} não encontrada.")
    # o id da alocacao vai junto: e' o cursor da pagina seguinte e a chave da linha na tela
    desfeitas, mais_desfeitas = _pagina(conn, f"""
        SELECT a.id, a.medicao_id, a.desfeita_em, a.motivo_desfazer, n.numero, n.serie, n.coligada, c.numero_instrumento,
               m.numero AS numero_medicao, m.estado {de_desfeitas}""", ("a.desfeita_em", "a.id"),
        cursor_desfeitas and tuple(cursor_desfeitas), PAGINA_DESFEITAS)
    total_desfeitas = conn.execute(f"SELECT COUNT(*) {de_desfeitas}").fetchone()[0]
    return {"nfs_sem_medicao": nfs_sem_medicao, "medicoes_sem_nf": medicoes_sem_nf,
            "divergencias": divergencias, "alocacoes_desfeitas": desfeitas,
            "recebidas_sem_baixa": _recebidas_sem_baixa(conn),
            "totais": {"nfs_sem_medicao": total_nfs, "alocacoes_desfeitas": total_desfeitas},
            "ha_mais": {"nfs_sem_medicao": mais_nfs, "alocacoes_desfeitas": mais_desfeitas}}


def agendar(intervalo_seg: int = INTERVALO_SEG) -> threading.Thread | None:
    """Thread horaria (como o backup, processo unico hoje). Sem RM configurado, nada sobe."""
    cliente = rm.de_ambiente()
    ESTADO["configurado"] = cliente is not None
    if cliente is None:
        return None

    def loop():
        while True:
            try:
                conn = db.get_conn()
                try:
                    sincronizar(conn, cliente, "agendado")
                finally:
                    conn.close()
            except Exception:
                log.exception("rodada agendada do RM falhou fora da sincronizacao")
            time.sleep(intervalo_seg)

    t = threading.Thread(target=loop, name="rm-sync", daemon=True)
    t.start()
    return t
