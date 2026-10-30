"""Leituras do monitor do SIGA (issue #327) e pedidos de leitura pela tela, com as rodadas do robo (issue #342).

O robo do SIGA (Playwright local, fora do repositorio) le a cada 15 minutos a situacao e as movimentacoes de cada
processo protocolado e manda para `POST /api/siga/leituras`. Aqui: gravar sem apagar nem sobrescrever, ligar o
processo ao protocolo pelo numero IGUAL, devolver ao robo a lista do que acompanhar e montar a leitura das telas.

As derivacoes (setor, com quem, desde, dias uteis...) vem do `relatorio_html.py` do robo, aprovado pelo Leo em
13/10/2026; a unica diferenca e' que os dias uteis descontam os feriados nacionais (`app/feriados.py`).
"""
import datetime
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from app import auditoria, db, medicoes, tempo
from app import avisos as registro_avisos
from app.feriados import dia_util

SEM_IDENTIFICACAO = "Processo sem o código ou o número do SIGA"
# Link de acompanhamento que o orgao manda por e-mail (issue #328): so' o dominio do SIGA, com o codigo em `n=`
LINK_INVALIDO = "Link do SIGA inválido: cole o link que o órgão mandou"
LIGADO_A_OUTRO = "Este processo do SIGA já está ligado a outro protocolo ou a outra medição"
LIGADO_A_OUTRA_MEDICAO = "Este processo do SIGA já está ligado a outra medição"
# Processo avulso colado na tela SIGA (issue #339)
JA_ACOMPANHADO = "Este processo do SIGA já está sendo acompanhado"
NOME_OBRIGATORIO = "Dê um nome ao processo"
OBRA_INEXISTENTE = "Obra não encontrada"


class JaAcompanhado(ValueError):
    """O código colado já está em `siga_processos`; `nome` é o do processo existente."""

    def __init__(self, nome: str | None):
        super().__init__(f"{JA_ACOMPANHADO}: {nome}" if nome else JA_ACOMPANHADO)
        self.nome = nome
_CODIGO = re.compile(r"[A-Za-z0-9]{6,20}")
MOVIMENTACOES_NA_TELA = 30
ATRASO = datetime.timedelta(hours=2)
# Relogio do robo adiantado (ou leitura com data errada) nao pode desligar o aviso de atraso ate' aquela data
FOLGA_FUTURO = datetime.timedelta(minutes=10)
LEITURA_NO_FUTURO = "Data da leitura no futuro: confira o relógio da máquina do robô"
# Horario em que o robo roda (hora de Cuiaba), nos dias uteis
ROBO_INICIO, ROBO_FIM = datetime.time(8, 0), datetime.time(17, 30)
# Processo parado no mesmo setor: aviso de atencao a partir de 5 dias uteis, de acao a partir de 10 (limites do
# e-mail do robo de 13/10/2026; a tela SIGA usa os mesmos em `siga.ts`)
DIAS_ATENCAO, DIAS_ACAO = 5, 10
_CAMPOS_MOV = ("evento", "cad_lotacao", "cad_pessoa", "at_lotacao", "at_pessoa")
# Pedido de leitura pela tela e rodadas do robo (issue #342)
PROCESSO_INEXISTENTE = "Processo do SIGA não encontrado"
RODADA_INEXISTENTE = "Rodada do SIGA não encontrada"
RODADA_TERMINADA = "Esta rodada do SIGA já terminou"
PRAZO_DISPARO = 15                                    # segundos de espera pelo schtasks
MAX_MOTIVO = 300
EM_ANDAMENTO = datetime.timedelta(minutes=12)          # na tela, "lendo" ate' aqui; depois, "nao terminou"
ROBO_VIVO = datetime.timedelta(minutes=10)             # o Windows encerra o robo aos 10: depois disso, dispara
SEM_INICIO = datetime.timedelta(minutes=2)
COMPLETA_A_CADA = datetime.timedelta(minutes=14)       # a tarefa agendada roda de 15 em 15 minutos
log = logging.getLogger("app.siga")


class RodadaTerminada(Exception):
    """Fim ou falha de uma rodada que ja' terminou."""


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


