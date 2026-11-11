"""Correcao de medicoes existentes por arquivo YAML do cadastro (`cadastro corrigir-medicoes`).

A carga por CSV (`carga_medicoes`) cria medicoes e corrige competencia/aprovado; o que ela nao alcanca (medicao
cancelada por engano, tipo trocado, NF ligada na medicao errada, protocolo que faltou) se corrige aqui, operacao a
operacao, cada uma com a `fonte` (o documento que a justifica).

Regras:
- tudo numa transacao so': uma operacao invalida recusa o arquivo inteiro (CorrecaoRecusada, nada gravado);
- nada se apaga: vinculo de NF desfeito e' marcado (`desfeita_em`), estado e tipo mudam com antes/depois na auditoria;
- toda operacao feita grava `medicao.correcao_cadastro` na auditoria, com a fonte e a origem "correção de cadastro";
- rodar de novo o mesmo arquivo nao duplica: a operacao ja' aplicada sai como "já feito";
- o ensaio executa o arquivo inteiro na mesma transacao e a desfaz no fim: o relatorio e' o do que seria gravado.

Issue #638: `desconsiderar_nf` e `reconsiderar_nf` nao tem medicao; o alvo e' a nota. A nota desconsiderada continua
ativa no RM e vale, para a dashboard, como cancelada: `situacao` passa a 'cancelada' com a marca `desconsiderada_em`
(todo leitor de nota ativa ja' a deixa de fora, e a sincronizacao nao a devolve); o registro e' so' a auditoria.
"""
import datetime
import re
import sqlite3
from pathlib import Path

import yaml

from app import auditoria, db, dinheiro, medicoes
from app.cadastro_arquivos import slug

ORIGEM = "correção de cadastro"
REGRA_NF = "correcao_cadastro"
TIPOS = ("execucao", "projeto", "reajuste")
OPERACOES_DE_NOTA = ("desconsiderar_nf", "reconsiderar_nf")      # issue #638: sem medicao, o alvo e' a nota
OPERACOES = ("cancelar", "reabrir", "trocar_tipo", "desligar_nf", "ligar_nf", "protocolar", "estado", *OPERACOES_DE_NOTA)
ENCERRADAS = ("cancelada", "desistida")
# Campos que cada operacao aceita, alem de `operacao`, `fonte`, `medicao_id`, `obra`, `numero` e `tipo`
CAMPOS = {"cancelar": {"duplicata_de", "motivo"}, "reabrir": set(), "trocar_tipo": {"novo_tipo", "novo_numero"},
          "desligar_nf": {"nf", "coligada"}, "ligar_nf": {"nfs", "coligada", "forcar_centro", "parcial"},
          "protocolar": {"data", "processo", "oficio"}, "estado": {"novo", "motivo", "data", "processo", "oficio"},
          "desconsiderar_nf": {"nf", "coligada", "motivo", "substituida_por"},
          "reconsiderar_nf": {"nf", "coligada", "motivo"}}
CAMPOS_COMUNS = {"operacao", "fonte", "medicao_id", "obra", "numero", "tipo"}
CAMPOS_COMUNS_DE_NOTA = {"operacao", "fonte"}


class ArquivoInvalido(ValueError):
    """O arquivo nao se le como lista de operacoes: nada a relatar por operacao."""


class CorrecaoRecusada(ValueError):
    """Alguma operacao e' invalida: nada foi gravado. `relatorio` traz cada operacao com o erro."""

    def __init__(self, relatorio: dict):
        n = relatorio["erros"]
        super().__init__(f"{n} operação(ões) com erro; corrija o arquivo (rode com --ensaio para ver quais)")
        self.relatorio = relatorio


class _Desfazer(Exception):
    """Fim do ensaio (ou arquivo com erro): desfaz a transacao inteira."""


class _JaFeito(Exception):
    """A operacao ja' esta' aplicada no banco."""


def ler(caminho: Path) -> list[dict]:
    try:
        texto = caminho.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise ArquivoInvalido(f"não foi possível ler o arquivo {caminho.name} (salve em UTF-8)") from None
    try:
        dados = yaml.safe_load(texto)
    except yaml.YAMLError as e:
        linha = getattr(getattr(e, "problem_mark", None), "line", None)
        raise ArquivoInvalido("o arquivo não se lê como YAML" + (f" (linha {linha + 1})" if linha is not None else "")
                              ) from None
    if isinstance(dados, dict) and "operacoes" in dados:
        dados = dados["operacoes"]
    if not isinstance(dados, list) or not dados:
        raise ArquivoInvalido("o arquivo deve ser uma lista de operações (cada uma começando com `- operacao:`)")
    return dados


# ------------------------------------------------------------------ apoio

def _texto(op: dict, campo: str) -> str | None:
    v = op.get(campo)
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    return str(v).strip()


def _inteiro(op: dict, campo: str) -> int | None:
    v = op.get(campo)
    if v is None:
        return None
    if isinstance(v, bool) or not re.fullmatch(r"[0-9]{1,9}", str(v).strip()) or int(v) < 1:
        raise ValueError(f"{campo} inválido: {v!r}")
    return int(v)


def _booleano(op: dict, campo: str) -> bool:
    v = op.get(campo, False)
    if not isinstance(v, bool):
        raise ValueError(f"{campo} deve ser true ou false, não {v!r}")
    return v


def _data(op: dict, campo: str = "data") -> str | None:
    v = op.get(campo)
    if v is None:
        return None
    if isinstance(v, datetime.datetime):
        raise ValueError(f"{campo} sem hora (use AAAA-MM-DD)")
    if isinstance(v, datetime.date):
        return v.isoformat()
    try:
        return datetime.date.fromisoformat(str(v).strip()).isoformat()
    except ValueError:
        raise ValueError(f"{campo} inválida: {v!r} (use AAAA-MM-DD)") from None


