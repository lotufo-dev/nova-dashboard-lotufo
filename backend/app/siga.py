"""Leituras do monitor do SIGA (issue #327) e pedidos de leitura pela tela, com as rodadas do robo (issue #342).

O robo do SIGA (Playwright local, fora do repositorio) le de hora em hora (#657) a situacao e as movimentacoes de cada
processo protocolado e manda para `POST /api/siga/leituras`. Aqui: gravar sem apagar nem sobrescrever, ligar o
processo ao protocolo pelo numero IGUAL, devolver ao robo a lista do que acompanhar e montar a leitura das telas.

As derivacoes (setor, com quem, desde, dias uteis...) vem do `relatorio_html.py` do robo, aprovado pelo dono em
13/10/2026; a unica diferenca e' que os dias uteis descontam os feriados nacionais (`app/feriados.py`).
"""
import datetime
import json
import logging
import os
import re
import subprocess
import unicodedata
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from app import auditoria, db, medicoes, tempo, texto
from app import avisos as registro_avisos
from app.feriados import dia_util

SEM_IDENTIFICACAO = "Processo sem o código ou o número do SIGA"
# Link de acompanhamento que o orgao manda por e-mail (issue #328): so' o dominio do SIGA, com o codigo em `n=`
LINK_INVALIDO = "Link do SIGA inválido: cole o link que o órgão mandou"
LIGADO_A_OUTRO = "Este processo do SIGA já está ligado a outro protocolo ou a outra medição"
LIGADO_A_OUTRA_MEDICAO = "Este processo do SIGA já está ligado a outra medição"
# Processo avulso colado na tela SIGA (issue #339)
JA_ACOMPANHADO = "Este processo do SIGA já está sendo acompanhado"
OBRA_INEXISTENTE = "Obra não encontrada"
# Categorias e nome montado pelo sistema (issue #663). "medicoes" e' automatica: todo processo ligado a medicao ou a
# protocolo de medicao; as outras sao escolhidas por quem cadastra.
CATEGORIAS = ("medicoes", "aditivos", "indenizatorios", "outros")
SINGULAR = {"aditivos": "Aditivo", "indenizatorios": "Indenizatório", "outros": "Outro"}
MAX_COMPLEMENTO = 100
CATEGORIA_INVALIDA = "Escolha a categoria do processo"
OBRA_OBRIGATORIA = "Escolha a obra do processo"
MEDICAO_OBRIGATORIA = "Escolha a medição do processo"
MEDICAO_NAO_ENCONTRADA = "Medição não encontrada"
MEDICAO_INEXISTENTE ="Medição não encontrada nesta obra"
MEDICAO_FORA_DA_CATEGORIA = "Medição só entra na categoria Medições"
COMPLEMENTO_LONGO = f"Complemento com mais de {MAX_COMPLEMENTO} caracteres"
LIGADO_A_PROTOCOLO = "Este processo está ligado a um protocolo enviado pelo sistema: a categoria dele é Medições"


class JaAcompanhado(ValueError):
    """O código colado já está em `siga_processos`; `nome` é o do processo existente."""

    def __init__(self, nome: str | None):
        super().__init__(f"{JA_ACOMPANHADO}: {nome}" if nome else JA_ACOMPANHADO)
        self.nome = nome
_CODIGO = re.compile(r"[A-Za-z0-9]{6,20}")
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
COMPLETA_A_CADA = datetime.timedelta(minutes=59)       # rodada completa no maximo de hora em hora (#657)
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


def tipo_da_movimentacao(evento: str | None) -> str:
    """Tipo para os filtros do historico (#512): transferencia, recebimento, juntada, marcacao ou outras."""
    texto = unicodedata.normalize("NFD", evento or "").encode("ascii", "ignore").decode().lower()
    for tipo, raiz in (("transferencia", "transfer"), ("recebimento", "recebimento"), ("juntada", "juntada"),
                       ("marcacao", "marcacao")):
        if raiz in texto:
            return tipo
    return "outras"


def _sigla(lotacao: str | None) -> str:
    """'COFIN/ORGAO' -> 'COFIN': a sigla antes da barra, em maiusculas e sem espaco nenhum (o SIGA escreve o mesmo
    setor como 'SETOR I' e 'SETORI'), comparada por igualdade (GAB nao e' GABIN)."""
    return re.sub(r"\s+", "", (lotacao or "").split("/")[0]).upper()


def _entrada_no_setor(validas: list[dict], setor: str) -> dict | None:
    """Primeira movimentacao da permanencia atual no setor (#650): das Transferencias e Recebimentos com destino
    informado, a mais antiga do ultimo trecho seguido no `setor`. Recebimento seguinte no mesmo setor nao recomeca;
    saiu e voltou, vale a volta. None quando a ultima dessas movimentacoes nao e' do setor."""
    entrada = None
    for m in reversed(validas):
        if tipo_da_movimentacao(m["evento"]) not in ("transferencia", "recebimento") or not _sigla(m["at_lotacao"]):
            continue
        if _sigla(m["at_lotacao"]) != _sigla(setor):
            break
        entrada = m
    return entrada


def _marcacao_ou_anotacao(evento: str | None) -> bool:
    texto = unicodedata.normalize("NFD", evento or "").encode("ascii", "ignore").decode().lower()
    return "marcacao" in texto or "anotacao" in texto


def _estado(situacao: str | None) -> str:
    """O estado do ultimo volume ou via da situacao, sem acento e em minusculas: '1º Volume - Arquivado [PROTOC, [X]]'
    -> 'arquivado'; '1ª Via (Setor Competente) - Sobrestado [X]' -> 'sobrestado'."""
    ultimo_volume = (situacao or "").split(" | ")[-1]
    return _sem_acento(ultimo_volume.split("[")[0]).split(" - ", 1)[-1].strip()


def sobrestado(situacao: str | None) -> bool:
    """Processo suspenso pelo orgao (#841): o estado do ultimo volume ou via comeca por "sobrestad". Nao e' atraso."""
    return _estado(situacao).startswith("sobrestad")


def juntado(situacao: str | None) -> bool:
    """Processo juntado a outro (#841): o estado do ultimo volume ou via comeca por "juntad" ('1º Volume - Juntado
    [...]'). A movimentacao "Juntada" e' outra coisa (um documento juntado a ESTE processo) e nao encerra."""
    return _estado(situacao).startswith("juntad")


def derivar(situacao: str | None, movimentacoes: list[dict], hoje: datetime.date) -> dict:
    """Movimentacoes com `data` em 'AAAA-MM-DD HH:MM:SS'. As canceladas nao entram em nenhuma conta.

    `desde` e' a entrada no setor atual (`_entrada_no_setor`): a Transferencia que levou o processo para la'; sem
    ela, o primeiro Recebimento. Sem nenhuma das duas: na caixa de entrada, a ultima Transferencia (senao a
    movimentacao mais recente); fora dela, a movimentacao mais antiga. "Com quem" e' quem fez o ultimo Recebimento
    no setor (na caixa de entrada ninguem recebeu ainda). `ultima` nao considera Marcacao nem Anotacao.

    O tempo parado (#840) conta da `ultima`, a mesma movimentacao que a coluna "Ultima movimentacao" mostra:
    `dias_sem_movimentacao` sao os dias uteis desde ela e `hoje` quantas dessas movimentacoes (fora Marcacao e
    Anotacao) sao de hoje. `dias_uteis` (desde a entrada no setor) continua so' como informacao."""
    validas = sorted((m for m in movimentacoes if "cancelad" not in (m["evento"] or "").lower()),
                     key=lambda m: m["data"])
    setor = _setor(situacao)
    caixa_entrada = "caixa de entrada" in (situacao or "").lower()
    recebimento = None
    entrada = _entrada_no_setor(validas, setor) if setor else None
    if caixa_entrada:
        transferencias = [m for m in validas if "transfer" in (m["evento"] or "").lower()]
        desde = entrada["data"] if entrada else (transferencias or validas or [{"data": None}])[-1]["data"]
    else:
        recebimentos = [m for m in validas if "recebimento" in (m["evento"] or "").lower()
                        and setor and _sigla(m["at_lotacao"]) == _sigla(setor)]
        recebimento = recebimentos[-1] if recebimentos else None
        desde = entrada["data"] if entrada else (validas[0]["data"] if validas else None)
    hoje_iso = hoje.isoformat()
    andamentos = [m for m in validas if not _marcacao_ou_anotacao(m["evento"])]
    ultima = andamentos[-1] if andamentos else None
    return {
        "setor": setor,
        "caixa_entrada": caixa_entrada,
        "com_quem": recebimento["at_pessoa"] if recebimento else "",
        "desde": desde,
        "dias_uteis": _dias_uteis(datetime.date.fromisoformat(desde[:10]), hoje) if desde else None,
        "dias_sem_movimentacao": _dias_uteis(datetime.date.fromisoformat(ultima["data"][:10]), hoje) if ultima else None,
        "hoje": sum(m["data"][:10] == hoje_iso for m in andamentos),
        "ultima": ultima,
        "protocolado_em": validas[0]["data"] if validas else None,
        # #841: suspenso pelo orgao; a leitura de "parado" (`parado`) diz "sobrestado" no lugar dos dias
        "sobrestado": sobrestado(situacao),
    }


