"""Extracao de texto de PDF com tetos e em subprocesso (app/leitura_pdf.py).

Os testes do localizador/validador generico de certidao sairam no bloco 4 com o codigo; a leitura
das seis certidoes e' testada em test_leitura_certidao.py contra textos reais.
"""
import base64
import pathlib
import re
import zlib

import pytest

from app import leitura_certidao, leitura_pdf

# A configuracao REAL do OCR, guardada antes de o `sem_ocr` do conftest desliga-la em cada teste.
_CONFIGURACAO_OCR = leitura_pdf.configuracao_ocr


def test_ocr_le_o_fgts_sem_camada_de_texto(monkeypatch):
    """CRF real salvo do site da Caixa: as letras viraram curvas, nao ha texto. O OCR local le e o
    leitor do FGTS aceita. So' roda onde o Tesseract e o portugues estao instalados (DASH_TESSDATA)."""
    cfg = _CONFIGURACAO_OCR()
    if cfg is None:
        pytest.skip("Tesseract com português não instalado")
    monkeypatch.setattr(leitura_pdf, "configuracao_ocr", lambda: cfg)
    pdf = (pathlib.Path(__file__).parent / "fixtures" / "certidoes" / "fgts-sem-texto.pdf").read_bytes()
    assert leitura_pdf.texto_de_pdf_com_limite(pdf).strip() == ""
    lido = leitura_certidao.ler(leitura_pdf.texto_por_ocr_com_limite(pdf))
    assert (lido["tipo"], lido["cnpj"], lido["emissao"], lido["validade"]) == \
        ("fgts", "31200606000102", "2026-08-26", "2026-09-24")



































def test_texto_de_pdf_de_pagina_em_branco_e_vazio():
    import io
    from pypdf import PdfWriter
    w = PdfWriter(); w.add_blank_page(width=595, height=842)
    buf = io.BytesIO(); w.write(buf)
    assert leitura_pdf.texto_de_pdf(buf.getvalue()).strip() == ""


def _pdf_de_n_paginas(n: int) -> bytes:
    import io
    from pypdf import PdfWriter
    w = PdfWriter()
    for _ in range(n):
        w.add_blank_page(width=595, height=842)
    buf = io.BytesIO(); w.write(buf)
    return buf.getvalue()


def test_regexes_nao_explodem_com_espacos_ate_o_teto():
    # Orcamento de tempo, nao de perfil: com `\s*:?\s*` cada uma destas frases custava
    # dezenas de SEGUNDOS de CPU (backtracking quadratico) numa rota sincrona aberta a
    # quem edita cadastros. Com o `:` dentro de um grupo opcional, custa milissegundos.
    import time
    # Uma palavra-chave por regex de campo: o prefixo literal dela (ate o primeiro metacaractere),
    # para nenhuma falhar no primeiro caractere e escapar dos espacos. Sai de `_CAMPOS`, nao de lista fixa.
    # Regex sem prefixo literal (comeca por lookbehind, grupo etc.) nao da' palavra-chave: so' pode
    # ficar de fora se estiver aqui, de modo que uma regex nova sem prefixo derruba o teste.
    sem_prefixo_ok = {("municipal", "numero")}
    palavras, sem_prefixo = set(), set()
    for tipo, campos in leitura_certidao._CAMPOS.items():
        for campo, regex in campos.items():
            prefixo = re.match(r"(?:\\b)?([A-Z0-9 /,\-]*)", regex).group(1)
            if prefixo:
                palavras.add(prefixo)
            else:
                sem_prefixo.add((tipo, campo))
    assert sem_prefixo <= sem_prefixo_ok, f"regex sem prefixo literal, nao estressada: {sem_prefixo - sem_prefixo_ok}"
    assert len(palavras) >= 12, palavras
    for palavra in sorted(palavras):
        texto = palavra + " " * (leitura_pdf.TETO_CARACTERES - len(palavra) - 1) + "x"
        inicio = time.perf_counter()
        # `ler` normaliza os espacos antes de casar (`plano`) e recusa por "sem-texto" (o que sobra
        # fica abaixo de MIN_TEXTO): so exercita `plano`. O que estressa os padroes e' casar cada
        # regex de campo contra o texto CRU, com os espacos intactos.
        with pytest.raises(leitura_certidao.Recusa):
            leitura_certidao.ler(texto)
        for campos in leitura_certidao._CAMPOS.values():
            for regex in campos.values():
                re.search(regex, texto)
        # 3 s, e nao 1 s: a assercao e' "milissegundos contra dezenas de SEGUNDOS", e
        # nesta maquina compartilhada um orcamento apertado falha por carga alheia, nao
        # por regressao (M7 da revisao final).
        assert time.perf_counter() - inicio < 3.0, repr(palavra)