def _tipo(op: dict, campo: str) -> str | None:
    v = _texto(op, campo)
    if v is None:
        return None
    v = {"execução": "execucao"}.get(v.lower(), v.lower())
    if v not in TIPOS:
        raise ValueError(f"{campo} desconhecido: {op.get(campo)!r} (use execucao, projeto ou reajuste)")
    return v


def _medicao_por_id(conn, mid: int):
    return conn.execute("SELECT * FROM medicoes WHERE id=?", (mid,)).fetchone()


def _contrato(conn, obra: str) -> int:
    alvo = slug(obra)
    achados = [r["id"] for r in conn.execute("SELECT id, nome_curto FROM contratos WHERE nome_curto IS NOT NULL")
               if slug(r["nome_curto"]) == alvo]
    if len(achados) != 1:
        raise ValueError(f"obra {obra!r} não encontrada no banco" if not achados
                         else f"obra {obra!r} corresponde a mais de um contrato")
    return achados[0]


def _por_chave(conn, contrato_id: int, numero: int, tipo: str):
    return conn.execute("SELECT * FROM medicoes WHERE contrato_id=? AND numero=? AND tipo=?",
                        (contrato_id, numero, tipo)).fetchone()


def _resolver(conn, op: dict):
    """A medicao da operacao: `medicao_id`, ou `obra` + `numero` + `tipo`. Na troca de tipo por chave, a chave
    antiga que sumiu e a nova que existe e' operacao ja' aplicada (rodar de novo nao e' erro)."""
    if op.get("medicao_id") is not None:
        mid = _inteiro(op, "medicao_id")
        m = _medicao_por_id(conn, mid)
        if m is None:
            raise ValueError(f"medição id {mid} não existe")
        return m
    obra, numero, tipo = _texto(op, "obra"), _inteiro(op, "numero"), _tipo(op, "tipo")
    if not (obra and numero and tipo):
        raise ValueError("diga a medição: medicao_id, ou obra + numero + tipo")
    cid = _contrato(conn, obra)
    m = _por_chave(conn, cid, numero, tipo)
    if m is None and op.get("operacao") == "trocar_tipo":
        novo = _por_chave(conn, cid, _inteiro(op, "novo_numero") or numero, _tipo(op, "novo_tipo") or tipo)
        if novo is not None:
            raise _JaFeito(f"já trocada: {_rotulo(conn, novo)}")
    if m is None:
        raise ValueError(f"não há {medicoes.nome_medicao(numero, tipo).lower()} na obra {obra}")
    return m


def _rotulo(conn, m) -> str:
    obra = conn.execute("SELECT COALESCE(nome_curto, numero_instrumento) FROM contratos WHERE id=?",
                        (m["contrato_id"],)).fetchone()[0]
    return f"{obra}: {medicoes.nome_medicao(m['numero'], m['tipo']).lower()} (id {m['id']})"


def _coligada(conn, m, op: dict) -> int:
    col = _inteiro(op, "coligada")
    if col is not None:
        return col
    col = conn.execute("SELECT e.coligada_rm FROM contratos c JOIN entidades e ON e.id=COALESCE(c.entidade_id, 1) "
                       "WHERE c.id=?", (m["contrato_id"],)).fetchone()[0]
    if col is None:
        raise ValueError("a empresa do contrato não tem coligada no RM: diga a coligada")
    return col


def _notas(conn, coligada: int, nf: str, so_ativas: bool) -> list:
    numero = int(nf) if nf.isdigit() and len(nf) <= 18 else None
    return conn.execute("SELECT * FROM notas_fiscais WHERE coligada=? AND (numero=? OR numero_int=?)"
                        + (" AND situacao='ativa'" if so_ativas else ""), (coligada, nf, numero)).fetchall()


def _nfs_ativas(conn, mid: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT a.id, a.nota_id, n.numero, n.coligada, n.serie, n.idmov, n.valor_centavos FROM nf_alocacoes a "
        "JOIN notas_fiscais n ON n.id=a.nota_id WHERE a.medicao_id=? AND a.desfeita_em IS NULL ORDER BY a.id", (mid,))]


def _fmt_nf(n: dict) -> str:
    """Gate Sol da #565: numero repetido no RM se distingue pela serie e pelo idmov, que o ensaio mostra."""
    ident = (f", série {n['serie']}" if n["serie"] not in (None, "") else "") \
        + (f", idmov {n['idmov']}" if n["idmov"] is not None else ", sem idmov")
    return f"NF {n['numero']}{ident} ({dinheiro.format_brl(n['valor_centavos'])})"


def _ident_nf(n: dict) -> dict:
    return {"nota_id": n["nota_id"], "numero": n["numero"], "coligada": n["coligada"], "serie": n["serie"],
            "idmov": n["idmov"]}


def _foto(conn, mid: int) -> dict:
    m = _medicao_por_id(conn, mid)
    ativas = _nfs_ativas(conn, mid)
    return {"estado": m["estado"], "numero": m["numero"], "tipo": m["tipo"], "congelada": m["congelada"],
            "motivo": m["motivo_represamento"],
            "nfs": [f"{n['numero']}/{n['coligada']}" for n in ativas],
            "notas": [_ident_nf(n) for n in ativas],
            "protocolos": [r[0] for r in conn.execute("SELECT data FROM medicao_protocolos WHERE medicao_id=? "
                                                      "AND etapa='nota' ORDER BY data, id", (mid,))]}


def _desfazer_vinculo(conn, usuario_id: int, mid: int, alocacao: dict, motivo: str) -> None:
    """Marca o vinculo como desfeito a' mao (o casador do RM nao volta a casar a nota sozinho). Nunca DELETE."""
    from app import sincronizacao_rm   # import local: sincronizacao_rm importa medicoes
    texto = sincronizacao_rm.MOTIVO_A_MAO + motivo
    cur = conn.execute("UPDATE nf_alocacoes SET desfeita_em=datetime('now'), motivo_desfazer=? "
                       "WHERE id=? AND desfeita_em IS NULL", (texto, alocacao["id"]))
    db.exigir_uma_linha(cur, f"O vínculo da NF {alocacao['numero']} mudou concorrentemente")
    auditoria.registrar(conn, usuario_id, "nf.desalocar", "medicao", mid,
                        {"alocacao_id": alocacao["id"], "nota_id": alocacao["nota_id"], "nf": alocacao["numero"],
                         "coligada": alocacao["coligada"], "valor_centavos": alocacao["valor_centavos"]},
                        {"motivo": texto, "origem": ORIGEM})


