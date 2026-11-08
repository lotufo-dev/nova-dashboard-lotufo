"""Planilha/carta de medicao (issue #281; spec 2026-10-20 §2.1, passo 1; D3, D6).

Cada registro e' uma versao de `medicao_planilhas` (evento append-only, migracao 042); a 1a poe a medicao em
`planilha_gerada`, as seguintes (Rev01, Rev02...) exigem motivo. O pedido vai para `valor_protocolado_centavos`
(o "pedido" da spec) enquanto a planilha nao foi enviada; depois do envio o pedido congelado e' o da versao
enviada, e a revisao so' acrescenta a versao. So' total e periodo (D3): a planilha vai anexada.

Modulo proprio, ao lado de `medicoes.py`: o boletim, a assinatura e a lista em andamento (issues irmas) mexem la'.
"""
import datetime

from app import arquivos, auditoria, contratos, db, espelho, medicoes, reajuste, tempo
from app.medicoes import ESTADOS_NO_MEDIDO, LOTE_AUDITORIA, _data_br, _json_dict, nome_medicao, rotulo_estado

# o reajuste nao entra pela planilha/carta: nasce pelo campo "Reajuste" do formulario da execucao, em prevista,
# com data-base e ciclo (decisao do Leo na #276, 08/11/2026)
TIPOS = ("execucao", "projeto")
ESTADOS_REVISAO = ("planilha_gerada", "planilha_enviada")
FORA_DO_ACUMULADO = ("prevista", "cancelada", "desistida")
# #561: o acumulado anterior (congelado na versao da planilha/carta) parte da lista unica do medido e soma a planilha
# gerada: ela ocupa o numero e, no envio por fora sem registro, o orgao ja' a recebeu. O Medido da obra nao a conta.
ESTADOS_NO_ACUMULADO = (*ESTADOS_NO_MEDIDO, "planilha_gerada")


def _mes_seguinte(competencia: str) -> str:
    ano, mes = int(competencia[:4]), int(competencia[5:7])
    return f"{ano + mes // 12}-{mes % 12 + 1:02d}"


def _mes_br(competencia: str) -> str:
    return f"{competencia[5:7]}/{competencia[:4]}"


def acumulado_anterior(conn, contrato_id: int, tipo: str, numero: int) -> int:
    """Soma das medicoes do mesmo tipo com numero menor: o aprovado (atestado) de cada uma, senao o pedido
    (protocolado). So' os estados de ESTADOS_NO_ACUMULADO (#561: o medido mais a planilha gerada; prevista,
    cancelada e desistida nao contam). Soma em Python: o SUM do SQLite e' int64 e
    estoura com valores que cabem um a um na coluna (mesmo motivo de paineis.saldo)."""
    return sum(r["v"] for r in conn.execute(
        "SELECT COALESCE(valor_atestado_centavos, valor_protocolado_centavos, 0) AS v FROM medicoes "
        f"WHERE contrato_id=? AND tipo=? AND numero<? AND estado IN ({','.join('?' * len(ESTADOS_NO_ACUMULADO))})",
        (contrato_id, tipo, numero, *ESTADOS_NO_ACUMULADO)))


def _anterior(conn, contrato_id: int, tipo: str, numero: int):
    """A medicao imediatamente anterior (maior numero abaixo deste), fora prevista, cancelada e desistida."""
    return conn.execute(
        "SELECT numero, competencia, periodo_inicio, periodo_fim FROM medicoes WHERE contrato_id=? AND tipo=? "
        f"AND numero<? AND estado NOT IN ({','.join('?' * len(FORA_DO_ACUMULADO))}) ORDER BY numero DESC LIMIT 1",
        (contrato_id, tipo, numero, *FORA_DO_ACUMULADO)).fetchone()


def avisos(conn, contrato_id: int, tipo: str, numero: int, competencia: str, inicio: str) -> list[str]:
    """Avisos que NAO impedem a gravacao: periodo que se sobrepoe ao da medicao anterior ou pula dias depois
    dela, e competencia anterior a da medicao anterior. Anterior sem periodo registrado (historico) nao avisa
    sobre o periodo."""
    ant = _anterior(conn, contrato_id, tipo, numero)
    if ant is None:
        return []
    saida = []
    if ant["periodo_fim"]:
        fim_ant = datetime.date.fromisoformat(ant["periodo_fim"])
        ini = datetime.date.fromisoformat(inicio)
        if ini <= fim_ant:
            saida.append(f"O período se sobrepõe ao da {ant['numero']}ª medição, que vai até "
                         f"{_data_br(ant['periodo_fim'])}")
        elif ini > fim_ant + datetime.timedelta(days=1):
            saida.append(f"O período pula dias: a {ant['numero']}ª medição terminou em "
                         f"{_data_br(ant['periodo_fim'])} e esta começa em {_data_br(inicio)}")
    if competencia < ant["competencia"]:
        saida.append(f"Competência {_mes_br(competencia)} anterior à da {ant['numero']}ª medição "
                     f"({_mes_br(ant['competencia'])})")
    return saida