def test_pdf_com_paginas_demais_e_recusado_antes_de_extrair():
    with pytest.raises(leitura_pdf.TextoInadequado) as e:
        leitura_pdf.texto_de_pdf(_pdf_de_n_paginas(leitura_pdf.TETO_PAGINAS + 1))
    assert "páginas" in str(e.value)


def test_pdf_no_limite_de_paginas_ainda_e_lido():
    assert leitura_pdf.texto_de_pdf(_pdf_de_n_paginas(leitura_pdf.TETO_PAGINAS)).strip() == ""


def test_pdf_com_texto_acima_do_teto_para_a_extracao():
    from tests.conftest import _pdf_com_texto
    pdf = _pdf_com_texto("a" * (leitura_pdf.TETO_CARACTERES + 10))
    with pytest.raises(leitura_pdf.TextoInadequado) as e:
        leitura_pdf.texto_de_pdf(pdf)
    assert "texto demais" in str(e.value)


def test_bomba_de_descompressao_cai_antes_do_pypdf():
    """Achado 1 do gate 3. UMA pagina, poucos KB em disco, MB inflando no `extract_text`:
    o teto de paginas nao ve, o de 10 MB nao ve, e o de caracteres so' valeria DEPOIS de
    a memoria ja ter sido alocada. O tempo e' parte da assercao -- a defesa nao pode ser
    "inflar tudo e medir no fim"."""
    import time
    from tests.conftest import _pdf_com_texto
    pdf = _pdf_com_texto("0" * (leitura_pdf.TETO_STREAM_BYTES + 1_000_000), comprimir=True)
    assert len(pdf) < 100_000, "a bomba tem que ser pequena EM DISCO"
    inicio = time.perf_counter()
    with pytest.raises(leitura_pdf.TextoInadequado) as e:
        leitura_pdf.texto_de_pdf(pdf)
    assert time.perf_counter() - inicio < 5.0     # "rapido", nao "instantaneo" (M7)
    assert "comprimido" in str(e.value)


def _zlib_com_marcador(carga: bytes, marcador: bytes) -> bytes:
    """Stream zlib que CONTEM `marcador` literalmente nos bytes comprimidos.

    Um bloco 'stored' do deflate escreve os bytes crus e termina alinhado, entao da'
    para emenda-lo na frente do corpo comprimido de verdade -- e' assim que um atacante
    poe um `endstream` falso logo no comeco do stream sem estragar a descompressao.
    """
    bloco = (b"\x00" + len(marcador).to_bytes(2, "little")
             + (len(marcador) ^ 0xFFFF).to_bytes(2, "little") + marcador)
    co = zlib.compressobj(9, zlib.DEFLATED, -15)     # deflate cru, sem cabecalho zlib
    return (b"\x78\x9c" + bloco + co.compress(carga) + co.flush()
            + zlib.adler32(marcador + carga).to_bytes(4, "big"))


def test_endstream_falso_dentro_do_stream_nao_engana_a_pre_checagem():
    """Delimitar pelo primeiro `endstream` deixava a bomba passar: a pre-checagem
    inflava so' o pedaco antes do marcador falso e o pypdf, que le `/Length` bytes,
    inflava tudo. Com `/Length` direto e plausivel, os dois olham o mesmo trecho."""
    dados = _zlib_com_marcador(b"0" * (leitura_pdf.TETO_STREAM_BYTES + 1_000_000),
                               b"\nendstream\n     ")
    assert b"endstream" in dados[:64], "o marcador falso tem que estar no comeco"
    pdf = (b"%PDF-1.4\n1 0 obj\n<< /Length " + str(len(dados)).encode()
           + b" /Filter /FlateDecode >>\nstream\n" + dados + b"\nendstream\nendobj\n")
    with pytest.raises(leitura_pdf.TextoInadequado):
        leitura_pdf.conferir_streams(pdf)


