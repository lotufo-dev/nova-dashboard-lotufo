"""Leituras do monitor do SIGA (issue #327).

O robo do SIGA (Playwright local, fora do repositorio) le a cada 15 minutos a situacao e as movimentacoes de cada
processo protocolado e manda para `POST /api/siga/leituras`. Aqui: gravar sem apagar nem sobrescrever, ligar o
processo ao protocolo pelo numero IGUAL, devolver ao robo a lista do que acompanhar e montar a leitura das telas.

As derivacoes (setor, com quem, desde, dias uteis...) vem do `relatorio_html.py` do robo, aprovado pelo Leo em
13/10/2026; a unica diferenca e' que os dias uteis descontam os feriados nacionais (`app/feriados.py`).
"""
import datetime
import os
import re
from urllib.parse import parse_qs, quote, urlsplit

from app import auditoria, db, medicoes, tempo
from app.feriados import dia_util

SEM_IDENTIFICACAO = "Processo sem o código ou o número do SIGA"
# Link de acompanhamento que o orgao manda por e-mail (issue #328): so' o dominio do SIGA, com o codigo em `n=`
LINK_INVALIDO = "Link do SIGA inválido: cole o link que o órgão mandou"
OUTRO_LINK = "Este protocolo já tem outro link do SIGA gravado"
LIGADO_A_OUTRO = "Este processo do SIGA já está ligado a outro protocolo"
_CODIGO = re.compile(r"[A-Za-z0-9]{6,20}")
MOVIMENTACOES_NA_TELA = 30
ATRASO = datetime.timedelta(hours=2)
# Relogio do robo adiantado (ou leitura com data errada) nao pode desligar o aviso de atraso ate' aquela data
FOLGA_FUTURO = datetime.timedelta(minutes=10)
LEITURA_NO_FUTURO = "Data da leitura no futuro: confira o relógio da máquina do robô"
# Horario em que o robo roda (hora de Cuiaba), nos dias uteis
ROBO_INICIO, ROBO_FIM = datetime.time(8, 0), datetime.time(17, 30)
_CAMPOS_MOV = ("evento", "cad_lotacao", "cad_pessoa", "at_lotacao", "at_pessoa")


def sem_espacos(numero: str | None) -> str:
    return re.sub(r"\s+", "", numero or "")


def normalizar_numero(numero: str | None) -> str:
    """Numero do processo para comparar: maiusculas e sem espacos. Igual e' igual; parecido nao liga."""
    return sem_espacos(numero).upper()


def _texto(valor) -> str:
    return (valor or "").strip()