def _saldo(conn, contrato_id: int, tipo: str, acumulado: int, pedido: int | None) -> dict:
    """saldo = vigente − acumulado anterior (e − pedido, no `saldo_apos_pedido`). O acumulado conta as medicoes
    anteriores pela lista do medido de paineis.saldo mais a planilha gerada (#561, ESTADOS_NO_ACUMULADO; spec §2.1
    passo 1, "soma dos aprovados, senao pedidos").
    So' a execucao tem saldo contra o valor do contrato (como em paineis.saldo); no projeto, os saldos sao nulos."""
    c = contratos.vigente(conn, contrato_id)
    vigente = c["valor_vigente_centavos"]
    # a base do saldo e' a da execucao, como a do painel (#262, paineis.saldo): o aditivo de reajuste nao entra
    base = c["valor_vigente_execucao_centavos"]
    if tipo != "execucao":
        return {"vigente_centavos": vigente, "acumulado_anterior_centavos": acumulado,
                "saldo_centavos": None, "saldo_apos_pedido_centavos": None}
    return {"vigente_centavos": vigente, "acumulado_anterior_centavos": acumulado,
            "saldo_centavos": base - acumulado,
            "saldo_apos_pedido_centavos": None if pedido is None else base - acumulado - pedido}


def tipo_da_ultima(conn, contrato_id: int) -> str:
    """Issue #567: o tipo da ultima medicao de execucao ou projeto da obra (competencia mais recente; na mesma, a
    execucao), fora prevista, cancelada e desistida. O reajuste nao conta: acompanha o numero da execucao e sai
    depois dela (como em medicoes, #154), e pre-seleciona-lo trocaria a serie da proxima medicao. Sem medicao:
    execucao."""
    r = conn.execute(
        "SELECT tipo FROM medicoes WHERE contrato_id=? AND tipo IN ('execucao','projeto') "
        f"AND estado NOT IN ({','.join('?' * len(FORA_DO_ACUMULADO))}) "
        "ORDER BY competencia DESC, tipo='execucao' DESC, numero DESC, id DESC LIMIT 1",
        (contrato_id, *FORA_DO_ACUMULADO)).fetchone()
    return r["tipo"] if r is not None else "execucao"


def sugestao(conn, contrato_id: int, tipo: str | None = None) -> dict:
    """Nº (ultimo + 1; o do orgao tambem, onde ja' difere, D6), competencia (a da 1a prevista, senao o mes
    seguinte ao da ultima, senao o mes corrente), periodo (o mes civil da competencia), acumulado e saldo.
    Sem tipo, o da ultima medicao da obra (issue #567: a obra so' de projeto sugere a proxima de projeto). Tudo de
    um retrato so' (db.leitura): uma medicao gravada no meio nao mistura o nº de depois com a competencia de antes."""
    with db.leitura(conn):
        return _sugestao(conn, contrato_id, tipo_da_ultima(conn, contrato_id) if tipo is None else tipo)


def _sugestao(conn, contrato_id: int, tipo: str) -> dict:
    prevista = conn.execute(
        "SELECT numero, competencia FROM medicoes WHERE contrato_id=? AND tipo=? AND estado='prevista' "
        "ORDER BY competencia, numero LIMIT 1", (contrato_id, tipo)).fetchone()
    ultima = conn.execute(
        "SELECT numero, competencia, numero_orgao FROM medicoes WHERE contrato_id=? AND tipo=? "
        f"AND estado NOT IN ({','.join('?' * len(FORA_DO_ACUMULADO))}) ORDER BY numero DESC LIMIT 1",
        (contrato_id, tipo, *FORA_DO_ACUMULADO)).fetchone()
    # o numero conta tambem as canceladas/desistidas: (contrato, numero, tipo) e' UNIQUE, e sugerir o nº de uma
    # cancelada levaria a uma gravacao recusada
    maior = conn.execute("SELECT MAX(numero) FROM medicoes WHERE contrato_id=? AND tipo=?",
                         (contrato_id, tipo)).fetchone()[0] or 0
    if prevista is not None:
        numero, competencia = prevista["numero"], prevista["competencia"]
    elif ultima is not None:
        numero, competencia = maior + 1, _mes_seguinte(ultima["competencia"])
    else:
        numero, competencia = maior + 1, tempo.hoje_local().isoformat()[:7]
    numero_orgao = None
    if ultima is not None and ultima["numero_orgao"] is not None and numero > ultima["numero"]:
        numero_orgao = ultima["numero_orgao"] + (numero - ultima["numero"])
    inicio, fim = espelho.periodo_do_mes(competencia)
    acumulado = acumulado_anterior(conn, contrato_id, tipo, numero)
    return {"tipo": tipo, "numero": numero, "numero_orgao": numero_orgao, "competencia": competencia,
            "periodo_inicio": inicio, "periodo_fim": fim, **_saldo(conn, contrato_id, tipo, acumulado, None)}


def _conferir_periodo(inicio: str, fim: str) -> None:
    if inicio > fim:
        raise ValueError("Período inválido: o início é depois do fim")


def _gravar_versao(conn, usuario_id: int, medicao_id: int, versao: int, dados: dict, acumulado: int,
                   anexos: dict, motivo: str | None) -> int:
    cur = conn.execute(
        "INSERT INTO medicao_planilhas (medicao_id, versao, periodo_inicio, periodo_fim, valor_pedido_centavos, "
        "acumulado_anterior_centavos, arquivo, sha256, arquivo_planilha, sha256_planilha, origem, usuario_id, motivo) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,'manual',?,?)",
        (medicao_id, versao, dados["periodo_inicio"], dados["periodo_fim"], dados["valor_centavos"], acumulado,
         anexos["arquivo"], anexos["sha256"], anexos["arquivo_planilha"], anexos["sha256_planilha"], usuario_id,
         motivo))
    return cur.lastrowid