def _objeto(dicionario: bytes, dados: bytes) -> bytes:
    """Um objeto de stream solto, para exercitar `conferir_streams` (que le bytes crus,
    antes de qualquer parser -- nao precisa de xref)."""
    return (b"%PDF-1.4\n1 0 obj\n" + dicionario + b"\nstream\n" + dados
            + b"\nendstream\nendobj\n")


def _bomba() -> bytes:
    return zlib.compress(b"0" * (leitura_pdf.TETO_STREAM_BYTES + 1_000_000))


def test_enchimento_no_dicionario_nao_esconde_a_bomba():
    """Achado do round 3. Com janela fixa de bytes, 3 KB de chave inútil entre
    `/FlateDecode` e `stream` punham o objeto fora do alcance: a pré-checagem dava o
    stream por não-Flate e o pypdf inflava a bomba (12 s a partir de 8,7 KB)."""
    import time
    dados = _bomba()
    pdf = _objeto(b"<< /Filter /FlateDecode /Xx " + b"a" * 3000 + b" /Length "
                  + str(len(dados)).encode() + b" >>", dados)
    inicio = time.perf_counter()
    with pytest.raises(leitura_pdf.TextoInadequado):
        leitura_pdf.conferir_streams(pdf)
    assert time.perf_counter() - inicio < 1.0     # "rapido", nao "instantaneo" (M7)


def test_bomba_com_filtros_em_cadeia_e_recusada():
    """`/Filter [/ASCII85Decode /FlateDecode]` é PDF válido: os bytes crus não são zlib,
    o stream ficava sem medir -- e o pypdf desfazia os dois filtros e inflava tudo."""
    a85 = base64.a85encode(_bomba(), adobe=True)
    with pytest.raises(leitura_pdf.TextoInadequado):
        leitura_pdf.conferir_streams(_objeto(
            b"<< /Filter [/ASCII85Decode /FlateDecode] /Length "
            + str(len(a85)).encode() + b" >>", a85))
    hexa = _bomba().hex().encode() + b">"
    with pytest.raises(leitura_pdf.TextoInadequado):
        leitura_pdf.conferir_streams(_objeto(
            b"<< /Filter [/ASCIIHexDecode /FlateDecode] /Length "
            + str(len(hexa)).encode() + b" >>", hexa))


def test_cadeia_legitima_continua_passando():
    """A mesma cadeia com conteúdo de certidão não pode ser recusada."""
    pequeno = base64.a85encode(zlib.compress(b"BT (Valida ate 29/01/2027) Tj ET"),
                               adobe=True)
    leitura_pdf.conferir_streams(_objeto(
        b"<< /Filter [/ASCII85Decode /FlateDecode] /Length "
        + str(len(pequeno)).encode() + b" >>", pequeno))


def test_filtro_que_nao_sabemos_desfazer_fica_com_o_subprocesso():
    """Ruling R28 (revoga R25). O que a pré-checagem não mede ela IGNORA -- recusar
    virava falso positivo em PDF legítimo, e um leitor de bytes crus nunca ficou
    estanque. Quem segura o arquivo é o limite de tempo do subprocesso: o caminho
    completo termina em 422 ou 200 dentro do tempo, sem travar o processo."""
    import time
    dados = _bomba()
    pdf = _objeto(b"<< /Filter [/LZWDecode /FlateDecode] /Length "
                  + str(len(dados)).encode() + b" >>", dados)
    leitura_pdf.conferir_streams(pdf)            # não recusa mais
    inicio = time.perf_counter()
    try:
        leitura_pdf.com_limite(pdf, "texto")     # 200
    except ValueError:                           # TextoInadequado ou pypdf: 422
        pass
    # folga larga: com a CPU freada (13% sob carga) so' abrir o subprocesso leva segundos;
    # o que o teste prova e' que termina, nao que termina rapido (issue #19)
    assert time.perf_counter() - inicio < leitura_pdf.TEMPO_LIMITE_S + 20


