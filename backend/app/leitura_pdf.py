"""Extracao do texto de PDF com tetos e em subprocesso (spec §15).

Unica implementacao do projeto de "como abrir um PDF": tetos de paginas, de caracteres e de
descompressao (bomba), limite de tempo de parede e de concorrencia. Quem interpreta o texto mora
em outro modulo: `leitura_certidao.py` (as seis certidoes, bloco 4), `leitura_nfse.py` (nota
fiscal, bloco 3). A leitura do termo aditivo saiu no bloco 9 (aditivo entra pelo cadastro). O localizador e o validador genericos de
certidao que moravam aqui (fase 3) sairam no bloco 4.

OCR local (emenda de 2026-09-24 a spec 2026-09-21 §9): PDF de certidao sem texto e' desenhado
pagina a pagina (pypdfium2) e lido pelo Tesseract instalado no servidor, no mesmo subprocesso com
limite. Nada sai da maquina e nada e' pago por uso.
"""
import base64
import binascii
import bisect
import io
import multiprocessing
import os
import re
import shutil
import subprocess
import threading
import time
import zlib
from pathlib import Path

import pypdf


MANUAL = "preencha manualmente"
TETO_CARACTERES = 60_000
TETO_PAGINAS = 20
# Tetos da PRE-CHECAGEM de descompressao (ver `conferir_streams`): 4 MB por stream
# Flate e 16 MB somando todos. Uma certidao de 1-3 paginas com fonte embutida nao
# chega perto disso; um PDF que chega e' bomba ou e' outro tipo de arquivo.
TETO_STREAM_BYTES = 4 * 1024 * 1024
TETO_STREAMS_TOTAL = 16 * 1024 * 1024
# Assinatura de bomba: quantas vezes o trecho pode crescer antes de virar recusa. Uma
# digitalizacao de certidao em 300 dpi comprime de 3 a 5 vezes; um PDF de texto, algumas
# dezenas; bomba de descompressao passa de mil. So' o teto de bytes, sem esta razao,
# recusava a certidao escaneada -- documento legitimo, e o que mais chega pela mesa.
RAZAO_BOMBA = 50
# Tempo de PAREDE que uma leitura de PDF pode levar no subprocesso (ver `com_limite`).
# Certidao real le em decimos de segundo; o que passa disso e' arquivo hostil ou errado.
TEMPO_LIMITE_S = 10.0
# Quantas leituras podem estar em subprocesso AO MESMO TEMPO (ruling R30). O limite de
# tempo protege cada requisicao; sem um teto de concorrencia, N uploads hostis simultaneos
# viram N processos de pypdf inflando memoria por ate `TEMPO_LIMITE_S` cada -- a maquina
# e' um servidor de escritorio com uma mesa usando o sistema, nao um cluster. Dois: o
# suficiente para o operador que le uma certidao enquanto outra sobe, e nada alem disso.
# `BoundedSemaphore` (e nao `Semaphore`) para que um `release` a mais estoure aqui, e nao
# vire teto silenciosamente maior.
_VAGAS = threading.BoundedSemaphore(2)
# Uma frase so' para as duas guardas de tamanho (a da extracao e a de `ler_certidao`):
# quem recebe o 422 nao precisa saber em qual das duas o arquivo bateu.
_TEXTO_DEMAIS = ("O PDF tem texto demais para uma certidão ({n} caracteres) — "
                 f"confira o arquivo e {MANUAL}.")
_COMPRIMIDO_DEMAIS = (f"O PDF contém um trecho que expande mais de {RAZAO_BOMBA} vezes "
                      f"ao ser descomprimido (bomba de descompressão) — confira o "
                      f"arquivo e {MANUAL}.")
_DEMOROU = ("O PDF demorou mais de {s} s para ser lido e a leitura foi interrompida — "
            f"{MANUAL}.")
_FALHOU = f"A leitura do PDF falhou por falta de memória ou erro interno — {MANUAL}."
# Teto de concorrencia estourado (ver `_VAGAS`): nao e' erro do arquivo, e' fila. A frase
# diz o que fazer -- esperar -- em vez de mandar conferir um PDF que esta certo.
_LOTADO = "Há leituras de PDF demais em andamento — tente de novo em alguns segundos."

# OCR: so' as primeiras paginas (a certidao cabe em uma ou duas), a 300 dpi, UM por vez (o
# servidor tambem roda o RM) e com prazo proprio: medido em ~1 s por pagina nesta maquina, mas a
# CPU dela cai a 13% sob carga. Pagina gigante e' reduzida para caber em `OCR_MAX_PIXELS_LADO`.
OCR_PAGINAS = 2
OCR_DPI = 300
OCR_MAX_PIXELS_LADO = 5000
OCR_TEMPO_LIMITE_S = 40.0
_VAGA_OCR = threading.BoundedSemaphore(1)
_TESSERACT_PADRAO = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
_SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Pacote de protocolo (bloco 5): a conferencia do assinado le o texto de CADA pagina de um PDF grande.
TEMPO_PACOTE_S = 60.0
# Tetos da guarda de bomba para o PACOTE: o pacote real da Cavalaria (CT-291, 92 paginas) tem trecho que
# infla mais de 50:1 (pagina escaneada quase em branco) e passa do teto de 4 MB da certidao. A guarda
# continua (memoria limitada), com teto proporcional a um PDF de ate' 40 MB.
TETO_STREAM_PACOTE = 64 * 1024 * 1024
TETO_STREAMS_PACOTE = 512 * 1024 * 1024
TETO_CARACTERES_PAGINA = 20_000


