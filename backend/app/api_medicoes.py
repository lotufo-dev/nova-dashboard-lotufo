"""Rotas de medicoes (fase 2): criar, valores, protocolo e estados.

Toda escrita desta fase grava origem "manual" -- a deteccao automatica
(origem "detectado"/"aceito") entra nas fases 5-6.
"""
import datetime
import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, UploadFile
from pydantic import BaseModel, Field

from app import arquivos, db, espelhos, medicao_planilhas, medicoes, permissoes, siga, tempo
from app.api_auth import conexao
from app.dinheiro import parse_brl
from app.permissoes import exigir

router = APIRouter()

# Competencia e' o mes de referencia "AAAA-MM": o mesmo formato que o CHECK
# (GLOB) da tabela medicoes exige. Validar aqui devolve 422 em vez de deixar
# o CHECK do SQLite estourar como 500.
# [0-9] em vez de \d de proposito: o \d do Python casa DIGITO UNICODE (arabe-indico,
# devanagari...). "٢٠٢٦-07" passaria por aqui e so morreria no GLOB '[0-9]...' do
# SQLite, como IntegrityError dentro do handler -> 500.
COMPETENCIA = r"^[0-9]{4}-(0[1-9]|1[0-2])$"

# Maior inteiro que o SQLite grava numa coluna INTEGER (int64). Acima disso o driver
# levanta OverflowError DENTRO do handler -> 500. Mesmo teto de api_contratos.py.
MAX_INT64 = 9223372036854775807
# A-07 (testes de quebra 10/10/2026): id de caminho acima de int64 dava 500 (OverflowError) em 31 rotas.
# Todo parametro inteiro de caminho dos api_*.py usa este tipo: fora da faixa e' 422 na entrada.
ID = Annotated[int, Path(ge=1, le=MAX_INT64)]


class MedicaoIn(BaseModel):
    numero: int = Field(ge=1, le=999)
    tipo: Literal["execucao", "projeto", "reajuste"]
    competencia: str = Field(pattern=COMPETENCIA)


class ValorIn(BaseModel):
    campo: Literal["protocolado", "atestado"]
    # max_length: parse_brl aceita qualquer quantidade de digitos (int do Python nao
    # estoura), entao um texto de megabytes seria convertido antes de qualquer teto.
    # 40 caracteres cobrem qualquer contrato real com folga.
    valor: str = Field(max_length=40)  # BRL "50.000,00"
    # Dia do atesto (fase 3,5, spec §6). So' vale com campo=atestado; o servidor
    # recusa a combinacao com protocolado (422), que tem a data no protocolo.
    data: datetime.date | None = None


class ProtocoloIn(BaseModel):
    data: datetime.date
    # Tetos nos textos que vao para o audit_log: a cadeia e' append-only (nao da para
    # apagar um registro gigante depois) e estes campos sao numeros de oficio/processo.
    numero_oficio: str | None = Field(default=None, max_length=100)
    numero_processo: str | None = Field(default=None, max_length=100)
    # Fase 3,5: o checklist "pronto para protocolar" (fase 3) passa a TRAVAR o ato.
    # Com pendencia de certidao o protocolo e' recusado, salvo se o operador assumir
    # -- e ai a justificativa e' obrigatoria e vai para a auditoria.
    apesar_das_pendencias: bool = False
    justificativa: str | None = Field(default=None, max_length=500)
    # Issue #328: o link de acompanhamento do SIGA (ou so' o codigo); o servidor extrai o codigo e recusa o resto
    link_siga: str | None = Field(default=None, max_length=500)


class EstadoIn(BaseModel):
    # `protocolada` fica FORA: prevista -> protocolada e' exclusividade de
    # POST /protocolo, que cria a linha de protocolo e congela o valor (spec §5).
    # `nota_emitida` entra por api_notas (nota lida ou declarada); `nf_emitida` saiu no
    # bloco 3. Ver o comentario de TRANSICOES em medicoes.py.
    estado: Literal["recebida", "cancelada", "desistida"]
    motivo: str | None = Field(default=None, max_length=1000)  # tambem vai ao audit_log
    # Data do marco (emissao da NF / baixa), spec §6. Opcional: quem registra depois
    # do fato pode nao ter a data a mao, e o painel diz "sem data" em vez de inventar.
    data: datetime.date | None = None