def _so_da_planilha(conn, medicao_id: int, numero: str, ocupantes: list) -> bool:
    """Issue #283: o processo `numero` casa com o protocolo da NOTA da medicao e todos os `ocupantes` (ligados a'
    medicao sem protocolo) casam so' com o nº do SIGA da planilha/carta (etapa 'planilha', migracao 054)."""
    etapas: dict[str, set[str]] = {"planilha": set(), "nota": set()}
    for r in conn.execute("SELECT etapa, numero_processo FROM medicao_protocolos WHERE medicao_id=? "
                          "AND numero_processo IS NOT NULL", (medicao_id,)):
        etapas[r["etapa"]].add(normalizar_numero(r["numero_processo"]))
    if normalizar_numero(numero) not in etapas["nota"]:
        return False
    return bool(ocupantes) and all(o["numero"] and normalizar_numero(o["numero"]) in etapas["planilha"]
                                   and normalizar_numero(o["numero"]) not in etapas["nota"] for o in ocupantes)


def _vincular(conn, processo_id: int) -> None:
    p = conn.execute("SELECT numero, contrato_id, protocolo_id, medicao_id FROM siga_processos WHERE id=?",
                     (processo_id,)).fetchone()
    if not p["numero"] or p["protocolo_id"] is not None or p["medicao_id"] is not None:
        return
    achado = _vinculo(conn, p["numero"])
    if achado:
        contrato_id, protocolo_id, medicao_id = achado
        # issue #328: o processo que um link novo substituiu nao volta ao protocolo (ou a' medicao) pelo numero igual
        ocupantes = conn.execute("SELECT id, numero FROM siga_processos WHERE id<>? AND (protocolo_id=? OR "
                                 "(? IS NULL AND medicao_id=? AND protocolo_id IS NULL))",
                                 (processo_id, protocolo_id, protocolo_id, medicao_id)).fetchall()
        antes = None
        if ocupantes:
            # issue #283: o processo da planilha/carta cede ao da nota (o que importa para o pagamento). Ele perde o
            # vinculo e continua gravado, com as leituras, como o processo que um link novo substitui (`_ligar`)
            if protocolo_id is not None or medicao_id is None or \
                    not _so_da_planilha(conn, medicao_id, p["numero"], ocupantes):
                return
            for o in ocupantes:
                conn.execute("UPDATE siga_processos SET contrato_id=NULL, protocolo_id=NULL, medicao_id=NULL "
                             "WHERE id=?", (o["id"],))
            antes = {"processos_siga_da_planilha": [o["numero"] for o in ocupantes], "medicao_id": medicao_id}
        conn.execute("UPDATE siga_processos SET contrato_id=?, protocolo_id=?, medicao_id=? "
                     "WHERE id=? AND protocolo_id IS NULL AND medicao_id IS NULL", (*achado, processo_id))
        entidade = ("medicao", medicao_id) if medicao_id is not None else ("protocolo", protocolo_id)
        auditoria.registrar(conn, None, "siga.vinculo", *entidade, antes,
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
           protocolo_id: int | None, medicao_id: int | None, medicoes_alvo: set[int], entidade: str,
           entidade_id: int) -> None:
    """Cria ou liga o processo do `codigo` ao protocolo (ou, no envio por fora, a' medicao). Link com outro codigo
    SUBSTITUI o anterior (como o nº do orgao, que se corrige; decisao da orquestradora em 28/10/2026): o processo
    anterior perde o vinculo e continua gravado, com as leituras. Recusa so' o codigo ja' ligado a outro protocolo
    ou a outra medicao. Quem chama abre a transacao (`db.mutacao`) e confere o codigo com `extrair_codigo`.
    `medicoes_alvo`: as medicoes do protocolo; o processo que o robo ja' ligou so' a uma delas (pelo numero do envio
    por fora) nao e' "de outro protocolo"."""
    numero = sem_espacos(numero) or None
    ligado_a_outro = LIGADO_A_OUTRA_MEDICAO if protocolo_id is None else LIGADO_A_OUTRO
    if protocolo_id is not None:
        proprio = conn.execute("SELECT * FROM siga_processos WHERE protocolo_id=? ORDER BY id LIMIT 1",
                               (protocolo_id,)).fetchone()
    else:
        proprio = conn.execute("SELECT * FROM siga_processos WHERE medicao_id=? AND protocolo_id IS NULL "
                               "ORDER BY id LIMIT 1", (medicao_id,)).fetchone()
    depois = {"codigo": codigo, "numero": numero, "contrato_id": contrato_id,
              "protocolo_id": protocolo_id, "medicao_id": medicao_id}
    antes = None
    if proprio is not None and proprio["codigo"] == codigo:
        # ligado antes pela leitura do robo, ja' com o codigo: so' falta o registro de quem colou o link
        if entidade_id not in registrado_em(conn, entidade, [entidade_id]):
            auditoria.registrar(conn, usuario_id, "protocolo.siga", entidade, entidade_id, None, depois)
        return
    if proprio is not None and proprio["codigo"] is None \
            and not conn.execute("SELECT 1 FROM siga_processos WHERE codigo=?", (codigo,)).fetchone():
        # ligado antes so' pelo numero igual (a leitura do robo): ganha o codigo, se nenhum outro processo o tem.
        # Se o codigo ja' existe (livre ou nao), cai no ramo abaixo: livre, o processo do codigo e' ligado e o que
        # so' tinha o numero perde o vinculo (continua gravado, com as leituras); ligado a outro, e' recusado.
        conn.execute("UPDATE siga_processos SET codigo=?, numero=COALESCE(numero, ?) WHERE id=?",
                     (codigo, numero, proprio["id"]))
    else:
        achado = _achar_processo(conn, codigo, numero)
        if achado is not None and (achado["protocolo_id"] is not None
                                   or achado["medicao_id"] not in (None, *medicoes_alvo)):
            raise ValueError(ligado_a_outro)
        if proprio is not None:
            antes = {"codigo": proprio["codigo"]}
            conn.execute("UPDATE siga_processos SET contrato_id=NULL, protocolo_id=NULL, medicao_id=NULL "
                         "WHERE id=?", (proprio["id"],))
        alvo = _gravar_processo(conn, codigo, numero, nome)
        conn.execute("UPDATE siga_processos SET contrato_id=?, protocolo_id=?, medicao_id=? WHERE id=?",
                     (contrato_id, protocolo_id, medicao_id, alvo))
    auditoria.registrar(conn, usuario_id, "protocolo.siga", entidade, entidade_id, antes, depois)


