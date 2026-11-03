"""Guardas e gravacao de arquivo do sistema (spec §15): PDF validado por content-type, assinatura
`%PDF-`, teto de 10 MB e abertura num leitor de verdade; nome em disco pelo sha256; caminho gravado
no banco RELATIVO a pasta do banco e resolvido de volta so' dentro dela.

Nasceu em api_certidoes.py (fase 3) e foi extraido no bloco 2 para o espelho (docx gerado,
evidencia do orgao) usar exatamente as mesmas guardas. Uma implementacao: duas divergiriam no
primeiro conserto feito so' de um lado.
"""
import hashlib
import os
import secrets
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app import db, leitura_pdf

MAGIC = b"%PDF-"                    # todo PDF comeca por aqui (ISO 32000-1 §7.5.2)
MIME = "application/pdf"
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAGIC_XLSX = b"PK\x03\x04"
# zip do DocuSign (relatorios assinados) no envio: mesma assinatura do xlsx; o navegador manda um destes
MIMES_ZIP = ("application/zip", "application/x-zip-compressed", "application/x-zip", "application/octet-stream")
TETO_MB = 10
TETO_BYTES = TETO_MB * 1024 * 1024
BLOCO = 64 * 1024


def pasta(nome: str) -> Path:
    """Subpasta ao lado do banco (certidoes, espelhos, modelos, evidencias, backups).

    Derivar de `db.db_path().parent` e' o que mantem os testes honestos: com
    DASH_DB_PATH=<tmp>/test.db os arquivos vao para <tmp>/<nome> e somem com o tmp_path.
    """
    p = db.db_path().parent / nome
    p.mkdir(parents=True, exist_ok=True)
    return p


def pasta_certidoes() -> Path:
    return pasta("certidoes")


