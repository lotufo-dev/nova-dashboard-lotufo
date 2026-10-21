"""Planilha/carta de medicao (issue #281; spec 2026-10-20 §2.1, passo 1; D3, D6).

Cada registro e' uma versao de `medicao_planilhas` (evento append-only, migracao 042); a 1a poe a medicao em
`planilha_gerada`, as seguintes (Rev01, Rev02...) exigem motivo. O pedido vai para `valor_protocolado_centavos`
(o "pedido" da spec) enquanto a planilha nao foi enviada; depois do envio o pedido congelado e' o da versao
enviada, e a revisao so' acrescenta a versao. So' total e periodo (D3): a planilha vai anexada.

Modulo proprio, ao lado de `medicoes.py`: o boletim, a assinatura e a lista em andamento (issues irmas) mexem la'.
"""
import datetime

from app import auditoria, contratos, db, espelho, tempo
from app.medicoes import _data_br, nome_medicao, rotulo_estado

TIPOS = ("execucao", "projeto")
ESTADOS_REVISAO = ("planilha_gerada", "planilha_enviada")
FORA_DO_ACUMULADO = ("prevista", "cancelada", "desistida")


def _mes_seguinte(competencia: str) -> str:
    ano, mes = int(competencia[:4]), int(competencia[5:7])
    return f"{ano + mes // 12}-{mes % 12 + 1:02d}"


def _mes_br(competencia: str) -> str:
    return f"{competencia[5:7]}/{competencia[:4]}"


def acumulado_anterior(conn, contrato_id: int, tipo: str, numero: int) -> int:
    """Soma das medicoes do mesmo tipo com numero menor: o aprovado (atestado) de cada uma, senao o pedido
    (protocolado). Prevista, cancelada e desistida nao contam. Soma em Python: o SUM do SQLite e' int64 e
    estoura com valores que cabem um a um na coluna (mesmo motivo de paineis.saldo)."""
    return sum(r["v"] for r in conn.execute(
        "SELECT COALESCE(valor_atestado_centavos, valor_protocolado_centavos, 0) AS v FROM medicoes "
        f"WHERE contrato_id=? AND tipo=? AND numero<? AND estado NOT IN ({','.join('?' * len(FORA_DO_ACUMULADO))})",
        (contrato_id, tipo, numero, *FORA_DO_ACUMULADO)))


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


def _saldo(conn, contrato_id: int, acumulado: int, pedido: int | None) -> dict:
    """saldo = vigente − acumulado anterior (e − pedido, no `saldo_apos_pedido`). Difere de paineis.saldo de
    proposito: o acumulado da planilha/carta conta o pedido ainda nao protocolado das medicoes anteriores (spec
    §2.1 passo 1, "soma dos aprovados, senao pedidos"), e o painel so' o que ja' foi protocolado."""
    vigente = contratos.vigente(conn, contrato_id)["valor_vigente_centavos"]
    return {"vigente_centavos": vigente, "acumulado_anterior_centavos": acumulado,
            "saldo_centavos": vigente - acumulado,
            "saldo_apos_pedido_centavos": None if pedido is None else vigente - acumulado - pedido}


def sugestao(conn, contrato_id: int, tipo: str = "execucao") -> dict:
    """Nº (ultimo + 1; o do orgao tambem, onde ja' difere, D6), competencia (a da 1a prevista, senao o mes
    seguinte ao da ultima, senao o mes corrente), periodo (o mes civil da competencia), acumulado e saldo."""
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
            "periodo_inicio": inicio, "periodo_fim": fim, **_saldo(conn, contrato_id, acumulado, None)}


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
    existe com o mesmo nº e tipo (so' pode ser uma prevista), ou None."""
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
        raise ValueError(f"{nome_medicao(numero, tipo)} já existe neste contrato e está "
                         f"{rotulo_estado(ja['estado'])}: para corrigir a planilha/carta, registre uma revisão")
    return ja


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
        ja = conferir_registro(conn, contrato_id, dados)
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
        saldo = _saldo(conn, contrato_id, acumulado, dados["valor_centavos"])
    return {"medicao_id": mid, "versao": 1, "estado": "planilha_gerada", "avisos": avisos_, **saldo}


def revisar(conn, usuario_id: int, medicao_id: int, dados: dict, anexos: dict) -> dict:
    """Revisao (Rev01, Rev02...): versao nova com motivo. Antes do envio, o pedido e o periodo da medicao passam a
    ser os da revisao; depois do envio ficam os da versao enviada (o pedido congela no envio, spec §2.1)."""
    motivo = (dados.get("motivo") or "").strip()
    with db.mutacao(conn):
        m = conferir_revisao(conn, medicao_id, dados)
        versao = conn.execute("SELECT MAX(versao) + 1 FROM medicao_planilhas WHERE medicao_id=?",
                              (medicao_id,)).fetchone()[0]
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
        saldo = _saldo(conn, m["contrato_id"], acumulado, dados["valor_centavos"])
    return {"medicao_id": medicao_id, "versao": versao, "estado": m["estado"], "avisos": avisos_, **saldo}


def versoes(conn, medicao_id: int) -> list[dict]:
    """Todas as versoes da planilha/carta, da 1a a vigente (a tela mostra todas, spec §2.1 Revisoes)."""
    return [dict(r) for r in conn.execute(
        "SELECT p.id, p.versao, p.periodo_inicio, p.periodo_fim, p.valor_pedido_centavos, "
        "p.acumulado_anterior_centavos, p.sha256, p.sha256_planilha, p.origem, p.motivo, p.criado_em, "
        "u.nome AS usuario FROM medicao_planilhas p LEFT JOIN usuarios u ON u.id=p.usuario_id "
        "WHERE p.medicao_id=? ORDER BY p.versao", (medicao_id,))]