def _medicao_existe(conn: sqlite3.Connection, medicao_id: int) -> None:
    """404 antes de tocar no repositorio.

    definir_valor/registrar_protocolo/mudar_estado fazem `detalhe(...)[...]` e
    estouram TypeError (500) com id inexistente -- a rota tem que barrar antes.
    """
    if conn.execute("SELECT id FROM medicoes WHERE id=?", (medicao_id,)).fetchone() is None:
        raise HTTPException(404, "Medição não encontrada")


def _contrato_existe(conn: sqlite3.Connection, contrato_id: int) -> None:
    if conn.execute("SELECT id FROM contratos WHERE id=?", (contrato_id,)).fetchone() is None:
        raise HTTPException(404, "Contrato não encontrado")


def _erro_do_cliente(conn: sqlite3.Connection, e: ValueError) -> HTTPException:
    """ValueError do repositorio -> 422, com a transacao desfeita.

    Desde a fase 3 quem desfaz e' o proprio `db.mutacao` do repositorio, e este
    rollback e' no-op. Fica como defesa: garante que a conexao nunca volte ao pool
    de dependencias com transacao aberta, segurando o lock de escrita ate o fim da
    requisicao. Mesmo padrao de api_usuarios.py.
    """
    conn.rollback()
    return HTTPException(422, str(e))


@router.get("/api/contratos/{contrato_id}/medicoes")
def listar(contrato_id: ID, usuario: dict = Depends(exigir("ver_paineis", com_csrf=False)),
           conn: sqlite3.Connection = Depends(conexao)):
    _contrato_existe(conn, contrato_id)
    lista = medicoes.listar(conn, contrato_id)
    edicoes = medicoes.edicoes_valor(conn, [m["id"] for m in lista])   # B-02 (10/10/2026): a pagina da medicao le daqui
    sigas = siga.registrado_em(conn, "medicao", [m["id"] for m in lista])    # issue #328: link do SIGA do envio por fora
    return [{**m, "edicoes_valor": edicoes[m["id"]], "siga_registrado_em": sigas.get(m["id"])} for m in lista]


@router.post("/api/contratos/{contrato_id}/medicoes", status_code=201)
def criar(contrato_id: ID, dados: MedicaoIn,
          usuario: dict = Depends(exigir("editar_cadastros")),
          conn: sqlite3.Connection = Depends(conexao)):
    _contrato_existe(conn, contrato_id)
    # Issue #12: obra com regra ativa gera a medicao pelo espelho (valor com a regra fiscal). A trava
    # fica na rota, nao em medicoes.criar, porque a carga do legado e o ledger criam medicao historica.
    # Vale para qualquer tipo, como a issue pede: a tela tambem nao oferece a manual nessas obras.
    regra = espelhos.regra_do_contrato(conn, contrato_id)
    if regra is not None and regra["situacao"] == "ativa":
        raise HTTPException(422, "Esta obra gera a medição pelo espelho: use “Gerar espelho” na página da obra")
    try:
        mid = medicoes.criar(conn, usuario["id"], {"contrato_id": contrato_id, **dados.model_dump()})
    except ValueError as e:
        raise _erro_do_cliente(conn, e)
    return {"id": mid}


@router.get("/api/medicoes/{medicao_id}")
def detalhe(medicao_id: ID, usuario: dict = Depends(exigir("ver_paineis", com_csrf=False)),
            conn: sqlite3.Connection = Depends(conexao)):
    d = medicoes.detalhe(conn, medicao_id)
    if d is None:
        raise HTTPException(404, "Medição não encontrada")
    d["edicoes_valor"] = medicoes.edicoes_valor(conn, [medicao_id])[medicao_id]   # B-02 (10/10/2026): linha do tempo
    d["planilhas"] = medicao_planilhas.versoes(conn, medicao_id)   # issue #281: todas as versoes da planilha/carta
    d["siga_registrado_em"] = siga.registrado_em(conn, "medicao", [medicao_id]).get(medicao_id)
    return d


