"""Rotas do radar de licitacoes (issue #908, docs/adr/0018).

Rotas de SERVICO, para o radar, que roda fora deste repositorio: nao usam sessao nem CSRF; exigem
`Authorization: Bearer <token>`, com o token lido do arquivo apontado por `DASH_RADAR_TOKEN_ARQUIVO` (fora do
repositorio; lido a cada pedido, entao trocar o token nao pede reinicio). Sem a variavel, 503. O molde e' o do
monitor do SIGA (`api_siga.py`), com token proprio: quem tem um nao entra pelo outro.

Uma rodada sao tres passos: `GET /api/radar/estado` (o que a dashboard ja' tem), `POST /api/radar/certames` (so' os
que mudaram, em pedidos abaixo do teto geral de 2 MB) e `POST /api/radar/leituras` (fecha a rodada). Depois do corte
o radar tambem busca as decisoes em `GET /api/radar/decisoes`, e o fechamento com decisoes e' recusado (409).
"""
import datetime
import hmac
import logging
import os
import sqlite3
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import AwareDatetime, BaseModel, Field, model_validator

from app import licitacoes, licitacoes_decisoes
from app.api_auth import conexao

router = APIRouter()
log = logging.getLogger("app.licitacoes")

NAO_CONFIGURADO = "Radar de licitações não configurado"
TOKEN_INVALIDO = "Token do radar de licitações inválido ou ausente"

Etapa = Literal["acompanhando", "em_analise", "proposta_enviada", "vencida", "perdida", "desistida", "encerrada"]
# o link vira `href` na tela: so' endereco da internet, inteiro, sem espaco nem caractere de controle
LINK = r"^(https?://[^\s\x00-\x1f\x7f]+)?$"
HORA = r"^([01]\d|2[0-3]):[0-5]\d$"
CHAVE = r"^\S(.*\S)?$"
# data de documento: fora desta faixa e' erro de leitura, e a conta de dias uteis anda dia a dia
Data = Annotated[datetime.date, Field(ge=datetime.date(2000, 1, 1), le=datetime.date(2100, 12, 31))]
Chave = Annotated[str, Field(min_length=1, max_length=200, pattern=CHAVE)]


def _token_esperado() -> bytes:
    caminho = os.environ.get("DASH_RADAR_TOKEN_ARQUIVO")
    if not caminho:
        raise HTTPException(503, NAO_CONFIGURADO)
    # utf-8-sig: o Set-Content -Encoding UTF8 do PowerShell 5.1 grava BOM, que viraria parte do token (401 eterno).
    # UTF-16 (o `>` do PowerShell 5.1) nao decodifica: 503 com log, nunca 500.
    try:
        token = Path(caminho).read_text(encoding="utf-8-sig").strip()
    except (OSError, UnicodeError):
        log.exception("arquivo do token do radar ilegivel")
        raise HTTPException(503, NAO_CONFIGURADO) from None
    if not token:
        log.error("arquivo do token do radar vazio")
        raise HTTPException(503, NAO_CONFIGURADO)
    return token.encode("utf-8")


def exigir_radar(authorization: str | None = Header(default=None)) -> None:
    esperado = _token_esperado()
    tipo, _, valor = (authorization or "").partition(" ")
    # compare_digest em bytes: tempo constante, e o cabecalho pode trazer nao-ASCII
    if tipo.lower() != "bearer" or not hmac.compare_digest(valor.strip().encode("utf-8"), esperado):
        raise HTTPException(401, TOKEN_INVALIDO, headers={"WWW-Authenticate": "Bearer"})


class PontosIn(BaseModel):
    valor: int = Field(ge=0, le=20)
    distancia: int = Field(ge=0, le=20)
    acervo: int = Field(ge=0, le=20)


class RecomendadaIn(BaseModel):
    nota: int = Field(ge=0, le=60)
    pontos: PontosIn
    motivo: str = Field(max_length=600)
    # o local da obra pelo radar: o municipio do orgao ou, na obra do Estado e da Uniao, o que o objeto cita
    km: int | None = Field(default=None, ge=0, le=10000)
    cidade: str = Field(default="", max_length=120)


class EventoIn(BaseModel):
    data: Data
    fonte: str = Field(default="", max_length=80)
    texto: str = Field(max_length=600)
    rotulo: str | None = Field(default=None, max_length=40)       # so' o evento que e' mudanca do certame tem


class EspelhoIn(BaseModel):
    edital: str = Field(max_length=120)
    link: str = Field(default="", max_length=2000, pattern=LINK)


class PrazoIn(BaseModel):
    codigo: str = Field(max_length=30)
    rotulo: str = Field(max_length=60)
    data: Data
    hora: str | None = Field(default=None, pattern=HORA)
    aviso: str = Field(default="", max_length=200)