class TextoInadequado(ValueError):
    """PDF sem texto legivel (digitalizado, imagem) ou texto acima do teto."""


# --- leitura do PDF (unica implementacao do projeto; o upload tambem usa) -------------

# Um marcador por alternativa, NAO `stream\r?\n(.*?)\r?\nendstream`: o `.*?` do meio
# custa uma varredura ate o fim do arquivo por `stream` que nao tem `endstream` depois,
# e um arquivo de 1 MB feito so de "stream\n" levava MAIS DE DOIS MINUTOS de CPU
# (medido) -- seria trocar a bomba de descompressao por uma bomba de regex na funcao
# que existe para desarmar a primeira. Emparelhar os marcadores de uma varredura so' e'
# linear e da' o mesmo par (inicio, fim) que a forma com `.*?` daria.
_MARCADOR_STREAM = re.compile(rb"stream\r?\n|endstream")
# O `stream` vem logo depois do `>>` que fecha o dicionario do objeto (ISO 32000-1
# §7.3.8.1: entre os dois so' ha espaco em branco).
_FOLGA_ANTES_STREAM = 64
# Ate onde se procura o `<<` que abre esse dicionario, e quantos niveis de aninhamento
# se aceita (`/DecodeParms << ... >>` e' UM). Dicionario de certidao tem dezenas de
# bytes; a folga e' para o objeto com muita chave, nao para o arquivo hostil (a memoria
# dos memos de `_Dicionarios` e' proporcional a ela). Dicionario maior que isso sai da
# medicao -- e quem segura o resto e' o limite de tempo do subprocesso, nao esta janela.
_JANELA_OBJETO = 8_192
_MAX_ANINHAMENTO = 8
# `/Length N` DIRETO. O lookahead recusa a referencia indireta (`/Length 5 0 R`), cujo
# valor mora em outro objeto e so' o parser resolve. Classes disjuntas e um quantificador
# cada: nao ha o que retroceder.
_LENGTH = re.compile(rb"/Length[ \t\r\n]+(\d{1,12})(?![ \t\r\n]*\d)")
_FOLGA_ENDSTREAM = 32     # espaco em branco tolerado entre o fim dos dados e `endstream`
# `/Filter` com um nome (`/FlateDecode`) ou um vetor (`[/ASCII85Decode /FlateDecode]`).
# O vetor e' lido por uma classe negada com teto -- sem aninhamento, sem retrocesso.
_FILTRO = re.compile(rb"/Filter[ \t\r\n]*(\[[^\]]{0,400}\]|/[A-Za-z0-9]{1,40})")
_NOME = re.compile(rb"/([A-Za-z0-9]{1,40})")
_FLATE = (b"FlateDecode", b"Fl")


class _FiltroDesconhecido(Exception):
    """Filtro que a pre-checagem nao sabe desfazer: o stream fica SEM MEDIR."""


def _de_hex(dados: bytes) -> bytes:
    """ASCIIHexDecode (ISO 32000-1 §7.4.2): pares hexadecimais ate' o `>`."""
    corte = dados.find(b">")
    if corte != -1:
        dados = dados[:corte]
    limpo = re.sub(rb"[^0-9A-Fa-f]", b"", dados)
    if len(limpo) % 2:
        limpo += b"0"                    # digito solto no fim se completa com zero
    return binascii.a2b_hex(limpo)


def _de_85(dados: bytes) -> bytes:
    """ASCII85Decode (§7.4.3). Os delimitadores sao opcionais no arquivo real."""
    dados = dados.strip()
    if not dados.startswith(b"<~"):
        dados = b"<~" + dados
    if not dados.endswith(b"~>"):
        dados = dados + b"~>"
    return base64.a85decode(dados, adobe=True)


# Filtros que podem vir ANTES do Flate na cadeia e que a biblioteca padrao desfaz. Os
# dois so' reembalam bytes (hex e base85) e ENCOLHEM o dado -- desfaze-los antes de
# medir e' barato e nao abre buraco de memoria.
_PRE_FILTROS = {b"ASCIIHexDecode": _de_hex, b"AHx": _de_hex,
                b"ASCII85Decode": _de_85, b"A85": _de_85}


def _ocorrencias(dados: bytes, alvo: bytes) -> list[int]:
    """Offsets de `alvo` em `dados`, do inicio ao fim (varredura unica, em C)."""
    saida: list[int] = []
    i = dados.find(alvo)
    while i != -1:
        saida.append(i)
        i = dados.find(alvo, i + 1)
    return saida


# Teto dos memos de `_Dicionarios`: so' limita memoria num arquivo feito de `<<>>`.
# Quando estoura, o memo e' esvaziado -- e o que se repete a partir dai e' trecho curto.
_MEMO_MAX = 65_536
_TRECHO_CURTO = 64        # ate' aqui, varrer de novo e' mais barato que lembrar