def _recebimentos(conn, mid: int) -> str:
    from app import sincronizacao_rm   # import local: sincronizacao_rm importa medicoes
    sincronizacao_rm._recebimentos(conn, [mid])
    return "; recebida (baixa no RM)" if _medicao_por_id(conn, mid)["estado"] == "recebida" else ""


# ------------------------------------------------------------------ operacoes
# Cada uma devolve (estado novo, detalhes) ou levanta _JaFeito / ValueError.

def _verdadeira(conn, m, op):
    """Issue #565: a medicao de que esta e' duplicata (`duplicata_de`), conferida: existe, e' outra, do mesmo
    contrato e nao encerrada. Ela nao muda; so' justifica o cancelamento."""
    vid = _inteiro(op, "duplicata_de")
    if vid == m["id"]:
        raise ValueError("duplicata_de aponta para ela mesma")
    v = _medicao_por_id(conn, vid)
    if v is None:
        raise ValueError(f"duplicata_de: medição id {vid} não existe")
    if v["contrato_id"] != m["contrato_id"]:
        raise ValueError(f"duplicata_de: a medição id {vid} é de outro contrato")
    if v["estado"] in ENCERRADAS:
        raise ValueError(f"duplicata_de: a medição id {vid} está {medicoes.rotulo_estado(v['estado'])}; "
                         "a verdadeira tem de estar ativa")
    return v


def _cancelar(conn, uid, m, op, fonte):
    duplicata = op.get("duplicata_de") is not None
    motivo = _texto(op, "motivo")
    if motivo is not None and not duplicata:
        raise ValueError("motivo só vale com duplicata_de (no cancelamento comum, o motivo é a fonte)")
    if m["estado"] == "cancelada":
        raise _JaFeito("já cancelada")
    # Issue #565: a duplicata da carga antiga pode estar recebida (recebida -> cancelada nao e' transicao da
    # tela); com `duplicata_de` e motivo, a correcao de cadastro a cancela e desliga as notas
    recebida_duplicata = duplicata and m["estado"] == "recebida"
    if "cancelada" not in medicoes.TRANSICOES.get(m["estado"], set()) and not recebida_duplicata:
        raise ValueError(f"medição {medicoes.rotulo_estado(m['estado'])} não se cancela "
                         f"(transição inválida: {m['estado']} → cancelada)"
                         + ("; se é duplicata de outra, diga duplicata_de e motivo"
                            if m["estado"] == "recebida" else ""))
    detalhes, texto = [], fonte
    if duplicata:
        if motivo is None:
            raise ValueError("cancelar duplicata exige motivo: diga o motivo (motivo: ...)")
        v = _verdadeira(conn, m, op)
        rotulo_v = f"{medicoes.nome_medicao(v['numero'], v['tipo']).lower()} (id {v['id']})"
        texto = f"Duplicata da {rotulo_v}: {motivo}"
        detalhes.append(f"duplicata da {rotulo_v}, que não muda")
        # revisao da #565: a verdadeira de outro tipo, ou ainda nao recebida quando a duplicata estava, merece olhar
        if v["tipo"] != m["tipo"]:
            detalhes.append(f"AVISO: a verdadeira é de {medicoes.ROTULO_TIPO.get(v['tipo'], v['tipo'])} e esta de "
                            f"{medicoes.ROTULO_TIPO.get(m['tipo'], m['tipo'])}")
        if recebida_duplicata and v["estado"] != "recebida":
            detalhes.append(f"AVISO: a verdadeira está {medicoes.rotulo_estado(v['estado'])}; o recebido desta sai "
                            "dos totais até a nota ser ligada à verdadeira (ligar_nf)")
        op["_duplicata"] = {"duplicata_de": v["id"], "motivo_cancelamento": motivo}
    desligadas = _nfs_ativas(conn, m["id"])
    for a in desligadas:
        _desfazer_vinculo(conn, uid, m["id"], a, f"medição cancelada ({texto}; {fonte})" if duplicata
                          else f"medição cancelada ({fonte})")
        detalhes.append(f"{_fmt_nf(a)} desligada")
    if duplicata and desligadas:
        # Revisor da #565: a nota desligada fica "desfeita à mão" e o casador do RM nao a liga sozinho; se a
        # verdadeira nao tem nota que cubra o valor dela (qualquer que seja o estado), a nota paga ficaria sem medicao
        # Conta por coligada (rodada 2 do revisor): em consorcio a medicao tem a fatura do consorcio (valor cheio,
        # coligada do consorcio) e a NF da Lotufo (a cota, coligada da Lotufo); uma nao cobre a outra
        from app import contratos, notas   # import local: notas importa medicoes
        lotufo = notas._coligada_lotufo(conn)
        pct = conn.execute("SELECT percentual_direito_bp FROM contratos WHERE id=?", (v["contrato_id"],)).fetchone()[0]
        notas_v = _nfs_ativas(conn, v["id"])
        valor_v = v["valor_atestado_centavos"] if v["valor_atestado_centavos"] is not None \
            else v["valor_protocolado_centavos"]
        for col in dict.fromkeys(a["coligada"] for a in desligadas):
            da_col = [n for n in notas_v if n["coligada"] == col]
            alvo = contratos.cota(valor_v, pct) if col == lotufo else valor_v
            if da_col and (alvo is None or sum(n["valor_centavos"] for n in da_col) >= alvo):
                continue
            falta = (f"tem NF da coligada {col} que não cobre o valor dela" if da_col
                     else f"não tem NF ligada da coligada {col}")
            detalhes.append(f"AVISO: a verdadeira {falta}; o casador do RM não religa a nota desligada: ligue "
                            + ", ".join(_fmt_nf(a) for a in desligadas if a["coligada"] == col)
                            + " à verdadeira (ligar_nf)")
    if recebida_duplicata:
        cur = conn.execute("UPDATE medicoes SET estado='cancelada', motivo_represamento=? WHERE id=? AND estado=?",
                           (texto, m["id"], m["estado"]))
        db.exigir_uma_linha(cur, "Estado da medição mudou concorrentemente; tente novamente")
        auditoria.registrar(conn, uid, "medicao.estado", "medicao", m["id"],
                            {"estado": m["estado"], "motivo": m["motivo_represamento"]},
                            {"estado": "cancelada", "motivo": texto, "origem": ORIGEM, "fonte": fonte,
                             "duplicata_de": op["_duplicata"]["duplicata_de"]})
    else:
        medicoes.mudar_estado(conn, uid, m["id"], "cancelada", texto, origem=ORIGEM)
    return detalhes