class DossieIn(BaseModel):
    pasta: str = Field(max_length=200)
    etapa: Etapa | None = None
    selos: list[Annotated[str, Field(max_length=60)]] = Field(default_factory=list, max_length=5)   # o que o dossie diz alem da etapa ("Diretoria: interesse")
    prazos: list[PrazoIn] = Field(default_factory=list, max_length=12)


class CertameIn(BaseModel):
    chave: Chave
    resumo: str = Field(min_length=8, max_length=64, pattern=r"^[0-9a-f]+$")
    orgao: str = Field(max_length=300)
    unidade: str = Field(default="", max_length=300)
    sigla_orgao: str = Field(default="", max_length=60)
    grupo_orgao: str = Field(default="", max_length=60)
    orgao_de_interesse: bool = False                      # um dos orgaos que o dono acompanha de perto
    esfera: str | None = Field(default=None, max_length=20)
    municipio: str = Field(default="", max_length=120)
    uf: str = Field(default="", max_length=2)
    cidade: str = Field(default="", max_length=120)
    km: int | None = Field(default=None, ge=0, le=10000)
    edital: str = Field(default="", max_length=120)
    modalidade: str = Field(default="", max_length=120)
    processo: str = Field(default="", max_length=120)
    objeto: str = Field(max_length=600)
    objeto_completo: str = Field(default="", max_length=8000)
    tipo_obra: str = Field(default="", max_length=40)
    categoria: str | None = Field(default=None, max_length=20)
    valor_centavos: int | None = Field(default=None, ge=0, le=10**15)
    valor_rotulo: str = Field(default="", max_length=200)
    situacao: str = Field(default="", max_length=300)
    situacao_grupo: str = Field(default="", max_length=60)
    encerrada: bool = False
    data_publicacao: Data | None = None
    data_sessao: Data | None = None
    hora_sessao: str | None = Field(default=None, pattern=HORA)
    primeira_vez: Data | None = None
    link: str = Field(default="", max_length=2000, pattern=LINK)
    portal: str = Field(default="", max_length=60)
    modo_disputa: str = Field(default="", max_length=60)
    srp: bool | None = None
    fontes: list[Annotated[str, Field(max_length=80)]] = Field(default_factory=list, max_length=30)
    nova: bool = False
    grande_vulto: bool = False
    recomendada: RecomendadaIn | None = None
    historico: list[EventoIn] = Field(default_factory=list, max_length=300)
    espelhos: list[EspelhoIn] = Field(default_factory=list, max_length=5)
    dossie: DossieIn | None = None


class CertamesIn(BaseModel):
    certames: list[CertameIn] = Field(max_length=2000)


class FonteIn(BaseModel):
    fonte: str = Field(max_length=60)
    nome: str = Field(max_length=120)
    estado: str | None = Field(default=None, max_length=20)
    lidos: int | None = Field(default=None, ge=0)
    hora: str | None = Field(default=None, pattern=HORA)
    problema: str | None = Field(default=None, max_length=400)
    aguardando: str | None = Field(default=None, max_length=400)


class FavoritaIn(BaseModel):
    chave: Chave
    desde: Data
    etapa: Etapa | None = None
    autor: str | None = Field(default=None, max_length=120)


class DescartadaIn(BaseModel):
    chave: Chave
    motivo: Literal["tipo de obra", "local", "valor", "órgão", "outro"]
    autor: str | None = Field(default=None, max_length=120)
    quando: AwareDatetime | None = None                   # quando foi descartada no radar; sem ela, a hora do espelho


class ConferenciaIn(BaseModel):
    """A resposta que o radar ja' tem para um par (fatia 4): espelho ate' o corte. As chaves nao precisam ser de
    certames que a dashboard recebeu: a conferencia antiga pode ser de certame que nenhuma tela mostra."""
    par: Chave
    a: Chave
    b: Chave
    resposta: Literal["mesmo", "outro"]
    autor: str | None = Field(default=None, max_length=120)
    quando: AwareDatetime | None = None

    @model_validator(mode="after")
    def _dois_certames(self):
        if self.a == self.b:
            raise ValueError("o par precisa de dois certames diferentes")
        return self


class DecisoesIn(BaseModel):
    # obrigatoria: `decisoes: {}` nao vale por lista vazia (que tira todas as favoritas). Quem nao leu as proprias
    # favoritas omite `decisoes`, e ai' nada mexe
    favoritas: list[FavoritaIn] = Field(max_length=2000)
    descartadas: list[DescartadaIn] | None = Field(default=None, max_length=5000)   # ausente: nao mexe nas que existem
    conferencias: list[ConferenciaIn] | None = Field(default=None, max_length=5000)  # idem