class _Dicionarios:
    """Acha o dicionario `<<`...`>>` que antecede cada `stream`, em custo LINEAR.

    Delimitado por `<<`/`>>`, e NAO por uma janela fixa de bytes antes do `stream`.
    Com janela fixa bastava enfiar chave inutil no dicionario --
    `<< /Filter /FlateDecode /Xx (3 KB de lixo) /Length N >>` -- para o `/FlateDecode`
    cair fora do alcance: a pre-checagem dava o objeto por nao-Flate, nao media nada, e
    o pypdf inflava a bomba (medido: 12 s a partir de 8,7 KB de arquivo).

    O caminho e' de tras para frente: o `>>` esta colado no `stream`, e dai o `<<`
    correspondente e' o primeiro (recuando) que nao tenha um `>>` entre ele e o alvo.
    Cada passo e' um `rfind`/`find` em C -- mas REPETIDO por `stream`, e 10 MB de
    `>>\\nstream\\n01234567\\nendstream\\n` (um `stream` a cada 27 bytes, nenhum `<<`)
    faziam cada um varrer a janela inteira de novo: 13 s com 64 KB, 2 s com 8 KB
    (medido). Daqui o estado: o ultimo `<<` e' acompanhado numa varredura so', para a
    frente; o `<<` anterior a um `<<` e o primeiro `>>` depois dele sao lembrados por
    posicao. Cada trecho do arquivo e' varrido uma vez, por mais `stream` que haja.
    """

    def __init__(self, pdf: bytes):
        self.pdf = pdf
        self.ultimo_abre = -1             # ultimo `<<` antes de `varrido_ate`
        self.varrido_ate = 0
        self.abre_antes: dict[int, tuple[int, int]] = {}   # `<<` -> (anterior, limite olhado)
        self.fecha_apos: dict[int, tuple[int, int]] = {}   # `<<` -> (1o `>>` depois, ate' onde)

    def do_stream(self, palavra: int) -> tuple[int, int] | None:
        """(inicio, fim) do dicionario que antecede o `stream` -- ou None se nao der."""
        pdf = self.pdf
        fim = pdf.rfind(b">>", max(0, palavra - _FOLGA_ANTES_STREAM), palavra)
        if fim == -1:
            return None
        if fim > self.varrido_ate:        # `-1`: um `<<` pode estar partido na fronteira
            achado = pdf.rfind(b"<<", max(0, self.varrido_ate - 1), fim)
            if achado != -1:
                self.ultimo_abre = achado
            self.varrido_ate = fim
        limite = max(0, palavra - _JANELA_OBJETO)
        alvo, ini = fim, self.ultimo_abre
        for _ in range(_MAX_ANINHAMENTO):
            if ini < limite:              # inclusive `-1`: nenhum `<<` na janela
                return None
            # Trecho curto se olha direto em C; o memo e' para o trecho longo, que e' o
            # que um arquivo hostil faz repetir (`<<>>` a cada byte custava 2,3 s so' de
            # dicionario, medido).
            if alvo - ini <= _TRECHO_CURTO:
                fechado = pdf.find(b">>", ini + 2, alvo) != -1
            else:
                fechado = self._fecha_entre(ini, alvo)
            if not fechado:
                return ini, fim           # nada fecha no meio: e' o par do objeto
            alvo = ini                    # aquele `<<` era de um dicionario aninhado
            ini = pdf.rfind(b"<<", max(limite, alvo - _TRECHO_CURTO), alvo)
            if ini == -1:
                ini = self._abre_antes(alvo, limite)
        return None

    def _fecha_entre(self, ini: int, alvo: int) -> bool:
        """Ha `>>` em [ini+2, alvo)? Lembra o primeiro `>>` depois de `ini`."""
        pos, ate = self.fecha_apos.get(ini, (-1, ini + 2))
        if pos == -1 and ate < alvo:
            pos = self.pdf.find(b">>", max(ini + 2, ate - 1), alvo)
            if len(self.fecha_apos) >= _MEMO_MAX:
                self.fecha_apos.clear()
            self.fecha_apos[ini] = (pos, alvo)
        return pos != -1 and pos < alvo

    def _abre_antes(self, alvo: int, limite: int) -> int:
        """Ultimo `<<` em [limite, alvo) -- ou -1. Lembra o resultado por `alvo`."""
        pos, olhado = self.abre_antes.get(alvo, (-1, alvo))
        if pos == -1 and olhado > limite:
            pos = self.pdf.rfind(b"<<", limite, alvo)
            if len(self.abre_antes) >= _MEMO_MAX:
                self.abre_antes.clear()
            self.abre_antes[alvo] = (pos, limite)
        return pos if pos >= limite else -1


def _fim_declarado(pdf: bytes, ini_dic: int, fim_dic: int, inicio: int) -> int | None:
    """Fim do stream segundo o `/Length` do dicionario -- ou None quando ele nao serve.

    Por que o marcador `endstream` sozinho nao basta: quem monta a bomba controla os
    BYTES COMPRIMIDOS, e um bloco 'stored' do deflate escreve o que se quiser,
    literalmente -- inclusive a palavra `endstream`, logo no comeco. O primeiro marcador
    cairia no meio do stream, a pre-checagem inflaria so' o pedaco de antes (que cabe no
    teto) e o pypdf, que le `/Length` bytes, inflaria a bomba inteira. Quando o
    `/Length` e' direto e PLAUSIVEL -- cabe no arquivo e tem `endstream` logo depois --
    ele delimita o mesmo trecho que o pypdf vai ler, que e' o que interessa medir.
    """
    pos = pdf.rfind(b"/Length", ini_dic, fim_dic)      # o do proprio objeto
    if pos == -1:
        return None
    m = _LENGTH.match(pdf, pos)
    if m is None:
        return None
    n = int(m.group(1))
    if not 0 < n <= len(pdf) - inicio:
        return None
    fim = inicio + n
    if not pdf[fim:fim + _FOLGA_ENDSTREAM].lstrip(b"\r\n \t").startswith(b"endstream"):
        return None
    return fim


