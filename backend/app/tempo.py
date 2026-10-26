"""Politica de fuso do projeto (divida da fase 2, decidida na fase 3):

- ARMAZENAR: sempre UTC (datetime('now') do SQLite). Nenhum dado migra.
- DECIDIR/EXIBIR: America/Cuiaba (UTC-4 fixo desde 2019, mas via zoneinfo
  para nao hardcodar). Fronteira de mes/dia do negocio = a local.

So estas funcoes convertem; nenhum outro modulo importa zoneinfo.

PROIBIDO fora daqui: `datetime.now()` sem tzinfo (ele devolve a hora do
RELOGIO DA MAQUINA, que nao e' nem o que o banco grava nem o que o negocio
decide -- um servidor em UTC passa a errar a virada do mes em silencio).
Quem precisa de "agora" usa `agora_utc()`; quem precisa da data/mes do
negocio usa `hoje_local()` / `mes_local()`. O par no frontend e'
`frontend/src/tempo.ts`, que proibe `new Date().toLocaleString()` direto.

Por que isso importa: 21:30 do dia 31 em Cuiaba ja e' 01:30 do dia 1 em UTC.
Ler o mes direto da string do banco (`criado_em[:7]`) joga tudo que foi
criado depois das 20h do ultimo dia do mes para o mes seguinte -- e, no
cronograma, isso congela competencia que ainda deveria ser reescrita.

Requer o pacote `tzdata` (pinado em pyproject.toml): o Windows nao tem a
base IANA do sistema, entao sem ele o ZoneInfo abaixo levanta
ZoneInfoNotFoundError ja na importacao do modulo -- de proposito, porque
cair na importacao e' melhor que silenciosamente decidir em outro fuso.
"""
import datetime
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("America/Cuiaba")
_UTC = datetime.timezone.utc


def agora_utc() -> datetime.datetime:
    """Instante atual, aware, em UTC -- o mesmo referencial do banco."""
    return datetime.datetime.now(_UTC)


def para_local(dt: datetime.datetime) -> datetime.datetime:
    """UTC (aware ou ingenuo) -> America/Cuiaba.

    Ingenuo e' tratado como UTC porque a unica fonte de datetime sem tzinfo
    aqui e' o banco, e o banco so grava UTC.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_UTC)
    return dt.astimezone(_TZ)


def mes_local(utc_str: str) -> str:
    """'AAAA-MM-DD HH:MM:SS' (UTC, formato do SQLite) -> 'AAAA-MM' em Cuiaba."""
    dt = datetime.datetime.fromisoformat(utc_str.replace("Z", "")).replace(tzinfo=_UTC)
    return para_local(dt).strftime("%Y-%m")


def hoje_local() -> datetime.date:
    """A data de HOJE para o negocio -- a de Cuiaba, nao a de UTC."""
    return para_local(agora_utc()).date()


def inicio_do_dia_utc(data_iso: str) -> str:
    """'AAAA-MM-DD' (dia do negocio) -> carimbo UTC do SQLite da meia-noite de Cuiaba desse dia.

    E' o inverso de `mes_local` para quem grava uma DATA de documento numa coluna de carimbo
    (cronograma do cadastro, issue #256): gravar '2026-10-01 00:00:00' leria, em Cuiaba, 30/09."""
    d = datetime.date.fromisoformat(data_iso)
    local = datetime.datetime(d.year, d.month, d.day, tzinfo=_TZ)
    return local.astimezone(_UTC).strftime("%Y-%m-%d %H:%M:%S")