def _sem_acento(texto: str | None) -> str:
    return unicodedata.normalize("NFD", texto or "").encode("ascii", "ignore").decode().lower()


def arquivado(situacao: str | None, movimentacoes: list[dict]) -> bool:
    """Processo arquivado no SIGA (#657), sem diferenca de acento e maiuscula: o setor do ultimo volume contem
    "arquivo", o estado do ultimo volume comeca por "arquiv" ('1º Volume - Arquivado [...]'), ou a movimentacao mais
    recente (fora Marcacao e Anotacao) comeca por "arquiv" e nao foi cancelada. Desarquivamento, transferencia ou
    qualquer outro andamento depois do arquivamento passa a ser a mais recente, e o processo volta."""
    ultimo_volume = (situacao or "").split(" | ")[-1]
    estado = _sem_acento(ultimo_volume.split("[")[0]).split(" - ", 1)[-1].strip()
    if "arquivo" in _sem_acento(_setor(situacao)) or estado.startswith("arquiv"):
        return True
    andamentos = [m for m in movimentacoes if not _marcacao_ou_anotacao(m["evento"])]
    if not andamentos:
        return False
    evento = _sem_acento(max(andamentos, key=lambda m: m["data"])["evento"]).strip()
    return evento.startswith("arquiv") and "cancelad" not in evento


def _local(carimbo_utc: str) -> str:
    """Carimbo UTC do banco -> 'AAAA-MM-DD HH:MM:SS' em hora de Cuiaba, o formato das movimentacoes do SIGA."""
    return tempo.para_local(_instante(carimbo_utc)).strftime("%Y-%m-%d %H:%M:%S")


def movimentacao_depois(movimentacoes: list[dict], encerrado_em: str) -> dict | None:
    """A primeira movimentacao posterior ao encerramento a' mao (`encerrado_em`, UTC do banco), fora Marcacao,
    Anotacao e cancelada (a regua da #840). E' ela que devolve o processo ao quadro (#841)."""
    desde = _local(encerrado_em)
    depois = sorted((m for m in movimentacoes if m["data"] > desde and not _marcacao_ou_anotacao(m["evento"])
                     and "cancelad" not in (m["evento"] or "").lower()), key=lambda m: m["data"])
    return depois[0] if depois else None


# Por que o processo esta' encerrado (#657, #841): os automaticos e o encerrado a' mao
MOTIVOS_AUTOMATICOS = ("recebida", "arquivado", "juntado")


def _encerramento(estado_da_medicao: str | None, situacao: str | None, movimentacoes: list[dict],
                  manual_em: str | None = None) -> str | None:
    """A leitura unica de "encerrado" (#657, #841): `recebida` (ligado a medicao recebida), `arquivado`, `juntado`
    (juntado a outro processo), `manual` (encerrado a' mao em `manual_em`, UTC, sem movimentacao depois) ou None
    (vivo). Os automaticos sao derivados a cada leitura, nunca gravados: a medicao que deixa de estar recebida devolve
    o processo. `situacao` e' a da ultima leitura com movimentacoes (`_situacoes`): a leitura vazia nao conta. Nada por
    setor nem por tempo."""
    if estado_da_medicao == "recebida":
        return "recebida"
    if arquivado(situacao, movimentacoes):
        return "arquivado"
    if juntado(situacao):
        return "juntado"
    if manual_em is not None and movimentacao_depois(movimentacoes, manual_em) is None:
        return "manual"
    return None


def _situacoes(conn, ids=None) -> dict[int, str | None]:
    """{processo: situacao da ultima leitura que vale} (#841): a leitura vazia (`sem_movimentacoes`) fica gravada e
    nao vale como situacao. Processo sem leitura que vale nao entra."""
    filtro, args = "", []
    if ids is not None:
        ids = list(ids)
        if not ids:
            return {}
        filtro, args = f" AND l.processo_id IN ({','.join('?' * len(ids))})", ids
    return {r[0]: r[1] for r in conn.execute(
        "SELECT l.processo_id, l.situacao FROM siga_leituras l WHERE l.id=(SELECT u.id FROM siga_leituras u "
        "WHERE u.processo_id=l.processo_id AND u.sem_movimentacoes=0 ORDER BY u.lido_em DESC, u.id DESC LIMIT 1)"
        + filtro, args)}


def _manuais(conn) -> dict[int, dict]:
    """{processo: encerramento a' mao em aberto} (#841), com o nome de quem encerrou."""
    return {r["processo_id"]: dict(r) for r in conn.execute(
        "SELECT e.id, e.processo_id, e.motivo, e.encerrado_em, u.nome AS por FROM siga_encerramentos e "
        "JOIN usuarios u ON u.id=e.encerrado_por WHERE e.reaberto_em IS NULL")}


def encerrados(conn) -> dict[int, str]:
    """{id do processo: motivo} dos processos encerrados (`_encerramento`)."""
    out = {}
    situacoes, manuais = _situacoes(conn), _manuais(conn)
    for p in conn.execute("SELECT sp.id, m.estado FROM siga_processos sp LEFT JOIN medicoes m ON m.id=sp.medicao_id "
                          "ORDER BY sp.id").fetchall():
        movs = [] if p["estado"] == "recebida" else conn.execute(
            "SELECT data, evento FROM siga_movimentacoes WHERE processo_id=?", (p["id"],)).fetchall()
        manual = manuais.get(p["id"])
        motivo = _encerramento(p["estado"], situacoes.get(p["id"]), movs, manual["encerrado_em"] if manual else None)
        if motivo:
            out[p["id"]] = motivo
    return out


def fora_do_robo(conn) -> dict[int, str]:
    """Os encerrados que o robo deixa de ler: o encerrado a' mao continua sendo lido (#841), para voltar sozinho com
    movimentacao nova."""
    return {pid: motivo for pid, motivo in encerrados(conn).items() if motivo != "manual"}


def _ultimas_leituras(conn) -> dict[int, str]:
    return dict(conn.execute("SELECT processo_id, MAX(lido_em) FROM siga_leituras GROUP BY processo_id").fetchall())


def _leitura_dos_vivos(conn, fora: dict[int, str]) -> str | None:
    """A leitura mais recente entre os processos vivos (UTC do banco): o encerrado nao e' mais lido, e a leitura
    antiga dele nao acusa atraso nem a nova o esconde."""
    return max((lido for pid, lido in _ultimas_leituras(conn).items() if pid not in fora), default=None)


def _ha_vivo(conn, fora: dict[int, str]) -> bool:
    return any(r[0] not in fora for r in conn.execute("SELECT id FROM siga_processos"))


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
    """Issue #283: o processo `numero` casa com o protocolo da NOTA da medicao e nenhum dos `ocupantes` (ligados a'
    medicao sem protocolo) e' o da nota: o numero deles nao esta' entre os da nota e eles nao entraram pelo link
    colado na medicao (`protocolo.siga` com o codigo deles). Nao exige o numero na linha da planilha/carta (etapa
    'planilha', migracao 054): corrigido o nº do SIGA da planilha, o processo que o robo ligou pelo numero antigo
    tambem cede."""
    notas = {normalizar_numero(r[0]) for r in conn.execute(
        "SELECT numero_processo FROM medicao_protocolos WHERE medicao_id=? AND etapa='nota' AND desfeita_em IS NULL "
        "AND numero_processo IS NOT NULL", (medicao_id,))}
    if normalizar_numero(numero) not in notas:
        return False
    colados = {r[0] for r in conn.execute(
        "SELECT json_extract(depois, '$.codigo') FROM audit_log WHERE acao='protocolo.siga' AND entidade='medicao' "
        "AND entidade_id=?", (medicao_id,))}
    return bool(ocupantes) and all((not o["numero"] or normalizar_numero(o["numero"]) not in notas)
                                   and (not o["codigo"] or o["codigo"] not in colados) for o in ocupantes)