def _evento(dados: dict, versao: int, pid: int, acumulado: int, anexos: dict, avisos_: list[str]) -> dict:
    return {"versao": versao, "planilha_id": pid, "periodo_inicio": dados["periodo_inicio"],
            "periodo_fim": dados["periodo_fim"], "valor_pedido_centavos": dados["valor_centavos"],
            "acumulado_anterior_centavos": acumulado, "sha256": anexos["sha256"],
            "sha256_planilha": anexos["sha256_planilha"], "avisos": avisos_}


def conferir_registro(conn, contrato_id: int, dados: dict):
    """Recusas da 1a versao (ValueError), sem gravar nada: a rota chama ANTES de gravar os anexos, para a recusa
    nao deixar arquivo sem registro, e `registrar` chama de novo dentro da transacao. Devolve a medicao que ja'
    existe com o mesmo nº e tipo (so' pode ser uma prevista), ou None, e o reajuste conferido (`_conferir_reajuste`)."""
    numero, tipo, competencia = dados["numero"], dados["tipo"], dados["competencia"]
    if tipo not in TIPOS:
        raise ValueError("A planilha/carta é de medição de execução ou de projeto")
    _conferir_periodo(dados["periodo_inicio"], dados["periodo_fim"])
    c = contratos.vigente(conn, contrato_id)
    inicio_contrato = c.get("execucao_inicio") or c.get("vigencia_inicio")
    if inicio_contrato and competencia < inicio_contrato[:7]:
        raise ValueError(f"Competência {_mes_br(competencia)} é anterior ao início do contrato "
                         f"({_mes_br(inicio_contrato[:7])})")
    ja = conn.execute("SELECT * FROM medicoes WHERE contrato_id=? AND numero=? AND tipo=?",
                      (contrato_id, numero, tipo)).fetchone()
    if ja is not None and ja["estado"] != "prevista":
        # so' orienta a revisao onde ela e' aceita (revisor, rodada 1)
        dica = ": para corrigir a planilha/carta, registre uma revisão" if ja["estado"] in ESTADOS_REVISAO else ""
        raise ValueError(f"{nome_medicao(numero, tipo)} já existe neste contrato e está "
                         f"{rotulo_estado(ja['estado'])}{dica}")
    return ja, _conferir_reajuste(conn, contrato_id, dados)


def reajuste_do_numero(conn, contrato_id: int, numero: int, competencia: str):
    """Issue #276: a medicao de reajuste de mesmo nº que a planilha/carta completaria. Devolve a prevista da mesma
    competencia (sem pedido do espelho) ou None quando nao existe; a que nao recebe o reajuste (outro estado, outra
    competencia, pedido do espelho) e' recusada (ValueError, com o motivo)."""
    r = conn.execute("SELECT * FROM medicoes WHERE contrato_id=? AND numero=? AND tipo='reajuste'",
                     (contrato_id, numero)).fetchone()
    if r is None:
        return None
    nome = nome_medicao(numero, "reajuste")
    if r["estado"] != "prevista":
        raise ValueError(f"{nome} já existe neste contrato e está {rotulo_estado(r['estado'])}")
    if r["competencia"] != competencia:
        raise ValueError(f"{nome} já existe neste contrato com a competência {_mes_br(r['competencia'])}")
    if r["valor_protocolado_origem"] == "espelho":
        raise ValueError(f"O pedido da {nome[0].lower()}{nome[1:]} vem do espelho: deixe o reajuste em branco")
    return r


def _conferir_reajuste(conn, contrato_id: int, dados: dict):
    """Issue #276 (decisao do Leo, 08/11/2026): com o campo "Reajuste" preenchido, a planilha/carta de execucao faz
    nascer a medicao de reajuste de mesmo nº e competencia, em `prevista`, com o pedido, a data-base e o ciclo. Ja'
    existindo a prevista de reajuste desse nº (`reajuste_do_numero`), ela recebe os valores; sem data-base escolhida,
    vale a que ela ja' tem. Devolve (data-base, ciclo, medicao de reajuste existente ou None); sem o campo, None."""
    if dados.get("reajuste_centavos") is None:
        if dados.get("reajuste_data_base"):
            raise ValueError("Informe o valor do reajuste ou deixe a data-base em branco")
        return None
    numero, competencia = dados["numero"], dados["competencia"]
    if dados["tipo"] != "execucao":
        raise ValueError("O reajuste acompanha só a planilha/carta de execução")
    r = reajuste_do_numero(conn, contrato_id, numero, competencia)
    escolhida = dados.get("reajuste_data_base") or (r["data_base_mes"] if r is not None else None)
    base, ciclo = reajuste.base_e_ciclo_da_medicao(conn, contrato_id, competencia, escolhida, numero)
    return base, ciclo, r


CAMPOS_REAJUSTE = ("valor_protocolado_centavos", "valor_protocolado_origem", "data_base_mes", "ciclo")