def _reabrir(conn, uid, m, op, fonte):
    if m["estado"] not in ENCERRADAS:
        if m["estado"] in ("protocolada", "nf_emitida", "recebida"):
            raise _JaFeito(f"já {medicoes.rotulo_estado(m['estado'])}")
        raise ValueError(f"só se reabre medição cancelada ou desistida (esta está "
                         f"{medicoes.rotulo_estado(m['estado'])})")
    motivo = f"Reaberta ({ORIGEM}): {fonte}"
    cur = conn.execute("UPDATE medicoes SET estado='protocolada', congelada=1, motivo_represamento=? "
                       "WHERE id=? AND estado=?", (motivo, m["id"], m["estado"]))
    db.exigir_uma_linha(cur, "Estado da medição mudou concorrentemente; tente novamente")
    auditoria.registrar(conn, uid, "medicao.estado", "medicao", m["id"],
                        {"estado": m["estado"], "motivo": m["motivo_represamento"]},
                        {"estado": "protocolada", "motivo": motivo, "origem": ORIGEM, "fonte": fonte})
    detalhes = []
    if not conn.execute("SELECT 1 FROM medicao_protocolos WHERE medicao_id=? AND etapa='nota'", (m["id"],)).fetchone():
        detalhes.append("AVISO: sem protocolo da nota registrado (use a operação protocolar)")
    if not _nfs_ativas(conn, m["id"]):
        detalhes.append("AVISO: sem NF ligada (use a operação ligar_nf)")
    else:
        recebida = _recebimentos(conn, m["id"])
        if recebida:
            detalhes.append(recebida.lstrip("; "))
    return detalhes


def _trocar_tipo(conn, uid, m, op, fonte):
    novo_tipo = _tipo(op, "novo_tipo") or m["tipo"]
    novo_numero = _inteiro(op, "novo_numero") or m["numero"]
    if op.get("novo_tipo") is None and op.get("novo_numero") is None:
        raise ValueError("diga novo_tipo (e, se mudar, novo_numero)")
    if (novo_tipo, novo_numero) == (m["tipo"], m["numero"]):
        raise _JaFeito(f"já é {medicoes.nome_medicao(novo_numero, novo_tipo).lower()}")
    outra = conn.execute("SELECT * FROM medicoes WHERE contrato_id=? AND numero=? AND tipo=? AND id<>?",
                         (m["contrato_id"], novo_numero, novo_tipo, m["id"])).fetchone()
    if outra is not None:
        raise ValueError(f"já existe {medicoes.nome_medicao(novo_numero, novo_tipo).lower()} neste contrato "
                         f"(id {outra['id']}, {medicoes.rotulo_estado(outra['estado'])})"
                         + ("; o banco não aceita duas com o mesmo nº e tipo, mesmo cancelada"
                            if outra["estado"] in ENCERRADAS else ""))
    cur = conn.execute("UPDATE medicoes SET tipo=?, numero=? WHERE id=? AND tipo=? AND numero=?",
                       (novo_tipo, novo_numero, m["id"], m["tipo"], m["numero"]))
    db.exigir_uma_linha(cur, "Medição alterada concorrentemente; tente novamente")
    auditoria.registrar(conn, uid, "medicao.tipo", "medicao", m["id"], {"tipo": m["tipo"], "numero": m["numero"]},
                        {"tipo": novo_tipo, "numero": novo_numero, "origem": ORIGEM, "fonte": fonte})
    return [f"{medicoes.nome_medicao(m['numero'], m['tipo'])} → {medicoes.nome_medicao(novo_numero, novo_tipo).lower()}"]


def _desligar_nf(conn, uid, m, op, fonte):
    nf = _texto(op, "nf")
    if nf is None:
        raise ValueError("diga a nf")
    coligada = _coligada(conn, m, op)
    ids = {n["id"] for n in _notas(conn, coligada, nf, so_ativas=False)}
    if not ids:
        raise ValueError(f"NF {nf} não encontrada na coligada {coligada}")
    ativas = [a for a in _nfs_ativas(conn, m["id"]) if a["nota_id"] in ids]
    if not ativas:
        if conn.execute(f"SELECT 1 FROM nf_alocacoes WHERE medicao_id=? AND desfeita_em IS NOT NULL AND nota_id IN "
                        f"({','.join('?' * len(ids))})", (m["id"], *ids)).fetchone():
            raise _JaFeito(f"NF {nf} já desligada")
        raise ValueError(f"NF {nf} não está ligada a esta medição")
    detalhes = []
    for a in ativas:
        _desfazer_vinculo(conn, uid, m["id"], a, fonte)
        detalhes.append(f"{_fmt_nf(a)} desligada")
    if m["estado"] == "recebida":
        detalhes.append("AVISO: a medição continua recebida")
    return detalhes


