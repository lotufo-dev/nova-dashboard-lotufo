import datetime
import json
import sqlite3
from decimal import Decimal, ROUND_HALF_UP

from app import auditoria, db, entidades, tempo

CAMPOS = ["obra_id", "entidade_id", "orgao", "numero_instrumento", "objeto",
          "valor_original_centavos", "data_base", "indice_reajuste", "vigencia_inicio",
          "vigencia_fim", "execucao_inicio", "execucao_fim", "numero_processo",
          "pasta_sharepoint", "percentual_direito_bp", "centro_custo_rm"]

# Entidade do grupo que assina o contrato. 1 = Lotufo (semeada na migracao 006): e' o
# caso da esmagadora maioria dos contratos, e obrigar o cadastro a escolher a entidade
# em toda obra propria so' criaria campo para errar. Obra de consorcio aponta para a
# entidade do consorcio -- e' o que faz o checklist de protocolo cobrar as certidoes do
# CNPJ certo.
ENTIDADE_PADRAO = 1

TRANSICOES = {"ativo": {"suspenso", "encerrado", "rescindido"},
              "suspenso": {"ativo"}, "encerrado": set(), "rescindido": set()}
EVENTO_POR_ESTADO = {"suspenso": "suspensao", "ativo": "retomada",
                     "encerrado": "encerramento", "rescindido": "rescisao"}


def criar(conn: sqlite3.Connection, usuario_id: int, dados: dict) -> int:
    # O default vive AQUI, e nao no schema: o SQLite recusa `ADD COLUMN ... REFERENCES
    # ... DEFAULT <valor>` (ver a migracao 009), entao a coluna e' nullable e quem
    # garante que todo contrato NOVO nasce com entidade e' esta linha.
    dados = {"entidade_id": ENTIDADE_PADRAO, **dados}
    presentes = [c for c in CAMPOS if c in dados]
    with db.mutacao(conn):
        cur = conn.execute(
            f"INSERT INTO contratos ({','.join(presentes)}) VALUES ({','.join('?' * len(presentes))})",
            [dados[c] for c in presentes])
        auditoria.registrar(conn, usuario_id, "contrato.criar", "contrato", str(cur.lastrowid),
                            depois={c: dados.get(c) for c in presentes})
    return cur.lastrowid


def atualizar(conn: sqlite3.Connection, usuario_id: int, contrato_id: int, dados: dict) -> None:
    presentes = [c for c in CAMPOS if c in dados]
    if not presentes:
        return
    with db.mutacao(conn):
        # a leitura do "antes" vem DEPOIS do BEGIN IMMEDIATE: e' o mesmo instante
        # em que o UPDATE acontece, entao a auditoria descreve a versao real trocada.
        antes = dict(conn.execute("SELECT * FROM contratos WHERE id=?", (contrato_id,)).fetchone())
        # Valor original congela no primeiro protocolo: depois disso saldo e curva so
        # mudam por aditivo (vigente = original + deltas), nunca por reescrita.
        if ("valor_original_centavos" in presentes
                and dados["valor_original_centavos"] != antes["valor_original_centavos"]
                and conn.execute("SELECT 1 FROM medicoes WHERE contrato_id=? AND congelada=1 LIMIT 1",
                                 (contrato_id,)).fetchone()):
            raise ValueError("Valor original congelado: o contrato já tem medição protocolada; "
                             "altere o valor por aditivo")
        conn.execute(f"UPDATE contratos SET {','.join(f'{c}=?' for c in presentes)} WHERE id=?",
                     [dados[c] for c in presentes] + [contrato_id])
        auditoria.registrar(conn, usuario_id, "contrato.atualizar", "contrato", str(contrato_id),
                            antes={c: antes[c] for c in presentes},
                            depois={c: dados[c] for c in presentes})


def mudar_estado(conn, usuario_id: int, contrato_id: int, novo: str, data: str, observacao) -> None:
    with db.mutacao(conn):
        r = conn.execute("SELECT estado, entidade_id FROM contratos WHERE id=?",
                         (contrato_id,)).fetchone()
        atual = r["estado"]
        if novo not in TRANSICOES.get(atual, set()):
            raise ValueError(f"Transição inválida: {atual} → {novo}")
        # A OUTRA porta da mesma regra de `entidades.desativar` (que recusa desativar
        # entidade com contrato ativo): sem esta, bastava suspender o contrato,
        # desativar a entidade e retomar o contrato para chegar ao mesmo estado
        # proibido -- contrato em execucao pendurado num CNPJ que sumiu dos paineis e
        # do checklist de protocolo, com a pendencia aparecendo so' na sessao do orgao.
        if novo == "ativo":
            e = entidades.detalhe(conn, entidade_de(r))
            if e is not None and not e["ativo"]:
                raise ValueError(f"Entidade {e['nome']} está desativada; reative-a "
                                 f"antes de reativar o contrato")
        cur = conn.execute("UPDATE contratos SET estado=? WHERE id=? AND estado=?", (novo, contrato_id, atual))
        db.exigir_uma_linha(cur, "Estado do contrato mudou concorrentemente; tente novamente")
        conn.execute("INSERT INTO contrato_eventos (contrato_id, tipo, data, observacao) VALUES (?,?,?,?)",
                     (contrato_id, EVENTO_POR_ESTADO[novo], data, observacao))
        auditoria.registrar(conn, usuario_id, "contrato.mudar_estado", "contrato", str(contrato_id),
                            antes={"estado": atual}, depois={"estado": novo, "data": data})