def _gravar_reajuste(conn, usuario_id: int, contrato_id: int, dados: dict, conferido) -> int | None:
    """Issue #276: cria (ou completa a prevista de) a medicao de reajuste que acompanha a planilha/carta, com
    auditoria. Devolve o id dela, ou None sem o campo."""
    if conferido is None:
        return None
    base, ciclo, ja = conferido
    numero, competencia, valor = dados["numero"], dados["competencia"], dados["reajuste_centavos"]
    if ja is None:
        return medicoes.criar(conn, usuario_id, {"contrato_id": contrato_id, "numero": numero, "tipo": "reajuste",
                                                 "competencia": competencia, "valor_centavos": valor,
                                                 "data_base_mes": base, "ciclo": ciclo})
    rid, antes = ja["id"], {k: ja[k] for k in CAMPOS_REAJUSTE}
    cur = conn.execute(
        "UPDATE medicoes SET valor_protocolado_centavos=?, valor_protocolado_origem='manual', data_base_mes=?, "
        "ciclo=? WHERE id=? AND estado='prevista' AND COALESCE(valor_protocolado_origem, '') <> 'espelho'",
        (valor, base, ciclo, rid))
    db.exigir_uma_linha(cur, "Estado da medição de reajuste mudou concorrentemente; tente novamente")
    auditoria.registrar(conn, usuario_id, "medicao.reajuste_da_planilha", "medicao", rid, antes, {
        "valor_protocolado_centavos": valor, "valor_protocolado_origem": "manual", "data_base_mes": base,
        "ciclo": ciclo})
    return rid


def conferir_revisao(conn, medicao_id: int, dados: dict):
    """Recusas da revisao (ValueError), sem gravar nada; mesmo uso de `conferir_registro`. Devolve a medicao."""
    if not (dados.get("motivo") or "").strip():
        raise ValueError("Informe o motivo da revisão da planilha/carta")
    _conferir_periodo(dados["periodo_inicio"], dados["periodo_fim"])
    m = conn.execute("SELECT * FROM medicoes WHERE id=?", (medicao_id,)).fetchone()
    if m["estado"] not in ESTADOS_REVISAO:
        raise ValueError(f"{nome_medicao(m['numero'], m['tipo'])} está {rotulo_estado(m['estado'])}: "
                         "a planilha/carta só se revisa antes do boletim do órgão")
    if conn.execute("SELECT 1 FROM medicao_planilhas WHERE medicao_id=?", (medicao_id,)).fetchone() is None:
        raise ValueError("Esta medição não tem planilha/carta registrada para revisar")
    return m


CAMPOS_MEDICAO = ("estado", "competencia", "valor_protocolado_centavos", "valor_protocolado_origem",
                  "periodo_inicio", "periodo_fim", "numero_orgao")


def registrar(conn, usuario_id: int, contrato_id: int, dados: dict, anexos: dict) -> dict:
    """1a versao: cria a medicao (ou promove a prevista do mesmo nº e tipo) em `planilha_gerada`, com periodo,
    pedido e nº do orgao. Devolve a medicao, a versao, o acumulado, o saldo e os avisos de periodo."""
    numero, tipo, competencia = dados["numero"], dados["tipo"], dados["competencia"]
    with db.mutacao(conn):
        ja, conferido = conferir_registro(conn, contrato_id, dados)
        avisos_ = avisos(conn, contrato_id, tipo, numero, competencia, dados["periodo_inicio"])
        acumulado = acumulado_anterior(conn, contrato_id, tipo, numero)
        valores = (competencia, dados["valor_centavos"], dados["periodo_inicio"], dados["periodo_fim"],
                   dados.get("numero_orgao"))
        if ja is None:
            cur = conn.execute(
                "INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, "
                "valor_protocolado_origem, periodo_inicio, periodo_fim, numero_orgao) "
                "VALUES (?,?,?,?,'planilha_gerada',?,'manual',?,?,?)", (contrato_id, numero, tipo, *valores))
            mid, antes = cur.lastrowid, None
        else:
            mid, antes = ja["id"], {k: ja[k] for k in CAMPOS_MEDICAO}
            cur = conn.execute(
                "UPDATE medicoes SET estado='planilha_gerada', competencia=?, valor_protocolado_centavos=?, "
                # COALESCE: sem nº do orgao no formulario, o que a prevista ja' tinha fica
                "valor_protocolado_origem='manual', periodo_inicio=?, periodo_fim=?, "
                "numero_orgao=COALESCE(?, numero_orgao) WHERE id=? AND estado='prevista'", (*valores, mid))
            db.exigir_uma_linha(cur, "Estado da medição mudou concorrentemente; tente novamente")
        numero_orgao = conn.execute("SELECT numero_orgao FROM medicoes WHERE id=?", (mid,)).fetchone()[0]
        pid = _gravar_versao(conn, usuario_id, mid, 1, dados, acumulado, anexos, None)
        auditoria.registrar(conn, usuario_id, "medicao.planilha", "medicao", mid, antes, {
            "estado": "planilha_gerada", "numero": numero, "tipo": tipo, "competencia": competencia,
            "numero_orgao": numero_orgao, **_evento(dados, 1, pid, acumulado, anexos, avisos_)})
        saldo = _saldo(conn, contrato_id, tipo, acumulado, dados["valor_centavos"])
        reajuste_id = _gravar_reajuste(conn, usuario_id, contrato_id, dados, conferido)
    return {"medicao_id": mid, "versao": 1, "estado": "planilha_gerada", "avisos": avisos_,
            "reajuste_medicao_id": reajuste_id, **saldo}


