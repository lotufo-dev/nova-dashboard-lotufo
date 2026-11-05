import pathlib
import sqlite3
import zlib

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from app import db
from app.main import create_app

# O cadastro dos testes e' sempre o de EXEMPLO (fictício), nunca o que `DASH_CADASTRO_DIR` aponta: o cadastro
# real mora fora do repositório e so' o teste de regressao dos valores reais (test_espelho_cadastro_real) o le.
CADASTRO_EXEMPLO = pathlib.Path(__file__).resolve().parents[2] / "cadastro-exemplo"

# --- Suite rapida (issue #88) ------------------------------------------------------------
# Duas coisas faziam cada teste de API custar segundos: o argon2 com custo de producao
# (hash + verify + verify-dummy a cada `client_admin`) e as 36 migracoes rodando num banco
# novo a cada teste. Nenhuma das duas prova nada num teste; as fixtures abaixo tiram o custo
# sem mudar o codigo de producao nem os testes.

_migrate_real = db.migrate


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "migracao_real: o teste exercita o proprio db.migrate e parte de um banco vazio, sem o banco-modelo")
    config.addinivalue_line(
        "markers",
        "instalacao_real: o teste confere o arquivo de instalacao de verdade, em vez de rodar como dev")


@pytest.fixture(autouse=True)
def conferencias_zeradas(monkeypatch):
    """Issue #457: a ultima conferencia do codigo em producao (#421) mora no modulo `app.integridade`. Sem zerar, o
    "Sem registro do ultimo deploy" de um teste aparecia no bloco Seguranca do teste seguinte do mesmo worker do xdist.
    Cada teste comeca como o processo recem-subido: sem conferencia. As threads que preenchiam isso no meio de outro
    teste (subida com jobs em test_instalacao) nao sobem mais nos testes."""
    from app import integridade, seguranca
    monkeypatch.setattr(integridade, "ESTADO", None)
    monkeypatch.setattr(integridade, "_anterior", None)
    monkeypatch.setattr(seguranca, "_conferencia", [])      # a conferencia da protecao de usuarios (#422), idem


@pytest.fixture(autouse=True)
def instalacao_dev(request, monkeypatch):
    """Os testes rodam como `dev` (issue #417): nada desligado e nenhum arquivo de instalacao exigido. Quem testa a
    conferencia de verdade marca `instalacao_real` e assina o arquivo com um par de chaves gerado no proprio teste."""
    from app import instalacao
    monkeypatch.setattr(instalacao, "_estado", None)
    if request.node.get_closest_marker("instalacao_real"):
        return
    monkeypatch.setattr(instalacao, "verificar", lambda: {"instalacao": instalacao.DEV, "motivo": None})


@pytest.fixture(autouse=True)
def argon2_leve(monkeypatch):
    """Hasher de custo minimo so' nos testes; `auth._ph` de producao nao muda.

    O `_HASH_DUMMY` vai junto: o verify do argon2 le o custo de dentro do hash, entao um
    dummy gerado com custo de producao continuaria caro em todo login de e-mail inexistente.
    """
    from app import auth
    ph = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    monkeypatch.setattr(auth, "_ph", ph)
    monkeypatch.setattr(auth, "_HASH_DUMMY", ph.hash("hash-dummy-para-tempo-uniforme"))


@pytest.fixture(scope="session")
def _banco_modelo(tmp_path_factory):
    """Migra uma vez por sessao; cada teste recebe uma copia (ver `banco_modelo`)."""
    caminho = tmp_path_factory.mktemp("modelo") / "modelo.db"
    with pytest.MonkeyPatch.context() as mp:  # o modelo nasce pelo mesmo get_conn que a app usa
        mp.setenv("DASH_DB_PATH", str(caminho))
        conn = db.get_conn()
    _migrate_real(conn)
    conn.close()
    return caminho


