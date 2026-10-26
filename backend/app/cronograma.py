"""Cronograma versionado: passado congelado, futuro pela versao vigente (spec §5).

Operacionalizacao do congelamento: cada versao vale a partir do MES em que foi
criada (criado_em). O previsto efetivo de uma competencia e o valor da versao
mais recente criada ate aquela competencia -- revisar o cronograma nunca
reescreve meses ja decorridos.

Versao vinda do cadastro (issue #256): criado_em e' a DATA DO DOCUMENTO (aditivo, carta,
curva do SMO), nao a da carga. Por isso a linha do tempo e' ordenada por criado_em (empate
pelo numero), nao so pelo numero: a versao contratual de 2024 aplicada depois da carga de
04/09/2026 vem ANTES dela, e a carga so' fica superada pela primeira versao de documento
posterior. Para as versoes manuais as duas ordens coincidem (o clamp abaixo garante).

O mes de criacao e o de CUIABA (app/tempo.py), nao o da string UTC gravada:
uma versao publicada as 21h do dia 31 nasceria no mes seguinte se lida como
UTC, e congelaria o mes corrente antes da hora.
"""
import sqlite3

from app import auditoria, db, prazos, tempo


def nova_versao(conn: sqlite3.Connection, usuario_id: int, contrato_id: int,
                itens: list[tuple[str, int]], origem: str, data_documento: str | None = None) -> int:
    """Cria a proxima versao e devolve o numero dela.

    `data_documento` ('AAAA-MM-DD', so' o cadastro passa): a versao nasce na meia-noite de Cuiaba
    desse dia, sem o clamp monotonico -- a data e' a do documento, nao a do relogio."""
    if not itens:
        raise ValueError("Versão de cronograma vazia: informe ao menos uma competência")
    comps = [c for c, _ in itens]
    if len(comps) != len(set(comps)):
        raise ValueError("Competência duplicada na versão do cronograma")
    with db.mutacao(conn):
        r = conn.execute("SELECT MAX(numero) AS n, MAX(criado_em) AS c FROM cronograma_versoes "
                         "WHERE contrato_id=?", (contrato_id,)).fetchone()
        ultimo = r["n"] or 0
        # CLAMP MONOTONICO do criado_em: e' ele que decide, na leitura, a partir de que mes a
        # versao passa a valer. Com o relogio andando para tras (acerto de NTP, fuso trocado),
        # uma versao NOVA nasceria com criado_em anterior ao da anterior e passaria a reescrever
        # competencias que ja estavam congeladas -- passado alterado por acidente. Nunca antes
        # da ultima versao do contrato; a coluna aceita valor explicito (o DEFAULT so vale
        # quando a coluna e' omitida).
        # O clamp compara STRING UTC contra STRING UTC de proposito: e' a mesma escala em
        # que a coluna e' gravada, e a conversao para Cuiaba (deslocamento fixo) preserva
        # a ordem — converter aqui so trocaria a unidade sem mudar a decisao. Quem converte
        # e' a LEITURA (previsto_efetivo), onde a fronteira de mes e' que importa.
        if data_documento is not None:
            criado_em = tempo.inicio_do_dia_utc(data_documento)
        else:
            agora = conn.execute("SELECT datetime('now')").fetchone()[0]
            criado_em = max(agora, r["c"] or agora)
        # O SELECT acima e' uma leitura; entre ela e o INSERT outra requisicao pode criar a
        # mesma versao. Quem de fato decide e' o UNIQUE (contrato_id, numero) do schema --
        # sem este catch o perdedor da corrida recebia IntegrityError crua no handler (500).
        try:
            cur = conn.execute("INSERT INTO cronograma_versoes (contrato_id, numero, origem, criado_em) "
                               "VALUES (?,?,?,?)", (contrato_id, ultimo + 1, origem, criado_em))
        except sqlite3.IntegrityError as e:
            # So a violacao de unicidade vira erro de dominio: FK/CHECK quebrados sao bug
            # nosso e devem continuar subindo como 500.
            if "UNIQUE" not in str(e).upper():
                raise
            raise ValueError("Cronograma versionado concorrentemente; tente novamente") from e
        vid = cur.lastrowid
        conn.executemany("INSERT INTO cronograma_itens (versao_id, competencia, valor_previsto_centavos) VALUES (?,?,?)",
                         [(vid, c, v) for c, v in itens])
        depois = {"versao": ultimo + 1, "itens": len(itens)}
        if data_documento is not None:
            depois["data_documento"] = data_documento
        auditoria.registrar(conn, usuario_id, "cronograma.nova_versao", "contrato", contrato_id,
                            None, depois)
    return ultimo + 1


def _versoes(conn, contrato_id: int) -> list[dict]:
    """Linha do tempo das versoes: pela data em que passam a valer (criado_em), empate pelo numero."""
    return [dict(r) for r in conn.execute(
        "SELECT * FROM cronograma_versoes WHERE contrato_id=? ORDER BY criado_em, numero", (contrato_id,))]


def _itens(conn, versao_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT competencia, valor_previsto_centavos FROM cronograma_itens "
        "WHERE versao_id=? ORDER BY competencia", (versao_id,))]


def vigente(conn: sqlite3.Connection, contrato_id: int) -> dict | None:
    vs = _versoes(conn, contrato_id)
    if not vs:
        return None
    v = vs[-1]
    return {"numero": v["numero"], "criado_em": v["criado_em"], "origem": v["origem"],
            "itens": _itens(conn, v["id"])}