def revisar(conn, usuario_id: int, medicao_id: int, dados: dict, anexos: dict) -> dict:
    """Revisao (Rev01, Rev02...): versao nova com motivo. Antes do envio, o pedido e o periodo da medicao passam a
    ser os da revisao; depois do envio ficam os da versao enviada (o pedido congela no envio, spec §2.1)."""
    motivo = (dados.get("motivo") or "").strip()
    with db.mutacao(conn):
        m = conferir_revisao(conn, medicao_id, dados)
        vigente = conn.execute(
            "SELECT versao, valor_pedido_centavos, periodo_inicio, periodo_fim, sha256, sha256_planilha "
            "FROM medicao_planilhas WHERE medicao_id=? ORDER BY versao DESC LIMIT 1", (medicao_id,)).fetchone()
        # dois cliques em "revisar" nao viram duas versoes iguais (revisor e gate Sol, rodada 1)
        if (vigente["valor_pedido_centavos"], vigente["periodo_inicio"], vigente["periodo_fim"], vigente["sha256"],
                vigente["sha256_planilha"]) == (dados["valor_centavos"], dados["periodo_inicio"], dados["periodo_fim"],
                                                 anexos["sha256"], anexos["sha256_planilha"]):
            raise ValueError(f"Esta revisão é igual à versão {vigente['versao']} já registrada")
        versao = vigente["versao"] + 1
        avisos_ = avisos(conn, m["contrato_id"], m["tipo"], m["numero"], m["competencia"], dados["periodo_inicio"])
        acumulado = acumulado_anterior(conn, m["contrato_id"], m["tipo"], m["numero"])
        antes = None
        if m["estado"] == "planilha_gerada":
            antes = {k: m[k] for k in ("valor_protocolado_centavos", "periodo_inicio", "periodo_fim")}
            cur = conn.execute(
                "UPDATE medicoes SET valor_protocolado_centavos=?, valor_protocolado_origem='manual', "
                "periodo_inicio=?, periodo_fim=? WHERE id=? AND estado='planilha_gerada'",
                (dados["valor_centavos"], dados["periodo_inicio"], dados["periodo_fim"], medicao_id))
            db.exigir_uma_linha(cur, "Estado da medição mudou concorrentemente; tente novamente")
        pid = _gravar_versao(conn, usuario_id, medicao_id, versao, dados, acumulado, anexos, motivo)
        auditoria.registrar(conn, usuario_id, "medicao.planilha", "medicao", medicao_id, antes,
                            {"motivo": motivo, **_evento(dados, versao, pid, acumulado, anexos, avisos_)})
        # o pedido do saldo e' o que FICOU na medicao: depois do envio a revisao nao o troca (gate Sol, rodada 1)
        pedido = dados["valor_centavos"] if m["estado"] == "planilha_gerada" else m["valor_protocolado_centavos"]
        saldo = _saldo(conn, m["contrato_id"], m["tipo"], acumulado, pedido)
    return {"medicao_id": medicao_id, "versao": versao, "estado": m["estado"], "avisos": avisos_, **saldo}


def versoes(conn, medicao_id: int) -> list[dict]:
    """Todas as versoes da planilha/carta, da 1a a vigente (a tela mostra todas, spec §2.1 Revisoes)."""
    return [dict(r) for r in conn.execute(
        "SELECT p.id, p.versao, p.periodo_inicio, p.periodo_fim, p.valor_pedido_centavos, "
        "p.acumulado_anterior_centavos, p.sha256, p.sha256_planilha, p.origem, p.motivo, p.criado_em, "
        "u.nome AS usuario FROM medicao_planilhas p LEFT JOIN usuarios u ON u.id=p.usuario_id "
        "WHERE p.medicao_id=? ORDER BY p.versao", (medicao_id,))]


def anexo(conn, medicao_id: int, planilha_id: int, peca: str) -> dict | None:
    """O anexo (`oficio` ou `planilha`) de UMA versao, so' se a versao for da medicao pedida (gate Sol S3: a versao
    de outra medicao nao se baixa pela URL desta). Devolve o caminho gravado, que a rota resolve com
    `arquivos.caminho_seguro` e nunca expoe, e o que ela precisa para o nome do arquivo."""
    coluna = {"oficio": "p.arquivo", "planilha": "p.arquivo_planilha"}[peca]
    r = conn.execute(f"SELECT {coluna} AS arquivo, p.versao, m.numero FROM medicao_planilhas p "
                     "JOIN medicoes m ON m.id=p.medicao_id WHERE p.id=? AND p.medicao_id=?",
                     (planilha_id, medicao_id)).fetchone()
    return dict(r) if r else None


# --- issue #283: planilha/carta enviada por fora e nº do SIGA (spec 2026-10-20 §2.1, passo 2; E3) -------------

ENVIO = "medicao.planilha_envio"          # o envio (por fora; o do sistema, issue #282, grava o mesmo evento)
NUMERO_SIGA = "medicao.numero_siga"
ESTADOS_ENVIO = ("planilha_gerada", "planilha_enviada")
# O nº do SIGA da planilha/carta entra do envio ate' antes do protocolo da nota. Mora em `medicao_protocolos` com
# etapa 'planilha' (migracao 054): os paineis, a conciliacao e as telas so' contam a etapa 'nota' como protocolo
ESTADOS_NUMERO_SIGA = ("planilha_enviada", "boletim_recebido", "espelho_gerado", "espelho_enviado", "nota_emitida")
TETO_MEIO = 200
REAJUSTE_CONGELADO = "medicao.reajuste_congelado"