@pytest.fixture(autouse=True)
def banco_modelo(request, monkeypatch, _banco_modelo):
    """Troca `db.migrate` por uma copia do banco-modelo quando o banco ainda esta vazio.

    Cobre tanto `create_app()` (fixture `client`) quanto os modulos que chamam `db.migrate`
    na propria fixture. Banco que ja tem tabela segue pelo `migrate` real: e' o caso de quem
    apaga uma linha de `schema_migrations` para reaplicar uma migracao (test_frc). Quem testa
    o proprio runner marca `migracao_real` e fica de fora.
    """
    if request.node.get_closest_marker("migracao_real"):
        return

    def migrate_pela_copia(conn: sqlite3.Connection) -> None:
        if conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone() is None:
            origem = sqlite3.connect(_banco_modelo)
            try:
                origem.backup(conn)
            finally:
                origem.close()
            return
        _migrate_real(conn)

    monkeypatch.setattr(db, "migrate", migrate_pela_copia)


@pytest.fixture(autouse=True)
def sem_ocr(monkeypatch):
    """OCR desligado por padrao: o resultado de um teste nao pode depender do Tesseract instalado na
    maquina. Quem testa o OCR religa (`leitura_pdf.configuracao_ocr` real ou texto simulado)."""
    from app import leitura_pdf
    monkeypatch.setattr(leitura_pdf, "configuracao_ocr", lambda: None)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("DASH_SEM_JOBS", "1")  # nada de thread de backup nos testes
    monkeypatch.setenv("DASH_SEM_FRONTEND", "1")  # sem o mount "/" (ele engoliria rotas de teste)
    app = create_app()
    with TestClient(app) as c:
        yield c

@pytest.fixture
def client_admin(client):
    """Client ja logado como admin, com o header X-CSRF-Token preenchido."""
    from app import auth, db
    conn = db.get_conn()
    auth.criar_usuario(conn, "Admin", "admin@lotufo.com", "senha-forte-123", "admin")
    conn.close()
    r = client.post("/api/auth/login", json={"email": "admin@lotufo.com", "senha": "senha-forte-123"})
    assert r.status_code == 200, r.text
    # o cookie de sessao e secure=True e nao volta sozinho em http://testserver:
    # injetar na jar do client (mesmo tratamento usado em test_permissoes.py)
    token = r.cookies.get("sessao") or client.cookies.get("sessao")
    client.cookies.set("sessao", token)
    client.headers["X-CSRF-Token"] = r.json()["csrf"]
    return client


@pytest.fixture
def sem_certidoes_exigidas(client):
    """Desliga a exigencia dos tipos de certidao SEMEADOS (migracao 006).

    Desde a fase 3,5 o checklist trava o protocolo com certidao pendente, e num banco
    recem-criado TODO contrato esta' pendente. Os modulos que testam medicoes e
    paineis usam esta fixture (autouse) porque nao sao sobre certidoes; quem testa o
    travamento cria o proprio tipo exigido.
    """
    from app import db
    conn = db.get_conn()
    try:
        conn.execute("UPDATE certidao_tipos SET aplicavel_por_padrao=0")
        conn.commit()
    finally:
        conn.close()


# --- PDF de mentira, montado a mao ----------------------------------------------------
# Mora aqui desde que o robo das federais saiu (spec §15.2): o helper nasceu no teste do
# robo, mas quem o usa hoje sao os testes de upload e de leitura do PDF.

def _pdf_com_texto(texto: str, comprimir: bool = False) -> bytes:
    """PDF de 1 pagina com `texto` no content stream, com xref de offsets reais.

    Montado a mao de proposito: gerar PDF exigiria dependencia nova so para o teste,
    e o que esta sendo testado e' a EXTRACAO (pypdf + regex), nao a geracao. Os
    offsets do xref sao calculados sobre os bytes ja emitidos -- um xref torto faria
    o pypdf cair no modo de reconstrucao e o teste passaria por acidente.

    `comprimir=True` grava o content stream com /Filter /FlateDecode, que e' como
    quase todo PDF real vem. E' o que permite montar tanto a bomba de descompressao
    (texto enorme, arquivo de poucos KB) quanto o caso legitimo que a pre-checagem de
    `leitura_pdf.conferir_streams` tem que continuar deixando passar.
    """
    # Parenteses e barra invertida sao delimitadores de string literal no PDF.
    escapado = texto.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    fluxo = f"BT /F1 12 Tf 40 700 Td ({escapado}) Tj ET".encode("latin-1")
    filtro = b""
    if comprimir:
        fluxo = zlib.compress(fluxo)
        filtro = b" /Filter /FlateDecode"
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d%s >>\nstream\n%s\nendstream" % (len(fluxo), filtro, fluxo),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    saida = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, corpo in enumerate(objetos, start=1):
        offsets.append(len(saida))
        saida += b"%d 0 obj\n" % i + corpo + b"\nendobj\n"
    inicio_xref = len(saida)
    saida += b"xref\n0 %d\n" % (len(objetos) + 1)
    saida += b"0000000000 65535 f \n"
    for off in offsets:
        saida += b"%010d 00000 n \n" % off
    saida += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
              % (len(objetos) + 1, inicio_xref))
    return bytes(saida)


