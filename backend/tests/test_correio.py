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
    real, chamadas, dormidas = correio.os.replace, [], []
    monkeypatch.setattr(correio.time, "sleep", _dormir_sem_trava(conn, dormidas))

    def ocupado_uma_vez(a, b):
        chamadas.append(a)
        if len(chamadas) == 1:
            raise PermissionError("arquivo aberto por outro processo")
        real(a, b)

    monkeypatch.setattr(correio.os, "replace", ocupado_uma_vez)
    correio.gravar_assinatura(conn, 1, nova)
    assert correio.assinatura(1)[0] == nova and len(chamadas) == 2 and len(dormidas) == 1
    assert _eventos_assinatura(conn) == 2           # a tentativa desfeita nao deixa evento

    def sempre_ocupado(a, b):
        raise PermissionError("arquivo aberto por outro processo")

    monkeypatch.setattr(correio.os, "replace", sempre_ocupado)
    with pytest.raises(ValueError, match=correio.GRAVAR_ASSINATURA_OCUPADA):
        correio.gravar_assinatura(conn, 1, outra)
    assert correio.assinatura(1)[0] == nova and _eventos_assinatura(conn) == 2
    assert [a.name for a in correio._arquivo_assinatura(1).parent.iterdir()] == ["usuario-1"]


def _dormir_sem_trava(conn, dormidas):
    """No lugar de time.sleep: a espera entre tentativas nao pode segurar a trava de escrita do banco (#479, gate
    Sol): a transacao da tentativa que falhou ja' foi desfeita quando se dorme."""
    def dormir(s):
        assert not conn.in_transaction, "dormiu com a transacao aberta (trava de escrita segura)"
        dormidas.append(s)
    return dormir


def _eventos_assinatura(conn):
    return conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='correio.assinatura'").fetchone()[0]


def test_remover_assinatura_ocupada_pelo_backup_tenta_de_novo_e_depois_recusa_em_portugues(conn, monkeypatch):
    """Issue #479 (revisor na PR #472): no Windows, `unlink` da assinatura aberta pelo backup da' PermissionError e a
    rota respondia 500 em ingles. Um bloqueio curto passa na tentativa seguinte; o que persiste vira ValueError (422),
    a assinatura fica e o evento de remocao nao fica no banco. A espera entre tentativas e' fora da transacao."""
    from pathlib import Path
    correio.gravar_assinatura(conn, 1, _png(2, 2))
    dormidas = []
    monkeypatch.setattr(correio.time, "sleep", _dormir_sem_trava(conn, dormidas))
    real, chamadas = Path.unlink, []

    def sempre_ocupado(self, missing_ok=False):
        if self.name == "usuario-1":
            raise PermissionError("arquivo aberto por outro processo")
        real(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", sempre_ocupado)
    with pytest.raises(ValueError, match=correio.REMOVER_ASSINATURA_OCUPADA):
        correio.remover_assinatura(conn, 1)
    assert correio.REMOVER_ASSINATURA_OCUPADA == "Não foi possível tirar a assinatura agora; tente de novo"
    assert correio.assinatura(1) is not None
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='correio.assinatura' "
                        "AND depois LIKE '%removida%'").fetchone()[0] == 0

    def ocupado_uma_vez(self, missing_ok=False):
        chamadas.append(self.name)
        if self.name == "usuario-1" and len(chamadas) == 1:
            raise PermissionError("arquivo aberto por outro processo")
        real(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", ocupado_uma_vez)
    correio.remover_assinatura(conn, 1)
    assert correio.assinatura(1) is None and chamadas == ["usuario-1", "usuario-1"]
    assert len(dormidas) == len(correio._TENTATIVAS_TROCA) + 1 and _eventos_assinatura(conn) == 2


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


def _simulado(tmp_path):
    arquivos = sorted((tmp_path / "sim" / "enviados").glob("*.json"))
    return [json.loads(a.read_text(encoding="utf-8")) for a in arquivos]


def test_redirecionamento_de_teste_manda_so_para_o_endereco_de_teste_e_audita(conn, tmp_path, monkeypatch):
    """Teste em producao (06/11/2026): com o redirecionamento ligado, o e-mail vai SO' para o endereco de teste, com
    [TESTE] no assunto e os destinatarios de verdade no alto do corpo; o registro guarda os destinatarios de verdade
    e a auditoria diz para onde foi."""
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    monkeypatch.setenv("DASH_EMAIL_REDIRECIONAR", "teste@exemplo.com.br")
    eid = correio.enviar_e_registrar(conn, {"id": 1, "email": "quem.envia@l.com"}, "teste", ["orgao@exemplo.com.br"],
                                     ["fiscal@exemplo.com.br"], "Assunto", "<p>corpo</p>", [("a.txt", b"oi")],
                                     cco=["oculto@exemplo.com.br"])
    (enviado,) = _simulado(tmp_path)
    assert (enviado["para"], enviado["copia"], enviado["cco"]) == (["teste@exemplo.com.br"], [], [])
    assert enviado["assunto"] == "[TESTE] Assunto"
    for trecho in ("redirecionado", "orgao@exemplo.com.br", "fiscal@exemplo.com.br", "oculto@exemplo.com.br", "<p>corpo</p>"):
        assert trecho in enviado["corpo"]
    assert [a["nome"] for a in enviado["anexos"]] == ["a.txt"]
    e = conn.execute("SELECT para, copia, cco, assunto FROM envios WHERE id=?", (eid,)).fetchone()
    assert (json.loads(e["para"]), json.loads(e["copia"]), json.loads(e["cco"]), e["assunto"]) == (
        ["orgao@exemplo.com.br"], ["fiscal@exemplo.com.br"], ["oculto@exemplo.com.br"], "Assunto")
    depois = json.loads(conn.execute("SELECT depois FROM audit_log WHERE acao='correio.envio' AND entidade_id=?",
                                     (eid,)).fetchone()[0])
    assert depois["redirecionado_para"] == "teste@exemplo.com.br"


def test_sem_redirecionamento_o_envio_segue_como_antes(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    monkeypatch.delenv("DASH_EMAIL_REDIRECIONAR", raising=False)
    assert correio.redirecionamento() is None and correio.redirecionamento_ativo() is False
    eid = correio.enviar_e_registrar(conn, {"id": 1, "email": "quem.envia@l.com"}, "teste", ["orgao@exemplo.com.br"], [],
                                     "Assunto", "<p>corpo</p>", [])
    (enviado,) = _simulado(tmp_path)
    assert enviado["para"] == ["orgao@exemplo.com.br"] and enviado["assunto"] == "Assunto"
    assert "redirecionado" not in enviado["corpo"]
    depois = json.loads(conn.execute("SELECT depois FROM audit_log WHERE acao='correio.envio' AND entidade_id=?",
                                     (eid,)).fetchone()[0])
    assert "redirecionado_para" not in depois


def test_redirecionamento_pelo_arquivo_de_segredos_e_lido_a_cada_envio(conn, tmp_path, monkeypatch):
    monkeypatch.delenv("DASH_EMAIL_REDIRECIONAR", raising=False)
    # a pasta de segredos fica ao lado de `dados`: uma raiz so' deste teste, para o arquivo nao vazar para os outros
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "raiz" / "dados" / "t.db"))
    segredos = db.db_path().parent.parent / "segredos"
    segredos.mkdir(parents=True, exist_ok=True)
    arquivo = segredos / correio.ARQUIVO_REDIRECIONAR
    assert correio.redirecionamento() is None
    arquivo.write_text("teste@exemplo.com.br\n", encoding="utf-8")
    assert correio.redirecionamento() == "teste@exemplo.com.br" and correio.redirecionamento_ativo() is True
    arquivo.unlink()
    assert correio.redirecionamento() is None and correio.redirecionamento_ativo() is False


