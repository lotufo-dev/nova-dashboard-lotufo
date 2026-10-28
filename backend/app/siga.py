"""Leituras do monitor do SIGA (issue #327).

O robo do SIGA (Playwright local, fora do repositorio) le a cada 15 minutos a situacao e as movimentacoes de cada
processo protocolado e manda para `POST /api/siga/leituras`. Aqui: gravar sem apagar nem sobrescrever, ligar o
processo ao protocolo pelo numero IGUAL, devolver ao robo a lista do que acompanhar e montar a leitura das telas.

As derivacoes (setor, com quem, desde, dias uteis...) vem do `relatorio_html.py` do robo, aprovado pelo Leo em
13/10/2026; a unica diferenca e' que os dias uteis descontam os feriados nacionais (`app/feriados.py`).
"""
import datetime
import re

from app import db, medicoes, tempo
from app.feriados import dia_util

SEM_IDENTIFICACAO = "Processo sem o código ou o número do SIGA"
MOVIMENTACOES_NA_TELA = 30
ATRASO = datetime.timedelta(hours=2)
# Horario em que o robo roda (hora de Cuiaba), nos dias uteis
ROBO_INICIO, ROBO_FIM = datetime.time(8, 0), datetime.time(17, 30)
_CAMPOS_MOV = ("evento", "cad_lotacao", "cad_pessoa", "at_lotacao", "at_pessoa")


def normalizar_numero(numero: str | None) -> str:
    """Numero do processo para comparar: maiusculas e sem espacos. Igual e' igual; parecido nao liga."""
    return re.sub(r"\s+", "", numero or "").upper()


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


def derivar(situacao: str | None, movimentacoes: list[dict], hoje: datetime.date) -> dict:
    """Movimentacoes com `data` em 'AAAA-MM-DD HH:MM:SS'. As canceladas nao entram em nenhuma conta."""
    validas = sorted((m for m in movimentacoes if "cancelad" not in (m["evento"] or "").lower()),
                     key=lambda m: m["data"])
    setor = _setor(situacao)
    caixa_entrada = "caixa de entrada" in (situacao or "").lower()
    recebimentos = [m for m in validas if "recebimento" in (m["evento"] or "").lower()
                    and setor and (m["at_lotacao"] or "").upper().startswith(setor.upper())]
    transferencias = [m for m in validas if "transfer" in (m["evento"] or "").lower()]
    if recebimentos:
        desde = recebimentos[-1]["data"]
    elif caixa_entrada and transferencias:
        desde = transferencias[-1]["data"]
    else:
        desde = validas[0]["data"] if validas else None
    hoje_iso = hoje.isoformat()
    return {
        "setor": setor,
        "caixa_entrada": caixa_entrada,
        "com_quem": recebimentos[-1]["at_pessoa"] if recebimentos else "",
        "desde": desde,
        "dias_uteis": _dias_uteis(datetime.date.fromisoformat(desde[:10]), hoje) if desde else None,
        "hoje": sum(m["data"][:10] == hoje_iso for m in validas),
        "ultima": validas[-1] if validas else None,
        "protocolado_em": validas[0]["data"] if validas else None,
    }


def atrasado(lido_em: str | None, agora: datetime.datetime) -> bool:
    """Ultima leitura (UTC do banco) com mais de 2 h num dia util entre 08h00 e 17h30 de Cuiaba."""
    if not lido_em:
        return False
    local = tempo.para_local(agora)
    if not dia_util(local.date()) or not (ROBO_INICIO <= local.time() <= ROBO_FIM):
        return False
    ultima = datetime.datetime.fromisoformat(lido_em).replace(tzinfo=datetime.timezone.utc)
    return agora - ultima > ATRASO


# --- gravacao ----------------------------------------------------------------------------------------------

def _achar_processo(conn, codigo: str | None, numero: str | None):
    if codigo:
        linha = conn.execute("SELECT * FROM siga_processos WHERE codigo=?", (codigo,)).fetchone()
        if linha is not None or not numero:
            return linha
        # o mesmo processo ja' recebido so' pelo numero ganha o codigo (campo vazio, nada sobrescrito)
        return conn.execute("SELECT * FROM siga_processos WHERE codigo IS NULL AND UPPER(REPLACE(numero,' ',''))=? "
                            "ORDER BY id LIMIT 1", (normalizar_numero(numero),)).fetchone()
    return conn.execute("SELECT * FROM siga_processos WHERE UPPER(REPLACE(numero,' ',''))=? ORDER BY id LIMIT 1",
                        (normalizar_numero(numero),)).fetchone()