def _antes_do_flate(dicionario: bytes, dados: bytes) -> bytes | None:
    """Desfaz os filtros que vem ANTES do Flate na cadeia. None = nao e' stream Flate.

    `/Filter [/ASCII85Decode /FlateDecode]` e' PDF valido e comum: os bytes crus nao sao
    zlib, o `decompressobj` recusava, o stream ficava sem medir -- e o pypdf desfazia os
    dois filtros e inflava a bomba. Os dois pre-filtros do padrao que a biblioteca
    padrao desfaz (hex e base85) sao aplicados aqui; qualquer outro na frente do Flate
    levanta `_FiltroDesconhecido`, e o chamador deixa o stream sem medir.
    """
    m = _FILTRO.search(dicionario)
    if m is None:
        return None            # dicionario sem /Filter: o `/FlateDecode` era outra coisa
    nomes = _NOME.findall(m.group(1))
    if not any(n in _FLATE for n in nomes):
        return None
    for nome in nomes:
        if nome in _FLATE:
            return dados
        desfazer = _PRE_FILTROS.get(nome)
        if desfazer is None:
            raise _FiltroDesconhecido(nome)
        try:
            dados = desfazer(dados)
        except Exception as e:            # entrada torta no pre-filtro: idem
            raise _FiltroDesconhecido(nome) from e
    return dados


def _razao(inflado: int, consumido: int) -> float:
    """Quantas vezes o trecho cresceu. Sem entrada consumida, o crescimento e' infinito."""
    return inflado / consumido if consumido > 0 else float("inf")


def _sem_eol(dados: bytes) -> bytes:
    """Tira a quebra de linha que separa os dados do `endstream`."""
    if dados.endswith(b"\r\n"):
        return dados[:-2]
    if dados[-1:] in (b"\n", b"\r"):
        return dados[:-1]
    return dados


def conferir_streams(pdf: bytes, teto_stream: int | None = None, teto_total: int | None = None) -> None:
    """Recusa a BOMBA DE DESCOMPRESSAO antes de o pypdf encostar no arquivo.

    A checagem e' sobre os BYTES CRUS, e nao sobre o PDF ja aberto, porque o pypdf
    infla o stream INTEIRO dentro de `extract_text()`, sem `max_length`: o teto de
    caracteres deste modulo so' vale DEPOIS de a memoria ja ter sido alocada e a CPU
    ja ter sido gasta. Um PDF de UMA pagina com poucos KB em disco cujo content stream
    infla para centenas de MB passava por todas as guardas anteriores -- 10 MB de
    arquivo, 20 paginas, 60 mil caracteres -- e travava o worker antes de qualquer uma
    delas ser consultada.

    O criterio NAO e' "inflou demais", e' ASSINATURA DE BOMBA: passar do teto por stream
    so' condena quando o trecho cresceu mais de `RAZAO_BOMBA` vezes. Certidao
    digitalizada em 300 dpi tem imagem Flate de 8 a 9 MB com razao de 3 ou 4 para 1 --
    documento legitimo, que o teto sozinho recusava. Bomba de verdade passa de 1000:1.

    O `decompressobj` para no teto (`max_length`), entao o custo e' proporcional ao
    TETO, nao ao que o arquivo promete inflar.

    Objeto identificado pelo DICIONARIO delimitado (`_dicionario_do_stream`), dados
    delimitados pelo `/Length` quando ele serve (`_fim_declarado`) e cadeia de filtros
    desfeita ate' o Flate (`_antes_do_flate`).

    Esta funcao e' um ATALHO, nao a ultima linha de defesa. Tres rounds de revisao
    mostraram que um leitor heuristico de bytes crus nao fica estanque: cada furo
    fechado (enchimento do dicionario, cadeia de filtros, `endstream` falso) abria outro
    (`>>` dentro de string, aninhamento duplo, `/Filter` falso, `/Encrypt` forjado por
    comentario). A garantia de verdade e' `com_limite`: a leitura roda num subprocesso
    com tempo de parede e e' morta ao estourar. Por isso tudo que NAO da' para medir aqui
    -- filtro que nao sabemos desfazer, bytes que o zlib nao abre, dicionario que nao
    fecha na janela, PDF cifrado -- e' IGNORADO em silencio, e a unica recusa e' a bomba
    evidente (razao acima de `RAZAO_BOMBA`), que assim nao chega a ser inflada pelo pypdf.

    RODA SO' NO FILHO, por `leitor_de_pdf` (M2/M3 da revisao final). Ela e' heuristica
    sobre bytes crus, e um arquivo hostil pode faze-la varrer o proprio arquivo por
    segundos: no pai isso era CPU da thread do uvicorn, gasta antes de qualquer limite
    de tempo e sem processo para matar. Dentro do subprocesso, esse custo entra no
    mesmo orcamento de parede de todo o resto.
    """
    teto_stream = TETO_STREAM_BYTES if teto_stream is None else teto_stream   # lido na chamada: o teste o troca
    teto_total = TETO_STREAMS_TOTAL if teto_total is None else teto_total
    flate = _ocorrencias(pdf, b"/FlateDecode")
    if not flate:
        return
    total_inflado = total_consumido = 0
    dicionarios = _Dicionarios(pdf)
    abertura: int | None = None          # offset do `stream` ainda sem `endstream`
    dados_em: int = 0                    # onde comecam os bytes comprimidos dele
    ignorar_ate = 0                      # fim do stream ja examinado (ver `/Length`)
    for m in _MARCADOR_STREAM.finditer(pdf):
        if m.start() < ignorar_ate:
            # Marcador DENTRO de um stream ja delimitado: e' byte de dado que por acaso
            # soletra `stream`, nao um objeto novo.
            continue
        if m.group() != b"endstream":
            # O PRIMEIRO `stream` pendente e' o que vale: um "stream\n" que apareca
            # dentro dos bytes comprimidos nao pode encurtar o trecho examinado.
            if abertura is None:
                abertura, dados_em = m.start(), m.end()
            continue
        if abertura is None:
            continue
        palavra, inicio, fim, abertura = abertura, dados_em, m.start(), None
        if fim - inicio < 8:             # nem cabecalho de zlib cabe: nao ha o que medir
            continue
        dicionario = dicionarios.do_stream(palavra)
        if dicionario is None:
            continue
        ini_dic, fim_dic = dicionario
        # O `/FlateDecode` tem que estar DENTRO deste dicionario -- containment, nao
        # proximidade. A busca e' por bisseccao sobre os offsets ja levantados.
        k = bisect.bisect_left(flate, fim_dic)
        if not (k and flate[k - 1] >= ini_dic):
            continue
        declarado = _fim_declarado(pdf, ini_dic, fim_dic, inicio)
        if declarado is not None:
            fim = declarado
        ignorar_ate = fim
        try:
            comprimido = _antes_do_flate(pdf[ini_dic:fim_dic + 2],
                                         _sem_eol(pdf[inicio:fim]))
        except _FiltroDesconhecido:
            continue                      # nao da' para medir: fica com o subprocesso
        if comprimido is None:
            continue
        descompressor = zlib.decompressobj()
        try:
            inflado = descompressor.decompress(comprimido, teto_stream)
        except zlib.error:
            continue                      # idem (cifrado, corrompido, nao e' zlib)
        consumido = (len(comprimido) - len(descompressor.unconsumed_tail)
                     - len(descompressor.unused_data))
        total_inflado += len(inflado)
        total_consumido += max(consumido, 0)
        if len(inflado) >= teto_stream and \
                _razao(len(inflado), consumido) > RAZAO_BOMBA:
            raise TextoInadequado(_COMPRIMIDO_DEMAIS)
        if total_inflado > teto_total and \
                _razao(total_inflado, total_consumido) > RAZAO_BOMBA:
            raise TextoInadequado(_COMPRIMIDO_DEMAIS)