def _conferir_centro(conn, m, nota, forcar: bool, mapa) -> str | None:
    """A mesma conferencia de `carga_medicoes._vincular_nfs`: a nota e' desta obra pelo centro de custo (o atual
    ou um anterior). Devolve o problema; com `forcar_centro`, o problema vira registro na auditoria."""
    _, por_centro, por_coligada = mapa
    cid, coligada = m["contrato_id"], nota["coligada"]
    centros = {cc for (col, cc), donos in por_centro.items() if col == coligada and cid in donos}
    cc = (nota["centro_custo"] or "").strip()
    donos = por_centro.get((coligada, cc), []) if cc else []
    problema = None
    if not centros and por_coligada.get(coligada) != [cid]:
        problema = "o contrato não tem centro de custo do RM no cadastro"
    elif centros and donos != [cid]:
        problema = ("é de outra obra no RM, pelo centro de custo" if cid not in donos
                    else "tem centro de custo de mais de uma obra no cadastro")
    elif not centros and donos:
        problema = "é de outra obra no RM, pelo centro de custo"
    if problema and not forcar:
        raise ValueError(f"NF {nota['numero']} {problema} (se o documento confirma, use forcar_centro: true)")
    return problema


def _descrever_nota(n) -> str:
    serie = f"série {n['serie']}" if n["serie"] not in (None, "") else "sem série"
    ident = f"idmov {n['idmov']}" if n["idmov"] is not None else "sem idmov (lida do PDF)"
    return f"{ident} ({serie}, emissão {n['emissao'] or '?'}, {dinheiro.format_brl(n['valor_centavos'])})"


def _mesma_serie(gravada, pedida: str) -> bool:
    """A serie do RM ('01') e a do YAML (`serie: 1`, que o YAML le como numero) sao a mesma."""
    g = (gravada or "").strip()
    return g == pedida or (g.isdigit() and pedida.isdigit() and int(g) == int(pedida))


def _ler_referencia(ref) -> tuple:
    """`(idmov, numero, serie)` de uma referencia de nota: o número sozinho, `{idmov: N}` ou `{numero: N, serie: S}`."""
    if isinstance(ref, dict):
        chaves, forma = set(ref), "{idmov: N} ou {numero: N, serie: S}"
        if not chaves or chaves - {"idmov", "numero", "serie"}:
            raise ValueError(f"nota {ref!r} inválida: os campos são idmov, numero e serie ({forma})")
        if "idmov" in chaves and chaves != {"idmov"}:
            raise ValueError(f"nota {ref!r} inválida: diga idmov ou numero + serie, não os dois ({forma})")
        if "idmov" in chaves:
            idmov = _inteiro(ref, "idmov")
            if idmov is None:           # `{idmov: }` no YAML e' nulo: sem isto seguiria pelo caminho do numero
                raise ValueError(f"nota {ref!r} inválida: falta o idmov")
            return idmov, None, None
        nf, serie = _texto(ref, "numero"), _texto(ref, "serie")
        if nf is None:
            raise ValueError(f"nota {ref!r} inválida: falta o numero")
        return None, nf, serie
    if isinstance(ref, (str, int)) and not isinstance(ref, bool):
        return None, str(ref).strip(), None
    raise ValueError(f"nota {ref!r} inválida: use o número, {{idmov: N}} ou {{numero: N, serie: S}}")


def _desconsiderada(n) -> bool:
    """A nota tem a marca da #638. O ensaio nao migra: no banco de antes da migracao 081 a coluna nao existe, nenhuma
    nota esta' desconsiderada e o `ligar_nf` responde como sempre respondeu."""
    return "desconsiderada_em" in n.keys() and n["desconsiderada_em"] is not None


def _nota_da_referencia(conn, coligada: int, ref):
    """Issue #565: a nota de um item de `nfs`. O número sozinho (`501`) vale quando é único na coligada; quando se
    repete no RM (outra série, outro movimento), o item diz qual: `{idmov: N}` ou `{numero: N, serie: S}`."""
    idmov, nf, serie = _ler_referencia(ref)
    # issue #638: a nota desconsiderada nao recebe medicao, e a recusa diz por que (ela nao esta' "ativa")
    recusa = "foi desconsiderada pela correção de cadastro e não recebe medição (reconsiderar_nf a devolve)"
    if idmov is not None:
        todas = conn.execute("SELECT * FROM notas_fiscais WHERE coligada=? AND idmov=?", (coligada, idmov)).fetchall()
        achadas = [n for n in todas if n["situacao"] == "ativa"]
        if not achadas:
            if any(_desconsiderada(n) for n in todas):
                raise ValueError(f"NF idmov {idmov} {recusa}")
            raise ValueError(f"NF idmov {idmov} não encontrada (ativa) na coligada {coligada}")
        return achadas[0]
    todas = [n for n in _notas(conn, coligada, nf, so_ativas=False)
             if serie is None or _mesma_serie(n["serie"], serie)]
    achadas = [n for n in todas if n["situacao"] == "ativa"]
    rotulo = f"NF {nf}" + (f" série {serie}" if serie is not None else "")
    if not achadas:
        if any(_desconsiderada(n) for n in todas):
            raise ValueError(f"{rotulo} {recusa}")
        raise ValueError(f"{rotulo} não encontrada (ativa) na coligada {coligada}")
    if len(achadas) > 1:
        raise ValueError(f"{rotulo} é ambígua: {len(achadas)} notas ativas com esse número na coligada {coligada} ("
                         + "; ".join(_descrever_nota(n) for n in achadas)
                         + "); diga qual com {idmov: N} ou {numero: N, serie: S}")
    return achadas[0]


