import hashlib
import json
import urllib.error
import urllib.request
import zlib

import pytest
from app import auth, correio, db, graph
from tests.conftest import _jpg, _png


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("DASH_GRAPH_TOKENS_DIR", str(tmp_path / "tokens"))
    monkeypatch.setenv("DASH_GRAPH_CLIENT_ID", "cliente-teste")
    c = db.get_conn(); db.migrate(c)
    auth.criar_usuario(c, "Maria", "maria@l.com", "senha-forte-123", "engenharia")
    yield c
    c.close()


def test_token_e_um_arquivo_por_usuario(conn, tmp_path):
    assert correio.arquivo_token(1) == tmp_path / "tokens" / "usuario-1.txt"
    assert correio.conectado(1) is False
    graph.gravar_token(correio.arquivo_token(1), "refresh-da-maria")
    assert correio.conectado(1) is True and correio.conectado(2) is False


def test_escopos_de_envio_nao_pedem_leitura_de_caixa_alheia():
    assert "Mail.Send" in correio.ESCOPOS and "Mail.ReadWrite" in correio.ESCOPOS
    assert "Mail.Read.Shared" not in correio.ESCOPOS and "Sites.Read.All" not in correio.ESCOPOS


def test_device_code_usa_os_escopos_pedidos(monkeypatch):
    visto = {}
    monkeypatch.setattr(graph, "_post_form", lambda url, campos, timeout=60: visto.update(campos) or {
        "device_code": "d", "user_code": "ABCD", "verification_uri": "https://microsoft.com/devicelogin"})
    graph.iniciar_device_code("organizations", "cliente", escopos=correio.ESCOPOS)
    assert visto["scope"] == correio.ESCOPOS


def test_registrar_envio_grava_anexos_com_hash_e_audita(conn):
    eid = correio.registrar_envio(conn, 1, "teste", "maria@l.com", ["fab@l.com"], ["leo@l.com"],
                                  "Emissão NF - 27ª Medição", "<id@outlook>", [("espelho.docx", b"abc")])
    e = conn.execute("SELECT * FROM envios WHERE id=?", (eid,)).fetchone()
    assert (e["tipo"], e["remetente"], json.loads(e["para"]), json.loads(e["copia"])) == (
        "teste", "maria@l.com", ["fab@l.com"], ["leo@l.com"])
    a = conn.execute("SELECT nome, tamanho, sha256 FROM envio_anexos WHERE envio_id=?", (eid,)).fetchone()
    assert (a["nome"], a["tamanho"], a["sha256"]) == ("espelho.docx", 3, hashlib.sha256(b"abc").hexdigest())
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='correio.envio'").fetchone()[0] == 1


class _Falso:
    """Fica no lugar de correio._http e grava as chamadas na ordem."""
    def __init__(self, falhar_em=None, status=None, ilegivel=False):
        self.chamadas, self.falhar_em, self.status, self.ilegivel = [], falhar_em, status, ilegivel

    def __call__(self, metodo, url, corpo=None, headers=None, bearer=None):
        self.chamadas.append((metodo, url.replace(graph.GRAPH, ""), len(corpo or b""), bool(bearer),
                              (headers or {}).get("Content-Range")))
        if self.falhar_em and self.falhar_em in url:
            if self.ilegivel:
                raise json.JSONDecodeError("resposta ilegivel", "<html>", 0)
            raise graph.ErroGraph("Graph falhou", status=self.status)
        if url.endswith("/me"):
            return {"mail": "maria@l.com"}
        if url.endswith("/me/messages"):
            return {"id": "RASCUNHO", "internetMessageId": "<abc@outlook>"}
        if url.endswith("/createUploadSession"):
            return {"uploadUrl": "https://outlook.office.com/upload/sessao"}
        return {}