def leitor_de_pdf(pdf: bytes, pacote: bool = False) -> pypdf.PdfReader:
    """Abre os bytes num leitor de PDF -- ou levanta o que o pypdf levantar.

    Fonte UNICA de "como este projeto abre um PDF": esta leitura e o upload manual
    passam os dois por aqui. Duas implementacoes divergiriam em silencio no dia em que
    uma trocasse de biblioteca -- e a divergencia apareceria como "uma tela aceitou um
    arquivo que a outra nao le".

    A pre-checagem de streams vem ANTES do construtor de proposito: e' o que faz a
    guarda valer para as DUAS portas de PDF do sistema (a leitura de certidao e o
    upload que arquiva), sem cada uma lembrar de chama-la. E e' AQUI o unico lugar em
    que ela roda -- ou seja, sempre dentro do subprocesso de `com_limite`.
    """
    _guarda_de_streams(pdf, pacote)
    return pypdf.PdfReader(io.BytesIO(pdf))


def _guarda_de_streams(pdf: bytes, pacote: bool) -> None:
    """Os tetos da pre-checagem num lugar so' (o leitor de texto e o OCR usam os mesmos)."""
    if pacote:     # bloco 5: pacote de protocolo (paginas escaneadas em branco comprimem > 50:1)
        conferir_streams(pdf, TETO_STREAM_PACOTE, TETO_STREAMS_PACOTE)
    else:
        conferir_streams(pdf)


def texto_de_pdf(pdf: bytes) -> str:
    """Texto das paginas. PDF de imagem pura devolve string vazia (o OCR e' `texto_por_ocr`).

    Os dois tetos sao aplicados ANTES de parsear, nao depois: um PDF de 10 MB (o teto
    do upload) cabe centenas de MB de stream FlateDecode, e extrair tudo para so entao
    medir o tamanho custava minutos de CPU numa rota sincrona. Contar paginas e' leitura
    do dicionario de paginas (barato); a partir dai a extracao e' pagina a pagina, e para
    assim que o acumulado passa do teto de caracteres. Certidao tem 1-3 paginas: um PDF
    com mais que `TETO_PAGINAS` ou nao e' certidao ou e' um arquivo errado.
    """
    paginas = leitor_de_pdf(pdf).pages
    if len(paginas) > TETO_PAGINAS:
        raise TextoInadequado(f"O PDF tem {len(paginas)} páginas — uma certidão tem "
                              f"poucas; confira o arquivo e {MANUAL}.")
    partes: list[str] = []
    total = 0
    for i, p in enumerate(paginas):
        parte = p.extract_text() or ""
        partes.append(parte)
        total += len(parte) + (1 if i else 0)    # o "\n" do join entre as paginas
        if total > TETO_CARACTERES:
            raise TextoInadequado(_TEXTO_DEMAIS.format(n=total))
    return "\n".join(partes)


# --- OCR local ------------------------------------------------------------------------