@router.put("/api/medicoes/{medicao_id}/valor")
def definir_valor(medicao_id: ID, dados: ValorIn,
                  usuario: dict = Depends(exigir("editar_cadastros")),
                  conn: sqlite3.Connection = Depends(conexao)):
    _medicao_existe(conn, medicao_id)
    try:
        centavos = parse_brl(dados.valor)
        if centavos > MAX_INT64:
            raise ValueError("Valor monetário fora do limite")
        medicoes.definir_valor(conn, usuario["id"], medicao_id, dados.campo, centavos, "manual",
                               dados.data.isoformat() if dados.data else None)
    except ValueError as e:  # BRL invalido, acima do int64, ou medicao congelada
        raise _erro_do_cliente(conn, e)
    return {"ok": True}


@router.post("/api/medicoes/{medicao_id}/protocolo", status_code=201)
def protocolo(medicao_id: ID, dados: ProtocoloIn,
              usuario: dict = Depends(exigir("editar_cadastros")),
              conn: sqlite3.Connection = Depends(conexao)):
    _medicao_existe(conn, medicao_id)
    # O checklist e' conferido pelo repositorio, dentro da transacao do protocolo (gate
    # Sol da fase 3,5): a rota so' traduz a recusa em 422.
    try:
        codigo = siga.extrair_codigo(dados.link_siga)       # link invalido recusa antes de gravar qualquer coisa
        with db.mutacao(conn):
            pid, ressalva = medicoes.registrar_protocolo(
                conn, usuario["id"], medicao_id, dados.data.isoformat(), dados.numero_oficio,
                dados.numero_processo, "manual", dados.apesar_das_pendencias, dados.justificativa, exige_nota=True)
            if codigo:
                siga.registrar_link_medicao(conn, usuario["id"], medicao_id, codigo, dados.numero_processo)
    except ValueError as e:
        raise _erro_do_cliente(conn, e)
    return {"id": pid, "ressalva": ressalva}


MOTIVO_RECEBIMENTO_MINIMO = 10  # a tela acompanha (MIN_MOTIVO_RECEBIMENTO em MedicaoAtos.tsx)


@router.post("/api/medicoes/{medicao_id}/estado")
def estado(medicao_id: ID, dados: EstadoIn,
           usuario: dict = Depends(exigir("editar_cadastros")),
           conn: sqlite3.Connection = Depends(conexao)):
    _medicao_existe(conn, medicao_id)
    motivo = dados.motivo
    if dados.estado == "recebida":
        # Issue #53 (decisao do dono, 15/10/2026): o recebimento vem do RM (spec §7.1); a mao, so' o
        # admin, com motivo obrigatorio que vai para a auditoria -- saida para quando o RM falhar.
        # As baixas do RM e da conciliacao chamam medicoes.mudar_estado direto, sem passar por aqui.
        if not permissoes.tem(usuario["perfil"], "administrar"):
            raise HTTPException(403, "Só o administrador registra o recebimento à mão: o RM marca a baixa sozinho")
        motivo = (motivo or "").strip()
        if len(motivo) < MOTIVO_RECEBIMENTO_MINIMO:
            raise HTTPException(422, f"Informe o motivo do recebimento à mão (ao menos {MOTIVO_RECEBIMENTO_MINIMO} "
                                     "caracteres): fica registrado na auditoria")
    try:
        medicoes.mudar_estado(conn, usuario["id"], medicao_id, dados.estado, motivo,
                              dados.data.isoformat() if dados.data else None,
                              origem="manual" if dados.estado == "recebida" else None)
    except ValueError as e:
        raise _erro_do_cliente(conn, e)
    return {"ok": True}


class AssinaturaIn(BaseModel):
    data: datetime.date
    envelope: str | None = Field(default=None, max_length=200)