@pytest.fixture
def rede(conn, monkeypatch):
    graph.gravar_token(correio.arquivo_token(1), "refresh")
    monkeypatch.setattr(graph.Token, "acesso", lambda self: "TOKEN")
    falso = _Falso()
    monkeypatch.setattr(correio, "_http", falso)
    return falso


def test_anexo_pequeno_vai_direto_e_grande_vai_por_sessao_em_blocos(conn, rede):
    grande = b"x" * (correio.BLOCO * 2 + 10)
    mid = correio.cliente(1).enviar(["fab@l.com"], ["leo@l.com"], "Assunto", "<p>oi</p>",
                                    [("pequeno.docx", b"abc"), ("pacote.pdf", grande)])
    assert mid == "<abc@outlook>"
    caminhos = [(m, u) for m, u, *_ in rede.chamadas]
    assert caminhos == [("POST", "/me/messages"), ("POST", "/me/messages/RASCUNHO/attachments"),
                        ("POST", "/me/messages/RASCUNHO/attachments/createUploadSession"),
                        ("PUT", "https://outlook.office.com/upload/sessao"),
                        ("PUT", "https://outlook.office.com/upload/sessao"),
                        ("PUT", "https://outlook.office.com/upload/sessao"),
                        ("POST", "/me/messages/RASCUNHO/send")]
    blocos = [c for c in rede.chamadas if c[0] == "PUT"]
    assert [b[4] for b in blocos] == [f"bytes 0-{correio.BLOCO - 1}/{len(grande)}",
                                      f"bytes {correio.BLOCO}-{correio.BLOCO * 2 - 1}/{len(grande)}",
                                      f"bytes {correio.BLOCO * 2}-{len(grande) - 1}/{len(grande)}"]
    assert all(b[3] is False for b in blocos)        # a URL de upload ja' e' autenticada: sem bearer


def test_redirect_nao_e_seguido_com_o_bearer(monkeypatch):
    class _Abridor:
        def open(self, req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 302, "Found", {"Location": "https://fora.example/"}, None)

    monkeypatch.setattr(graph, "_SEM_REDIRECT", _Abridor())
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("urlopen segue redirect"))
    with pytest.raises(graph.ErroGraph, match="302"):
        correio._http("GET", graph.GRAPH + "/me", bearer="TOKEN")


def test_pacote_acima_do_teto_e_recusado_antes_de_tocar_a_rede(conn, rede):
    with pytest.raises(graph.ErroGraph, match="MB"):
        correio.cliente(1).enviar(["a@l.com"], [], "A", "<p/>", [("g.pdf", b"x" * (correio.MAX_TOTAL + 1))])
    assert rede.chamadas == []


def _rede_falhando(conn, monkeypatch, **k):
    graph.gravar_token(correio.arquivo_token(1), "refresh")
    monkeypatch.setattr(graph.Token, "acesso", lambda self: "TOKEN")
    falso = _Falso(**k)
    monkeypatch.setattr(correio, "_http", falso)
    return falso


def _apagou(falso):
    return ("DELETE", "/me/messages/RASCUNHO") in [(m, u) for m, u, *_ in falso.chamadas]


def test_send_recusado_com_4xx_apaga_o_rascunho_e_nao_registra(conn, monkeypatch):
    """Recusa inequivoca do /send (413, 400, 403): nada saiu, o rascunho sai da caixa e a reserva pode ser solta."""
    falso = _rede_falhando(conn, monkeypatch, falhar_em="/send", status=413)
    with pytest.raises(graph.ErroGraph) as erro:
        correio.enviar_e_registrar(conn, {"id": 1}, "teste", ["a@l.com"], [], "A", "<p/>", [])
    assert not isinstance(erro.value, correio.EnvioIncerto) and _apagou(falso)
    assert conn.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0


@pytest.mark.parametrize("k", [{"status": None}, {"status": 503}, {"ilegivel": True}],
                         ids=["sem-resposta", "5xx", "resposta-ilegivel"])