def congelar_reajuste_do_envio(conn, usuario_id: int, m: dict, data: str, origem: str) -> int | None:
    """Issue #590 (spec 2026-10-20 §2.2, "como na execucao"): dentro da transacao do 1o envio da planilha/carta de
    execucao (pelo sistema ou por fora), a medicao de reajuste de mesmo nº e competencia, em `prevista` e com pedido,
    tem o pedido congelado. Congela como a execucao, pelo marcador do envio (`planilha_enviada_em`, que
    `medicoes.definir_valor` recusa), nao por `congelada` (do protocolo da nota; tambem congela o valor original do
    contrato). A de reajuste continua `prevista` ate' o espelho a promover. Sem pedido, nada muda. Devolve o id dela."""
    if m["tipo"] != "execucao":
        return None
    r = conn.execute(
        "SELECT id, valor_protocolado_centavos FROM medicoes WHERE contrato_id=? AND numero=? AND tipo='reajuste' "
        "AND competencia=? AND estado='prevista' AND valor_protocolado_centavos IS NOT NULL "
        "AND planilha_enviada_em IS NULL", (m["contrato_id"], m["numero"], m["competencia"])).fetchone()
    if r is None:
        return None
    cur = conn.execute("UPDATE medicoes SET planilha_enviada_em=?, planilha_envio_origem=? WHERE id=? "
                       "AND estado='prevista' AND planilha_enviada_em IS NULL", (data, origem, r["id"]))
    # nao recusa: no envio pelo sistema isto roda depois do e-mail, onde nada recusa (a leitura acima e' do mesmo lock)
    if not cur.rowcount:
        return None
    auditoria.registrar(conn, usuario_id, REAJUSTE_CONGELADO, "medicao", r["id"],
                        {"planilha_enviada_em": None, "planilha_envio_origem": None},
                        {"planilha_enviada_em": data, "planilha_envio_origem": origem,
                         "valor_protocolado_centavos": r["valor_protocolado_centavos"], "medicao_execucao_id": m["id"]})
    return r["id"]


def _versao_enviada(conn, medicao_id: int) -> int:
    """A maior versao ja' enviada, pelos eventos de envio da auditoria (append-only, como `notas_envio.liberacao`);
    0 sem evento. Quem chama trata `planilha_enviada` sem evento como a 1a enviada."""
    maior = 0
    for (depois,) in conn.execute("SELECT depois FROM audit_log WHERE entidade='medicao' AND entidade_id=? AND acao=?",
                                  (str(medicao_id), ENVIO)):
        v = (_json_dict(depois) or {}).get("versao")
        if isinstance(v, int):
            maior = max(maior, v)
    return maior


def conferir_envio_externo(conn, medicao_id: int, dados: dict) -> tuple[dict, dict]:
    """Recusas do "enviado por fora" (ValueError), sem gravar nada: a rota chama antes de ler o .eml e
    `registrar_envio_externo` de novo sob o lock. Devolve (medicao, versao vigente da planilha/carta).
    Na 1a vez a medicao esta' em `planilha_gerada`; depois, so' uma revisao ainda nao enviada vai (E3)."""
    try:
        data = datetime.date.fromisoformat(dados.get("enviado_em") or "")
    except (TypeError, ValueError):
        raise ValueError("Data do envio inválida (use AAAA-MM-DD)") from None
    if data > tempo.hoje_local():
        raise ValueError("A data do envio não pode ser futura")
    if not (dados.get("meio") or "").strip():
        raise ValueError("Informe o meio do envio (como a planilha/carta foi enviada)")
    m = conn.execute("SELECT * FROM medicoes WHERE id=?", (medicao_id,)).fetchone()
    vigente = conn.execute("SELECT id, versao FROM medicao_planilhas WHERE medicao_id=? ORDER BY versao DESC LIMIT 1",
                           (medicao_id,)).fetchone()
    if vigente is None:
        raise ValueError("Esta medição não tem planilha/carta registrada para enviar")
    if m["estado"] not in ESTADOS_ENVIO:
        raise ValueError(f"{nome_medicao(m['numero'], m['tipo'])} está {rotulo_estado(m['estado'])}: "
                         "a planilha/carta só se envia antes do boletim do órgão")
    if m["estado"] == "planilha_enviada" and vigente["versao"] <= max(_versao_enviada(conn, medicao_id), 1):
        raise ValueError(f"A versão {vigente['versao']} da planilha/carta já foi enviada: para enviar de novo, "
                         "registre uma revisão")
    # a versao que esta' saindo pelo sistema (reserva ativa) nao se registra por fora: seriam dois envios da mesma
    reservada = conn.execute("SELECT 1 FROM medicao_planilha_envios WHERE planilha_id=? AND envio_id IS NULL "
                             "AND envio_reservado_em IS NOT NULL", (vigente["id"],)).fetchone()
    if reservada is not None:
        raise ValueError(f"A versão {vigente['versao']} da planilha/carta está sendo enviada pelo sistema: aguarde o "
                         "envio terminar (ou libere o envio preso) antes de registrar o envio por fora")
    if m["estado"] == "planilha_enviada" and m["planilha_enviada_em"] and data.isoformat() < m["planilha_enviada_em"]:
        raise ValueError(f"A data do envio da revisão é anterior ao primeiro envio ({_data_br(m['planilha_enviada_em'])})")
    return dict(m), dict(vigente)