def vigente(conn: sqlite3.Connection, contrato_id: int) -> dict:
    c = dict(conn.execute("SELECT * FROM contratos WHERE id=?", (contrato_id,)).fetchone())
    valor = c["valor_original_centavos"]
    vig_fim, exe_fim = c["vigencia_fim"], c["execucao_fim"]
    for a in conn.execute("""SELECT * FROM aditivos WHERE contrato_id=? AND status='assinado'
                             ORDER BY data_assinatura, id""", (contrato_id,)):
        valor += a["delta_valor_centavos"]
        vig_fim = a["nova_vigencia_fim"] or vig_fim
        exe_fim = a["nova_execucao_fim"] or exe_fim
    return {**c, "entidade_id": entidade_de(c), "valor_vigente_centavos": valor,
            "cota_vigente_centavos": cota(valor, c["percentual_direito_bp"]),
            "vigencia_fim_vigente": vig_fim, "execucao_fim_vigente": exe_fim}


# 100,00% em pontos-base. Contrato próprio tem este valor e a cota é o valor cheio.
DIREITO_INTEGRAL_BP = 10000


def cota(centavos: int | None, percentual_bp: int | None) -> int | None:
    """A parte da Lotufo num valor do contrato (spec §3 decisão 14).

    Arredondamento único, meio para cima, como todo dinheiro do projeto. Contrato
    próprio (100%) devolve o próprio valor, sem passar por divisão -- não existe
    centavo a perder onde não há rateio.
    """
    if centavos is None:
        return None
    bp = DIREITO_INTEGRAL_BP if percentual_bp is None else percentual_bp
    if bp == DIREITO_INTEGRAL_BP:
        return centavos
    return int((Decimal(centavos) * bp / DIREITO_INTEGRAL_BP).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def entidade_de(contrato) -> int:
    """A entidade do contrato, com NULL lido como Lotufo (COALESCE de leitura).

    A coluna e' nullable por imposicao do SQLite (migracao 009). Deixar o NULL vazar
    para quem le transformaria "contrato da Lotufo gravado antes da 009" em "contrato
    sem entidade" -- e o checklist de protocolo, que e' a razao da coluna existir,
    devolveria vazio justamente para os contratos mais antigos da carteira.
    """
    return contrato["entidade_id"] or ENTIDADE_PADRAO


def listar(conn: sqlite3.Connection) -> list[dict]:
    ids = [r["id"] for r in conn.execute("SELECT id FROM contratos ORDER BY numero_instrumento")]
    return [vigente(conn, i) for i in ids]


# --- bloco 6: cabecalho e cadastro da pagina da obra (spec §10.3) ------------------------------------

def _dias_ate(iso: str | None, hoje: datetime.date) -> int | None:
    try:
        return (datetime.date.fromisoformat(iso) - hoje).days if iso else None
    except ValueError:
        return None


def cabecalho(conn: sqlite3.Connection, contrato_id: int, hoje: datetime.date | None = None) -> dict:
    """Orgao, instrumento, valor vigente e cota, prazos com os dias que faltam e o status da obra."""
    hoje = hoje or tempo.hoje_local()
    v = vigente(conn, contrato_id)
    o = conn.execute("SELECT nome FROM orgaos WHERE id=?", (v["orgao_id"],)).fetchone() if v.get("orgao_id") else None
    status = "em_encerramento" if v["estado"] == "ativo" and v.get("encerramento_iniciado_em") else v["estado"]
    return {"id": contrato_id, "obra": v.get("nome_curto") or v["numero_instrumento"],
            "orgao": o["nome"] if o else v["orgao"], "instrumento": v["numero_instrumento"],
            "valor_vigente_centavos": v["valor_vigente_centavos"], "cota_vigente_centavos": v["cota_vigente_centavos"],
            "percentual_lotufo_bp": v["percentual_direito_bp"] or DIREITO_INTEGRAL_BP,
            # os inicios (so' leitura) alimentam as linhas do tempo da pagina da obra; nulos quando o cadastro nao os tem
            "execucao_inicio": v.get("execucao_inicio"), "vigencia_inicio": v.get("vigencia_inicio"),
            "execucao_fim": v["execucao_fim_vigente"], "dias_execucao": _dias_ate(v["execucao_fim_vigente"], hoje),
            "vigencia_fim": v["vigencia_fim_vigente"], "dias_vigencia": _dias_ate(v["vigencia_fim_vigente"], hoje),
            "status": status}


def cadastro_da_obra(conn: sqlite3.Connection, contrato_id: int) -> dict:
    """O que o cadastro versionado tem da obra, so' para leitura (abas Reajuste, Prazos e Contrato)."""
    def linhas(sql):
        return [dict(r) for r in conn.execute(sql, (contrato_id,))]
    instrumentos = linhas("SELECT id, chave, tipo, numero, data, dados, pdf FROM instrumentos "
                          "WHERE contrato_id=? ORDER BY data, id")
    for i in instrumentos:
        i["dados"] = json.loads(i["dados"] or "{}")
    return {"datas_base": linhas("SELECT mes, indice, aplica_a FROM contrato_datas_base WHERE contrato_id=? ORDER BY mes"),
            "fiscais": linhas("SELECT nome, email, desde, cargo, tratamento, portaria FROM contrato_fiscais "
                              "WHERE contrato_id=? ORDER BY desde, id"),
            "aditivos": linhas("SELECT id, chave_cadastro, forma, tipo, numero, data_assinatura, delta_valor_centavos, "
                               "nova_execucao_fim, nova_vigencia_fim, status FROM aditivos WHERE contrato_id=? "
                               "ORDER BY data_assinatura, id"),
            "instrumentos": instrumentos}