def _gravar_processo(conn, codigo: str | None, numero: str | None, nome: str | None) -> int:
    linha = _achar_processo(conn, codigo, numero)
    if linha is None:
        return conn.execute("INSERT INTO siga_processos (codigo, numero, nome) VALUES (?,?,?)",
                            (codigo, numero, nome)).lastrowid
    conn.execute("UPDATE siga_processos SET codigo=COALESCE(codigo, ?), numero=COALESCE(numero, ?), "
                 "nome=COALESCE(nome, ?) WHERE id=?", (codigo, numero, nome, linha["id"]))
    return linha["id"]


def _vinculo(conn, numero: str) -> tuple[int, int | None, int] | None:
    """(contrato, protocolo, medicao) do protocolo enviado, ou do envio registrado por fora, com o numero IGUAL.

    Mais de um protocolo com o mesmo numero: o mais antigo (o processo e' o mesmo)."""
    alvo = normalizar_numero(numero)
    for p in conn.execute("SELECT id, contrato_id, numero_orgao FROM protocolos WHERE situacao='enviado' "
                          "AND numero_orgao IS NOT NULL ORDER BY id"):
        if normalizar_numero(p["numero_orgao"]) == alvo:
            medicao = conn.execute("SELECT MIN(medicao_id) FROM protocolo_medicoes WHERE protocolo_id=?",
                                   (p["id"],)).fetchone()[0]
            return p["contrato_id"], p["id"], medicao
    for mp in conn.execute("SELECT mp.medicao_id, mp.protocolo_id, mp.numero_processo, m.contrato_id "
                           "FROM medicao_protocolos mp JOIN medicoes m ON m.id=mp.medicao_id "
                           "WHERE mp.numero_processo IS NOT NULL ORDER BY mp.id"):
        if normalizar_numero(mp["numero_processo"]) == alvo:
            return mp["contrato_id"], mp["protocolo_id"], mp["medicao_id"]
    return None


def _vincular(conn, processo_id: int) -> None:
    p = conn.execute("SELECT numero, contrato_id, protocolo_id, medicao_id FROM siga_processos WHERE id=?",
                     (processo_id,)).fetchone()
    if not p["numero"] or p["protocolo_id"] is not None or p["medicao_id"] is not None:
        return
    achado = _vinculo(conn, p["numero"])
    if achado:
        conn.execute("UPDATE siga_processos SET contrato_id=?, protocolo_id=?, medicao_id=? "
                     "WHERE id=? AND protocolo_id IS NULL AND medicao_id IS NULL", (*achado, processo_id))


def gravar_leitura(conn, lido_em: datetime.datetime, processos: list[dict]) -> dict:
    """Uma rodada do robo. Confere tudo antes de gravar: um processo invalido recusa a rodada inteira."""
    lido = lido_em.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conferidos = []
    for p in processos:
        codigo, numero = _texto(p.get("codigo")) or None, _texto(p.get("numero")) or None
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


# --- leitura -----------------------------------------------------------------------------------------------

def processos_para_o_robo(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT codigo, numero, nome FROM siga_processos ORDER BY id")]


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
        saida.append({
            "id": p["id"], "codigo": p["codigo"], "numero": p["numero"], "nome": p["nome"],
            "contrato_id": p["contrato_id"],
            "obra": (p["nome_curto"] or p["numero_instrumento"]) if p["contrato_id"] else None,
            "medicao_id": p["medicao_id"],
            "medicao_titulo": medicoes.titulo({"numero": p["m_numero"], "tipo": p["m_tipo"]})
            if p["medicao_id"] else None,
            "protocolo_id": p["protocolo_id"], "situacao": situacao,
            **derivar(situacao, movs, hoje),
            "movimentacoes": movs[:MOVIMENTACOES_NA_TELA],
        })
    return {"lido_em": lido_em, "atrasado": atrasado(lido_em, agora), "processos": saida}