def codigo_do_protocolo(conn, protocolo_id: int) -> str | None:
    """Codigo do processo hoje ligado ao protocolo (None se nao ha' ou se so' o numero o liga)."""
    r = conn.execute("SELECT codigo FROM siga_processos WHERE protocolo_id=? ORDER BY id LIMIT 1",
                     (protocolo_id,)).fetchone()
    return r["codigo"] if r else None


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
           {m["id"] for m in ms}, "protocolo", protocolo_id)


def registrar_link_medicao(conn, usuario_id, medicao_id: int, codigo: str, numero: str | None) -> None:
    """Protocolo registrado como feito por fora: nao ha' protocolo, o processo liga so' a' medicao."""
    m = conn.execute("SELECT id, numero, tipo, contrato_id FROM medicoes WHERE id=?", (medicao_id,)).fetchone()
    _ligar(conn, usuario_id, codigo, numero, f"{medicoes.titulo(dict(m))} - {_obra(conn, m['contrato_id'])}",
           m["contrato_id"], None, medicao_id, {medicao_id}, "medicao", medicao_id)


def acompanhar_avulso(conn, usuario_id, link: str | None, numero: str | None, nome: str | None,
                      contrato_id: int | None) -> int:
    """Link colado na tela SIGA (issue #339): processo sem medição (aditivo, indenizatório, avulso). A pessoa da' o
    nome, porque a pagina do SIGA nao mostra o titulo; a obra e' opcional. Codigo ja' acompanhado e' recusado
    (`JaAcompanhado`, com o nome existente). Processo que o robo ja' mandou so' pelo numero igual ganha o codigo,
    o nome e a obra. -> id do processo."""
    codigo = extrair_codigo(link)
    if not codigo:
        raise ValueError(LINK_INVALIDO)
    nome = _texto(nome)
    if not nome:
        raise ValueError(NOME_OBRIGATORIO)
    numero = sem_espacos(numero) or None
    if contrato_id is not None and conn.execute("SELECT 1 FROM contratos WHERE id=?", (contrato_id,)).fetchone() is None:
        raise ValueError(OBRA_INEXISTENTE)
    with db.mutacao(conn):
        existente = conn.execute("SELECT nome FROM siga_processos WHERE codigo=?", (codigo,)).fetchone()
        if existente is not None:
            raise JaAcompanhado(existente["nome"])
        # Processo que o robo ja' mandou so' pelo numero: ganha o codigo, o nome e a obra se estiver livre; ligado a
        # um protocolo ou a uma medicao, nao e' avulso e nao se reescreve por aqui.
        achado = _achar_processo(conn, codigo, numero)
        antes = None
        if achado is not None:
            if achado["protocolo_id"] is not None or achado["medicao_id"] is not None:
                raise ValueError(LIGADO_A_OUTRO)
            antes = {"codigo": achado["codigo"], "numero": achado["numero"], "nome": achado["nome"],
                     "contrato_id": achado["contrato_id"]}
            contrato_id = achado["contrato_id"] if achado["contrato_id"] is not None else contrato_id
        pid = _gravar_processo(conn, codigo, numero, nome)
        conn.execute("UPDATE siga_processos SET nome=?, contrato_id=? WHERE id=?", (nome, contrato_id, pid))
        auditoria.registrar(conn, usuario_id, "protocolo.siga", "siga_processo", pid, antes,
                            {"codigo": codigo, "numero": numero, "nome": nome, "contrato_id": contrato_id})
    return pid


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
            "id": p["id"], "codigo": p["codigo"], "link": link_do_processo(p["codigo"]), "numero": p["numero"], "nome": p["nome"],
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
            "processos": saida, "pode_atualizar": bool(tarefa_do_robo()), "robo": situacao_robo(conn, agora)}