def _linha_siga(conn, medicao_id: int):
    return conn.execute("SELECT id, numero_processo FROM medicao_protocolos WHERE medicao_id=? AND etapa='planilha'",
                        (medicao_id,)).fetchone()


def _gravar_numero_siga(conn, usuario_id: int, m: dict, numero: str) -> None:
    """Dentro da transacao do chamador. A 1a vez cria a linha da planilha/carta (etapa 'planilha') em
    `medicao_protocolos`, na data do envio; depois, corrige o numero na mesma linha, com o antes e o depois na
    auditoria (o mesmo do nº do SIGA do envio da nota por fora, `notas_envio.registrar_numero_orgao`)."""
    linha = _linha_siga(conn, m["id"])
    if linha is None:
        conn.execute("INSERT INTO medicao_protocolos (medicao_id, data, numero_processo, origem, etapa) "
                     "VALUES (?,?,?,'manual','planilha')", (m["id"], m["planilha_enviada_em"], numero))
        auditoria.registrar(conn, usuario_id, NUMERO_SIGA, "medicao", m["id"], None,
                            {"numero_processo": numero, "data": m["planilha_enviada_em"]})
        return
    if linha["numero_processo"] == numero:
        raise ValueError("Este número do SIGA já está registrado")
    conn.execute("UPDATE medicao_protocolos SET numero_processo=? WHERE id=?", (numero, linha["id"]))
    auditoria.registrar(conn, usuario_id, NUMERO_SIGA, "medicao", m["id"],
                        {"numero_processo": linha["numero_processo"]}, {"numero_processo": numero})


def registrar_numero_siga(conn, usuario_id: int, medicao_id: int, numero: str) -> None:
    """O nº do SIGA que o orgao devolve, nos dois caminhos do envio (sistema e por fora)."""
    numero = (numero or "").strip()
    if not numero:
        raise ValueError("Informe o número do SIGA")
    with db.mutacao(conn):
        m = conn.execute("SELECT * FROM medicoes WHERE id=?", (medicao_id,)).fetchone()
        if m["estado"] not in ESTADOS_NUMERO_SIGA or not m["planilha_enviada_em"]:
            raise ValueError(f"{nome_medicao(m['numero'], m['tipo'])} está {rotulo_estado(m['estado'])}: "
                             "o número do SIGA vem depois do envio da planilha/carta e antes do protocolo da nota")
        _gravar_numero_siga(conn, usuario_id, dict(m), numero)


def registrar_envio_externo(conn, usuario_id: int, medicao_id: int, dados: dict,
                            eml: tuple[str, bytes] | None = None) -> dict:
    """"Enviado por fora": data, meio, nº do protocolo (opcional; e' o nº do SIGA) e o .eml (opcional, com a mesma
    conferencia do envio da nota por fora). A 1a vez poe a medicao em `planilha_enviada` com origem `externo` e
    congela o pedido; uma revisao enviada por fora so' registra o envio dela (o pedido fica o da 1a enviada)."""
    from app import notas_envio       # import local: notas_envio importa protocolo, que importa medicoes
    conferir_envio_externo(conn, medicao_id, dados)
    if eml:
        if len(eml[1]) > notas_envio.TETO_EML:
            raise ValueError("Arquivo .eml acima de 25 MB")
        if not notas_envio._e_email(eml[1]):
            raise ValueError(notas_envio.NAO_E_EML)
    data = datetime.date.fromisoformat(dados["enviado_em"]).isoformat()     # "20260803" grava "2026-08-03"
    meio = dados["meio"].strip()
    protocolo_ = (dados.get("numero_protocolo") or "").strip() or None
    gravado: dict = {}
    try:
        with db.mutacao(conn):
            try:
                m, vigente = conferir_envio_externo(conn, medicao_id, dados)     # de novo, sob o lock
                rel = None
                if eml:     # depois das conferencias: a recusa nao deixa arquivo solto (mesmo de notas_envio)
                    ja_existia = (arquivos.pasta("evidencias") / f"{arquivos.sha_de(eml[1])}.eml").exists()
                    rel, sha = arquivos.gravar_bytes("evidencias", eml[1], "eml")
                    gravado.update(rel=rel, novo=not ja_existia)
                    conn.execute("INSERT OR IGNORE INTO medicao_documentos (medicao_id, fonte, tipo_doc, nome, "
                                 "item_id, arquivo, sha256, tamanho) VALUES (?,'operacao','evidencia_orgao',?,?,?,?,?)",
                                 (medicao_id, (eml[0] or "envio.eml")[-200:], sha, rel, sha, len(eml[1])))
                antes = None
                if m["estado"] == "planilha_gerada":
                    antes = {k: m[k] for k in ("estado", "planilha_enviada_em", "planilha_envio_origem")}
                    # o pedido congela pelo estado, como no envio pelo sistema; `congelada` e' do protocolo da nota
                    # (ele tambem congela o valor original do contrato)
                    cur = conn.execute(
                        "UPDATE medicoes SET estado='planilha_enviada', planilha_enviada_em=?, "
                        "planilha_envio_origem='externo' WHERE id=? AND estado='planilha_gerada'",
                        (data, medicao_id))
                    db.exigir_uma_linha(cur, "Estado da medição mudou concorrentemente; tente novamente")
                    m = dict(conn.execute("SELECT * FROM medicoes WHERE id=?", (medicao_id,)).fetchone())
                    # issue #590: o pedido do reajuste que nasceu com esta planilha/carta congela junto
                    congelar_reajuste_do_envio(conn, usuario_id, m, data, "externo")
                auditoria.registrar(conn, usuario_id, ENVIO, "medicao", medicao_id, antes, {
                    "estado": "planilha_enviada", "origem": "externo", "versao": vigente["versao"],
                    "planilha_id": vigente["id"], "enviado_em": data, "meio": meio,
                    "numero_protocolo": protocolo_, "eml": rel})
                # o nº do protocolo so' vira o nº do SIGA quando ainda nao ha' um: o da revisao fica so' no evento do
                # envio (corrigir o nº gravado e' pela rota do nº do SIGA)
                if protocolo_ and _linha_siga(conn, medicao_id) is None:
                    _gravar_numero_siga(conn, usuario_id, m, protocolo_)
            except BaseException:
                if gravado.get("novo"):         # ainda sob o lock: o arquivo que ESTE registro criou sai
                    try:
                        arquivos.caminho_seguro(gravado["rel"]).unlink(missing_ok=True)
                        gravado["novo"] = False
                    except Exception:
                        pass
                raise
    except BaseException:
        if gravado.get("novo"):                 # falha no proprio COMMIT
            notas_envio._remover_eml_sem_registro(conn, gravado["rel"])
        raise
    return {"medicao_id": medicao_id, "estado": "planilha_enviada", "versao": vigente["versao"]}