def test_send_sem_resposta_clara_e_envio_incerto_e_nao_apaga_nada(conn, monkeypatch, k):
    """Gate Sol S2 (10/10/2026): o /send pode ter sido aceito e a resposta se perdido. Apagar o 'rascunho' ou
    soltar a reserva abriria o segundo e-mail."""
    falso = _rede_falhando(conn, monkeypatch, falhar_em="/send", **k)
    with pytest.raises(correio.EnvioIncerto) as erro:
        correio.enviar_e_registrar(conn, {"id": 1}, "teste", ["a@l.com"], [], "Assunto S2", "<p/>", [])
    assert erro.value.assunto == "Assunto S2" and erro.value.mensagem_id is None
    assert not _apagou(falso)
    assert conn.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0


def test_falha_antes_do_send_continua_erro_do_graph_e_apaga_o_rascunho(conn, monkeypatch):
    falso = _rede_falhando(conn, monkeypatch, falhar_em="/attachments", status=None)
    with pytest.raises(graph.ErroGraph):
        correio.enviar_e_registrar(conn, {"id": 1}, "teste", ["a@l.com"], [], "A", "<p/>", [("a.txt", b"oi")])
    assert _apagou(falso) and ("POST", "/me/messages/RASCUNHO/send") not in [(m, u) for m, u, *_ in falso.chamadas]


def test_erro_do_graph_carrega_o_status_http(monkeypatch):
    class _Abridor:
        def __init__(self, erro):
            self.erro = erro

        def open(self, req, timeout=None):
            raise self.erro

    monkeypatch.setattr(graph, "_SEM_REDIRECT", _Abridor(urllib.error.HTTPError(graph.GRAPH, 413, "Too Large", {}, None)))
    with pytest.raises(graph.ErroGraph) as erro:
        correio._http("POST", graph.GRAPH + "/me/messages/X/send", bearer="TOKEN")
    assert erro.value.status == 413
    monkeypatch.setattr(graph, "_SEM_REDIRECT", _Abridor(TimeoutError()))
    with pytest.raises(graph.ErroGraph) as erro:
        correio._http("POST", graph.GRAPH + "/me/messages/X/send", bearer="TOKEN")
    assert erro.value.status is None


def test_enviar_e_registrar_grava_remetente_e_mensagem(conn, rede):
    eid = correio.enviar_e_registrar(conn, {"id": 1}, "teste", ["a@l.com"], [], "Assunto", "<p/>",
                                     [("a.txt", b"oi")])
    e = conn.execute("SELECT remetente, mensagem_id FROM envios WHERE id=?", (eid,)).fetchone()
    assert (e["remetente"], e["mensagem_id"]) == ("maria@l.com", "<abc@outlook>")