def configuracao_ocr() -> tuple[str, str] | None:
    """(executavel do Tesseract, pasta com `por.traineddata`) ou None se o OCR nao esta instalado.

    Pasta do idioma: `DASH_TESSDATA`, senao `tessdata` ao lado do banco (a producao guarda la', fora
    de Arquivos de Programas), senao a do proprio Tesseract. Sem portugues nao ha OCR: o ingles le
    "CERTIDAO" mas erra acento e cedilha, e as regexes dos leitores sao em portugues.
    """
    exe = os.environ.get("DASH_TESSERACT") or shutil.which("tesseract") or _TESSERACT_PADRAO
    if not Path(exe).is_file():
        return None
    pastas = [os.environ.get("DASH_TESSDATA"), Path(exe).parent / "tessdata"]
    caminho_banco = os.environ.get("DASH_DB_PATH")
    if caminho_banco:
        pastas.insert(1, Path(caminho_banco).parent / "tessdata")
    for p in pastas:
        if p and (Path(p) / "por.traineddata").is_file():
            return exe, str(p)
    return None


def _pgm(bitmap) -> bytes:
    """Bitmap cinza do pdfium -> PGM binario, que o Tesseract le pela entrada padrao (sem Pillow)."""
    w, h, passo = bitmap.width, bitmap.height, bitmap.stride
    bruto = bytes(bitmap.buffer)
    linhas = bruto if passo == w else b"".join(bruto[i * passo:i * passo + w] for i in range(h))
    return b"P5\n%d %d\n255\n" % (w, h) + linhas


def texto_por_ocr(pdf: bytes, exe: str, tessdata: str) -> str:
    """Texto das primeiras `OCR_PAGINAS` paginas pelo Tesseract. Roda no filho de `com_limite`."""
    return "\n".join(paginas_por_ocr(pdf, exe, tessdata))


def paginas_por_ocr(pdf: bytes, exe: str, tessdata: str, pacote: bool = False) -> list[str]:
    """Texto de cada uma das primeiras `OCR_PAGINAS` paginas pelo Tesseract. Roda no filho de `com_limite`.

    `pacote=True` (capa do SMO, #285): o PDF pode ser o envelope inteiro do DocuSign (centenas de paginas, capa na
    p. 2); vale a guarda de streams do pacote e nao o teto de paginas da certidao. Le' so' as primeiras de todo modo.
    """
    import pypdfium2 as pdfium    # so' o filho do OCR carrega o pdfium

    _guarda_de_streams(pdf, pacote)    # a mesma guarda de bomba da leitura de texto
    doc = pdfium.PdfDocument(pdf)
    try:
        if not pacote and len(doc) > TETO_PAGINAS:
            raise TextoInadequado(f"O PDF tem {len(doc)} páginas — uma certidão tem "
                                  f"poucas; confira o arquivo e {MANUAL}.")
        partes = []
        for i in range(min(OCR_PAGINAS, len(doc))):
            pagina = doc[i]
            maior_lado_pt = max(pagina.get_size()) or 1
            escala = min(OCR_DPI / 72, OCR_MAX_PIXELS_LADO / maior_lado_pt)
            imagem = _pgm(pagina.render(scale=escala, grayscale=True))
            r = subprocess.run([exe, "stdin", "stdout", "-l", "por", "--dpi", str(OCR_DPI),
                                "--tessdata-dir", tessdata], input=imagem, capture_output=True,
                               timeout=OCR_TEMPO_LIMITE_S, creationflags=_SEM_JANELA)
            if r.returncode != 0:
                raise ValueError(f"Tesseract terminou com código {r.returncode}")
            partes.append(r.stdout.decode("utf-8", "replace"))
    finally:
        doc.close()
    n = len("\n".join(partes))
    if n > TETO_CARACTERES:
        raise TextoInadequado(_TEXTO_DEMAIS.format(n=n))
    return partes


def primeiras_paginas(pdf: bytes) -> list[str]:
    """Texto das primeiras `OCR_PAGINAS` paginas, sem teto de paginas (capa do SMO, #285: o pacote do DocuSign tem
    centenas). Guarda de streams do pacote. Roda no filho de `com_limite`."""
    return [_texto_da_pagina(p) for p in leitor_de_pdf(pdf, pacote=True).pages[:OCR_PAGINAS]]


def _texto_da_pagina(p) -> str:
    # Planilha impressa sai com milhares de espacos; e o carimbo do DocuSign costuma vir no FIM do
    # texto da pagina. Espaco repetido vira um so', e pagina longa guarda o comeco e o fim.
    t = re.sub(r"[ \t]{2,}", " ", p.extract_text() or "")
    if len(t) > TETO_CARACTERES_PAGINA:
        metade = TETO_CARACTERES_PAGINA // 2
        t = t[:metade] + "\n" + t[-metade:]
    return t


def textos_por_pagina(pdf: bytes, teto_paginas: int) -> list[str]:
    """Texto de cada pagina (pagina so' de imagem vem vazia). Roda no filho de `com_limite`."""
    paginas = leitor_de_pdf(pdf, pacote=True).pages
    if len(paginas) > teto_paginas:
        raise TextoInadequado(f"O PDF tem {len(paginas)} páginas, acima do limite de {teto_paginas} "
                              f"— confira o arquivo.")
    return [_texto_da_pagina(p) for p in paginas]


# --- leitura em subprocesso com limite de tempo ---------------------------------------