def sha_de(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def gravar_bytes(nome_pasta: str, dados: bytes, ext: str) -> tuple[str, str]:
    """Grava pelo hash (dedup natural) e devolve (caminho relativo a pasta do banco, sha256).
    Grava num temporario e renomeia: ou o arquivo aparece inteiro, ou nao aparece."""
    sha = sha_de(dados)
    destino = pasta(nome_pasta) / f"{sha}.{ext}"
    # Dedup por CONTEUDO: o nome ser <sha> e' promessa nossa, e promessa quebra (arquivo truncado,
    # copia manual). Se o que esta' la' nao bate com o hash, regrava.
    if not destino.exists() or sha_do_arquivo(destino) != sha:
        tmp = destino.with_suffix(f".{os.getpid()}-{secrets.token_hex(4)}.tmp")
        try:
            tmp.write_bytes(dados)
            os.replace(tmp, destino)
        except BaseException:
            tmp.unlink(missing_ok=True)       # issue #180: disco cheio no meio nao deixa o temporario na pasta
            raise
    return f"{nome_pasta}/{sha}.{ext}", sha


def caminho_seguro(relativo: str) -> Path:
    """Resolve um caminho gravado no banco; recusa qualquer coisa fora da pasta de dados."""
    base = db.db_path().parent.resolve()
    alvo = (base / relativo).resolve()
    if not alvo.is_relative_to(base):
        raise ValueError("caminho fora da pasta de dados")
    return alvo


def blocos_validados(arquivo: UploadFile, teto_bytes: int = TETO_BYTES, tipo: str = "pdf"):
    """Itera o upload em blocos de 64 KB, recusando ANTES de consumir.

    O content-type e os magic bytes barram o arquivo errado no primeiro bloco, e o
    contador de bytes corta o arquivo grande no meio do stream -- em nenhum dos casos
    o conteudo inteiro chega a ser consumido.

    `teto_bytes` e `tipo` (bloco 5): o pacote de protocolo assinado vai a 40 MB, e a planilha
    editavel da SINFRA e' `.xlsx` (zip: assinatura "PK\\x03\\x04").
    """
    # split(';'): "application/pdf; charset=binary" e' content-type valido.
    ct = (arquivo.content_type or "").split(";")[0].strip().lower()
    if tipo == "xlsx":
        if ct not in (MIME_XLSX, "application/octet-stream"):
            raise HTTPException(415, f"Envie uma planilha .xlsx; recebido: {arquivo.content_type!r}")
        magico, erro = MAGIC_XLSX, "O arquivo não é uma planilha .xlsx"
    elif tipo == "zip":
        if ct not in MIMES_ZIP:
            raise HTTPException(415, f"Envie um arquivo .zip; recebido: {arquivo.content_type!r}")
        magico, erro = MAGIC_XLSX, "O arquivo não é um .zip"
    else:
        if ct != MIME:
            raise HTTPException(415, f"Envie um PDF ({MIME}); "
                                     f"recebido: {arquivo.content_type!r}")
        magico, erro = MAGIC, ("O arquivo não é um PDF (assinatura '%PDF-' ausente) "
                               "— renomear a extensão não converte o arquivo")
    origem = arquivo.file
    origem.seek(0)
    total = 0
    primeiro = True
    while True:
        bloco = origem.read(BLOCO)
        if not bloco:
            break
        if primeiro:
            # O primeiro bloco tem 64 KB (ou o arquivo inteiro, se menor): em ambos
            # os casos os 5 primeiros bytes ja estao aqui.
            if not bloco.startswith(magico):
                raise HTTPException(415, erro)
            primeiro = False
        total += len(bloco)
        if total > teto_bytes:
            raise HTTPException(413, f"Arquivo acima do limite de {teto_bytes // (1024 * 1024)} MB")
        yield bloco
    if primeiro:          # nenhum bloco: arquivo vazio
        raise HTTPException(415, "Arquivo vazio: envie o arquivo")


def sha_do_arquivo(caminho: Path) -> str:
    """sha256 do que esta EM DISCO, lido em blocos (o arquivo pode ter 10 MB)."""
    h = hashlib.sha256()
    with caminho.open("rb") as f:
        for bloco in iter(lambda: f.read(BLOCO), b""):
            h.update(bloco)
    return h.hexdigest()


def conferir_parseavel(caminho: Path) -> None:
    """O arquivo abre num leitor de PDF de verdade? Senao, 415.

    `%PDF-` sao CINCO BYTES: provam intencao, nao conteudo. A leitura e' a de
    `leitura_pdf` (implementacao unica de "como este projeto abre um PDF"), em
    subprocesso com limite de tempo: PDF hostil e' morto la' e vira 415 aqui.
    """
    conferir_bytes_parseaveis(caminho.read_bytes())


def conferir_bytes_parseaveis(dados: bytes) -> None:
    """`conferir_parseavel` sobre bytes ja' lidos (issue #281: dois anexos validados antes de gravar qualquer um)."""
    try:
        if not leitura_pdf.paginas_com_limite(dados):
            raise ValueError("PDF sem páginas")
    except leitura_pdf.TextoInadequado as e:
        raise HTTPException(415, str(e)) from e
    except Exception as e:
        raise HTTPException(415, leitura_pdf.PDF_CORROMPIDO) from e


def receber_pdf(arquivo: UploadFile, destino_pasta: Path) -> str:
    """Grava o upload num temporario conferindo tipo/tamanho/abertura e devolve o sha256.
    O arquivo final e' `<destino_pasta>/<sha>.pdf` (dedup por CONTEUDO, reconferindo o hash
    do que ja' existe no lugar)."""
    tmp = destino_pasta / f"upload-{os.getpid()}-{secrets.token_hex(8)}.tmp"
    h = hashlib.sha256()
    try:
        with tmp.open("wb") as saida:
            for bloco in blocos_validados(arquivo):
                h.update(bloco)
                saida.write(bloco)
        conferir_parseavel(tmp)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

    sha = h.hexdigest()
    final = destino_pasta / f"{sha}.pdf"
    if final.exists() and sha_do_arquivo(final) == sha:
        tmp.unlink(missing_ok=True)
    else:
        tmp.replace(final)   # rename no mesmo volume: ou aparece inteiro, ou nao aparece
    return sha