def eventos_geracao(conn, medicao_ids: list[int], out: dict[int, list[dict]]) -> None:
    """Linha do tempo (#568): um evento por versao da planilha/carta gerada (a 1a e as revisoes), na hora do registro."""
    for i in range(0, len(medicao_ids), LOTE_AUDITORIA):
        lote = [str(x) for x in medicao_ids[i:i + LOTE_AUDITORIA]]
        for r in conn.execute(
                "SELECT a.entidade_id, a.depois, a.criado_em, u.nome FROM audit_log a "
                "LEFT JOIN usuarios u ON u.id=a.usuario_id "
                f"WHERE a.entidade='medicao' AND a.acao='medicao.planilha' AND a.entidade_id IN ({','.join('?' * len(lote))}) "
                "ORDER BY a.id", lote):
            d = _json_dict(r["depois"]) or {}
            versao = d.get("versao")
            if not isinstance(versao, int):
                versao = 1
            texto = "Planilha/carta gerada" if versao == 1 else f"Versão {versao} da planilha/carta gerada"
            if d.get("motivo"):
                texto += f" (motivo: {d['motivo']})"
            # so' o dia (de Cuiaba), como os outros marcos do envio: com hora, o "enviada por fora" do mesmo dia
            # (so' data) ia para antes da geracao na ordenacao por texto
            dia = tempo.para_local(datetime.datetime.fromisoformat(r["criado_em"])).date().isoformat()
            out[int(r["entidade_id"])].append({"data": dia,
                                               "texto": f"{texto} por {r['nome']}" if r["nome"]
                                               else f"{texto} pelo sistema"})


def eventos_envio(conn, medicao_ids: list[int], out: dict[int, list[dict]]) -> None:
    """Linha do tempo: um evento por envio da planilha/carta, na data do envio (como a assinatura)."""
    for i in range(0, len(medicao_ids), LOTE_AUDITORIA):
        lote = [str(x) for x in medicao_ids[i:i + LOTE_AUDITORIA]]
        for r in conn.execute(
                "SELECT a.entidade_id, a.depois, u.nome FROM audit_log a LEFT JOIN usuarios u ON u.id=a.usuario_id "
                f"WHERE a.entidade='medicao' AND a.acao=? AND a.entidade_id IN ({','.join('?' * len(lote))}) "
                "ORDER BY a.id", (ENVIO, *lote)):
            d = _json_dict(r["depois"]) or {}
            envio = None
            if d.get("enviado_em") is None and isinstance(d.get("envio_id"), int):
                # envio pelo sistema (#282): a auditoria guarda o e-mail; data e assunto vem de `envios`
                envio = conn.execute("SELECT enviado_em, assunto FROM envios WHERE id=?", (d["envio_id"],)).fetchone()
            try:
                versao = int(d.get("versao") or 1)
                if envio:
                    data = tempo.iso_utc(envio["enviado_em"])
                    dia = tempo.para_local(datetime.datetime.fromisoformat(envio["enviado_em"])).date().isoformat()
                else:
                    data = dia = datetime.date.fromisoformat(d["enviado_em"]).isoformat()
            except (ValueError, TypeError, KeyError):
                continue
            qual = "Planilha/carta" if versao == 1 else f"Versão {versao} da planilha/carta"
            como = "por fora" if d.get("origem") == "externo" else "pelo sistema"
            detalhe = ", ".join(x for x in (d.get("meio"), d.get("numero_protocolo") and
                                            f"protocolo {d['numero_protocolo']}",
                                            envio and f"assunto: {envio['assunto']}") if x)
            texto = f"{qual} enviada {como} em {_data_br(dia)}" + (f" ({detalhe})" if detalhe else "")
            out[int(r["entidade_id"])].append({"data": data, "texto": f"{texto} por {r['nome']}" if r["nome"]
                                               else f"{texto} pelo sistema"})