def _ligar_nf(conn, uid, m, op, fonte):
    from app import diretoria, sincronizacao_rm   # import local: ambos importam medicoes
    nfs = op.get("nfs")
    if isinstance(nfs, (str, int, dict)):
        nfs = [nfs]
    if not isinstance(nfs, list) or not nfs:
        raise ValueError("diga as nfs (lista: nfs: [101, 102])")
    forcar, parcial = _booleano(op, "forcar_centro"), _booleano(op, "parcial")
    coligada = _coligada(conn, m, op)
    ligadas = {a["nota_id"] for a in _nfs_ativas(conn, m["id"])}
    mapa = diretoria._mapa_contratos(conn)
    novas, ja = [], []
    for ref in nfs:
        nota = _nota_da_referencia(conn, coligada, ref)
        nf = nota["numero"]
        if nota["id"] in ligadas:
            ja.append(nota)
            continue
        if any(n["id"] == nota["id"] for n, _ in novas):
            raise ValueError(f"NF {nf} repetida na operação")
        outra = conn.execute("SELECT m.id, m.numero, m.tipo FROM nf_alocacoes a JOIN medicoes m ON m.id=a.medicao_id "
                             "WHERE a.nota_id=? AND a.desfeita_em IS NULL", (nota["id"],)).fetchone()
        if outra is not None:
            raise ValueError(f"NF {nf} já está na {medicoes.nome_medicao(outra['numero'], outra['tipo']).lower()} "
                             f"(id {outra['id']}): desligue-a lá antes (desligar_nf)")
        novas.append((nota, _conferir_centro(conn, m, nota, forcar, mapa)))
    if not novas:
        raise _JaFeito("NF " + ", ".join(n["numero"] for n in ja) + " já ligada")
    # Recebida sem a nota ligada (paga, mas o vinculo faltou) recebe a NF: o estado fica, so' o elo com o RM entra
    if m["estado"] in ENCERRADAS:
        raise ValueError(f"medição {medicoes.rotulo_estado(m['estado'])} não recebe NF")
    valor = m["valor_atestado_centavos"] if m["valor_atestado_centavos"] is not None else m["valor_protocolado_centavos"]
    soma = sum(n["valor_centavos"] for n in _nfs_ativas(conn, m["id"]) if n["coligada"] == coligada) + sum(
        n["valor_centavos"] for n, _ in novas)
    cobre = valor is None or soma >= valor
    if not cobre and not parcial:
        raise ValueError(f"as notas somam {dinheiro.format_brl(soma)} e a medição vale {dinheiro.format_brl(valor)} "
                         "(se a medição foi faturada em mais notas e só estas vêm agora, use parcial: true)")
    detalhes = []
    for nota, problema in novas:
        sincronizacao_rm.alocar(conn, uid, nota["id"], m["id"], "manual", None, REGRA_NF, aceita_recebida=True)
        texto = f"{_fmt_nf(nota)} ligada"
        if problema:
            texto += f" (centro de custo forçado: {problema})"
        detalhes.append(texto)
    if m["estado"] == "recebida":
        detalhes[-1] += "; a medição já estava recebida"
    elif cobre:
        detalhes[-1] += _recebimentos(conn, m["id"])
    else:
        # Cobertura parcial nao fecha a medicao como recebida: a nota que falta ainda nao entrou (revisor da #259)
        detalhes.append(f"AVISO: parcial, as notas somam {dinheiro.format_brl(soma)} de {dinheiro.format_brl(valor)}; "
                        "não passa a recebida agora (a sincronização com o RM pode fechá-la quando os títulos destas notas forem "
                        "pagos)")
    op["_forcado"] = [{"nf": n["numero"], "problema": p} for n, p in novas if p]
    return detalhes


def _protocolar(conn, uid, m, op, fonte):
    data = _data(op)
    if data is None:
        raise ValueError("diga a data do protocolo (AAAA-MM-DD)")
    processo, oficio = _texto(op, "processo"), _texto(op, "oficio")
    if conn.execute("SELECT 1 FROM medicao_protocolos WHERE medicao_id=? AND etapa='nota' AND data=? "
                    "AND numero_processo IS ?", (m["id"], data, processo)).fetchone():
        raise _JaFeito(f"protocolo de {data} já registrado")
    atual = m["estado"]
    if atual in ENCERRADAS:
        raise ValueError(f"medição {atual} não recebe protocolo (reabra antes)")
    if atual in medicoes.ESTADOS_PROMOVIDOS_PELO_PROTOCOLO:
        cur = conn.execute("UPDATE medicoes SET estado='protocolada', congelada=1 WHERE id=? AND estado=?",
                           (m["id"], atual))
    elif atual in (*medicoes.ESTADOS_DE_NOVO_PROTOCOLO, "recebida"):
        # recebida: o protocolo que faltou no historico entra so' como registro; o estado fica
        cur = conn.execute("UPDATE medicoes SET congelada=1 WHERE id=? AND estado=?", (m["id"], atual))
    else:
        raise ValueError(f"medição {medicoes.rotulo_estado(atual)} não recebe protocolo")
    db.exigir_uma_linha(cur, "Estado da medição mudou concorrentemente; tente novamente")
    conn.execute("INSERT INTO medicao_protocolos (medicao_id, data, numero_oficio, numero_processo, origem, etapa) "
                 "VALUES (?,?,?,?,'manual','nota')", (m["id"], data, oficio, processo))
    auditoria.registrar(conn, uid, "medicao.protocolo", "medicao", m["id"], None,
                        {"data": data, "numero_oficio": oficio, "numero_processo": processo, "origem": "manual",
                         "etapa": "nota", "correcao": ORIGEM, "fonte": fonte})
    detalhes = [f"protocolo da nota em {data}" + (f", processo {processo}" if processo else "")]
    if atual in medicoes.ESTADOS_PROMOVIDOS_PELO_PROTOCOLO:
        detalhes[-1] += _recebimentos(conn, m["id"])
    return detalhes