def versoes(conn: sqlite3.Connection, contrato_id: int) -> list[dict]:
    """Todas as versoes, na ordem da linha do tempo, com o que o cadastro diz do documento (issue #256).
    Versao sem linha no cadastro (manual ou da carga de 04/09/2026) vem com chave, origem, data e instrumento nulos."""
    linhas = conn.execute(
        """SELECT v.numero, v.criado_em, v.origem, k.chave, k.origem AS origem_documento, k.data_documento,
                  k.instrumento, COUNT(i.id) AS competencias,
                  COALESCE(SUM(i.valor_previsto_centavos), 0) AS total_centavos
             FROM cronograma_versoes v
             LEFT JOIN cronograma_versoes_cadastro k ON k.versao_id = v.id
             LEFT JOIN cronograma_itens i ON i.versao_id = v.id
            WHERE v.contrato_id=?
            GROUP BY v.id
            ORDER BY v.criado_em, v.numero""", (contrato_id,)).fetchall()
    out = [{**dict(r), "vigente": False} for r in linhas]
    if out:
        out[-1]["vigente"] = True     # a mesma que `vigente()` devolve: a ultima da linha do tempo
    return out


def previsto_efetivo(conn: sqlite3.Connection, contrato_id: int, antes_da_versao: int | None = None) -> dict[str, int]:
    """`antes_da_versao` (numero): so' as versoes que vem ESTRITAMENTE antes dela na linha do tempo -- o previsto
    como estava antes dessa versao (issue #295)."""
    efetivo: dict[str, int] = {}
    versoes_do_contrato = _versoes(conn, contrato_id)
    if antes_da_versao is not None:
        versoes_do_contrato = versoes_do_contrato[:[x["numero"] for x in versoes_do_contrato].index(antes_da_versao)]
    for v in versoes_do_contrato:        # linha do tempo: criado_em, empate pelo numero
        # 'AAAA-MM' do criado_em (UTC no banco) convertido para Cuiaba: e' a
        # fronteira de mes do NEGOCIO que decide o congelamento, nao a de UTC.
        mes_criacao = tempo.mes_local(v["criado_em"])
        # A versao e' um SNAPSHOT do futuro, nao um patch sobre a anterior: o que ela
        # NAO preve a partir do mes em que nasceu deixou de estar previsto. Sem limpar
        # antes de aplicar, uma competencia futura omitida na versao nova conservaria o
        # valor da antiga e o painel exibiria previsao ja retirada do cronograma
        # (contraria "futuro pela versao vigente", spec §5). O passado (< mes_criacao)
        # nao e' tocado -- e' justamente o que fica congelado.
        for comp in [c for c in efetivo if c >= mes_criacao]:
            del efetivo[comp]
        for item in _itens(conn, v["id"]):
            comp = item["competencia"]
            # a versao so pode reescrever competencias >= mes em que nasceu;
            # excecao: se a competencia nunca teve valor, qualquer versao semeia
            # (cronograma cadastrado com a obra ja em andamento precisa dos meses
            # ja decorridos -- sem a excecao eles ficariam previstos zero).
            if comp >= mes_criacao or comp not in efetivo:
                efetivo[comp] = item["valor_previsto_centavos"]
    return efetivo


ORIGENS_DE_REPACTUACAO = ("aditivo", "carta", "smo")


def curva_comparativa(conn: sqlite3.Connection, contrato_id: int) -> dict:
    """Issue #295 (spec 2026-10-20 §3.4, D9): o que a curva S desenha alem do vigente.

    `anterior`: previsto por competencia ANTES da ultima repactuacao, isto e', das versoes estritamente
    anteriores a ultima versao da linha do tempo cujo documento e' aditivo, carta ou curva do SMO. A vigente quase
    nunca e' essa versao (a carga de 04/09/2026 e as versoes manuais vem depois dos documentos), por isso nao
    se tira simplesmente a ultima. None sem repactuacao ou sem nada antes dela.
    `aditivos`: uma marca por aditivo ASSINADO e nao cancelado do contrato, no mes da assinatura, com o nome do
    termo ("3º TA", com a regra de ordinal da carta de prazo; sem ordinal, o numero; sem numero, "Termo aditivo"). Apostilamento nao e' aditivo e nao leva marca."""
    vs = versoes(conn, contrato_id)
    repactuacoes = [v for v in vs if v["origem_documento"] in ORIGENS_DE_REPACTUACAO]
    anterior = None
    if repactuacoes and vs.index(repactuacoes[-1]) > 0:
        efetivo = previsto_efetivo(conn, contrato_id, antes_da_versao=repactuacoes[-1]["numero"])
        anterior = [{"competencia": c, "previsto_centavos": v} for c, v in sorted(efetivo.items())]
    aditivos = []
    for r in conn.execute("SELECT numero, ordinal, data_assinatura FROM aditivos WHERE contrato_id=? "
                          "AND status='assinado' AND cancelado_em IS NULL AND data_assinatura IS NOT NULL "
                          "AND COALESCE(forma,'termo_aditivo')='termo_aditivo' "
                          "ORDER BY data_assinatura, id", (contrato_id,)):
        # mesma regra da carta de prazo (#261): o sufixo do numero manda, depois a coluna `ordinal`
        n = prazos._ordinal(dict(r), 0)
        nome = f"{n}º TA" if n else (f"TA {r['numero']}" if r["numero"] else "Termo aditivo")
        aditivos.append({"competencia": r["data_assinatura"][:7], "data": r["data_assinatura"], "nome": nome})
    return {"anterior": anterior or None, "aditivos": aditivos}