# --- fatia 4 da #906: alertas do dia, pares para conferir e o quadro de resultados ---------------------------------

class AlertaIn(BaseModel):
    regra: str = Field(min_length=1, max_length=60)
    nome: str = Field(min_length=1, max_length=200)
    chaves: list[Chave] = Field(max_length=2000)


class ParIn(BaseModel):
    """Dois certames que o radar achou parecidos e nao conseguiu provar iguais. `par`: a identidade que ele da'."""
    par: Chave
    a: Chave
    b: Chave
    motivo: str = Field(default="", max_length=400)

    @model_validator(mode="after")
    def _dois_certames(self):
        if self.a == self.b:
            raise ValueError("o par precisa de dois certames diferentes")
        return self


class PassoDoFunilIn(BaseModel):
    rotulo: str = Field(min_length=1, max_length=60)
    n: int = Field(ge=0, le=100_000)


class GrupoIn(BaseModel):
    grupo: str = Field(min_length=1, max_length=120)
    participadas: int = Field(ge=0, le=100_000)
    vencidas: int = Field(ge=0, le=100_000)

    @model_validator(mode="after")
    def _vencidas_cabem(self):
        if self.vencidas > self.participadas:
            raise ValueError("vencidas acima das participadas")
        return self


class PerdaIn(BaseModel):
    licitacao: str = Field(min_length=1, max_length=300)
    motivo: str = Field(default="", max_length=400)
    data: Data | None = None


# desconto em centesimos de ponto percentual: 1234 e' 12,34%
Desconto = Annotated[int, Field(ge=-10_000, le=10_000)]


class DescontoIn(BaseModel):
    licitacao: str = Field(min_length=1, max_length=300)
    empresa: Desconto
    vencedor: Desconto | None = None
    vencemos: bool = False


class ResultadosIn(BaseModel):
    """O quadro que o radar calcula dos dossies: o funil, participadas e vencidas por tipo de obra e por modalidade,
    as perdas com o motivo e os descontos. A dashboard guarda o ultimo e mostra."""
    funil: list[PassoDoFunilIn] = Field(default_factory=list, max_length=12)
    por_tipo: list[GrupoIn] = Field(default_factory=list, max_length=60)
    por_modalidade: list[GrupoIn] = Field(default_factory=list, max_length=60)
    perdas: list[PerdaIn] = Field(default_factory=list, max_length=500)
    descontos: list[DescontoIn] = Field(default_factory=list, max_length=500)


class LeituraIn(BaseModel):
    lido_em: AwareDatetime
    chaves: list[Chave] = Field(max_length=20000)
    fontes: list[FonteIn] = Field(default_factory=list, max_length=60)
    decisoes: DecisoesIn | None = None
    alertas: list[AlertaIn] = Field(default_factory=list, max_length=60)
    pares: list[ParIn] | None = Field(default=None, max_length=5000)     # ausente: nao mexe nos pares gravados
    resultados: ResultadosIn | None = None                               # ausente: vale o ultimo que veio


@router.get("/api/radar/estado", dependencies=[Depends(exigir_radar)], include_in_schema=False)
def estado(conn: sqlite3.Connection = Depends(conexao)):
    return licitacoes.estado(conn)


@router.post("/api/radar/certames", dependencies=[Depends(exigir_radar)], include_in_schema=False)
def receber_certames(dados: CertamesIn, conn: sqlite3.Connection = Depends(conexao)):
    return licitacoes.gravar_certames(conn, [c.model_dump(mode="json") for c in dados.certames])


@router.post("/api/radar/leituras", dependencies=[Depends(exigir_radar)], include_in_schema=False)
def fechar_leitura(dados: LeituraIn, conn: sqlite3.Connection = Depends(conexao)):
    decisoes = dados.decisoes.model_dump(mode="json") if dados.decisoes is not None else None
    try:
        return licitacoes.fechar_leitura(
            conn, dados.lido_em, dados.chaves, [f.model_dump(mode="json") for f in dados.fontes], decisoes,
            alertas=[a.model_dump(mode="json") for a in dados.alertas],
            pares=None if dados.pares is None else [p.model_dump(mode="json") for p in dados.pares],
            resultados=None if dados.resultados is None else dados.resultados.model_dump(mode="json"))
    except licitacoes.DecisoesNaDashboard as e:
        raise HTTPException(409, str(e)) from None
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


@router.get("/api/radar/decisoes", dependencies=[Depends(exigir_radar)], include_in_schema=False)
def decisoes(conn: sqlite3.Connection = Depends(conexao)):
    """Depois do corte o radar busca aqui as favoritas, as descartadas e as conferencias em vigor, antes de cada leitura."""
    return licitacoes_decisoes.para_o_radar(conn)