@pytest.mark.parametrize("conteudo", ["", "nao-e-um-endereco", "a@b", "dois@exemplo.com.br outro@exemplo.com.br"])
def test_redirecionamento_ligado_e_ilegivel_recusa_o_envio(conn, tmp_path, monkeypatch, conteudo):
    """Ligado com endereco que nao se le, NADA sai: o e-mail nao pode ir ao destinatario de verdade por engano."""
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    monkeypatch.delenv("DASH_EMAIL_REDIRECIONAR", raising=False)
    # a pasta de segredos fica ao lado de `dados`: uma raiz so' deste teste, para o arquivo nao vazar para os outros
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "raiz" / "dados" / "t.db"))
    segredos = db.db_path().parent.parent / "segredos"
    segredos.mkdir(parents=True, exist_ok=True)
    (segredos / correio.ARQUIVO_REDIRECIONAR).write_text(conteudo, encoding="utf-8")
    assert correio.redirecionamento_ativo() is True
    with pytest.raises(graph.ErroGraph, match="mal configurado"):
        correio.enviar_e_registrar(conn, {"id": 1, "email": "quem.envia@l.com"}, "teste", ["orgao@exemplo.com.br"], [],
                                   "Assunto", "<p/>", [])
    assert _simulado(tmp_path) == [] and conn.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0


# --- leitura das respostas: so' a conversa de um envio registrado (issue #644) -------------------------------

def test_consulta_de_leitura_filtra_pela_conversa_e_nao_lista_a_caixa():
    import urllib.parse
    caminho, _, consulta = correio.consulta_da_conversa("AAQk-conversa_1=").partition("?")
    q = urllib.parse.parse_qs(consulta)
    assert caminho == "/me/messages"
    assert q["$filter"] == ["conversationId eq 'AAQk-conversa_1='"]
    assert set(q) == {"$filter", "$select", "$top"}            # sem busca, sem pasta, sem ordenacao
    # aspas no identificador nao abrem o filtro: viram aspas dobradas, dentro do literal
    q = urllib.parse.parse_qs(correio.consulta_da_conversa("x' or '1' eq '1").partition("?")[2])
    assert q["$filter"] == ["conversationId eq 'x'' or ''1'' eq ''1'"]