@router.post("/api/medicoes/{medicao_id}/assinatura", status_code=201)
def registrar_assinatura(medicao_id: ID, dados: AssinaturaIn, usuario: dict = Depends(exigir("editar_cadastros")),
                         conn: sqlite3.Connection = Depends(conexao)):
    _medicao_existe(conn, medicao_id)
    try:
        aid = medicoes.registrar_assinatura(conn, usuario["id"], medicao_id, dados.data.isoformat(), dados.envelope)
    except ValueError as e:
        raise _erro_do_cliente(conn, e)
    return {"id": aid}


# --- bloco 7: medicao final (poe o contrato em encerramento) ------------------------------------------

class FinalIn(BaseModel):
    data: datetime.date | None = None


class DesmarcarFinalIn(BaseModel):
    motivo: str = Field(min_length=1, max_length=500)


@router.post("/api/medicoes/{medicao_id}/final")
def marcar_final(medicao_id: ID, dados: FinalIn, usuario: dict = Depends(exigir("editar_cadastros")),
                 conn: sqlite3.Connection = Depends(conexao)):
    _medicao_existe(conn, medicao_id)
    try:
        medicoes.marcar_final(conn, usuario["id"], medicao_id,
                              (dados.data or tempo.hoje_local()).isoformat())
    except ValueError as e:
        raise _erro_do_cliente(conn, e)
    return medicoes.detalhe(conn, medicao_id)


@router.post("/api/medicoes/{medicao_id}/final/desmarcar")
def desmarcar_final(medicao_id: ID, dados: DesmarcarFinalIn, usuario: dict = Depends(exigir("editar_cadastros")),
                    conn: sqlite3.Connection = Depends(conexao)):
    _medicao_existe(conn, medicao_id)
    try:
        medicoes.desmarcar_final(conn, usuario["id"], medicao_id, dados.motivo)
    except ValueError as e:
        raise _erro_do_cliente(conn, e)
    return medicoes.detalhe(conn, medicao_id)


# --- issue #281: planilha/carta de medicao (spec 2026-10-20 §2.1, passo 1) -----------------------------

# mesmo teto da planilha editavel do protocolo (api_protocolos.TETO_PLANILHA; importar daria ciclo: ele importa
# este modulo)
TETO_PLANILHA = 25 * 1024 * 1024


def _pdf_validado(arquivo: UploadFile) -> bytes:
    dados = b"".join(arquivos.blocos_validados(arquivo))     # tipo, %PDF- e 10 MB (415/413)
    arquivos.conferir_bytes_parseaveis(dados)                # abre num leitor de verdade (415)
    return dados


def _anexos_validados(oficio: UploadFile, planilha: UploadFile) -> list[tuple[bytes, str]]:
    """Oficio assinado (PDF, com as guardas de app/arquivos.py) e planilha (.xlsx; .pdf onde a planilha/carta e'
    o proprio boletim da Lotufo, Prefeitura e SES). Os DOIS sao validados antes de gravar qualquer um: recusa da
    planilha nao deixa o oficio orfao na pasta (gate Sol, rodada 1)."""
    if (planilha.filename or "").lower().endswith(".pdf"):
        da_planilha = (_pdf_validado(planilha), "pdf")
    else:
        da_planilha = (b"".join(arquivos.blocos_validados(planilha, teto_bytes=TETO_PLANILHA, tipo="xlsx")), "xlsx")
    return [(_pdf_validado(oficio), "pdf"), da_planilha]


def _gravar_e_registrar(conn: sqlite3.Connection, validados: list[tuple[bytes, str]], registrar):
    """Grava os anexos (ja' validados) pelo hash e chama `registrar(anexos)`.

    Nada e' apagado se o registro falhar (gate Sol, rodada 2): a decisao de apagar ficaria fora do BEGIN
    IMMEDIATE, e no clique duplo com o mesmo PDF a requisicao que falha apagaria o arquivo de que a outra acabou
    de depender. O arquivo sem versao e' inofensivo: tem o nome do proprio hash e e' reaproveitado no proximo
    envio do mesmo conteudo."""
    (arq, sha), (arq_p, sha_p) = (arquivos.gravar_bytes("planilhas", dados, ext) for dados, ext in validados)
    return registrar({"arquivo": arq, "sha256": sha, "arquivo_planilha": arq_p, "sha256_planilha": sha_p})