def _data_iso(data_br: str) -> str:
    """'DD/MM/AAAA HH:MM:SS' do SIGA (hora de Cuiaba) -> 'AAAA-MM-DD HH:MM:SS'."""
    try:
        return datetime.datetime.strptime(_texto(data_br), "%d/%m/%Y %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        raise ValueError(f"Data de movimentação inválida: {data_br!r} (esperado DD/MM/AAAA HH:MM:SS)") from None


# --- derivacoes --------------------------------------------------------------------------------------------

def _setor(situacao: str | None) -> str:
    """Primeiro nome entre colchetes do ultimo volume: '... | 2º Volume - ... [COFIN, [X]]' -> 'COFIN'."""
    ultimo_volume = (situacao or "").split(" | ")[-1]
    achado = re.search(r"\[\s*([^\[\],]+)", ultimo_volume)
    return achado.group(1).strip() if achado else ""


def _dias_uteis(desde: datetime.date, hoje: datetime.date) -> int:
    """Dias uteis de `desde` (inclusive) ate' `hoje` (exclusive), sem sabado, domingo e feriado nacional."""
    dias, d = 0, desde
    while d < hoje:
        dias += dia_util(d)
        d += datetime.timedelta(days=1)
    return dias


def _sigla(lotacao: str | None) -> str:
    """'COFIN/ORGAO' -> 'COFIN': a sigla antes da barra, comparada por igualdade (GAB nao e' GABIN)."""
    return (lotacao or "").split("/")[0].strip().upper()


def derivar(situacao: str | None, movimentacoes: list[dict], hoje: datetime.date) -> dict:
    """Movimentacoes com `data` em 'AAAA-MM-DD HH:MM:SS'. As canceladas nao entram em nenhuma conta.

    Na caixa de entrada ninguem recebeu ainda: conta desde a ultima Transferencia (senao a movimentacao mais
    recente) e nao ha' "com quem". Fora dela, desde o ultimo Recebimento no setor (senao a mais antiga)."""
    validas = sorted((m for m in movimentacoes if "cancelad" not in (m["evento"] or "").lower()),
                     key=lambda m: m["data"])
    setor = _setor(situacao)
    caixa_entrada = "caixa de entrada" in (situacao or "").lower()
    recebimento = None
    if caixa_entrada:
        transferencias = [m for m in validas if "transfer" in (m["evento"] or "").lower()]
        desde = (transferencias or validas or [{"data": None}])[-1]["data"]
    else:
        recebimentos = [m for m in validas if "recebimento" in (m["evento"] or "").lower()
                        and setor and _sigla(m["at_lotacao"]) == setor.upper()]
        recebimento = recebimentos[-1] if recebimentos else None
        desde = recebimento["data"] if recebimento else (validas[0]["data"] if validas else None)
    hoje_iso = hoje.isoformat()
    return {
        "setor": setor,
        "caixa_entrada": caixa_entrada,
        "com_quem": recebimento["at_pessoa"] if recebimento else "",
        "desde": desde,
        "dias_uteis": _dias_uteis(datetime.date.fromisoformat(desde[:10]), hoje) if desde else None,
        "hoje": sum(m["data"][:10] == hoje_iso for m in validas),
        "ultima": validas[-1] if validas else None,
        "protocolado_em": validas[0]["data"] if validas else None,
    }


def atrasado(lido_em: str | None, agora: datetime.datetime) -> bool:
    """Ultima leitura (UTC do banco) com mais de 2 h num dia util entre 08h00 e 17h30 de Cuiaba.

    As 2 h contam a partir das 08h00 quando a ultima leitura e' de antes (a de ontem as 17h30 nao acusa atraso as
    08h05, antes da primeira rodada do dia)."""
    if not lido_em:
        return False
    local = tempo.para_local(agora)
    if not dia_util(local.date()) or not (ROBO_INICIO <= local.time() <= ROBO_FIM):
        return False
    ultima = datetime.datetime.fromisoformat(lido_em).replace(tzinfo=datetime.timezone.utc)
    inicio_do_dia = datetime.datetime.combine(local.date(), ROBO_INICIO, tzinfo=local.tzinfo)
    return agora - max(ultima, inicio_do_dia) > ATRASO


# --- gravacao ----------------------------------------------------------------------------------------------

def _achar_processo(conn, codigo: str | None, numero: str | None):
    if codigo:
        linha = conn.execute("SELECT * FROM siga_processos WHERE codigo=?", (codigo,)).fetchone()
        if linha is not None or not numero:
            return linha
        # o mesmo processo ja' recebido so' pelo numero ganha o codigo (campo vazio, nada sobrescrito)
        return conn.execute("SELECT * FROM siga_processos WHERE codigo IS NULL AND UPPER(numero)=UPPER(?) "
                            "ORDER BY id LIMIT 1", (numero,)).fetchone()
    # o numero chega e e' gravado sem espaco nenhum (gravar_leitura): os dois lados com o mesmo UPPER do SQLite
    return conn.execute("SELECT * FROM siga_processos WHERE UPPER(numero)=UPPER(?) ORDER BY id LIMIT 1",
                        (numero,)).fetchone()


def _gravar_processo(conn, codigo: str | None, numero: str | None, nome: str | None) -> int:
    linha = _achar_processo(conn, codigo, numero)
    if linha is None:
        return conn.execute("INSERT INTO siga_processos (codigo, numero, nome) VALUES (?,?,?)",
                            (codigo, numero, nome)).lastrowid
    conn.execute("UPDATE siga_processos SET codigo=COALESCE(codigo, ?), numero=COALESCE(numero, ?), "
                 "nome=COALESCE(nome, ?) WHERE id=?", (codigo, numero, nome, linha["id"]))
    return linha["id"]


def _vinculo(conn, numero: str) -> tuple[int, int | None, int | None] | None:
    """(contrato, protocolo, medicao) do protocolo enviado e/ou do envio registrado por fora com o numero IGUAL.

    Sem adivinhar: o numero tem que apontar um unico contrato e no maximo um protocolo; senao nao liga (fica em
    "Outros processos"). A medicao so' entra quando e' uma so' (protocolo que leva medicao e reajuste liga so' ao
    protocolo)."""
    alvo = normalizar_numero(numero)
    contratos, protocolos, medicoes_achadas = set(), set(), set()
    for p in conn.execute("SELECT id, contrato_id, numero_orgao FROM protocolos WHERE situacao='enviado' "
                          "AND numero_orgao IS NOT NULL").fetchall():
        if normalizar_numero(p["numero_orgao"]) == alvo:
            contratos.add(p["contrato_id"]); protocolos.add(p["id"])
            medicoes_achadas.update(r[0] for r in conn.execute(
                "SELECT medicao_id FROM protocolo_medicoes WHERE protocolo_id=?", (p["id"],)))
    for mp in conn.execute("SELECT mp.medicao_id, mp.protocolo_id, mp.numero_processo, m.contrato_id "
                           "FROM medicao_protocolos mp JOIN medicoes m ON m.id=mp.medicao_id "
                           "WHERE mp.numero_processo IS NOT NULL").fetchall():
        if normalizar_numero(mp["numero_processo"]) == alvo:
            contratos.add(mp["contrato_id"]); medicoes_achadas.add(mp["medicao_id"])
            if mp["protocolo_id"] is not None:
                protocolos.add(mp["protocolo_id"])
    if len(contratos) != 1 or len(protocolos) > 1:
        return None
    protocolo_id = next(iter(protocolos), None)
    medicao_id = next(iter(medicoes_achadas)) if len(medicoes_achadas) == 1 else None
    if protocolo_id is None and medicao_id is None:
        return None
    return next(iter(contratos)), protocolo_id, medicao_id


def _vincular(conn, processo_id: int) -> None:
    p = conn.execute("SELECT numero, contrato_id, protocolo_id, medicao_id FROM siga_processos WHERE id=?",
                     (processo_id,)).fetchone()
    if not p["numero"] or p["protocolo_id"] is not None or p["medicao_id"] is not None:
        return
    achado = _vinculo(conn, p["numero"])
    if achado:
        contrato_id, protocolo_id, medicao_id = achado
        conn.execute("UPDATE siga_processos SET contrato_id=?, protocolo_id=?, medicao_id=? "
                     "WHERE id=? AND protocolo_id IS NULL AND medicao_id IS NULL", (*achado, processo_id))
        entidade = ("medicao", medicao_id) if medicao_id is not None else ("protocolo", protocolo_id)
        auditoria.registrar(conn, None, "siga.vinculo", *entidade, None,
                            {"processo_siga": p["numero"], "contrato_id": contrato_id,
                             "protocolo_id": protocolo_id, "medicao_id": medicao_id})


def gravar_leitura(conn, lido_em: datetime.datetime, processos: list[dict]) -> dict:
    """Uma rodada do robo. Confere tudo antes de gravar: um processo invalido recusa a rodada inteira."""
    if lido_em > tempo.agora_utc() + FOLGA_FUTURO:
        raise ValueError(LEITURA_NO_FUTURO)
    lido = lido_em.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conferidos = []
    for p in processos:
        codigo, numero = _texto(p.get("codigo")) or None, sem_espacos(p.get("numero")) or None
        if not codigo and not numero:
            raise ValueError(SEM_IDENTIFICACAO)
        movs = [(_data_iso(m["data"]), *(_texto(m.get(c)) for c in _CAMPOS_MOV))
                for m in p.get("movimentacoes") or []]
        conferidos.append((codigo, numero, _texto(p.get("nome")) or None, p.get("situacao"), movs))
    novas = 0
    with db.mutacao(conn):
        for codigo, numero, nome, situacao, movs in conferidos:
            pid = _gravar_processo(conn, codigo, numero, nome)
            conn.execute("INSERT OR IGNORE INTO siga_leituras (processo_id, lido_em, situacao) VALUES (?,?,?)",
                         (pid, lido, situacao))
            for mov in movs:
                novas += conn.execute(
                    "INSERT OR IGNORE INTO siga_movimentacoes (processo_id, data, evento, cad_lotacao, cad_pessoa, "
                    "at_lotacao, at_pessoa) VALUES (?,?,?,?,?,?,?)", (pid, *mov)).rowcount
            _vincular(conn, pid)
    return {"gravados": len(conferidos), "novas_movimentacoes": novas}


# --- link do SIGA colado na etapa 4 (issue #328) -----------------------------------------------------------

def extrair_codigo(texto: str | None) -> str | None:
    """Codigo do processo (`n=` do link de acompanhamento): aceita o link inteiro ou so' o codigo. Vazio = None.
    O dominio do SIGA e' o do modelo de link (`DASH_SIGA_LINK_MODELO`, fora do repositorio): sem ele so' o codigo
    colado vale. Link de outro dominio, sem `n=` ou com codigo fora de 6 a 20 letras e numeros e' recusado."""
    texto = (texto or "").strip()
    if not texto:
        return None
    if _CODIGO.fullmatch(texto):
        return texto
    modelo = link_do_processo("x" * 6)
    try:
        url = urlsplit(texto if "://" in texto else "https://" + texto)
        host, valores = url.hostname, parse_qs(url.query).get("n", [])
        host_siga = urlsplit(modelo).hostname if modelo else None
    except ValueError:
        raise ValueError(LINK_INVALIDO) from None
    if url.scheme not in ("http", "https") or not host or host != host_siga or len(valores) != 1 \
            or not _CODIGO.fullmatch(valores[0]):
        raise ValueError(LINK_INVALIDO)
    return valores[0]


def _ligar(conn, usuario_id, codigo: str, numero: str | None, nome: str, contrato_id: int,
           protocolo_id: int | None, medicao_id: int | None, entidade: str, entidade_id: int) -> None:
    """Cria ou liga o processo do `codigo` ao protocolo (ou, no envio por fora, a' medicao). Nada se sobrescreve:
    o protocolo que ja' tem outro codigo, ou o codigo ja' ligado a outro protocolo, e' recusado. Quem chama abre a
    transacao (`db.mutacao`) e confere o codigo com `extrair_codigo`."""
    numero = sem_espacos(numero) or None
    if protocolo_id is not None:
        proprio = conn.execute("SELECT * FROM siga_processos WHERE protocolo_id=? ORDER BY id LIMIT 1",
                               (protocolo_id,)).fetchone()
    else:
        proprio = conn.execute("SELECT * FROM siga_processos WHERE medicao_id=? AND protocolo_id IS NULL "
                               "ORDER BY id LIMIT 1", (medicao_id,)).fetchone()
    if proprio is not None and proprio["codigo"] == codigo:
        return
    if proprio is not None and proprio["codigo"] is not None:
        raise ValueError(OUTRO_LINK)
    if proprio is not None:
        # ligado antes so' pelo numero igual (a leitura do robo): ganha o codigo, se nenhum outro processo o tem
        if conn.execute("SELECT 1 FROM siga_processos WHERE codigo=?", (codigo,)).fetchone():
            raise ValueError(LIGADO_A_OUTRO)
        conn.execute("UPDATE siga_processos SET codigo=?, numero=COALESCE(numero, ?) WHERE id=?",
                     (codigo, numero, proprio["id"]))
    else:
        achado = _achar_processo(conn, codigo, numero)
        if achado is not None and (achado["protocolo_id"] is not None or achado["medicao_id"] is not None):
            raise ValueError(LIGADO_A_OUTRO)
        alvo = _gravar_processo(conn, codigo, numero, nome)
        conn.execute("UPDATE siga_processos SET contrato_id=?, protocolo_id=?, medicao_id=? WHERE id=?",
                     (contrato_id, protocolo_id, medicao_id, alvo))
    auditoria.registrar(conn, usuario_id, "protocolo.siga", entidade, entidade_id, None,
                        {"codigo": codigo, "numero": numero, "contrato_id": contrato_id,
                         "protocolo_id": protocolo_id, "medicao_id": medicao_id})


def _obra(conn, contrato_id: int) -> str:
    c = conn.execute("SELECT nome_curto, numero_instrumento FROM contratos WHERE id=?", (contrato_id,)).fetchone()
    return (c["nome_curto"] or c["numero_instrumento"]) if c else ""


def registrar_link_protocolo(conn, usuario_id, protocolo_id: int, codigo: str, numero: str | None) -> None:
    """Etapa 4 do protocolo enviado pelo sistema. A medicao so' entra no vinculo quando o protocolo leva uma so'."""
    contrato_id = conn.execute("SELECT contrato_id FROM protocolos WHERE id=?", (protocolo_id,)).fetchone()[0]
    ms = [dict(r) for r in conn.execute(
        "SELECT m.id, m.numero, m.tipo FROM protocolo_medicoes pm JOIN medicoes m ON m.id=pm.medicao_id "
        "WHERE pm.protocolo_id=? ORDER BY m.tipo='reajuste', m.id", (protocolo_id,))]
    nome = f"{' e '.join(medicoes.titulo(m) for m in ms)} - {_obra(conn, contrato_id)}"
    _ligar(conn, usuario_id, codigo, numero, nome, contrato_id, protocolo_id, ms[0]["id"] if len(ms) == 1 else None,
           "protocolo", protocolo_id)


def registrar_link_medicao(conn, usuario_id, medicao_id: int, codigo: str, numero: str | None) -> None:
    """Protocolo registrado como feito por fora: nao ha' protocolo, o processo liga so' a' medicao."""
    m = conn.execute("SELECT id, numero, tipo, contrato_id FROM medicoes WHERE id=?", (medicao_id,)).fetchone()
    _ligar(conn, usuario_id, codigo, numero, f"{medicoes.titulo(dict(m))} - {_obra(conn, m['contrato_id'])}",
           m["contrato_id"], None, medicao_id, "medicao", medicao_id)


def registrado_em(conn, entidade: str, ids: list[int]) -> dict[int, str]:
    """Quando o link foi gravado (primeiro `protocolo.siga` do objeto; UTC do banco), para a linha do tempo."""
    out: dict[int, str] = {}
    for i in range(0, len(ids), 500):
        lote = [str(x) for x in ids[i:i + 500]]
        for r in conn.execute(
                "SELECT entidade_id, MIN(criado_em) FROM audit_log WHERE acao='protocolo.siga' AND entidade=? "
                f"AND entidade_id IN ({','.join('?' * len(lote))}) GROUP BY entidade_id", [entidade, *lote]):
            out[int(r[0])] = r[1]
    return out


def do_protocolo(conn, protocolo_id: int, hoje: datetime.date | None = None) -> dict | None:
    """O que a etapa 4 mostra do processo do protocolo: o link e, havendo leitura, setor, com quem e dias uteis.
    Sem codigo gravado nao ha' link, e nao ha' nada a mostrar."""
    p = conn.execute("SELECT id, codigo FROM siga_processos WHERE protocolo_id=? AND codigo IS NOT NULL "
                     "ORDER BY id LIMIT 1", (protocolo_id,)).fetchone()
    if p is None:
        return None
    saida = {"codigo": p["codigo"], "link": link_do_processo(p["codigo"]), "setor": None, "com_quem": None,
             "dias_uteis": None, "lido_em": None,
             "registrado_em": registrado_em(conn, "protocolo", [protocolo_id]).get(protocolo_id)}
    leitura = conn.execute("SELECT situacao, lido_em FROM siga_leituras WHERE processo_id=? "
                           "ORDER BY lido_em DESC, id DESC LIMIT 1", (p["id"],)).fetchone()
    if leitura is not None:
        movs = [dict(r) for r in conn.execute("SELECT data, evento, at_lotacao, at_pessoa FROM siga_movimentacoes "
                                              "WHERE processo_id=?", (p["id"],))]
        d = derivar(leitura["situacao"], movs, hoje or tempo.hoje_local())
        saida.update(setor=d["setor"] or None, com_quem=d["com_quem"] or None, dias_uteis=d["dias_uteis"],
                     lido_em=tempo.iso_utc(leitura["lido_em"]))
    return saida


# --- leitura -----------------------------------------------------------------------------------------------

def processos_para_o_robo(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT codigo, numero, nome FROM siga_processos ORDER BY id")]


def link_do_processo(codigo: str | None) -> str | None:
    """Link de acompanhamento no SIGA: o modelo (https, com `{codigo}`) vem de `DASH_SIGA_LINK_MODELO`, fora do
    repositorio. Sem codigo ou sem modelo valido, nao ha' link."""
    modelo = os.environ.get("DASH_SIGA_LINK_MODELO", "").strip()
    if not codigo or not modelo.startswith("https://") or "{codigo}" not in modelo:
        return None
    return modelo.replace("{codigo}", quote(codigo, safe=""))


def painel(conn, agora: datetime.datetime | None = None) -> dict:
    agora = agora or tempo.agora_utc()
    hoje = tempo.para_local(agora).date()
    lido_em = conn.execute("SELECT MAX(lido_em) FROM siga_leituras").fetchone()[0]
    saida = []
    for p in conn.execute(
            "SELECT sp.*, c.nome_curto, c.numero_instrumento, m.numero AS m_numero, m.tipo AS m_tipo "
            "FROM siga_processos sp LEFT JOIN contratos c ON c.id=sp.contrato_id "
            "LEFT JOIN medicoes m ON m.id=sp.medicao_id ORDER BY sp.id").fetchall():
        leitura = conn.execute("SELECT situacao FROM siga_leituras WHERE processo_id=? ORDER BY lido_em DESC, id DESC "
                               "LIMIT 1", (p["id"],)).fetchone()
        situacao = leitura["situacao"] if leitura else None
        movs = [dict(r) for r in conn.execute(
            "SELECT data, evento, cad_lotacao, cad_pessoa, at_lotacao, at_pessoa FROM siga_movimentacoes "
            "WHERE processo_id=? ORDER BY data DESC, id DESC", (p["id"],))]
        derivado = derivar(situacao, movs, hoje)
        # Na resposta, todo instante com o fuso explicito: as datas do SIGA sao de Cuiaba, o lido_em e' UTC
        movs = [{**m, "data": tempo.iso_local(m["data"])} for m in movs]
        for campo in ("desde", "protocolado_em"):
            if derivado[campo]:
                derivado[campo] = tempo.iso_local(derivado[campo])
        if derivado["ultima"]:
            derivado["ultima"] = {**derivado["ultima"], "data": tempo.iso_local(derivado["ultima"]["data"])}
        saida.append({
            "id": p["id"], "codigo": p["codigo"], "numero": p["numero"], "nome": p["nome"],
            "contrato_id": p["contrato_id"],
            "obra": (p["nome_curto"] or p["numero_instrumento"]) if p["contrato_id"] else None,
            "medicao_id": p["medicao_id"],
            "medicao_titulo": medicoes.titulo({"numero": p["m_numero"], "tipo": p["m_tipo"]})
            if p["medicao_id"] else None,
            "protocolo_id": p["protocolo_id"], "situacao": situacao,
            **derivado,
            "movimentacoes": movs[:MOVIMENTACOES_NA_TELA],
        })
    return {"lido_em": tempo.iso_utc(lido_em) if lido_em else None, "atrasado": atrasado(lido_em, agora),
            "processos": saida}