def _vincular(conn, processo_id: int) -> None:
    p = conn.execute("SELECT numero, contrato_id, protocolo_id, medicao_id FROM siga_processos WHERE id=?",
                     (processo_id,)).fetchone()
    if not p["numero"] or p["protocolo_id"] is not None or p["medicao_id"] is not None:
        return
    # #841: o vinculo que alguem desfez pela tela nao volta sozinho pelo numero igual
    if conn.execute("SELECT 1 FROM audit_log WHERE acao='siga.vinculo_desfeito' AND entidade='siga_processo' "
                    "AND entidade_id=? LIMIT 1", (str(processo_id),)).fetchone():
        return
    achado = _vinculo(conn, p["numero"])
    if achado:
        contrato_id, protocolo_id, medicao_id = achado
        # issue #328: o processo que um link novo substituiu nao volta ao protocolo (ou a' medicao) pelo numero igual
        ocupantes = conn.execute("SELECT id, codigo, numero FROM siga_processos WHERE id<>? AND (protocolo_id=? OR "
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
                conn.execute("UPDATE siga_processos SET contrato_id=NULL, protocolo_id=NULL, medicao_id=NULL, categoria='outros' "
                             "WHERE id=?", (o["id"],))
            antes = {"processos_siga_da_planilha": [o["numero"] for o in ocupantes], "medicao_id": medicao_id}
        conn.execute("UPDATE siga_processos SET contrato_id=?, protocolo_id=?, medicao_id=?, categoria='medicoes' "
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
            # #841: o SIGA as vezes devolve a lista vazia para um processo que tem historico. A leitura fica gravada
            # (o robo leu), marcada, e nao vale como situacao: nao apaga nada, nao muda os dias, nao encerra nem reabre
            vazia = not movs and conn.execute("SELECT 1 FROM siga_movimentacoes WHERE processo_id=? LIMIT 1",
                                              (pid,)).fetchone() is not None
            conn.execute("INSERT OR IGNORE INTO siga_leituras (processo_id, lido_em, situacao, sem_movimentacoes) "
                         "VALUES (?,?,?,?)", (pid, lido, situacao, int(vazia)))
            for mov in movs:
                novas += conn.execute(
                    "INSERT OR IGNORE INTO siga_movimentacoes (processo_id, data, evento, cad_lotacao, cad_pessoa, "
                    "at_lotacao, at_pessoa) VALUES (?,?,?,?,?,?,?)", (pid, *mov)).rowcount
            _vincular(conn, pid)
            _reabrir_com_movimentacao(conn, pid)
    return {"gravados": len(conferidos), "novas_movimentacoes": novas}


def _reabrir_com_movimentacao(conn, processo_id: int) -> None:
    """O encerrado a' mao volta sozinho com movimentacao posterior ao encerramento (#841), e isso fica registrado: a
    linha do encerramento ganha a data da reabertura e a movimentacao que a causou, e a auditoria, o ato sem usuario."""
    e = conn.execute("SELECT id, encerrado_em FROM siga_encerramentos WHERE processo_id=? AND reaberto_em IS NULL",
                     (processo_id,)).fetchone()
    if e is None:
        return
    movs = [dict(r) for r in conn.execute("SELECT data, evento FROM siga_movimentacoes WHERE processo_id=?",
                                          (processo_id,))]
    mov = movimentacao_depois(movs, e["encerrado_em"])
    if mov is None:
        return
    conn.execute("UPDATE siga_encerramentos SET reaberto_em=?, reaberto_pela_movimentacao=? WHERE id=?",
                 (_carimbo(tempo.agora_utc()), mov["data"], e["id"]))
    auditoria.registrar(conn, None, "siga.reabertura", "siga_processo", processo_id, {"encerramento_id": e["id"]},
                        {"pela_movimentacao": mov["data"], "evento": mov["evento"]})


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


def link_no_texto(texto: str | None) -> str | None:
    """O primeiro link de acompanhamento do SIGA escrito num texto livre (issue #667: o corpo da resposta do orgao), ou
    None. Candidato e' so' o que comeca no dominio do modelo de link; quem valida e' `extrair_codigo` (codigo solto no
    texto nao conta, nem link de outro dominio). Procura tambem no texto decodificado: a protecao de links do correio
    reescreve o link e leva o original codificado num parametro."""
    modelo = link_do_processo("x" * 6)
    host = urlsplit(modelo).hostname if modelo else None
    if not host or not texto:
        return None
    padrao = re.compile(r"(?<![\w.@/-])(?:https?://)?" + re.escape(host) + r"[^\s<>\"']*", re.IGNORECASE)
    for fonte in (texto, unquote(texto)):
        for achado in padrao.finditer(fonte):
            candidato = achado.group(0).rstrip(".,;:!)]}")
            try:
                if extrair_codigo(candidato):
                    return candidato
            except ValueError:
                continue
    return None


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
            conn.execute("UPDATE siga_processos SET contrato_id=NULL, protocolo_id=NULL, medicao_id=NULL, categoria='outros' "
                         "WHERE id=?", (proprio["id"],))
        alvo = _gravar_processo(conn, codigo, numero, nome)
        conn.execute("UPDATE siga_processos SET contrato_id=?, protocolo_id=?, medicao_id=?, categoria='medicoes' WHERE id=?",
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


def acompanhar_link_da_medicao(conn, usuario_id, medicao_id: int, link: str | None) -> int:
    """Link de acompanhamento colado no passo de analise da medicao (issue #668): cria (ou liga) o processo do codigo
    a' medicao, na categoria Medicoes, pelo caminho do link colado no protocolo da nota (`registrar_link_medicao`),
    com o nº do SIGA digitado na medicao (etapa 'planilha'), se houver. Abre a propria transacao (reentrante): serve
    tambem a quem acha o link sozinho, sem usuario (`usuario_id` None). Link invalido e codigo ligado a outra
    medicao: ValueError; medicao que nao existe: LookupError. -> id do processo."""
    codigo = extrair_codigo(link)
    if not codigo:
        raise ValueError(LINK_INVALIDO)
    with db.mutacao(conn):
        if conn.execute("SELECT 1 FROM medicoes WHERE id=?", (medicao_id,)).fetchone() is None:
            raise LookupError(MEDICAO_NAO_ENCONTRADA)
        linha = conn.execute("SELECT numero_processo FROM medicao_protocolos WHERE medicao_id=? AND etapa='planilha' "
                             "ORDER BY id LIMIT 1", (medicao_id,)).fetchone()
        registrar_link_medicao(conn, usuario_id, medicao_id, codigo, linha["numero_processo"] if linha else None)
        return conn.execute("SELECT id FROM siga_processos WHERE codigo=?", (codigo,)).fetchone()["id"]


def o_que_e(categoria: str, complemento: str | None, medicao_titulo: str | None) -> str:
    """A segunda parte do nome montado, "<obra> · <o que e'>" (#663): em Medicoes, o titulo da medicao; nas demais, a
    categoria no singular seguida do complemento ("Aditivo de prazo"). Em Outros o complemento vale sozinho."""
    if categoria == "medicoes":
        return medicao_titulo or "Medição"
    if categoria == "outros" and complemento:
        return complemento
    return " ".join(x for x in (SINGULAR[categoria], complemento) if x)


def _categoria(p) -> str:
    """Ligado a medicao ou a protocolo e' sempre Medicoes; senao, a gravada. "medicoes" gravado sem vinculo e' o
    processo cujo vinculo alguem desfez (#841): continua em Medicoes, a' espera da medicao."""
    if p["medicao_id"] is not None or p["protocolo_id"] is not None:
        return "medicoes"
    return p["categoria"]


# O robo manda o processo so' com o nome que ele tem na lista dele; o SIGA nao informa um tipo. Enquanto ninguem
# classifica, o processo ficava em Outros mesmo com o nome dizendo "7ª Medição", "Aditivo de prazo" ou
# "Indenizatório". A sugestao sai dessas palavras do nome, na ordem abaixo ("Aditivo de reajuste" e' aditivo), e so'
# da categoria: obra e medicao ninguem adivinha.
_SUGESTAO = (("indenizatorios", re.compile(r"indenizat", re.I)), ("aditivos", re.compile(r"aditiv", re.I)),
             ("medicoes", re.compile(r"medi[cç][aã]o|medi[cç][oõ]es|reajuste", re.I)))


def categoria_sugerida(nome: str | None) -> str | None:
    """A categoria que o nome do processo diz, ou None quando ele nao diz nenhuma (fica em Outros)."""
    return next((c for c, padrao in _SUGESTAO if padrao.search(nome or "")), None)


def _classificados_por_pessoa(conn) -> set[int]:
    """Os processos cuja categoria alguem ja' escolheu, ao acompanhar pela tela ou ao corrigir no historico (o
    registro da auditoria que traz a categoria). Neles a categoria gravada vale, mesmo sendo Outros: a sugestao nao
    volta. O link colado na tela antes das categorias (#339, ate' 11/11/2026) gravou o mesmo registro so' com o nome
    digitado, sem categoria: ali ninguem escolheu, e o processo segue o nome como o que o robo mandou."""
    return {int(r[0]) for r in conn.execute(
        "SELECT DISTINCT entidade_id FROM audit_log WHERE entidade='siga_processo' "
        "AND acao IN ('siga.classificacao', 'protocolo.siga') "
        "AND json_extract(depois, '$.categoria') IS NOT NULL") if str(r[0]).isdigit()}


def categoria_a_conferir(categoria: str, escolhida: bool, ligado: bool, nome_mostrado: str | None) -> str | None:
    """A categoria que o nome mostrado na tela indica, quando ela nao e' a que a pessoa escolheu (#805): "Outros" com
    o complemento "Aditivo de prazo", por exemplo. So' leitura: a tela avisa "categoria a conferir" e quem edita
    corrige no historico; nada e' gravado nem trocado de secao. None quando o nome nao indica outra, quando a
    categoria veio do vinculo com a medicao (`ligado`) ou quando ninguem escolheu ainda (ai' vale a sugestao)."""
    if ligado or not escolhida:
        return None
    indicada = categoria_sugerida(nome_mostrado)
    return indicada if indicada and indicada != categoria else None


def situacao_do_tempo(dias_sem_movimentacao: int | None, hoje: int) -> str | None:
    """A regua da familia "tempo parado" (docs/identidade-visual.md) sobre os dias uteis SEM MOVIMENTACAO de
    `derivar` (#840; nao o tempo no setor): andou hoje e' `feito`; `critico` a partir de `DIAS_ACAO`; `breve` a
    partir de `DIAS_ATENCAO`; antes disso, `andamento`. Sem movimentacao nenhuma, None."""
    if hoje > 0:
        return "feito"
    if dias_sem_movimentacao is None:
        return None
    if dias_sem_movimentacao >= DIAS_ACAO:
        return "critico"
    return "breve" if dias_sem_movimentacao >= DIAS_ATENCAO else "andamento"


def parado(derivado: dict) -> str | None:
    """A leitura unica de "parado" de um processo (#840), sobre o que `derivar` devolve: a da linha da tela SIGA, da
    faixa de numeros, do aviso `siga_parado`, da posicao na medicao e do protocolo. A tela nao calcula.
    #841: o processo sobrestado (suspenso pelo orgao) le `sobrestado`: nao e' atraso, nao conta nos parados nem avisa."""
    if derivado.get("sobrestado"):
        return "sobrestado"
    return situacao_do_tempo(derivado["dias_sem_movimentacao"], derivado["hoje"])


def _titulo_das_medicoes(conn, medicao_id: int | None, protocolo_id: int | None) -> str | None:
    """Titulo da medicao do processo; ligado so' ao protocolo (medicao e reajuste juntos), os titulos com " e "."""
    if medicao_id is not None:
        ms = conn.execute("SELECT numero, tipo FROM medicoes WHERE id=?", (medicao_id,)).fetchall()
    elif protocolo_id is not None:
        ms = conn.execute("SELECT m.numero, m.tipo FROM protocolo_medicoes pm JOIN medicoes m ON m.id=pm.medicao_id "
                          "WHERE pm.protocolo_id=? ORDER BY m.tipo='reajuste', m.id", (protocolo_id,)).fetchall()
    else:
        return None
    return " e ".join(medicoes.titulo(dict(m)) for m in ms) or None


def _classificacao(conn, categoria: str | None, contrato_id: int | None, medicao_id: int | None,
                   complemento: str | None) -> tuple[str, int | None, int | None, str | None]:
    """Confere o que o formulario manda (#663): categoria fechada; obra obrigatoria, menos em Outros; medicao so' em
    Medicoes, obrigatoria e da obra. -> (categoria, contrato, medicao, complemento sem espaco nas pontas ou None)."""
    if categoria not in CATEGORIAS:
        raise ValueError(CATEGORIA_INVALIDA)
    complemento = _texto(complemento) or None
    if complemento and len(complemento) > MAX_COMPLEMENTO:
        raise ValueError(COMPLEMENTO_LONGO)
    if contrato_id is None:
        if categoria != "outros":
            raise ValueError(OBRA_OBRIGATORIA)
    elif conn.execute("SELECT 1 FROM contratos WHERE id=?", (contrato_id,)).fetchone() is None:
        raise ValueError(OBRA_INEXISTENTE)
    if categoria != "medicoes":
        if medicao_id is not None:
            raise ValueError(MEDICAO_FORA_DA_CATEGORIA)
    elif medicao_id is None:
        raise ValueError(MEDICAO_OBRIGATORIA)
    elif conn.execute("SELECT 1 FROM medicoes WHERE id=? AND contrato_id=?", (medicao_id, contrato_id)).fetchone() is None:
        raise ValueError(MEDICAO_INEXISTENTE)
    return categoria, contrato_id, medicao_id, complemento


def _nome_montado(conn, categoria: str, contrato_id: int | None, medicao_id: int | None,
                  complemento: str | None) -> str | None:
    """O nome gravado quando a pessoa cadastra (e' o que o robo recebe): "<obra> · <o que e'>"; sem obra, o
    complemento."""
    if contrato_id is None:
        return complemento
    return f"{_obra(conn, contrato_id)} · {o_que_e(categoria, complemento, _titulo_das_medicoes(conn, medicao_id, None))}"


def acompanhar_avulso(conn, usuario_id, link: str | None, numero: str | None, categoria: str | None,
                      contrato_id: int | None, medicao_id: int | None = None, complemento: str | None = None) -> int:
    """Link colado na tela SIGA (issue #339), com categoria, obra, medicao e complemento (#663): ninguem digita o
    nome, o sistema monta. Em Medicoes o processo nasce ligado a' medicao escolhida (sem protocolo). Codigo ja'
    acompanhado e' recusado (`JaAcompanhado`, com o nome existente). Processo que o robo ja' mandou so' pelo numero
    igual ganha o codigo e a classificacao. -> id do processo."""
    codigo = extrair_codigo(link)
    if not codigo:
        raise ValueError(LINK_INVALIDO)
    numero = sem_espacos(numero) or None
    with db.mutacao(conn):
        categoria, contrato_id, medicao_id, complemento = _classificacao(conn, categoria, contrato_id, medicao_id,
                                                                        complemento)
        existente = conn.execute("SELECT nome FROM siga_processos WHERE codigo=?", (codigo,)).fetchone()
        if existente is not None:
            raise JaAcompanhado(existente["nome"])
        # Processo que o robo ja' mandou so' pelo numero: ganha o codigo e a classificacao se estiver livre; ligado a
        # um protocolo ou a uma medicao, nao e' avulso e nao se reescreve por aqui.
        achado = _achar_processo(conn, codigo, numero)
        antes = None
        if achado is not None:
            if achado["protocolo_id"] is not None or achado["medicao_id"] is not None:
                raise ValueError(LIGADO_A_OUTRO)
            antes = {"codigo": achado["codigo"], "numero": achado["numero"], "nome": achado["nome"],
                     "contrato_id": achado["contrato_id"], "categoria": achado["categoria"],
                     "complemento": achado["complemento"]}
            contrato_id = contrato_id if contrato_id is not None else achado["contrato_id"]
        nome = _nome_montado(conn, categoria, contrato_id, medicao_id, complemento)
        pid = _gravar_processo(conn, codigo, numero, nome)
        # sem nome montado (Outros sem obra nem complemento), fica o que o robo mandou
        conn.execute("UPDATE siga_processos SET nome=COALESCE(?, nome), contrato_id=?, medicao_id=?, categoria=?, "
                     "complemento=? WHERE id=?", (nome, contrato_id, medicao_id, categoria, complemento, pid))
        auditoria.registrar(conn, usuario_id, "protocolo.siga", "siga_processo", pid, antes,
                            {"codigo": codigo, "numero": numero, "nome": nome, "contrato_id": contrato_id,
                             "medicao_id": medicao_id, "categoria": categoria, "complemento": complemento})
    return pid


def classificar(conn, usuario_id, processo_id: int, categoria: str | None, contrato_id: int | None,
                medicao_id: int | None, complemento: str | None) -> None:
    """Correcao de categoria, obra e complemento na pagina do historico (#663). Passando a Medicoes, o processo fica
    ligado a' medicao escolhida (e encerra quando ela for recebida); saindo de Medicoes, perde a medicao. O processo
    ligado a um protocolo enviado pelo sistema nao muda por aqui. O nome que o robo mandou nao e' tocado. Cada
    correcao vai para a auditoria."""
    with db.mutacao(conn):
        p = conn.execute("SELECT * FROM siga_processos WHERE id=?", (processo_id,)).fetchone()
        if p is None:
            raise LookupError(PROCESSO_INEXISTENTE)
        if p["protocolo_id"] is not None:
            raise ValueError(LIGADO_A_PROTOCOLO)
        categoria, contrato_id, medicao_id, complemento = _classificacao(conn, categoria, contrato_id, medicao_id,
                                                                        complemento)
        campos = ("categoria", "contrato_id", "medicao_id", "complemento")
        antes = {**{c: p[c] for c in campos}, "categoria": _categoria(p)}
        depois = dict(zip(campos, (categoria, contrato_id, medicao_id, complemento)))
        conn.execute("UPDATE siga_processos SET categoria=?, contrato_id=?, medicao_id=?, complemento=? WHERE id=?",
                     (categoria, contrato_id, medicao_id, complemento, processo_id))
        # #841: a medicao escolhida aqui e' o mesmo vinculo da tela: quem e quando (sem medicao, nao ha' vinculo)
        if medicao_id != p["medicao_id"]:
            por, em = (usuario_id, _carimbo(tempo.agora_utc())) if medicao_id is not None else (None, None)
            conn.execute("UPDATE siga_processos SET medicao_vinculada_por=?, medicao_vinculada_em=? WHERE id=?",
                         (por, em, processo_id))
        auditoria.registrar(conn, usuario_id, "siga.classificacao", "siga_processo", processo_id, antes, depois)


# --- vinculo com a medicao, encerramento a' mao e pendencia do protocolo novo (issue #841) --------------------

MAX_MOTIVO_ENCERRAMENTO = 200
MOTIVO_OBRIGATORIO = "Escreva o motivo do encerramento"
MOTIVO_LONGO = f"Motivo com mais de {MAX_MOTIVO_ENCERRAMENTO} caracteres"
JA_ENCERRADO = "Este processo já está encerrado"
NAO_ENCERRADO_A_MAO = "Só o processo encerrado à mão se reabre por aqui"
SEM_VINCULO = "Este processo não está ligado a uma medição"
ROTULO_MOTIVO = {"recebida": "medição recebida", "arquivado": "arquivado", "juntado": "juntado a outro processo",
                 "manual": "encerrado à mão"}


def vincular_medicao(conn, usuario_id: int, processo_id: int, medicao_id: int) -> None:
    """Liga o processo a' medicao pela tela (#841): o mesmo vinculo da #663 (`siga_processos.medicao_id`), com quem e
    quando. A obra do processo passa a ser a da medicao e a categoria, Medicoes. Ligado a' medicao recebida, o processo
    encerra sozinho (`_encerramento`). O processo de protocolo enviado pelo sistema ja' tem o vinculo dele e nao muda
    por aqui."""
    with db.mutacao(conn):
        p = conn.execute("SELECT * FROM siga_processos WHERE id=?", (processo_id,)).fetchone()
        if p is None:
            raise LookupError(PROCESSO_INEXISTENTE)
        if p["protocolo_id"] is not None:
            raise ValueError(LIGADO_A_PROTOCOLO)
        m = conn.execute("SELECT id, contrato_id FROM medicoes WHERE id=?", (medicao_id,)).fetchone()
        if m is None:
            raise ValueError(MEDICAO_NAO_ENCONTRADA)
        antes = {"categoria": _categoria(p), "contrato_id": p["contrato_id"], "medicao_id": p["medicao_id"]}
        conn.execute("UPDATE siga_processos SET medicao_id=?, contrato_id=?, categoria='medicoes', "
                     "medicao_vinculada_por=?, medicao_vinculada_em=? WHERE id=?",
                     (medicao_id, m["contrato_id"], usuario_id, _carimbo(tempo.agora_utc()), processo_id))
        auditoria.registrar(conn, usuario_id, "siga.vinculo_medicao", "siga_processo", processo_id, antes,
                            {"categoria": "medicoes", "contrato_id": m["contrato_id"], "medicao_id": medicao_id})


def desfazer_vinculo(conn, usuario_id: int, processo_id: int) -> None:
    """Desfaz o vinculo com a medicao (#841). O processo continua em Medicoes, com a obra, a' espera da medicao certa;
    o robo nao o religa pelo numero igual (`_vincular`). O de protocolo enviado pelo sistema nao se desfaz por aqui."""
    with db.mutacao(conn):
        p = conn.execute("SELECT * FROM siga_processos WHERE id=?", (processo_id,)).fetchone()
        if p is None:
            raise LookupError(PROCESSO_INEXISTENTE)
        if p["protocolo_id"] is not None:
            raise ValueError(LIGADO_A_PROTOCOLO)
        if p["medicao_id"] is None:
            raise ValueError(SEM_VINCULO)
        conn.execute("UPDATE siga_processos SET medicao_id=NULL, categoria='medicoes', medicao_vinculada_por=NULL, "
                     "medicao_vinculada_em=NULL WHERE id=?", (processo_id,))
        auditoria.registrar(conn, usuario_id, "siga.vinculo_desfeito", "siga_processo", processo_id,
                            {"medicao_id": p["medicao_id"], "medicao_vinculada_por": p["medicao_vinculada_por"],
                             "medicao_vinculada_em": p["medicao_vinculada_em"]}, {"medicao_id": None})


def _motivo_do_processo(conn, processo_id: int) -> str | None:
    p = conn.execute("SELECT m.estado FROM siga_processos sp LEFT JOIN medicoes m ON m.id=sp.medicao_id "
                     "WHERE sp.id=?", (processo_id,)).fetchone()
    movs = [dict(r) for r in conn.execute("SELECT data, evento FROM siga_movimentacoes WHERE processo_id=?",
                                          (processo_id,))]
    manual = _manuais(conn).get(processo_id)
    return _encerramento(p["estado"], _situacoes(conn, [processo_id]).get(processo_id), movs,
                         manual["encerrado_em"] if manual else None)


def encerrar(conn, usuario_id: int, processo_id: int, motivo: str | None) -> None:
    """"Encerrar processo" a' mao, com motivo curto (#841), para o que nao tem sinal automatico. Guarda quem, quando e
    o motivo. O robo continua lendo o processo, que volta sozinho com movimentacao posterior."""
    motivo = _texto(motivo)
    if not motivo:
        raise ValueError(MOTIVO_OBRIGATORIO)
    if len(motivo) > MAX_MOTIVO_ENCERRAMENTO:
        raise ValueError(MOTIVO_LONGO)
    with db.mutacao(conn):
        if conn.execute("SELECT 1 FROM siga_processos WHERE id=?", (processo_id,)).fetchone() is None:
            raise LookupError(PROCESSO_INEXISTENTE)
        if _motivo_do_processo(conn, processo_id) is not None:
            raise JaEncerrado(JA_ENCERRADO)
        # encerramento antigo em aberto que uma movimentacao ja' venceu: registra a volta antes de encerrar de novo
        _reabrir_com_movimentacao(conn, processo_id)
        agora = _carimbo(tempo.agora_utc())
        eid = conn.execute("INSERT INTO siga_encerramentos (processo_id, motivo, encerrado_por, encerrado_em) "
                           "VALUES (?,?,?,?)", (processo_id, motivo, usuario_id, agora)).lastrowid
        auditoria.registrar(conn, usuario_id, "siga.encerramento", "siga_processo", processo_id, None,
                            {"encerramento_id": eid, "motivo": motivo, "encerrado_em": agora})


def reabrir(conn, usuario_id: int, processo_id: int) -> None:
    """"Reabrir" na secao Encerrados (#841): so' o encerrado a' mao; o automatico segue a regra (a medicao recebida, o
    arquivamento e a juntada so' se desfazem no proprio sinal)."""
    with db.mutacao(conn):
        if conn.execute("SELECT 1 FROM siga_processos WHERE id=?", (processo_id,)).fetchone() is None:
            raise LookupError(PROCESSO_INEXISTENTE)
        e = conn.execute("SELECT id FROM siga_encerramentos WHERE processo_id=? AND reaberto_em IS NULL",
                         (processo_id,)).fetchone()
        if e is None or _motivo_do_processo(conn, processo_id) != "manual":
            raise NaoEncerradoAMao(NAO_ENCERRADO_A_MAO)
        agora = _carimbo(tempo.agora_utc())
        conn.execute("UPDATE siga_encerramentos SET reaberto_em=?, reaberto_por=? WHERE id=?", (agora, usuario_id, e["id"]))
        auditoria.registrar(conn, usuario_id, "siga.reabertura", "siga_processo", processo_id,
                            {"encerramento_id": e["id"]}, {"reaberto_em": agora})


class JaEncerrado(ValueError):
    """Encerrar o que ja' esta' encerrado (409)."""


class NaoEncerradoAMao(ValueError):
    """Reabrir o que nao foi encerrado a' mao (409)."""


# A proposta de medicao (#841): pela obra e pelo numero que aparecem no nome do processo. "7ª Medição", "Reajuste da
# 15ª Medição", "3ª Medição de Projeto"; a obra pelo nº do instrumento ("IC 082/2025" casa com "082/2025/00/00-...")
# ou pelo nome curto escrito por inteiro. Sem obra unica ou sem medicao unica, nao ha' proposta: a pessoa escolhe.
_NUMERO_MEDICAO = re.compile(r"(?:(reajuste)\s+d[ao]\s+)?(\d{1,3})\s*[ªºa°o]?\s*medi[cç][aã]o(\s+de\s+projeto)?", re.I)
_INSTRUMENTO_NO_NOME = re.compile(r"(?<![\d/-])0*(\d{1,4})\s*/\s*(\d{4})(?!\d)")
_INSTRUMENTO = re.compile(r"^\s*0*(\d{1,4})\s*/\s*(\d{4})(?!\d)")


def _palavras(texto: str | None) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", _sem_acento(texto)).strip() + " "


def _obras_do_nome(nome: str | None, contratos: list) -> set[int]:
    instrumentos = {(int(n), a) for n, a in _INSTRUMENTO_NO_NOME.findall(nome or "")}
    no_nome = _palavras(nome)
    achadas = set()
    for c in contratos:
        i = _INSTRUMENTO.match(c["numero_instrumento"] or "")
        if i and (int(i.group(1)), i.group(2)) in instrumentos:
            achadas.add(c["id"])
        curto = _palavras(c["nome_curto"]).strip()
        if len(curto) >= 3 and f" {curto} " in no_nome:
            achadas.add(c["id"])
    return achadas


def _medicao_do_nome(nome: str | None) -> tuple[int, str] | None:
    """(numero, tipo) da primeira medicao escrita no nome; "7ª Medição/Reajuste" propoe a medicao (o reajuste vai no
    mesmo processo, e o vinculo e' de uma medicao so')."""
    achado = _NUMERO_MEDICAO.search(nome or "")
    if not achado:
        return None
    tipo = "reajuste" if achado.group(1) else "projeto" if achado.group(3) else "execucao"
    return int(achado.group(2)), tipo


def propostas_de_medicao(conn, processos: list) -> dict[int, dict]:
    """{processo: medicao proposta} para os processos de Medicoes sem medicao e sem protocolo (#841). `processos`: as
    linhas com id, nome, contrato_id, medicao_id e protocolo_id. A proposta so' sai com obra unica e medicao unica."""
    contratos = conn.execute("SELECT id, numero_instrumento, nome_curto FROM contratos").fetchall()
    out = {}
    for p in processos:
        if p["medicao_id"] is not None or p["protocolo_id"] is not None:
            continue
        alvo = _medicao_do_nome(p["nome"])
        if alvo is None:
            continue
        obras = {p["contrato_id"]} if p["contrato_id"] is not None else _obras_do_nome(p["nome"], contratos)
        if len(obras) != 1:
            continue
        ms = conn.execute("SELECT m.id, m.numero, m.tipo, m.contrato_id, m.estado FROM medicoes m WHERE m.contrato_id=? "
                          "AND m.numero=? AND m.tipo=? AND m.estado NOT IN ('cancelada', 'desistida')",
                          (next(iter(obras)), *alvo)).fetchall()
        if len(ms) == 1:
            m = dict(ms[0])
            out[p["id"]] = {"id": m["id"], "contrato_id": m["contrato_id"], "titulo": medicoes.titulo(m),
                            "obra": _obra(conn, m["contrato_id"]), "estado": m["estado"]}
    return out


def protocolo_novo_pendente(conn, medicao_ids) -> set[int]:
    """As medicoes que pedem o protocolo novo (#841): a medicao ainda nao recebida (nem cancelada ou desistida) cujos
    processos do SIGA, todos, foram arquivados ou juntados. Em algumas superintendencias o pleito, curto, e' arquivado
    quando o processo da medicao e' aberto, com outro codigo: o processo sai do quadro e a medicao pede o novo. Ligado
    pela medicao ou pelo protocolo que a leva, como em `posicao_das_medicoes`."""
    medicoes_de: dict[int, set[int]] = {}
    estados = {}
    for lote in _em_lotes(medicao_ids):
        marcas = ",".join("?" * len(lote))
        for r in conn.execute(f"SELECT id, estado FROM medicoes WHERE id IN ({marcas})", lote):
            estados[r[0]] = r[1]
        for r in conn.execute(
                f"SELECT id, medicao_id FROM siga_processos WHERE medicao_id IN ({marcas}) "
                "UNION SELECT sp.id, pm.medicao_id FROM siga_processos sp "
                f"JOIN protocolo_medicoes pm ON pm.protocolo_id=sp.protocolo_id WHERE pm.medicao_id IN ({marcas})",
                [*lote, *lote]):
            medicoes_de.setdefault(r[0], set()).add(r[1])
    if not medicoes_de:
        return set()
    situacoes, manuais = _situacoes(conn, medicoes_de), _manuais(conn)
    movs_de: dict[int, list] = {}
    for lote in _em_lotes(sorted(medicoes_de)):
        for r in conn.execute(f"SELECT processo_id, data, evento FROM siga_movimentacoes "
                              f"WHERE processo_id IN ({','.join('?' * len(lote))})", lote):
            movs_de.setdefault(r["processo_id"], []).append(dict(r))
    motivos_da: dict[int, list[str | None]] = {}
    for pid, mids in medicoes_de.items():
        manual = manuais.get(pid)
        motivo = _encerramento(None, situacoes.get(pid), movs_de.get(pid, []), manual["encerrado_em"] if manual else None)
        for mid in mids:
            motivos_da.setdefault(mid, []).append(motivo)
    return {mid for mid, motivos in motivos_da.items()
            if estados.get(mid) not in ("recebida", "cancelada", "desistida")
            and all(m in ("arquivado", "juntado") for m in motivos)}


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
             "dias_uteis": None, "dias_sem_movimentacao": None, "situacao_tempo": None, "lido_em": None,
             "registrado_em": registrado_em(conn, "protocolo", [protocolo_id]).get(protocolo_id)}
    leitura = conn.execute("SELECT situacao, lido_em FROM siga_leituras WHERE processo_id=? "
                           "ORDER BY lido_em DESC, id DESC LIMIT 1", (p["id"],)).fetchone()
    if leitura is not None:
        movs = [dict(r) for r in conn.execute("SELECT data, evento, at_lotacao, at_pessoa FROM siga_movimentacoes "
                                              "WHERE processo_id=?", (p["id"],))]
        # a situacao e' a da ultima leitura que vale (#841: a leitura vazia nao conta); `lido_em`, a da ultima leitura
        d = derivar(_situacoes(conn, [p["id"]]).get(p["id"]), movs, hoje or tempo.hoje_local())
        saida.update(setor=d["setor"] or None, com_quem=d["com_quem"] or None, dias_uteis=d["dias_uteis"],
                     dias_sem_movimentacao=d["dias_sem_movimentacao"], situacao_tempo=parado(d),
                     lido_em=tempo.iso_utc(leitura["lido_em"]))
    return saida


def _em_lotes(ids, tamanho: int = 500):
    ids = list(ids)
    for i in range(0, len(ids), tamanho):
        yield ids[i:i + tamanho]


def _mais_parado(posicao: dict) -> tuple:
    """Chave de ordem da tela SIGA (`ordenar` em siga.ts), pela leitura de "parado" (#840): mais dias uteis sem
    movimentacao, depois a ultima movimentacao mais antiga; sem movimentacao nenhuma, no fim. #841: o sobrestado
    nao esta' parado: vai depois dos outros."""
    dias = posicao["dias_sem_movimentacao"]
    return (posicao.get("situacao_tempo") == "sobrestado", -(dias if dias is not None else -1),
            posicao["ultima_em"] or "9", posicao["processo_id"])


def mais_parado(posicoes: list[dict]) -> dict | None:
    return min(posicoes, key=_mais_parado, default=None)


def posicao_das_medicoes(conn, medicao_ids, hoje: datetime.date) -> dict[int, dict]:
    """Issue #664: {medicao: posicao do processo vivo ligado a ela}, para o quadro do mes. Ligado pela medicao ou
    pelo protocolo que a leva. Fica de fora o processo encerrado (`_encerramento`), o que ainda nao foi lido e o que
    nao tem setor na situacao. Com mais de um processo vivo na medicao, o mais parado. Setor, entrada, dias uteis e
    movimentacoes de hoje sao os de `derivar`, os mesmos da tela SIGA; "mais parado" e' o de `_mais_parado` (#840). Le as movimentacoes de todos os processos numa consulta por lote."""
    medicoes_de: dict[int, set[int]] = {}
    for lote in _em_lotes(medicao_ids):
        marcas = ",".join("?" * len(lote))
        for r in conn.execute(
                f"SELECT id, medicao_id FROM siga_processos WHERE medicao_id IN ({marcas}) "
                "UNION SELECT sp.id, pm.medicao_id FROM siga_processos sp "
                f"JOIN protocolo_medicoes pm ON pm.protocolo_id=sp.protocolo_id WHERE pm.medicao_id IN ({marcas})",
                [*lote, *lote]):
            medicoes_de.setdefault(r[0], set()).add(r[1])
    lidos, movs_de = {}, {}
    manuais = _manuais(conn)
    for lote in _em_lotes(sorted(medicoes_de)):
        marcas = ",".join("?" * len(lote))
        # a situacao da ultima leitura que vale (#841: a leitura vazia nao conta)
        for r in conn.execute(
                "SELECT sp.id, m.estado, l.situacao FROM siga_processos sp "
                "JOIN siga_leituras l ON l.id=(SELECT u.id FROM siga_leituras u WHERE u.processo_id=sp.id "
                "AND u.sem_movimentacoes=0 ORDER BY u.lido_em DESC, u.id DESC LIMIT 1) "
                f"LEFT JOIN medicoes m ON m.id=sp.medicao_id WHERE sp.id IN ({marcas})", lote):
            lidos[r["id"]] = (r["estado"], r["situacao"])
    for lote in _em_lotes(sorted(lidos)):
        for r in conn.execute("SELECT processo_id, data, evento, at_lotacao, at_pessoa FROM siga_movimentacoes "
                              f"WHERE processo_id IN ({','.join('?' * len(lote))})", lote):
            movs_de.setdefault(r["processo_id"], []).append(dict(r))
    candidatas: dict[int, list[dict]] = {}
    for pid, (estado, situacao) in lidos.items():
        movs = movs_de.get(pid, [])
        manual = manuais.get(pid)
        if _encerramento(estado, situacao, movs, manual["encerrado_em"] if manual else None):
            continue
        d = derivar(situacao, movs, hoje)
        if not d["setor"]:
            continue
        posicao = {"processo_id": pid, "setor": d["setor"], "dias_uteis": d["dias_uteis"],
                   "desde": tempo.iso_local(d["desde"]) if d["desde"] else None, "hoje": d["hoje"],
                   "dias_sem_movimentacao": d["dias_sem_movimentacao"],
                   "ultima_em": tempo.iso_local(d["ultima"]["data"]) if d["ultima"] else None,
                   "situacao_tempo": parado(d)}
        for mid in medicoes_de[pid]:
            candidatas.setdefault(mid, []).append(posicao)
    return {mid: mais_parado(posicoes) for mid, posicoes in candidatas.items()}


# --- leitura -----------------------------------------------------------------------------------------------

def processos_para_o_robo(conn) -> list[dict]:
    """O que o robo acompanha: os processos vivos. O encerrado (#657) sai da lista; o encerrado a' mao fica (#841)."""
    fora = fora_do_robo(conn)
    return [{k: r[k] for k in ("codigo", "numero", "nome")}
            for r in conn.execute("SELECT id, codigo, numero, nome FROM siga_processos ORDER BY id") if r["id"] not in fora]


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
    classificados = _classificados_por_pessoa(conn)
    obras = medicoes._obras_com_contratante(conn)
    situacoes, manuais = _situacoes(conn), _manuais(conn)
    linhas = conn.execute(
        "SELECT sp.*, c.nome_curto, c.numero_instrumento, m.numero AS m_numero, m.tipo AS m_tipo, "
        "m.estado AS m_estado, u.nome AS vinculado_por "
        "FROM siga_processos sp LEFT JOIN contratos c ON c.id=sp.contrato_id "
        "LEFT JOIN medicoes m ON m.id=sp.medicao_id LEFT JOIN usuarios u ON u.id=sp.medicao_vinculada_por "
        "ORDER BY sp.id").fetchall()
    propostas = propostas_de_medicao(conn, linhas)
    for p in linhas:
        situacao = situacoes.get(p["id"])
        movs = [dict(r) for r in conn.execute(
            "SELECT data, evento, cad_lotacao, cad_pessoa, at_lotacao, at_pessoa FROM siga_movimentacoes "
            "WHERE processo_id=? ORDER BY data DESC, id DESC", (p["id"],))]
        derivado = derivar(situacao, movs, hoje)
        manual = manuais.get(p["id"])
        encerrado = _encerramento(p["m_estado"], situacao, movs, manual["encerrado_em"] if manual else None)
        # Na resposta, todo instante com o fuso explicito: as datas do SIGA sao de Cuiaba, o lido_em e' UTC
        movs = [{**m, "data": tempo.iso_local(m["data"]), "tipo": tipo_da_movimentacao(m["evento"])} for m in movs]
        for campo in ("desde", "protocolado_em"):
            if derivado[campo]:
                derivado[campo] = tempo.iso_local(derivado[campo])
        if derivado["ultima"]:
            derivado["ultima"] = {**derivado["ultima"], "data": tempo.iso_local(derivado["ultima"]["data"])}
        categoria = _categoria(p)
        # em Outros sem ninguem ter escolhido: a secao da tela e' a que o nome do processo diz, marcada como sugerida
        # ate' alguem confirmar ou corrigir no historico (nada e' gravado por aqui)
        sugerida = categoria_sugerida(p["nome"]) if categoria == "outros" and p["id"] not in classificados else None
        categoria = sugerida or categoria
        medicao_titulo = medicoes.titulo({"numero": p["m_numero"], "tipo": p["m_tipo"]}) if p["medicao_id"] \
            else _titulo_das_medicoes(conn, None, p["protocolo_id"])
        assunto = o_que_e(categoria, p["complemento"], medicao_titulo)
        obra = obras.get(p["contrato_id"]) if p["contrato_id"] else None
        saida.append({
            "id": p["id"], "codigo": p["codigo"], "link": link_do_processo(p["codigo"]), "numero": p["numero"], "nome": p["nome"],
            "contrato_id": p["contrato_id"],
            "obra": (p["nome_curto"] or p["numero_instrumento"]) if p["contrato_id"] else None,
            # o contratante da obra, como em Medicoes e em Obras ("SINFRA", "SUEF II"); processo sem obra nao tem
            "contratante": obra["contratante"] if obra else None, "orgao_sub": obra["orgao_sub"] if obra else None,
            "medicao_id": p["medicao_id"], "medicao_titulo": medicao_titulo,
            "categoria": categoria, "categoria_sugerida": sugerida is not None, "complemento": p["complemento"],
            # o nome que a tela mostra diz outra categoria que a escolhida: aviso na linha, nada muda (#805)
            "categoria_a_conferir": categoria_a_conferir(
                categoria, sugerida is None, p["medicao_id"] is not None or p["protocolo_id"] is not None,
                assunto if p["contrato_id"] else p["complemento"] or p["nome"]),
            "o_que_e": assunto,
            "protocolo_id": p["protocolo_id"], "situacao": situacao, "encerrado": encerrado,
            # #841: o encerrado a' mao diz o motivo, quem e quando; o vinculo pela tela, quem e quando; e o processo de
            # Medicoes sem medicao traz a medicao que o nome indica (a pessoa confirma ou troca)
            "encerramento": {"motivo": manual["motivo"], "por": manual["por"],
                             "em": tempo.iso_utc(manual["encerrado_em"])} if encerrado == "manual" else None,
            "vinculo": {"por": p["vinculado_por"], "em": tempo.iso_utc(p["medicao_vinculada_em"])}
            if p["medicao_id"] is not None and p["medicao_vinculada_em"] else None,
            "medicao_proposta": propostas.get(p["id"]) if categoria == "medicoes" else None,
            **derivado,
            # o encerrado (#657) nao esta' parado nem andando: sem leitura de tempo
            "situacao_tempo": None if encerrado else parado(derivado),
            "movimentacoes": movs,
        })
    fora = {p["id"]: p["encerrado"] for p in saida if p["encerrado"]}
    robo = situacao_robo(conn, agora, fora)
    vivos = [p for p in saida if not p["encerrado"]]
    nao_lidos = {a["processo_id"] for a in robo["avisos"] if a["tipo"] == "nao_lido"}
    return {"lido_em": tempo.iso_utc(lido_em) if lido_em else None,
            "atrasado": atrasado(_leitura_dos_vivos(conn, fora), agora),
            "processos": saida, "pode_atualizar": bool(tarefa_do_robo()), "robo": robo,
            # a faixa de numeros da tela (#805): so' os vivos, pela mesma leitura que pinta a linha. "Parados" sao os
            # criticos (`DIAS_ACAO` dias uteis ou mais sem movimentacao, #840); "nao lidos", os que levam o aviso na linha
            "numeros": {"acompanhados": len(vivos),
                        "parados": sum(p["situacao_tempo"] == "critico" for p in vivos),
                        "andaram_hoje": sum(p["hoje"] > 0 for p in vivos),
                        "nao_lidos": sum(p["id"] in nao_lidos for p in vivos)},
            "limites": {"dias_atencao": DIAS_ATENCAO, "dias_critico": DIAS_ACAO}}


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


def _novos(conn) -> set[int]:
    """Processos que acabaram de entrar: sem leitura nenhuma e que nenhuma rodada chamou ainda. O processo novo e'
    lido na pergunta seguinte do robo, sem esperar a rodada da hora (decisao do dono em 17/11/2026). Vale uma vez:
    chamado por uma rodada, mesmo sem ter sido lido, deixa de ser novo e segue na rodada da hora, para o codigo que
    nao abre nao virar uma entrada no SIGA a cada pergunta."""
    return {r[0] for r in conn.execute(
        "SELECT p.id FROM siga_processos p WHERE NOT EXISTS (SELECT 1 FROM siga_leituras l WHERE l.processo_id=p.id) "
        "AND NOT EXISTS (SELECT 1 FROM siga_rodadas r, json_each(r.processos) j WHERE j.value=p.id)")}


def iniciar_rodada(conn, agora: datetime.datetime | None = None, so_pedidos: bool = False) -> dict:
    """"Comecei" do robo: o servidor decide o que ler. Completa (todos os processos vivos; o encerrado so' entra
    com pedido da pessoa para ele, #657) com pedido "todos" em aberto, ou quando a ultima rodada completa terminada
    comecou ha' 59 minutos ou mais (ou nunca houve): e' a rodada automatica, no maximo uma por hora. Senao, so' os
    processos dos pedidos em aberto e os novos (`_novos`), que valem a qualquer hora. Os pedidos em aberto ficam
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
            fora = fora_do_robo(conn) if completa else {}
            chamados = pedidos | _novos(conn)
            processos = [p for p in todos if (completa and p["id"] not in fora) or p["id"] in chamados]
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


def situacao_robo(conn, agora: datetime.datetime | None = None, fora: dict[int, str] | None = None) -> dict:
    """Bloco `robo` da tela SIGA. `estado`: `lendo` (rodada em andamento), `na_fila` (pedido em aberto sem rodada) ou
    `parado`. Os avisos de rodada valem ate' a proxima rodada terminar sem aquele problema (a falha e os nao lidos
    sao os da ultima rodada terminada; a rodada sem fim avisa ate' uma seguinte terminar); o do disparo, ate' o
    proximo disparo aceito. O "nao lido" de um processo (e o resumo deles) so' aparece com o processo vivo ha' mais
    de 2 horas uteis sem leitura que deu certo (#657), pela regra de `atrasado`; o que nunca foi lido avisa logo.
    `fora`: os encerrados, quando quem chama ja' os tem."""
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
        fora = encerrados(conn) if fora is None else fora
        lidos = _ultimas_leituras(conn)
        # o processo que a dashboard nao conhece (sem id) nao tem leitura para medir: avisa como antes
        nao_lidos = [n for n in json.loads(ultima["nao_lidos"]) if n["processo_id"] is None or (
            n["processo_id"] not in fora
            and (n["processo_id"] not in lidos or atrasado(lidos[n["processo_id"]], agora)))]
        hora = _hora(ultima["iniciada_em"])
        # o processo que a dashboard nao conhece vai identificado no texto, porque nao ha' linha da tela para ele
        avisos += [_aviso_robo("nao_lido", ("" if n["processo_id"] is not None else
                                            f"processo {n['numero'] or n['codigo']} ")
                               + f"não lido às {hora}: {n['motivo']}", n["processo_id"]) for n in nao_lidos]
        # o resumo conta so' os processos da rodada: o robo tambem le a lista dele, que a rodada nao traz
        da_rodada = json.loads(ultima["processos"])
        faltaram = len({n["processo_id"] for n in nao_lidos} & set(da_rodada))
        if faltaram:
            avisos.append(_aviso_robo("nao_lidos", f"{faltaram} de {texto.contar(len(da_rodada), 'processo', 'processos')} "
                                      + ("não foi lido" if faltaram == 1 else "não foram lidos")))
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
            "atrasado": atrasado(_leitura_dos_vivos(conn, encerrados(conn)), tempo.agora_utc()),
            "processos": conn.execute("SELECT COUNT(*) FROM siga_processos").fetchone()[0]}


def avisos(conn, hoje: datetime.date, agora: datetime.datetime | None = None) -> list[dict]:
    """Avisos da fila (issue #330). `siga_parado`: processo ligado a medicao ainda nao recebida, 5 dias uteis ou
    mais sem movimentacao: os dias sao os da coluna "Dias sem movimentacao" da tela (`derivar`, desde a ultima
    movimentacao fora Marcacao e Anotacao, #840), e o nivel e' o de `parado`. Um so' por medicao: o do processo do protocolo mais recente (sem protocolo
    vale menos que com; empate, o processo mais novo), porque o antigo fica arquivado no SIGA depois de uma
    devolucao; o arquivado (#657) nao avisa. `siga_sem_leitura`: um so', quando o robo passou do atraso nos processos vivos. Processo sem
    medicao (Outros processos) nao avisa: nao ha' obra nem ato da dashboard que o faca sumir."""
    agora = agora or tempo.agora_utc()
    out = []
    situacoes, manuais = _situacoes(conn), _manuais(conn)
    for p in conn.execute(
            "SELECT sp.id, sp.numero, sp.contrato_id, sp.medicao_id FROM siga_processos sp "
            "JOIN medicoes m ON m.id=sp.medicao_id WHERE m.estado NOT IN ('cancelada','desistida','recebida') "
            "AND NOT EXISTS (SELECT 1 FROM siga_processos novo WHERE novo.medicao_id=sp.medicao_id AND "
            "(COALESCE(novo.protocolo_id, -1) > COALESCE(sp.protocolo_id, -1) OR "
            "(COALESCE(novo.protocolo_id, -1) = COALESCE(sp.protocolo_id, -1) AND novo.id > sp.id))) "
            "ORDER BY sp.id").fetchall():
        situacao = situacoes.get(p["id"])
        movs = [dict(r) for r in conn.execute(
            "SELECT data, evento, at_lotacao, at_pessoa FROM siga_movimentacoes WHERE processo_id=?", (p["id"],))]
        d = derivar(situacao, movs, hoje)
        # #841: o encerrado (arquivado, juntado ou a' mao) nao avisa; o sobrestado sai pela leitura de `parado`
        manual = manuais.get(p["id"])
        if d["ultima"] is None or _encerramento(None, situacao, movs, manual["encerrado_em"] if manual else None):
            continue
        situacao = parado(d)
        if situacao not in ("breve", "critico"):
            continue
        parado_desde, dias = d["ultima"]["data"][:10], d["dias_sem_movimentacao"]
        onde = f" em {d['setor']}" if d["setor"] else ""
        out.append({**registro_avisos.aviso(
            "siga_parado", "acao" if situacao == "critico" else "atencao",
            f"processo {p['numero']}{onde} sem movimentação há {texto.dias_uteis(dias)}", p["contrato_id"],
            registro_avisos.obra(conn, p["contrato_id"]), dias=dias,
            destino={"tela": "siga", "processo": p["id"]}, data=parado_desde, sentido="desde"),
            "medicao_id": p["medicao_id"]})
    lido_em = _leitura_dos_vivos(conn, encerrados(conn))
    if atrasado(lido_em, agora):
        local = tempo.para_local(datetime.datetime.fromisoformat(lido_em))
        out.append(registro_avisos.aviso(
            "siga_sem_leitura", "acao", f"monitor do SIGA sem leitura desde {local:%d/%m %H:%M}",
            destino={"tela": "siga"}, data=local.date().isoformat(), sentido="desde"))
    return out