# --- contrato sem a API ------------------------------------------------------------------
# A escrita de contrato pela API saiu no bloco 9 (o cadastro e' versionado). Os testes que
# precisam de um contrato para exercitar outra rota criam pelo repositorio, com o mesmo corpo
# que mandavam ao POST antigo ("valor_original" em BRL).

def novo_contrato(dados: dict) -> int:
    from app import contratos, db
    from app.dinheiro import parse_brl
    dados = dict(dados)
    if "valor_original" in dados:
        dados["valor_original_centavos"] = parse_brl(dados.pop("valor_original"))
    conn = db.get_conn()
    try:
        return contratos.criar(conn, None, dados)
    finally:
        conn.close()


# --- imagem de assinatura de mentira (issue #33) -----------------------------------------
# Montadas so' com a biblioteca padrao: o que se testa e' a conferencia da estrutura do arquivo.

def _png(largura=4, altura=2, cor=0, prof=8, plte=None, idat=None, idat_pela_metade=False, sobra=b"",
         iend=b"", depois_do_iend=b""):
    """PNG nao entrelacado; por padrao, integro (cinza 8 bits). `plte`: inclui o bloco de paleta (padrao: so'
    quando cor=3); `idat`: troca a imagem comprimida; `idat_pela_metade`: blocos certos (CRC, IEND no fim), mas
    a imagem comprimida para no meio; `sobra`: bytes depois do fim da imagem comprimida, dentro do IDAT."""
    import struct

    def bloco(tipo, dados):
        return struct.pack(">I", len(dados)) + tipo + dados + struct.pack(">I", zlib.crc32(tipo + dados))
    amostras = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[cor]
    linha = b"\x00" + bytes(i % 251 for i in range((largura * amostras * prof + 7) // 8))
    comprimido = zlib.compress(linha * altura) if idat is None else idat
    if idat_pela_metade:
        comprimido = comprimido[: len(comprimido) // 2]
    paleta = bloco(b"PLTE", bytes(range(256)) * 3) if (cor == 3 if plte is None else plte) else b""
    return (b"\x89PNG\r\n\x1a\n" + bloco(b"IHDR", struct.pack(">IIBBBBB", largura, altura, prof, cor, 0, 0, 0))
            + paleta + bloco(b"IDAT", comprimido + sobra) + bloco(b"IEND", iend) + depois_do_iend)


def _jpg(antes_do_quadro=b"", sof=None, entre_varreduras=None):
    """JPG minimo bem formado: SOI, APP0, SOF0, SOS, dados da varredura e EOI. `antes_do_quadro`: bytes
    (marcadores) inseridos entre o APP0 e o SOF0; `sof`: troca o segmento SOF0; `entre_varreduras`: segmento
    inserido depois da primeira varredura, seguido de uma segunda varredura (como no JPG progressivo)."""
    if sof is None:
        sof = b"\xff\xc0" + bytes([0, 11, 8, 0, 1, 0, 1, 1, 1, 0x11, 0])
    sos = b"\xff\xda" + bytes([0, 8, 1, 1, 0, 0, 0x3f, 0])
    varreduras = sos + b"\x12\x34\xff\x00\x56\xff\xd0\x78"
    if entre_varreduras is not None:
        varreduras += entre_varreduras + sos + b"\x9a\xbc"
    return b"\xff\xd8" + b"\xff\xe0\x00\x04\x00\x00" + antes_do_quadro + sof + varreduras + b"\xff\xd9"