def _estado(conn, uid, m, op, fonte):
    novo = _texto(op, "novo")
    if novo is None:
        raise ValueError("diga o novo estado (novo: ...)")
    if novo == m["estado"]:
        raise _JaFeito(f"já {medicoes.rotulo_estado(novo)}")
    if novo == "protocolada":
        if m["estado"] in ENCERRADAS:
            raise ValueError("medição encerrada volta pela operação reabrir")
        if _data(op) is None:
            raise ValueError("passar a protocolada é pelo protocolo: diga a data (ou use a operação protocolar)")
        return _protocolar(conn, uid, m, op, fonte)
    data = _data(op)
    if data is not None and novo not in medicoes.COLUNA_DATA:
        raise ValueError(f"o estado {novo} não tem data")
    medicoes.mudar_estado(conn, uid, m["id"], novo, _texto(op, "motivo") or fonte, data=data, origem=ORIGEM)
    return []


# ------------------------------------------------------------------ operacoes de nota (issue #638)

def _nota_da_operacao(conn, op: dict):
    """A nota de `desconsiderar_nf`/`reconsiderar_nf`: `nf` como no `ligar_nf` (número, `{idmov: N}` ou
    `{numero: N, serie: S}`), em qualquer situacao. Sem `coligada`, a nota e' procurada em todas: se o número (ou o
    idmov) existe em mais de uma, a operacao e' recusada com a lista, e nada e' escolhido por ela."""
    if op.get("nf") is None:
        raise ValueError("diga a nf (o número, {idmov: N} ou {numero: N, serie: S})")
    idmov, nf, serie = _ler_referencia(op["nf"])
    coligada = _inteiro(op, "coligada")
    onde, args = ("coligada=? AND ", (coligada,)) if coligada is not None else ("", ())
    if idmov is not None:
        achadas = conn.execute(f"SELECT * FROM notas_fiscais WHERE {onde}idmov=? ORDER BY id", (*args, idmov)).fetchall()
        rotulo = f"NF idmov {idmov}"
    else:
        numero = int(nf) if nf.isdigit() and len(nf) <= 18 else None
        achadas = [n for n in conn.execute(f"SELECT * FROM notas_fiscais WHERE {onde}(numero=? OR numero_int=?) "
                                           "ORDER BY id", (*args, nf, numero))
                   if serie is None or _mesma_serie(n["serie"], serie)]
        rotulo = f"NF {nf}" + (f" série {serie}" if serie is not None else "")
    if not achadas:
        raise ValueError(f"{rotulo} não encontrada" + (f" na coligada {coligada}" if coligada is not None else ""))
    if len(achadas) > 1:
        raise ValueError(f"{rotulo} é ambígua: {len(achadas)} notas ("
                         + "; ".join(f"coligada {n['coligada']}, {_descrever_nota(n)}" for n in achadas)
                         + "); diga qual com a coligada e {idmov: N} ou {numero: N, serie: S}")
    return achadas[0]


def _situacao_da_nota(n) -> str:
    return "desconsiderada" if n["desconsiderada_em"] is not None else n["situacao"]


def _registro_da_nota(n) -> dict:
    return {"numero": n["numero"], "coligada": n["coligada"], "serie": n["serie"], "idmov": n["idmov"],
            "emissao": n["emissao"], "valor_centavos": n["valor_centavos"]}


def _desconsiderar_nf(conn, uid, nota, op, fonte):
    from app import sincronizacao_rm   # import local: sincronizacao_rm importa medicoes
    motivo, substituta = _texto(op, "motivo"), _texto(op, "substituida_por")
    if motivo is None:
        raise ValueError("diga o motivo (motivo: ...)")
    if nota["desconsiderada_em"] is not None:
        raise _JaFeito("já desconsiderada")
    if nota["situacao"] != "ativa":
        raise ValueError(f"NF {nota['numero']} já está {nota['situacao']} no RM: não há o que desconsiderar")
    ligada = conn.execute("SELECT m.id, m.numero, m.tipo FROM nf_alocacoes a JOIN medicoes m ON m.id=a.medicao_id "
                          "WHERE a.nota_id=? AND a.desfeita_em IS NULL", (nota["id"],)).fetchone()
    if ligada is not None:
        raise ValueError(f"NF {nota['numero']} está ligada à {medicoes.nome_medicao(ligada['numero'], ligada['tipo']).lower()} "
                         f"(id {ligada['id']}): desligue-a antes (desligar_nf)")
    # dinheiro recebido nao some em silencio: qualquer baixa (com valor, ou baixa total sem valor) recusa
    marcas = ",".join("?" * len(sincronizacao_rm.STATUS_RECEBIDO))
    if conn.execute(f"SELECT 1 FROM baixas WHERE nota_id=? AND status_lan<>2 AND (status_lan IN ({marcas}) "
                    "OR COALESCE(valor_baixado_centavos, 0)>0)",
                    (nota["id"], *sincronizacao_rm.STATUS_RECEBIDO)).fetchone():
        raise ValueError(f"NF {nota['numero']} tem baixa no RM: nota com recebimento não se desconsidera")
    falta = sincronizacao_rm._falta_por_titulo(conn, nota["id"], aberto_inteiro=True, baixa_total_quita=True) or 0
    cur = conn.execute("UPDATE notas_fiscais SET situacao='cancelada', desconsiderada_em=datetime('now') "
                       "WHERE id=? AND situacao='ativa' AND desconsiderada_em IS NULL", (nota["id"],))
    db.exigir_uma_linha(cur, f"A NF {nota['numero']} mudou concorrentemente; tente novamente")
    auditoria.registrar(conn, uid, "nota.desconsiderar", "nota_fiscal", nota["id"], {"situacao": "ativa"},
                        {"situacao": "desconsiderada", **_registro_da_nota(nota), "titulo_aberto_centavos": falta,
                         "motivo": motivo, "fonte": fonte, "origem": ORIGEM,
                         **({"substituida_por": substituta} if substituta else {})})
    return [f"deixa de contar: {dinheiro.format_brl(nota['valor_centavos'])} no faturado e "
            f"{dinheiro.format_brl(falta)} de título em aberto no a receber (valores cheios)"]