def test_com_limite_devolve_o_mesmo_que_a_leitura_no_processo():
    from tests.conftest import _pdf_com_texto
    pdf = _pdf_com_texto("Valida ate 29/01/2027", comprimir=True)
    assert leitura_pdf.texto_de_pdf_com_limite(pdf) == leitura_pdf.texto_de_pdf(pdf)
    assert leitura_pdf.paginas_com_limite(pdf) == 1


def test_com_limite_mata_o_filho_que_estoura_o_tempo(monkeypatch):
    """Ruling R28. A garantia e' TEMPO DE PAREDE: estourou, o filho morre e o chamador
    recebe a recusa -- e nenhum processo fica para tras."""
    import multiprocessing
    import time
    monkeypatch.setattr(leitura_pdf, "TEMPO_LIMITE_S", 1.0)
    inicio = time.perf_counter()
    with pytest.raises(leitura_pdf.TextoInadequado) as e:
        leitura_pdf.com_limite(b"%PDF-1.4", "dormir")
    assert "demorou mais de 1 s" in str(e.value)
    assert time.perf_counter() - inicio < 4.0
    assert multiprocessing.active_children() == []


def test_leitura_sem_vaga_e_recusada_dentro_do_orcamento(monkeypatch):
    """Ruling R30. O limite de tempo protege UMA requisicao; sem teto de concorrencia,
    N uploads hostis simultaneos viram N pypdf inflando memoria ao mesmo tempo. Com as
    duas vagas ocupadas, a terceira espera o orcamento e vira recusa de fila -- nao
    fica pendurada nem abre um processo a mais."""
    import time
    monkeypatch.setattr(leitura_pdf, "TEMPO_LIMITE_S", 0.5)
    assert leitura_pdf._VAGAS.acquire(timeout=5)
    assert leitura_pdf._VAGAS.acquire(timeout=5)
    try:
        inicio = time.perf_counter()
        with pytest.raises(leitura_pdf.TextoInadequado) as e:
            leitura_pdf.com_limite(b"%PDF-1.4", "dormir")
        gasto = time.perf_counter() - inicio
    finally:
        leitura_pdf._VAGAS.release()
        leitura_pdf._VAGAS.release()
    assert "demais em andamento" in str(e.value)
    assert 0.4 <= gasto < 3.0, gasto      # esperou o orcamento, e so' ele


def test_filho_que_morre_sem_responder_nao_deixa_handle_nem_vaga(monkeypatch):
    """Dívida da fase 3: o filho morto sem resposta vira recusa, o cano e o processo são fechados
    (proc.close) e a vaga volta -- senão cada morte vazaria um handle e, em duas, travaria a fila."""
    import multiprocessing
    fechados = []
    real = multiprocessing.get_context("spawn")

    class Rastreado:
        """Embrulha o Process real (que o spawn precisa picklar inteiro) so' para ver o close."""
        def __init__(self, **kw):
            self._p = real.Process(**kw)
        def close(self):
            fechados.append(self._p.pid)
            self._p.close()
        def __getattr__(self, nome):
            return getattr(self._p, nome)

    class Contexto:
        Pipe = staticmethod(real.Pipe)
        Process = Rastreado

    monkeypatch.setattr(leitura_pdf.multiprocessing, "get_context", lambda _: Contexto())
    for _ in range(3):
        with pytest.raises(leitura_pdf.TextoInadequado) as e:
            leitura_pdf.com_limite(b"%PDF-1.4", "morrer")
        assert "falhou" in str(e.value)
    assert len(fechados) == 3
    assert multiprocessing.active_children() == []
    assert leitura_pdf._VAGAS.acquire(timeout=1) and leitura_pdf._VAGAS.acquire(timeout=1)
    leitura_pdf._VAGAS.release()
    leitura_pdf._VAGAS.release()


def test_spawn_que_falha_fecha_as_duas_pontas_do_cano_e_devolve_a_vaga(monkeypatch):
    pontas = []

    class Cano:
        def __init__(self):
            self.fechado = False
        def close(self):
            self.fechado = True

    class Contexto:
        def Pipe(self, duplex=False):
            par = (Cano(), Cano())
            pontas.extend(par)
            return par
        def Process(self, **_):
            raise OSError("sem handle")

    monkeypatch.setattr(leitura_pdf.multiprocessing, "get_context", lambda _: Contexto())
    with pytest.raises(OSError):
        leitura_pdf.com_limite(b"%PDF-1.4", "texto")
    assert len(pontas) == 2 and all(p.fechado for p in pontas)
    assert leitura_pdf._VAGAS.acquire(timeout=1) and leitura_pdf._VAGAS.acquire(timeout=1)
    leitura_pdf._VAGAS.release()
    leitura_pdf._VAGAS.release()