def _trabalho(pdf: bytes, modo: str, envia, opcoes=None) -> None:
    """Corpo do subprocesso: le o PDF e manda UMA resposta pelo `envia`.

    Funcao de modulo, e nao lambda/closure, porque o filho e' criado por `spawn` e
    importa esta funcao pelo nome. Resposta: `("ok", valor)` ou
    `("erro", nome_da_classe, mensagem)`. Captura `BaseException` para o filho nunca
    ficar pendurado sem responder -- ate' um `MemoryError` vira mensagem.

    `modo == "dormir"` e' GANCHO DE TESTE: dorme mais que qualquer limite, para o teste
    do estouro nao depender de um PDF que demore de verdade.
    """
    try:
        if modo == "texto":
            valor = texto_de_pdf(pdf)
        elif modo == "paginas":
            valor = len(leitor_de_pdf(pdf).pages)
        elif modo == "ocr":
            valor = texto_por_ocr(pdf, *opcoes)
        elif modo == "ocr_pacote":       # capa do SMO (#285): envelope inteiro, OCR so' das primeiras paginas
            valor = paginas_por_ocr(pdf, *opcoes, pacote=True)
        elif modo == "primeiras_paginas":
            valor = primeiras_paginas(pdf)
        elif modo == "paginas_texto":
            valor = textos_por_pagina(pdf, opcoes)
        elif modo == "primeira_pagina":    # regularidade do DP (32 a 160 p.): so' o cabecalho da 1a pagina
            valor = leitor_de_pdf(pdf, pacote=True).pages[0].extract_text() or ""
        elif modo == "juntar":           # bloco 5: montagem do pacote; `opcoes` = as partes, em ordem
            valor = _juntar(opcoes)
        elif modo == "dormir":
            time.sleep(60)
            valor = None
        elif modo == "morrer":           # GANCHO DE TESTE: morte sem resposta (OOM-killer, crash nativo)
            os._exit(3)
        else:
            raise ValueError(f"modo desconhecido: {modo}")
        resposta = ("ok", valor)
    except BaseException as e:
        resposta = ("erro", type(e).__name__, str(e))
    try:
        envia.send(resposta)
    finally:
        envia.close()


def _matar(proc) -> None:
    """Derruba o filho: `terminate`, dois segundos de folga, `kill` se ainda vive."""
    proc.terminate()
    proc.join(2.0)
    if proc.is_alive():
        proc.kill()
        proc.join(2.0)


def com_limite(pdf: bytes, modo: str, limite: float | None = None, opcoes=None, ate: float | None = None):
    """Roda `_trabalho` num subprocesso e devolve o valor -- ou mata o filho no tempo.

    E' a garantia de que a leitura de PDF NAO derruba o servidor: o que o pypdf faz com
    um arquivo hostil (inflar, recursar, laco em xref) acontece noutro processo, com
    `TEMPO_LIMITE_S` de PAREDE, e ao estourar o filho e' morto e o chamador recebe
    `TextoInadequado` (422 na leitura, 415 no upload).

    A pre-checagem de bytes (`conferir_streams`) NAO roda aqui: ela ja roda dentro de
    `leitor_de_pdf`, ou seja, NO FILHO (M2/M3 da revisao final). Chamada tambem no pai,
    ela era um atalho que custava o que devia poupar -- ate' ~3 s de CPU da thread do
    uvicorn por upload adversarial, gastos ANTES de o orcamento de tempo comecar a
    contar, e num processo que nao da' para matar. Com ela so' no filho, o orcamento
    desta funcao e' o tempo de parede do filho e nada mais; a bomba continua sendo
    recusada pelo caminho completo, so' que dentro do processo descartavel.

    TETO DE CONCORRENCIA (ruling R30): `_VAGAS` limita a duas leituras simultaneas, e a
    espera por vaga usa o MESMO orcamento de tempo. Quem nao consegue vaga recebe
    `TextoInadequado` de fila (`_LOTADO`), que a rota ja mapeia para 422 -- no upload
    vira 415, aceito: o codigo diz "nao deu para ler agora" nos dois casos e a frase
    manda tentar de novo.

    Custo: `spawn` no Windows -- o unico modo que existe la', e o uvicorn roda la' --
    custa de 0,3 a 1 s por chamada (processo novo + importar este modulo e o pypdf).
    Aceitavel para um botao manual e para o upload de uma certidao por vez.

    A resposta viaja por `Pipe`, nao por `Queue`, e e' LIDA ANTES do `join`: a `Queue`
    escreve por uma thread que o filho so' encerra depois de despejar tudo no cano, e
    um texto maior que o buffer do cano travaria o filho esperando um pai que espera o
    `join` -- estouro falso num PDF legitimo. Com `poll(timeout)` o tempo de parede e'
    o mesmo e nao ha o que travar.

    Erros do filho: `TextoInadequado` e' re-levantado com a mesma frase; `MemoryError` e
    morte sem resposta viram `TextoInadequado` de falha interna; qualquer outro vira
    `ValueError("PDF inválido (<classe>): <mensagem>")`, que os chamadores ja convertem
    em 415/422.

    `ate` (capa do SMO, #285): prazo de ponta a ponta, em `time.monotonic()`. A espera pela vaga e o tempo do filho
    saem do que sobra ate' la', em vez de `TEMPO_LIMITE_S` de espera mais `limite` de filho.
    """
    limite = TEMPO_LIMITE_S if limite is None else limite    # lido na chamada: o teste o troca
    espera = TEMPO_LIMITE_S if ate is None else max(0.0, ate - time.monotonic())
    if not _VAGAS.acquire(timeout=espera):
        raise TextoInadequado(_LOTADO)
    if ate is not None:
        limite = max(0.0, ate - time.monotonic())
    try:
        ctx = multiprocessing.get_context("spawn")
        recebe, envia = ctx.Pipe(duplex=False)
        try:
            proc = ctx.Process(target=_trabalho, args=(pdf, modo, envia, opcoes), daemon=True)
            proc.start()
        except BaseException:
            # `spawn` falhando (sem memoria, sem handle) deixava as DUAS pontas do cano
            # abertas ate' o coletor passar -- vazamento de handle por tentativa, no
            # exato momento em que o sistema ja esta sem eles.
            recebe.close()
            envia.close()
            raise
        envia.close()      # so' o filho escreve: e' o que faz o `recv` ver o fim do cano
        try:
            if not recebe.poll(limite):
                _matar(proc)
                raise TextoInadequado(_DEMOROU.format(s=int(limite)))
            try:
                resposta = recebe.recv()
            except EOFError:              # o filho morreu sem responder
                resposta = None
            proc.join(2.0)
            if proc.is_alive():
                _matar(proc)
        finally:
            recebe.close()
            if proc.exitcode is not None:
                proc.close()
    finally:
        _VAGAS.release()
    if resposta is None:
        raise TextoInadequado(_FALHOU)
    if resposta[0] == "ok":
        return resposta[1]
    _, nome, mensagem = resposta
    if nome == "TextoInadequado":
        raise TextoInadequado(mensagem)
    if nome == "MemoryError":
        raise TextoInadequado(_FALHOU)
    raise ValueError(f"PDF inválido ({nome}): {mensagem}")