def _reconsiderar_nf(conn, uid, nota, op, fonte):
    if nota["desconsiderada_em"] is None:
        raise _JaFeito("não está desconsiderada")
    # o que o RM diz da nota ficou em `status_rm`: se ele a cancelou nesse meio-tempo, ela segue cancelada
    nova = "cancelada" if str(nota["status_rm"] or "").upper() == "C" else "ativa"
    cur = conn.execute("UPDATE notas_fiscais SET situacao=?, desconsiderada_em=NULL "
                       "WHERE id=? AND desconsiderada_em IS NOT NULL", (nova, nota["id"]))
    db.exigir_uma_linha(cur, f"A NF {nota['numero']} mudou concorrentemente; tente novamente")
    motivo = _texto(op, "motivo")
    auditoria.registrar(conn, uid, "nota.reconsiderar", "nota_fiscal", nota["id"],
                        {"situacao": "desconsiderada", "desconsiderada_em": nota["desconsiderada_em"]},
                        {"situacao": nova, **_registro_da_nota(nota), "fonte": fonte, "origem": ORIGEM,
                         **({"motivo": motivo} if motivo else {})})
    return ["AVISO: o RM cancelou a nota: ela continua cancelada"] if nova == "cancelada" else ["volta a contar"]


EXECUTORES_DE_NOTA = {"desconsiderar_nf": _desconsiderar_nf, "reconsiderar_nf": _reconsiderar_nf}


def _aplicar_nota(conn, uid: int, op: dict, item: dict, nome: str, fonte: str) -> None:
    # o ensaio nao migra (`cli._corrigir_medicoes`): na copia do banco de antes do deploy a marca ainda nao existe
    if not any(r[1] == "desconsiderada_em" for r in conn.execute("PRAGMA table_info(notas_fiscais)")):
        raise ValueError("este banco ainda não tem a migração da nota desconsiderada (081) e o ensaio não migra: "
                         "rode num banco já migrado")
    nota = _nota_da_operacao(conn, op)
    item["alvo"] = f"{_fmt_nf(nota)}, coligada {nota['coligada']}"
    item["antes"] = _situacao_da_nota(nota)
    detalhes = EXECUTORES_DE_NOTA[nome](conn, uid, nota, op, fonte)
    depois = conn.execute("SELECT * FROM notas_fiscais WHERE id=?", (nota["id"],)).fetchone()
    item["depois"], item["detalhes"], item["situacao"] = _situacao_da_nota(depois), detalhes, "feito"


EXECUTORES = {"cancelar": _cancelar, "reabrir": _reabrir, "trocar_tipo": _trocar_tipo, "desligar_nf": _desligar_nf,
              "ligar_nf": _ligar_nf, "protocolar": _protocolar, "estado": _estado}


def _aplicar(conn, uid: int, op, item: dict) -> None:
    if not isinstance(op, dict):
        raise ValueError("a operação deve ser um bloco com operacao, fonte e a medição")
    nome = op.get("operacao")
    if nome not in OPERACOES:
        raise ValueError(f"operação desconhecida: {nome!r} (use {', '.join(OPERACOES)})")
    sobra = set(op) - (CAMPOS_COMUNS_DE_NOTA if nome in OPERACOES_DE_NOTA else CAMPOS_COMUNS) - CAMPOS[nome]
    if sobra:
        raise ValueError(f"campo que {nome} não usa: {', '.join(sorted(map(str, sobra)))}")
    fonte = _texto(op, "fonte")
    if fonte is None:
        raise ValueError("falta a fonte (o documento que justifica a correção)")
    if nome in OPERACOES_DE_NOTA:
        return _aplicar_nota(conn, uid, op, item, nome, fonte)
    m = _resolver(conn, op)
    item["alvo"], item["antes"] = _rotulo(conn, m), m["estado"]
    antes = _foto(conn, m["id"])
    op = dict(op)
    detalhes = EXECUTORES[nome](conn, uid, m, op, fonte)
    depois = _foto(conn, m["id"])
    auditoria.registrar(conn, uid, "medicao.correcao_cadastro", "medicao", m["id"], antes,
                        {**depois, "operacao": nome, "fonte": fonte, "origem": ORIGEM,
                         **({"centro_forcado": op["_forcado"]} if op.get("_forcado") else {}),
                         **op.get("_duplicata", {})})
    item["depois"], item["detalhes"], item["situacao"] = depois["estado"], detalhes, "feito"


def executar(conn, usuario_id: int, operacoes: list, ensaio: bool) -> dict:
    """Executa as operacoes em ordem, numa transacao so'. No ensaio (ou com erro), desfaz tudo no fim.
    Cada operacao roda no seu SAVEPOINT: a que falha nao deixa meio feito para as seguintes do relatorio."""
    itens = []
    try:
        with db.mutacao(conn):
            for n, op in enumerate(operacoes, 1):
                item = {"n": n, "operacao": op.get("operacao") if isinstance(op, dict) else None, "alvo": None,
                        "antes": None, "depois": None, "detalhes": []}
                try:
                    with db.mutacao(conn):
                        _aplicar(conn, usuario_id, op, item)
                except _JaFeito as e:
                    item["situacao"], item["detalhes"] = "já feito", [str(e)]
                    item["depois"] = item["antes"]
                except (ValueError, sqlite3.IntegrityError) as e:
                    item["situacao"], item["erro"] = "erro", str(e)
                itens.append(item)
            if ensaio or any(i["situacao"] == "erro" for i in itens):
                raise _Desfazer
    except _Desfazer:
        pass
    rel = {"ensaio": ensaio, "itens": itens, "erros": sum(1 for i in itens if i["situacao"] == "erro"),
           "feitos": sum(1 for i in itens if i["situacao"] == "feito"),
           "ja_feitos": sum(1 for i in itens if i["situacao"] == "já feito")}
    if rel["erros"] and not ensaio:
        raise CorrecaoRecusada(rel)
    return rel