def test_erro_do_pypdf_no_filho_vira_valueerror_no_pai():
    with pytest.raises(ValueError) as e:
        leitura_pdf.com_limite(b"%PDF-1.4 lixo", "texto")
    assert type(e.value) is ValueError and "PDF inválido" in str(e.value)


def test_stream_grande_e_honesto_passa_e_imagem_sem_flate_nao_e_tocada():
    """Ruling R26. Certidão digitalizada em 300 dpi tem imagem Flate de 8 a 9 MB com
    razão de 2 a 4 para 1: o teto de bytes sozinho recusava documento legítimo. O que
    condena é a RAZÃO de expansão."""
    import os
    bruto = os.urandom(6 * 1024 * 1024).translate(bytes(range(16)) * 16)
    scan = zlib.compress(bruto, 1)
    assert len(bruto) / len(scan) < leitura_pdf.RAZAO_BOMBA
    leitura_pdf.conferir_streams(_objeto(
        b"<< /Filter /FlateDecode /Length " + str(len(scan)).encode() + b" >>", scan))
    # imagem sem Flate nenhum (JPEG dentro do PDF) nao entra na conta
    leitura_pdf.conferir_streams(_objeto(b"<< /Filter /DCTDecode /Length 64 >>",
                                         os.urandom(64)) + b"/FlateDecode\n")


def test_pdf_com_flate_legitimo_continua_sendo_lido():
    """A pre-checagem nao pode recusar o caso normal: quase todo PDF real comprime o
    content stream."""
    from tests.conftest import _pdf_com_texto
    pdf = _pdf_com_texto("Valida ate 29/01/2027", comprimir=True)
    assert "29/01/2027" in leitura_pdf.texto_de_pdf(pdf)


def test_primeiras_paginas_le_so_duas_e_nao_tem_o_teto_da_certidao():
    """Capa do SMO (#285): o envelope do DocuSign tem centenas de paginas e a capa vem na p. 1 ou 2."""
    pdf = _pdf_de_n_paginas(leitura_pdf.TETO_PAGINAS + 5)
    assert leitura_pdf.primeiras_paginas_com_limite(pdf) == ["", ""]


def test_ocr_do_pacote_nao_tem_o_teto_de_paginas_da_certidao(monkeypatch):
    import types
    chamadas = []

    def tesseract(cmd, input, **k):
        chamadas.append(cmd[0])
        return types.SimpleNamespace(returncode=0, stdout="página".encode())
    monkeypatch.setattr(leitura_pdf.subprocess, "run", tesseract)
    pdf = _pdf_de_n_paginas(leitura_pdf.TETO_PAGINAS + 5)
    with pytest.raises(leitura_pdf.TextoInadequado):
        leitura_pdf.texto_por_ocr(pdf, "tesseract", "tessdata")
    assert leitura_pdf.texto_por_ocr(pdf, "tesseract", "tessdata", pacote=True) == "página\npágina"
    assert chamadas == ["tesseract", "tesseract"]       # so' as primeiras `OCR_PAGINAS`




# --- de quem e' o CNPJ (achado 3 do gate 3) -------------------------------------------
#
# Certidao estadual/municipal imprime o CNPJ DO ORGAO no timbre, acima do contribuinte.
# "O primeiro com DV valido" pendurava a certidao no orgao emissor -- e o CNPJ e' a
# chave que liga o documento a entidade.

ORGAO = "12345678000195"         # CNPJ SINTETICO com DV valido; nenhum orgao real
MUNICIPAL = """PREFEITURA MUNICIPAL DE CUIABÁ
SECRETARIA MUNICIPAL DE FAZENDA — CNPJ 12.345.678/0001-95
CERTIDÃO NEGATIVA DE DÉBITOS MUNICIPAIS
Contribuinte: LOTUFO ENGENHARIA LTDA
CNPJ: 31.200.101/0001-30
Emitida em: 17/08/2026
Válida até: 15/11/2026
"""