@pytest.mark.parametrize("vazia", ["", "   ", None])
def test_consulta_de_leitura_sem_conversa_recusa(vazia):
    with pytest.raises(graph.ErroGraph):
        correio.consulta_da_conversa(vazia)


class _TokenFixo:
    def acesso(self):
        return "token-de-quem-enviou"


def test_leitura_pelo_graph_so_chama_a_consulta_da_conversa_e_descarta_o_que_vier_de_fora(monkeypatch):
    chamadas = []

    def falso_http(metodo, url, corpo=None, headers=None, bearer=None):
        chamadas.append((metodo, url, bearer))
        if "/attachments" in url:
            return {"value": [{"name": "parecer.pdf", "isInline": False}, {"name": "logo.png", "isInline": True}]}
        return {"value": [
            {"id": "g1", "internetMessageId": "<r1@orgao>", "conversationId": "conv-1", "hasAttachments": True,
             "from": {"emailAddress": {"address": "Fiscal@Orgao-A.exemplo.com.br", "name": "Fiscal do contrato"}},
             "receivedDateTime": "2026-11-10T14:00:00Z", "subject": "RES: medição",
             "body": {"contentType": "text", "content": "Recebido.\r\n\r\nSegue o parecer."}},
            {"id": "g2", "internetMessageId": "<r2@orgao>", "conversationId": "outra-conversa",
             "from": {"emailAddress": {"address": "alguem@exemplo.com.br"}},
             "receivedDateTime": "2026-11-10T15:00:00Z", "subject": "outro assunto", "body": {"content": "x"}},
            {"id": "g3", "internetMessageId": "<r3@orgao>", "conversationId": "conv-1", "isDraft": True,
             "from": {"emailAddress": {"address": "maria@l.com"}}, "body": {"content": "rascunho"}}]}

    monkeypatch.setattr(correio, "_http", falso_http)
    c = correio.ClienteCorreio(_TokenFixo())
    msgs = c.mensagens_da_conversa("conv-1")
    assert [(m["id"], m["de"], m["nome"], m["recebida_em"], m["assunto"], m["texto"]) for m in msgs] == [
        ("<r1@orgao>", "fiscal@orgao-a.exemplo.com.br", "Fiscal do contrato", "2026-11-10T14:00:00Z", "RES: medição",
         "Recebido.\r\n\r\nSegue o parecer.")]
    assert c.anexos_da_mensagem(msgs[0]) == ["parecer.pdf"]
    assert chamadas == [
        ("GET", graph.GRAPH + correio.consulta_da_conversa("conv-1"), "token-de-quem-enviou"),
        ("GET", graph.GRAPH + "/me/messages/g1/attachments?%24select=name%2CisInline", "token-de-quem-enviou")]


def test_envio_pelo_graph_guarda_a_conversa_do_rascunho(monkeypatch):
    def falso_http(metodo, url, corpo=None, headers=None, bearer=None):
        if metodo == "POST" and url.endswith("/me/messages"):
            return {"id": "g1", "internetMessageId": "<m1@l>", "conversationId": "conv-do-envio"}
        return {}

    monkeypatch.setattr(correio, "_http", falso_http)
    c = correio.ClienteCorreio(_TokenFixo())
    assert c.enviar(["protocolo@orgao-a.exemplo.com.br"], [], "assunto", "<p>corpo</p>", []) == "<m1@l>"
    assert c.conversa_do_ultimo_envio == "conv-do-envio"


def test_simulador_le_so_a_pasta_da_conversa_pedida(tmp_path):
    sim = correio.CorreioSimulado(tmp_path, "maria@l.com")
    sim.enviar(["protocolo@orgao-a.exemplo.com.br"], [], "assunto", "<p>corpo</p>", [])
    conversa = sim.conversa_do_ultimo_envio
    gravado = json.loads(next((tmp_path / "enviados").glob("*.json")).read_text("utf-8"))
    assert conversa and gravado["conversa"] == conversa
    for pasta, de in ((conversa, "fiscal@orgao-a.exemplo.com.br"), ("outra-conversa", "alguem@exemplo.com.br")):
        (tmp_path / "respostas" / pasta).mkdir(parents=True)
        (tmp_path / "respostas" / pasta / "001.json").write_text(json.dumps({
            "de": de, "recebida_em": "2026-11-10T14:00:00Z", "assunto": "RES: assunto", "texto": "Recebido.",
            "anexos": ["parecer.pdf"]}), encoding="utf-8")
    msgs = sim.mensagens_da_conversa(conversa)
    assert [m["de"] for m in msgs] == ["fiscal@orgao-a.exemplo.com.br"]
    assert sim.anexos_da_mensagem(msgs[0]) == ["parecer.pdf"]
    assert sim.mensagens_da_conversa("../enviados") == [] and sim.mensagens_da_conversa("sem-resposta") == []