# B-08 (10/10/2026): a frase da recusa ao usuario, sem o nome da excecao do leitor ("(ValueError)")
PDF_CORROMPIDO = "PDF inválido ou corrompido — envie o arquivo original emitido pelo órgão"


def texto_de_pdf_com_limite(pdf: bytes) -> str:
    """`texto_de_pdf` em subprocesso com limite de tempo (ver `com_limite`)."""
    return com_limite(pdf, "texto")


def primeira_pagina_com_limite(pdf: bytes) -> str:
    """Texto so' da primeira pagina, sem o teto de paginas da certidao (ver `com_limite`)."""
    return com_limite(pdf, "primeira_pagina")


def paginas_com_limite(pdf: bytes) -> int:
    """Numero de paginas, lido em subprocesso com limite de tempo (ver `com_limite`)."""
    return com_limite(pdf, "paginas")


def primeiras_paginas_com_limite(pdf: bytes) -> list[str]:
    """`primeiras_paginas` em subprocesso, com o prazo do pacote (ver `com_limite`)."""
    return com_limite(pdf, "primeiras_paginas", TEMPO_PACOTE_S)


def textos_por_pagina_com_limite(pdf: bytes, teto_paginas: int = 400) -> list[str]:
    """`textos_por_pagina` em subprocesso, com o prazo do pacote (ver `com_limite`)."""
    return com_limite(pdf, "paginas_texto", TEMPO_PACOTE_S, teto_paginas)


def _juntar(partes: list[bytes]) -> tuple[bytes, int]:
    """Junta as partes do pacote (cada uma passa pela guarda de streams do pacote) e conta as paginas."""
    w = pypdf.PdfWriter()
    for p in partes:
        w.append(leitor_de_pdf(p, pacote=True))
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue(), len(w.pages)


def juntar_com_limite(partes: list[bytes]) -> tuple[bytes, int]:
    """Pacote do protocolo montado no subprocesso, com o prazo do pacote (gate Sol do bloco 5: as pecas
    chegam de fora e so' passaram pelo `%PDF-` do upload)."""
    return com_limite(b"", "juntar", TEMPO_PACOTE_S, partes)


def texto_por_ocr_com_limite(pdf: bytes) -> str | None:
    """OCR em subprocesso, um por vez. None quando nao ha OCR instalado ou ele nao conseguiu
    (fila, prazo, Tesseract com erro): quem chama segue como PDF sem texto (campos digitados)."""
    return _ocr_com_limite(pdf, "ocr", OCR_TEMPO_LIMITE_S)


def paginas_por_ocr_com_limite(pdf: bytes) -> list[str] | None:
    """OCR das primeiras paginas de um pacote (capa do SMO, #285), uma lista por pagina; None como no
    `texto_por_ocr_com_limite`. O envelope inteiro passa pela guarda e pelo pdfium antes das 2 paginas: prazo do
    pacote, se maior que o do OCR."""
    return _ocr_com_limite(pdf, "ocr_pacote", max(OCR_TEMPO_LIMITE_S, TEMPO_PACOTE_S), ponta_a_ponta=True)


def _ocr_com_limite(pdf: bytes, modo: str, prazo: float, ponta_a_ponta: bool = False):
    """`ponta_a_ponta`: o `prazo` conta desde a entrada, com as esperas pela vaga do OCR e pela do PDF dentro dele.
    Sem ele (certidao, como sempre foi): ate' `TEMPO_LIMITE_S` em cada fila, mais `prazo` para o filho."""
    ate = time.monotonic() + prazo if ponta_a_ponta else None
    cfg = configuracao_ocr()
    espera = TEMPO_LIMITE_S if ate is None else min(TEMPO_LIMITE_S, max(0.0, ate - time.monotonic()))
    if cfg is None or not _VAGA_OCR.acquire(timeout=espera):
        return None
    try:
        if ate is not None:
            return com_limite(pdf, modo, None, cfg, ate=ate)
        return com_limite(pdf, modo, prazo, cfg)
    except (TextoInadequado, ValueError):
        return None
    finally:
        _VAGA_OCR.release()