def test_simulador_grava_em_pasta_e_nao_usa_rede(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    monkeypatch.setattr(correio, "_http", lambda *a, **k: pytest.fail("rede usada no simulador"))
    correio.enviar_e_registrar(conn, {"id": 1, "email": "maria@l.com"}, "teste", ["a@l.com"], [], "Assunto",
                               "<p/>", [("a.txt", b"oi")])
    gravado = json.loads(sorted((tmp_path / "sim" / "enviados").glob("*.json"))[0].read_text("utf-8"))
    assert gravado["assunto"] == "Assunto" and gravado["anexos"][0]["nome"] == "a.txt"


PNG = _png()
JPG = _jpg()
# Segmento entre varreduras (tabela de Huffman) cujo conteudo tem os bytes FF D9, que nao sao o fim da imagem
DHT_COM_FFD9 = b"\xff\xc4\x00\x06\x00\xff\xd9\x00"
JPG_PROGRESSIVO = _jpg(entre_varreduras=DHT_COM_FFD9)


def test_cco_e_assinatura_vao_no_email_e_no_registro(conn, tmp_path, monkeypatch):
    """Envio como no Outlook: copia oculta e a imagem da assinatura de quem envia no fim do corpo."""
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    correio.gravar_assinatura(conn, 1, PNG)
    eid = correio.enviar_e_registrar(conn, {"id": 1, "email": "maria@l.com"}, "teste", ["a@l.com"], [], "Assunto",
                                     "<p>Bom dia.</p>", [("a.txt", b"oi")], cco=["oculto@l.com"])
    gravado = json.loads(sorted((tmp_path / "sim" / "enviados").glob("*.json"))[0].read_text("utf-8"))
    assert gravado["cco"] == ["oculto@l.com"]
    assert f'cid:{correio.ASSINATURA_CID}' in gravado["corpo"] and gravado["inline"][0]["cid"] == correio.ASSINATURA_CID
    assert json.loads(conn.execute("SELECT cco FROM envios WHERE id=?", (eid,)).fetchone()[0]) == ["oculto@l.com"]
    with pytest.raises(ValueError):
        correio.gravar_assinatura(conn, 1, b"GIF89a nao e' png")


@pytest.mark.parametrize("imagem", [
    PNG,
    _png(300, 40),
    _png(30, 10, cor=6),                              # RGBA
    _png(30, 10, cor=3, prof=4),                      # paleta de 4 bits, com PLTE
    _png(30, 10, prof=16),                            # cinza de 16 bits
    JPG,
    _jpg(antes_do_quadro=b"\xff\x01\xff\xff\xd8"),    # marcadores sem tamanho (TEM, SOI) e preenchimento
    JPG_PROGRESSIVO,                                  # duas varreduras com segmento no meio
], ids=["png", "png-maior", "png-rgba", "png-paleta", "png-16bits", "jpg", "jpg-marcador-sem-tamanho",
        "jpg-progressivo"])
def test_assinatura_integra_continua_aceita(conn, imagem):
    correio.gravar_assinatura(conn, 1, imagem)
    assert correio.assinatura(1)[0] == imagem


def test_troca_de_assinatura_que_falha_no_meio_deixa_a_anterior_inteira(conn, monkeypatch):
    """Gate Sol na PR #472 (#441): o backup le `assinaturas/` sem trava e o nome nao e' o sha256. A gravacao vai a um
    temporario e so' entao troca de nome: nunca existe assinatura pela metade, nem sobra temporario."""
    antiga, nova = _png(2, 2), _png(3, 3)
    correio.gravar_assinatura(conn, 1, antiga)

    def falha(*_a):
        raise OSError("disco cheio")

    monkeypatch.setattr(correio.os, "replace", falha)
    with pytest.raises(OSError):
        correio.gravar_assinatura(conn, 1, nova)
    assert correio.assinatura(1)[0] == antiga
    assert [a.name for a in correio._arquivo_assinatura(1).parent.iterdir()] == ["usuario-1"]


def test_assinatura_ocupada_pelo_backup_tenta_de_novo_e_depois_recusa_em_portugues(conn, monkeypatch):
    """Gate Sol na PR #472 (#441): no Windows, `os.replace` sobre a assinatura aberta pelo backup da' PermissionError.
    Um bloqueio curto passa na tentativa seguinte; o que persiste vira ValueError (422 na rota), nao 500."""
    antiga, nova, outra = _png(2, 2), _png(3, 3), _png(4, 4)
    correio.gravar_assinatura(conn, 1, antiga)
    real, chamadas = correio.os.replace, []
    monkeypatch.setattr(correio.time, "sleep", lambda s: None)

    def ocupado_uma_vez(a, b):
        chamadas.append(a)
        if len(chamadas) == 1:
            raise PermissionError("arquivo aberto por outro processo")
        real(a, b)

    monkeypatch.setattr(correio.os, "replace", ocupado_uma_vez)
    correio.gravar_assinatura(conn, 1, nova)
    assert correio.assinatura(1)[0] == nova and len(chamadas) == 2

    def sempre_ocupado(a, b):
        raise PermissionError("arquivo aberto por outro processo")

    monkeypatch.setattr(correio.os, "replace", sempre_ocupado)
    with pytest.raises(ValueError, match=correio.GRAVAR_ASSINATURA_OCUPADA):
        correio.gravar_assinatura(conn, 1, outra)
    assert correio.assinatura(1)[0] == nova
    assert [a.name for a in correio._arquivo_assinatura(1).parent.iterdir()] == ["usuario-1"]


def test_gravar_assinatura_limpa_temporario_velho_de_gravacao_interrompida(conn):
    """Gate Sol na PR #472 (#441): queda entre escrever e renomear deixa o `.tmp`; a gravacao seguinte tira o que
    passou de 1 hora e segue o padrao exato do temporario. O recente (outra gravacao em curso) e o alheio ficam."""
    import os
    import time
    pasta = correio._arquivo_assinatura(1).parent
    velho, recente, alheio = (pasta / "usuario-1.123-abcdef01.tmp", pasta / "usuario-2.456-0123abcd.tmp",
                              pasta / "usuario-1.tmp")
    for a in (velho, recente, alheio):
        a.write_bytes(b"parcial")
    os.utime(velho, (time.time() - 7200, time.time() - 7200))
    os.utime(alheio, (time.time() - 7200, time.time() - 7200))
    correio.gravar_assinatura(conn, 1, _png(2, 2))
    assert not velho.exists() and recente.exists() and alheio.exists()


@pytest.mark.parametrize("imagem", [
    PNG[: len(PNG) // 2],                             # PNG cortado ao meio
    PNG[:-12],                                        # PNG sem o IEND
    PNG[:40] + bytes([PNG[40] ^ 0xFF]) + PNG[41:],    # byte trocado: CRC nao bate
    _png(300, 40, idat_pela_metade=True),             # blocos certos, imagem comprimida pela metade
    _png(sobra=b"lixo"),                              # sobra depois do fim da imagem comprimida
    _png(30, 10, cor=3, plte=False),                  # paleta sem o bloco PLTE
    _png(cor=3, prof=16),                             # profundidade que nao existe para paleta
    JPG[: len(JPG) // 2],                             # JPG cortado ao meio
    JPG[:-2],                                         # JPG sem o EOI
    _png(depois_do_iend=b"lixo"),                     # bytes depois do IEND
    _png(iend=b"x"),                                  # IEND com conteudo
    JPG_PROGRESSIVO[: JPG_PROGRESSIVO.index(DHT_COM_FFD9) + len(DHT_COM_FFD9)],   # cortado entre varreduras
    _jpg(sof=b"\xff\xc0\x00\x02"),                    # SOF sem conteudo
    _jpg(sof=b"\xff\xc0" + bytes([0, 11, 8, 0, 1, 0, 0, 1, 1, 0x11, 0])),         # SOF com largura zero
], ids=["png-metade", "png-sem-iend", "png-crc", "png-idat-curto", "png-sobra", "png-paleta-sem-plte",
        "png-profundidade", "jpg-metade", "jpg-sem-eoi", "png-depois-do-iend", "png-iend-com-conteudo",
        "jpg-ffd9-dentro-de-segmento", "jpg-sof-vazio", "jpg-largura-zero"])
def test_assinatura_truncada_ou_corrompida_e_recusada(conn, imagem):
    with pytest.raises(ValueError, match="incompleta ou corrompida"):
        correio.gravar_assinatura(conn, 1, imagem)
    assert correio.assinatura(1) is None


def test_png_que_promete_imagem_enorme_e_recusado_sem_descomprimir(conn):
    """Arquivo pequeno que declara 5000 x 5000 RGBA (~100 MB descomprimidos): recusado pelo tamanho prometido."""
    with pytest.raises(ValueError, match="grande demais: reduza as dimensões"):
        correio.gravar_assinatura(conn, 1, _png(5000, 5000, cor=6, idat=zlib.compress(b"\x00" * 1000)))
    assert correio.assinatura(1) is None