# --- pedidos de leitura e rodadas do robo (issue #342) -----------------------------------------------------

def tarefa_do_robo() -> str:
    """Nome da tarefa agendada do robo no Windows (`DASH_SIGA_TAREFA`, fora do repositorio). Vazio: a tela nao pede
    leitura (Mac, CI, dev)."""
    return os.environ.get("DASH_SIGA_TAREFA", "").strip()


def _carimbo(dt: datetime.datetime) -> str:
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _instante(carimbo: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(carimbo).replace(tzinfo=datetime.timezone.utc)


def _hora(carimbo: str) -> str:
    return f"{tempo.para_local(_instante(carimbo)):%H:%M}"


def _schtasks() -> str:
    # Caminho inteiro: so' pelo nome, o Windows procuraria o executavel tambem na pasta atual antes do System32
    return str(Path(os.environ.get("SystemRoot") or r"C:\Windows") / "System32" / "schtasks.exe")


def _saida(dados: bytes | None) -> str:
    # o schtasks escreve na pagina de codigo do console: UTF-8 quando ele esta' em UTF-8, senao a OEM (cp850 no
    # Windows em portugues). Byte acentuado da OEM nao forma UTF-8 valido, entao a tentativa em UTF-8 vem primeiro.
    try:
        return (dados or b"").decode("utf-8").strip()
    except UnicodeDecodeError:
        return dados.decode("oem" if os.name == "nt" else "latin-1", errors="replace").strip()


def disparar_robo(tarefa: str) -> str | None:
    """Pede ao Windows que inicie agora a tarefa do robo. Comando fixo, como lista de argumentos e sem shell: so' o
    nome da tarefa (da variavel de ambiente) entra nele. -> None se o Windows aceitou; senao o motivo, cortado em
    300 caracteres."""
    try:
        r = subprocess.run([_schtasks(), "/Run", "/TN", tarefa], stdin=subprocess.DEVNULL, capture_output=True,
                           timeout=PRAZO_DISPARO)
    except subprocess.TimeoutExpired:
        return f"sem resposta em {PRAZO_DISPARO} segundos"
    except OSError:
        log.exception("schtasks nao executou")
        return "agendador de tarefas do Windows indisponível"
    if r.returncode == 0:
        return None
    return (_saida(r.stderr) or _saida(r.stdout) or f"código de saída {r.returncode}")[:MAX_MOTIVO]


def _rodada_em_andamento(conn, agora: datetime.datetime, janela: datetime.timedelta = EM_ANDAMENTO):
    """A rodada mais recente sem fim nem falha, iniciada dentro da `janela`. Na tela, 12 minutos; para disparar, 10,
    porque o Windows encerra o robo aos 10 e a rodada mais velha morreu sem avisar: nao segura os pedidos."""
    return conn.execute("SELECT * FROM siga_rodadas WHERE terminada_em IS NULL AND iniciada_em >= ? "
                        "ORDER BY id DESC LIMIT 1", (_carimbo(agora - janela),)).fetchone()


def pedir_leitura(conn, usuario_id: int, processo_id: int | None, tarefa: str,
                  agora: datetime.datetime | None = None) -> dict:
    """Clique em "Atualizar processo" (`processo_id`) ou "Atualizar todos" (None). O pedido em aberto que ja' cobre o
    clique (o do mesmo processo, ou um "todos") volta no lugar de um novo, e o clique dispara de novo. Sem rodada em
    andamento, pede ao Windows que inicie o robo, fora da transacao (o `schtasks` pode levar ate' 15 s); com rodada
    iniciada ha' menos de 10 minutos, nao dispara, porque a tarefa ignoraria a segunda execucao: o robo atende ao
    terminar a rodada atual."""
    agora = agora or tempo.agora_utc()
    with db.mutacao(conn):
        if processo_id is not None and conn.execute("SELECT 1 FROM siga_processos WHERE id=?",
                                                    (processo_id,)).fetchone() is None:
            raise ValueError(PROCESSO_INEXISTENTE)
        pedido = conn.execute("SELECT id, processo_id, pedido_em FROM siga_pedidos WHERE rodada_id IS NULL "
                              "AND (processo_id IS NULL OR processo_id IS ?) ORDER BY id LIMIT 1",
                              (processo_id,)).fetchone()
        novo = pedido is None
        if novo:
            pedido = {"id": conn.execute("INSERT INTO siga_pedidos (processo_id, usuario_id, pedido_em) VALUES (?,?,?)",
                                         (processo_id, usuario_id, _carimbo(agora))).lastrowid,
                      "processo_id": processo_id, "pedido_em": _carimbo(agora)}
        lendo = _rodada_em_andamento(conn, agora, ROBO_VIVO) is not None
    erro = None
    if not lendo:
        erro = disparar_robo(tarefa)
        with db.mutacao(conn):
            # dois cliques no mesmo pedido: vale o resultado do clique mais recente, nao o do que respondeu por ultimo
            conn.execute("UPDATE siga_pedidos SET disparado_em=?, erro_disparo=? WHERE id=? "
                         "AND (disparado_em IS NULL OR disparado_em <= ?)",
                         (_carimbo(agora), erro, pedido["id"], _carimbo(agora)))
    return {"id": pedido["id"], "processo_id": pedido["processo_id"], "pedido_em": tempo.iso_utc(pedido["pedido_em"]),
            "novo": novo, "disparado": not lendo and erro is None, "erro_disparo": erro}


def iniciar_rodada(conn, agora: datetime.datetime | None = None, so_pedidos: bool = False) -> dict:
    """"Comecei" do robo: o servidor decide o que ler. Completa (todos os processos acompanhados) com pedido "todos"
    em aberto, ou quando a ultima rodada completa terminada comecou ha' 14 minutos ou mais (ou nunca houve): e' a
    rodada automatica de 15 em 15 minutos. Senao, so' os processos dos pedidos em aberto. Os pedidos em aberto ficam
    ligados a' rodada. Sem nada a ler nao grava nada: e' o que o robo recebe quando pergunta, antes de encerrar, se
    chegou pedido novo. Com rodada aberta ha' menos de 10 minutos (o robo dela pode estar vivo: so' ele chama aqui,
    porque o Windows nao roda a tarefa duas vezes), devolve a mesma: e' o robo repetindo o "comecei".
    `so_pedidos` (o robo fora do horario, issue #347): nunca completa por tempo, so' os pedidos em aberto."""
    agora = agora or tempo.agora_utc()
    with db.mutacao(conn):
        todos = [dict(r) for r in conn.execute("SELECT id, codigo, numero, nome FROM siga_processos ORDER BY id")]
        aberta = _rodada_em_andamento(conn, agora, ROBO_VIVO)
        if aberta is not None:
            rodada_id, tipo = aberta["id"], aberta["tipo"]
            ids = set(json.loads(aberta["processos"]))
            processos = [p for p in todos if p["id"] in ids]
        else:
            pedidos = {r[0] for r in conn.execute("SELECT processo_id FROM siga_pedidos WHERE rodada_id IS NULL")}
            ultima = conn.execute("SELECT MAX(iniciada_em) FROM siga_rodadas WHERE completa=1 "
                                  "AND terminada_em IS NOT NULL").fetchone()[0]
            por_tempo = not so_pedidos and (ultima is None or agora - _instante(ultima) >= COMPLETA_A_CADA)
            completa = por_tempo or None in pedidos
            processos = [p for p in todos if completa or p["id"] in pedidos]
            if not processos:
                return {"rodada_id": None, "tipo": None, "processos": []}
            tipo = "automatica" if por_tempo else "pedido"
            rodada_id = conn.execute(
                "INSERT INTO siga_rodadas (tipo, completa, processos, iniciada_em) VALUES (?,?,?,?)",
                (tipo, int(completa), json.dumps([p["id"] for p in processos]), _carimbo(agora))).lastrowid
            conn.execute("UPDATE siga_pedidos SET rodada_id=? WHERE rodada_id IS NULL", (rodada_id,))
    return {"rodada_id": rodada_id, "tipo": tipo,
            "processos": [{k: p[k] for k in ("codigo", "numero", "nome")} for p in processos]}


def _rodada_aberta(conn, rodada_id: int) -> None:
    r = conn.execute("SELECT terminada_em FROM siga_rodadas WHERE id=?", (rodada_id,)).fetchone()
    if r is None:
        raise LookupError(RODADA_INEXISTENTE)
    if r["terminada_em"] is not None:
        raise RodadaTerminada(RODADA_TERMINADA)


def _motivo(texto: str | None) -> str:
    return _texto(texto)[:MAX_MOTIVO] or "motivo não informado"


def terminar_rodada(conn, rodada_id: int, nao_lidos: list[dict], agora: datetime.datetime | None = None) -> None:
    """"Terminei" do robo, com os processos que ele nao conseguiu ler (codigo ou numero, e o motivo). As leituras
    chegam a' parte, por `gravar_leitura`. Confere tudo antes de gravar."""
    agora = agora or tempo.agora_utc()
    conferidos = []
    for n in nao_lidos:
        codigo, numero = _texto(n.get("codigo")) or None, sem_espacos(n.get("numero")) or None
        if not codigo and not numero:
            raise ValueError(SEM_IDENTIFICACAO)
        conferidos.append((codigo, numero, _motivo(n.get("motivo"))))
    with db.mutacao(conn):
        _rodada_aberta(conn, rodada_id)
        lista, vistos = [], set()
        for codigo, numero, motivo in conferidos:
            p = _achar_processo(conn, codigo, numero)
            chave = p["id"] if p else (codigo, numero)
            if chave in vistos:            # o mesmo processo de novo (pelo codigo e pelo numero): vale o primeiro
                continue
            vistos.add(chave)
            lista.append({"processo_id": p["id"] if p else None, "codigo": codigo, "numero": numero, "motivo": motivo})
        conn.execute("UPDATE siga_rodadas SET terminada_em=?, nao_lidos=? WHERE id=?",
                     (_carimbo(agora), json.dumps(lista, ensure_ascii=False), rodada_id))


def falhar_rodada(conn, rodada_id: int, motivo: str, agora: datetime.datetime | None = None) -> None:
    """"Cai" do robo: a rodada termina com falha."""
    agora = agora or tempo.agora_utc()
    with db.mutacao(conn):
        _rodada_aberta(conn, rodada_id)
        conn.execute("UPDATE siga_rodadas SET terminada_em=?, falha=? WHERE id=?",
                     (_carimbo(agora), _motivo(motivo), rodada_id))


def _aviso_robo(tipo: str, texto: str, processo_id: int | None = None) -> dict:
    return {"tipo": tipo, "processo_id": processo_id, "texto": texto}


def situacao_robo(conn, agora: datetime.datetime | None = None) -> dict:
    """Bloco `robo` da tela SIGA. `estado`: `lendo` (rodada em andamento), `na_fila` (pedido em aberto sem rodada) ou
    `parado`. Os avisos de rodada valem ate' a proxima rodada terminar sem aquele problema (a falha e os nao lidos
    sao os da ultima rodada terminada; a rodada sem fim avisa ate' uma seguinte terminar); o do disparo, ate' o
    proximo disparo aceito."""
    agora = agora or tempo.agora_utc()
    rodada = _rodada_em_andamento(conn, agora)
    abertos = conn.execute("SELECT p.id, p.processo_id, p.pedido_em, p.disparado_em, p.erro_disparo, u.nome "
                           "FROM siga_pedidos p JOIN usuarios u ON u.id=p.usuario_id WHERE p.rodada_id IS NULL "
                           "ORDER BY p.id").fetchall()
    avisos = []
    disparo = conn.execute("SELECT erro_disparo FROM siga_pedidos WHERE disparado_em IS NOT NULL "
                           "ORDER BY disparado_em DESC, id DESC LIMIT 1").fetchone()
    if disparo is not None and disparo["erro_disparo"]:
        avisos.append(_aviso_robo("disparo", f"O Windows não iniciou o robô: {disparo['erro_disparo']}"))
    # Pedido travado (#343): sem rodada, o Windows recusou o ultimo disparo dele ou o robo nao comecou. A tela
    # libera o botao para disparar de novo; o aviso `disparo` nao serve, porque e' o do ultimo disparo de qualquer pedido.
    travados = set()
    if rodada is None:
        # Os 2 minutos contam de quando o pedido podia comecar: o ultimo disparo dele (o clique repetido dispara de
        # novo), o pedido, ou o fim da rodada que o segurou (sem fim, quando ela deixou de estar em andamento). O
        # pedido cujo disparo o Windows recusou ja' tem o aviso da recusa.
        anterior = conn.execute("SELECT iniciada_em, terminada_em FROM siga_rodadas ORDER BY id DESC LIMIT 1"
                                ).fetchone()
        livre_desde = "" if anterior is None else anterior["terminada_em"] or _carimbo(
            _instante(anterior["iniciada_em"]) + EM_ANDAMENTO)
        limite = _carimbo(agora - SEM_INICIO)
        sem_inicio = {p["id"] for p in abertos
                      if not p["erro_disparo"] and max(p["disparado_em"] or p["pedido_em"], livre_desde) < limite}
        travados = sem_inicio | {p["id"] for p in abertos if p["erro_disparo"]}
        if sem_inicio:
            avisos.append(_aviso_robo("sem_inicio",
                                      "O robô não começou. O usuário dele pode estar desconectado do servidor."))
    ultima = conn.execute("SELECT * FROM siga_rodadas WHERE terminada_em IS NOT NULL ORDER BY id DESC LIMIT 1"
                          ).fetchone()
    if ultima is not None and ultima["falha"] is not None:
        avisos.append(_aviso_robo("falha", f"A rodada das {_hora(ultima['iniciada_em'])} falhou: {ultima['falha']}"))
    elif ultima is not None and ultima["nao_lidos"]:
        nao_lidos = json.loads(ultima["nao_lidos"])
        hora = _hora(ultima["iniciada_em"])
        # o processo que a dashboard nao conhece vai identificado no texto, porque nao ha' linha da tela para ele
        avisos += [_aviso_robo("nao_lido", ("" if n["processo_id"] is not None else
                                            f"processo {n['numero'] or n['codigo']} ")
                               + f"não lido às {hora}: {n['motivo']}", n["processo_id"]) for n in nao_lidos]
        # o resumo conta so' os processos da rodada: o robo tambem le a lista dele, que a rodada nao traz
        da_rodada = json.loads(ultima["processos"])
        faltaram = len({n["processo_id"] for n in nao_lidos} & set(da_rodada))
        if faltaram:
            avisos.append(_aviso_robo("nao_lidos", f"{faltaram} de {len(da_rodada)} processos não foram lidos"))
    # so' a mais recente: rodadas mortas seguidas (todas passando dos 10 minutos) nao viram uma linha cada
    morta = conn.execute("SELECT iniciada_em FROM siga_rodadas WHERE terminada_em IS NULL AND iniciada_em < ? "
                         "AND id > ? ORDER BY id DESC LIMIT 1",
                         (_carimbo(agora - EM_ANDAMENTO), ultima["id"] if ultima else 0)).fetchone()
    if morta is not None:
        avisos.append(_aviso_robo("nao_terminou", f"A rodada das {_hora(morta['iniciada_em'])} não terminou."))
    return {
        "estado": "lendo" if rodada is not None else "na_fila" if abertos else "parado",
        "rodada": None if rodada is None else {
            "id": rodada["id"], "tipo": rodada["tipo"], "iniciada_em": tempo.iso_utc(rodada["iniciada_em"]),
            "processos": json.loads(rodada["processos"])},
        "pedidos": [{"id": p["id"], "processo_id": p["processo_id"], "usuario": p["nome"],
                     "pedido_em": tempo.iso_utc(p["pedido_em"]), "travado": p["id"] in travados} for p in abertos],
        "avisos": avisos,
    }


def saude(conn) -> dict:
    """Administracao > Saude (issue #330): a ultima leitura do monitor e quantos processos ele acompanha."""
    lido_em = conn.execute("SELECT MAX(lido_em) FROM siga_leituras").fetchone()[0]
    return {"ultima_leitura": tempo.iso_utc(lido_em) if lido_em else None,
            "atrasado": atrasado(lido_em, tempo.agora_utc()),
            "processos": conn.execute("SELECT COUNT(*) FROM siga_processos").fetchone()[0]}


def avisos(conn, hoje: datetime.date, agora: datetime.datetime | None = None) -> list[dict]:
    """Avisos da fila (issue #330). `siga_parado`: processo ligado a medicao ainda nao recebida, 5 dias uteis ou
    mais parado: os dias contam da maior data entre o inicio no setor e a ultima movimentacao valida, e o nivel
    segue `DIAS_ATENCAO` e `DIAS_ACAO`. Um so' por medicao: o do processo do protocolo mais recente (sem protocolo
    vale menos que com; empate, o processo mais novo), porque o antigo fica arquivado no SIGA depois de uma
    devolucao. `siga_sem_leitura`: um so', quando o robo passou do atraso e ha' processo acompanhado. Processo sem
    medicao (Outros processos) nao avisa: nao ha' obra nem ato da dashboard que o faca sumir."""
    agora = agora or tempo.agora_utc()
    out = []
    for p in conn.execute(
            "SELECT sp.id, sp.numero, sp.contrato_id, sp.medicao_id FROM siga_processos sp "
            "JOIN medicoes m ON m.id=sp.medicao_id WHERE m.estado NOT IN ('cancelada','desistida','recebida') "
            "AND NOT EXISTS (SELECT 1 FROM siga_processos novo WHERE novo.medicao_id=sp.medicao_id AND "
            "(COALESCE(novo.protocolo_id, -1) > COALESCE(sp.protocolo_id, -1) OR "
            "(COALESCE(novo.protocolo_id, -1) = COALESCE(sp.protocolo_id, -1) AND novo.id > sp.id))) "
            "ORDER BY sp.id").fetchall():
        leitura = conn.execute("SELECT situacao FROM siga_leituras WHERE processo_id=? ORDER BY lido_em DESC, id DESC "
                               "LIMIT 1", (p["id"],)).fetchone()
        movs = [dict(r) for r in conn.execute(
            "SELECT data, evento, at_lotacao, at_pessoa FROM siga_movimentacoes WHERE processo_id=?", (p["id"],))]
        d = derivar(leitura["situacao"] if leitura else None, movs, hoje)
        if d["desde"] is None:
            continue
        parado_desde = max(d["desde"], d["ultima"]["data"])[:10]
        dias = _dias_uteis(datetime.date.fromisoformat(parado_desde), hoje)
        if dias < DIAS_ATENCAO:
            continue
        onde = f" em {d['setor']}" if d["setor"] else ""
        out.append({**registro_avisos.aviso(
            "siga_parado", "acao" if dias >= DIAS_ACAO else "atencao",
            f"processo {p['numero']} parado{onde} há {dias} dias úteis", p["contrato_id"],
            registro_avisos.obra(conn, p["contrato_id"]), dias=dias,
            destino={"tela": "siga", "processo": p["id"]}, data=parado_desde, sentido="desde"),
            "medicao_id": p["medicao_id"]})
    lido_em = conn.execute("SELECT MAX(lido_em) FROM siga_leituras").fetchone()[0]
    if atrasado(lido_em, agora) and conn.execute("SELECT 1 FROM siga_processos LIMIT 1").fetchone():
        local = tempo.para_local(datetime.datetime.fromisoformat(lido_em))
        out.append(registro_avisos.aviso(
            "siga_sem_leitura", "acao", f"monitor do SIGA sem leitura desde {local:%d/%m %H:%M}",
            destino={"tela": "siga"}, data=local.date().isoformat(), sentido="desde"))
    return out