def _centavos(valor: str) -> int:
    centavos = parse_brl(valor)
    if centavos > MAX_INT64:
        raise ValueError("Valor monetário fora do limite")
    return centavos


@router.get("/api/contratos/{contrato_id}/planilhas/sugestao")
def sugestao_planilha(contrato_id: ID, tipo: Literal["execucao", "projeto"] = Query("execucao"),
                      usuario: dict = Depends(exigir("ver_paineis", com_csrf=False)),
                      conn: sqlite3.Connection = Depends(conexao)):
    _contrato_existe(conn, contrato_id)
    return medicao_planilhas.sugestao(conn, contrato_id, tipo)


@router.post("/api/contratos/{contrato_id}/planilhas", status_code=201)
def registrar_planilha(contrato_id: ID,
                       numero: int = Form(..., ge=1, le=999),
                       tipo: Literal["execucao", "projeto"] = Form("execucao"),
                       competencia: str = Form(..., pattern=COMPETENCIA),
                       periodo_inicio: datetime.date = Form(...),
                       periodo_fim: datetime.date = Form(...),
                       valor: str = Form(..., max_length=40),
                       numero_orgao: int | None = Form(None, ge=1, le=9999),
                       oficio: UploadFile = File(...), planilha: UploadFile = File(...),
                       usuario: dict = Depends(exigir("editar_cadastros")),
                       conn: sqlite3.Connection = Depends(conexao)):
    """"Nova planilha/carta" na obra: a medicao entra em `planilha_gerada` com a versao 1; os avisos de periodo
    voltam junto com a gravacao (nao a impedem)."""
    _contrato_existe(conn, contrato_id)
    try:
        dados = {"numero": numero, "tipo": tipo, "competencia": competencia, "numero_orgao": numero_orgao,
                 "periodo_inicio": periodo_inicio.isoformat(), "periodo_fim": periodo_fim.isoformat(),
                 "valor_centavos": _centavos(valor)}
        medicao_planilhas.conferir_registro(conn, contrato_id, dados)   # recusa antes de gravar os anexos
    except ValueError as e:
        raise _erro_do_cliente(conn, e)
    validados = _anexos_validados(oficio, planilha)
    try:
        return _gravar_e_registrar(conn, validados, lambda anexos: medicao_planilhas.registrar(
            conn, usuario["id"], contrato_id, dados, anexos))
    except ValueError as e:
        raise _erro_do_cliente(conn, e)


@router.post("/api/medicoes/{medicao_id}/planilhas", status_code=201)
def revisar_planilha(medicao_id: ID,
                     motivo: str = Form("", max_length=1000),
                     periodo_inicio: datetime.date = Form(...),
                     periodo_fim: datetime.date = Form(...),
                     valor: str = Form(..., max_length=40),
                     oficio: UploadFile = File(...), planilha: UploadFile = File(...),
                     usuario: dict = Depends(exigir("editar_cadastros")),
                     conn: sqlite3.Connection = Depends(conexao)):
    """Revisao da planilha/carta (Rev01, Rev02...): versao nova, com motivo obrigatorio."""
    _medicao_existe(conn, medicao_id)
    try:
        dados = {"motivo": motivo, "periodo_inicio": periodo_inicio.isoformat(),
                 "periodo_fim": periodo_fim.isoformat(), "valor_centavos": _centavos(valor)}
        medicao_planilhas.conferir_revisao(conn, medicao_id, dados)   # recusa antes de gravar os anexos
    except ValueError as e:
        raise _erro_do_cliente(conn, e)
    validados = _anexos_validados(oficio, planilha)
    try:
        return _gravar_e_registrar(conn, validados, lambda anexos: medicao_planilhas.revisar(
            conn, usuario["id"], medicao_id, dados, anexos))
    except ValueError as e:
        raise _erro_do_cliente(conn, e)
