import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

import pytest

from app import backup

# Roda no Linux da CI (issue #385); o que so' vale no Windows (trava de arquivo aberto) se pula com skipif.

def test_snapshot_e_rotacao(tmp_path):
    origem = tmp_path / "app.db"
    conn = sqlite3.connect(origem)
    conn.execute("CREATE TABLE t (x)"); conn.execute("INSERT INTO t VALUES (42)")
    conn.commit(); conn.close()
    destino = tmp_path / "backups"
    arq = backup.criar_snapshot(origem, destino)
    assert arq.exists()
    check = sqlite3.connect(arq)
    assert check.execute("SELECT x FROM t").fetchone()[0] == 42  # backup abre e tem os dados
    check.close()

def test_rotacao_mantem_48(tmp_path):
    origem = tmp_path / "app.db"
    sqlite3.connect(origem).execute("CREATE TABLE t (x)")
    destino = tmp_path / "backups"; destino.mkdir()
    for i in range(50):
        (destino / f"dashboard-20260101-{i:06d}.db").write_bytes(b"velho")
    backup.criar_snapshot(origem, destino)
    assert len(list(destino.glob("dashboard-*.db"))) == 48


def test_rotacao_nao_conta_nem_apaga_backup_pre(tmp_path):
    origem = tmp_path / "app.db"
    sqlite3.connect(origem).execute("CREATE TABLE t (x)")
    destino = tmp_path / "backups"; destino.mkdir()
    for i in range(50):
        (destino / f"dashboard-PRE-DEPLOY-{i:02d}.db").write_bytes(b"pre")
    for i in range(48):
        (destino / f"dashboard-20260101-{i:06d}.db").write_bytes(b"velho")
    novo = backup.criar_snapshot(origem, destino)
    horarios = [a for a in destino.glob("dashboard-*.db") if backup._NOME.match(a.name)]
    assert len(horarios) == 48
    assert novo.exists()
    assert not (destino / "dashboard-20260101-000000.db").exists()  # o horario mais velho saiu
    assert len(list(destino.glob("dashboard-PRE-*.db"))) == 50


# --- snapshot atomico (revisao final: parcial nao pode expulsar backup bom) ----

def test_tmp_nao_conta_na_rotacao_e_e_limpo(tmp_path):
    # sobra de um processo morto no meio do VACUUM: nao pode contar como snapshot
    # (empurraria um backup bom para fora dos 48) nem ficar para sempre no disco.
    origem = tmp_path / "app.db"
    sqlite3.connect(origem).execute("CREATE TABLE t (x)")
    destino = tmp_path / "backups"; destino.mkdir()
    for i in range(47):
        (destino / f"dashboard-20260101-{i:06d}.db").write_bytes(b"velho")
    sobra = destino / "dashboard-20260101-999999-pid1.db.tmp"
    sobra.write_bytes(b"parcial")
    envelhecer(sobra, 7200)  # 2h: ninguem vivo escreveu isso

    backup.criar_snapshot(origem, destino)

    assert not sobra.exists()                                    # limpo no inicio
    assert list(destino.glob("*.db.tmp")) == []                  # nada pendente no fim
    assert len(list(destino.glob("dashboard-*.db"))) == 48       # 47 antigos + 1 novo
    assert (destino / "dashboard-20260101-000000.db").exists()   # o mais velho sobreviveu


# --- concorrencia entre processos (gate C) ------------------------------------

def envelhecer(caminho, segundos):
    antigo = time.time() - segundos
    os.utime(caminho, (antigo, antigo))

def test_tmp_recente_de_outro_processo_sobrevive(tmp_path):
    # o .tmp fresco pertence a um VACUUM em andamento de OUTRO processo (a tarefa
    # agendada e uma execucao manual dividem a pasta). Apaga-lo destruiria aquele
    # backup, que so descobriria a perda no rename final.
    origem = tmp_path / "app.db"
    sqlite3.connect(origem).execute("CREATE TABLE t (x)")
    destino = tmp_path / "backups"; destino.mkdir()
    vivo = destino / "dashboard-20260101-120000-pid4242.db.tmp"
    vivo.write_bytes(b"vacuum em andamento")

    backup.criar_snapshot(origem, destino)

    assert vivo.exists(), "o .tmp recente de outro processo foi apagado"
    assert vivo.read_bytes() == b"vacuum em andamento"

def test_tmp_leva_o_pid_no_nome(tmp_path, monkeypatch):
    # dois processos com o mesmo carimbo de segundo nao podem escrever no MESMO
    # arquivo parcial: o PID e' o que os separa.
    origem = tmp_path / "app.db"
    sqlite3.connect(origem).execute("CREATE TABLE t (x)")
    destino = tmp_path / "backups"

    vistos = []
    real_connect = sqlite3.connect

    class Espia:
        def __init__(self, c): self._c = c
        def execute(self, sql, params=()):
            if params:
                vistos.append(params[0])
            return self._c.execute(sql, params)
        def close(self): self._c.close()

    monkeypatch.setattr(backup.sqlite3, "connect", lambda *a, **kw: Espia(real_connect(*a, **kw)))
    backup.criar_snapshot(origem, destino)

    assert vistos and vistos[0].endswith(f"-pid{os.getpid()}.db.tmp"), vistos

def test_vacuum_falho_nao_deixa_snapshot(tmp_path, monkeypatch):
    # VACUUM interrompido: o arquivo parcial e removido e nenhum snapshot aparece
    # com nome valido -- a rotacao nunca ve um backup quebrado.
    origem = tmp_path / "app.db"
    sqlite3.connect(origem).execute("CREATE TABLE t (x)")
    destino = tmp_path / "backups"; destino.mkdir()

    real_connect = sqlite3.connect

    class ConnQuebrada:
        def __init__(self, c): self._c = c
        def execute(self, *a, **kw):
            self._c.execute("SELECT 1")  # so para provar que a conexao e usada
            raise KeyboardInterrupt("processo morto no meio do VACUUM")
        def close(self): self._c.close()

    monkeypatch.setattr(backup.sqlite3, "connect", lambda *a, **kw: ConnQuebrada(real_connect(*a, **kw)))

    try:
        backup.criar_snapshot(origem, destino)
        assert False, "criar_snapshot deveria propagar a falha"
    except KeyboardInterrupt:
        pass

    assert list(destino.glob("*.db.tmp")) == []
    assert list(destino.glob("dashboard-*.db")) == []


# --- ensaio de restauracao, copia externa e retencao em camadas (bloco de producao) ---

def _origem(tmp_path):
    origem = tmp_path / "app.db"
    conn = sqlite3.connect(origem)
    conn.execute("CREATE TABLE t (x)"); conn.execute("INSERT INTO t VALUES (1)")
    conn.commit(); conn.close()
    return origem

def test_snapshot_corrompido_nao_vira_backup(tmp_path, monkeypatch):
    # o ensaio de restauracao roda ANTES do rename: parcial que nao abre e' apagado
    origem = _origem(tmp_path)
    destino = tmp_path / "backups"
    monkeypatch.setattr(backup, "verificar_snapshot",
                        lambda a: (_ for _ in ()).throw(backup.SnapshotInvalido("x")))
    with pytest.raises(backup.SnapshotInvalido):
        backup.criar_snapshot(origem, destino)
    assert list(destino.glob("*")) == []

def test_verificar_snapshot_rejeita_lixo(tmp_path):
    lixo = tmp_path / "dashboard-20260101-000000.db"
    lixo.write_bytes(b"isto nao e um banco" * 100)
    with pytest.raises(backup.SnapshotInvalido):
        backup.verificar_snapshot(lixo)

def test_copia_externa_com_checksum_conferido(tmp_path):
    origem = _origem(tmp_path)
    snap = backup.criar_snapshot(origem, tmp_path / "backups")
    fora = tmp_path / "externo"
    copia = backup.copiar_externo(snap, fora)
    assert copia.read_bytes() == snap.read_bytes()
    sha = (fora / f"{snap.name}.sha256").read_text().split()[0]
    assert sha == backup._sha256(snap)
    assert list(fora.glob("*.tmp")) == []

def test_retencao_em_camadas(tmp_path):
    # 400 dias de copias diarias -> 7 diarias + 5 semanais + 12 mensais (com sobreposicao)
    import datetime
    fora = tmp_path / "externo"; fora.mkdir()
    fim = datetime.date(2026, 9, 2)
    for i in range(400):
        d = fim - datetime.timedelta(days=i)
        (fora / f"dashboard-{d:%Y%m%d}-030000.db").write_bytes(b"x")
    backup.rotacionar_externo(fora)
    restantes = sorted(backup._data_do_nome(a) for a in fora.glob("dashboard-*.db"))
    ultimos7 = [fim - datetime.timedelta(days=i) for i in range(7)]
    assert all(d in restantes for d in ultimos7)           # diarios
    assert datetime.date(2026, 8, 31) in restantes         # ultimo dia de agosto (mensal)
    assert datetime.date(2025, 10, 31) in restantes        # 12o mes contando o atual (mensal)
    assert datetime.date(2025, 9, 30) not in restantes     # 13o mes: fora
    assert len(restantes) <= 7 + 5 + 12

def test_rodada_copia_uma_vez_por_dia_e_registra_estado(tmp_path):
    origem = _origem(tmp_path)
    fora = tmp_path / "externo"
    backup.rodada(origem, tmp_path / "backups", fora)
    assert backup.ESTADO["ultimo_snapshot"] and backup.ESTADO["ultima_copia_externa"]
    assert len(list(fora.glob("dashboard-*.db"))) == 1
    time.sleep(1.1)  # segundo snapshot com carimbo diferente, mesmo dia
    backup.rodada(origem, tmp_path / "backups", fora)
    assert len(list((tmp_path / "backups").glob("dashboard-*.db"))) == 2
    assert len(list(fora.glob("dashboard-*.db"))) == 1     # nao copiou de novo hoje

def test_rodada_registra_erro_de_acesso_a_pasta_externa(tmp_path, monkeypatch):
    # compartilhamento sem permissao: exists()/glob() levantam PermissionError antes
    # de copiar; tem que virar erro registrado, nao thread morta
    origem = _origem(tmp_path)
    monkeypatch.setattr(backup, "_copiou_hoje",
                        lambda p, h: (_ for _ in ()).throw(PermissionError("Acesso negado")))
    backup.rodada(origem, tmp_path / "backups", tmp_path / "externo")
    assert "acesso negado" in backup.ESTADO["ultima_copia_externa_erro"]


def test_rodada_registra_erro_da_copia_sem_derrubar(tmp_path, monkeypatch):
    origem = _origem(tmp_path)
    monkeypatch.setattr(backup, "copiar_externo",
                        lambda s, p: (_ for _ in ()).throw(OSError("rede fora")))
    backup.rodada(origem, tmp_path / "backups", tmp_path / "externo")
    assert backup.ESTADO["ultimo_snapshot_erro"] is None
    assert "rede fora" in backup.ESTADO["ultima_copia_externa_erro"]


# --- arquivos ao lado do banco (issue #55): notas, espelhos, modelos e evidencias -----

@pytest.fixture(autouse=True)
def _worker_limpo(monkeypatch):
    # estado do worker dos arquivos e' do modulo: cada teste comeca do zero
    monkeypatch.setattr(backup, "_arquivos_fase", None)
    monkeypatch.setattr(backup, "_arquivos_desde", None)
    monkeypatch.setattr(backup, "_thread_arquivos", None)
    monkeypatch.setattr(backup, "_conferido_em", {})
    monkeypatch.setattr(backup, "_pendentes", {})
    for chave in ("ultima_copia_arquivos", "ultima_copia_arquivos_erro",
                  "ultima_copia_externa_arquivos", "ultima_copia_externa_arquivos_erro"):
        monkeypatch.setitem(backup.ESTADO, chave, None)


# Toda pasta de `dados` que o sistema grava pelo sha256 (issue #441), com a extensao de um arquivo tipico. A lista
# e' do teste, nao `backup.PASTAS_ARQUIVOS`: pasta que sair de la' faz a restauracao abaixo falhar.
PASTAS_DOS_DADOS = (("notas", "pdf"), ("espelhos", "docx"), ("modelos", "docx"), ("evidencias", "eml"),
                    ("certidoes", "pdf"), ("regularidades", "pdf"), ("protocolos", "pdf"), ("pleitos", "pdf"),
                    ("curvas", "xlsx"), ("planilhas", "xlsx"), ("frc", "pdf"), ("boletins", "pdf"),
                    ("anexos", "pdf"), ("assinados", "pdf"))   # issue #627
ASSINATURA = b"\x89PNG\r\n\x1a\n assinatura"


def _dados_com_arquivos(tmp_path):
    """Pasta de dados como a da producao: banco + as pastas pelo sha256 e a assinatura de quem envia
    (`assinaturas/usuario-<id>`, o unico nome que nao e' o sha256)."""
    dados = tmp_path / "dados"; dados.mkdir()
    origem = dados / "dashboard.db"
    conn = sqlite3.connect(origem)
    conn.execute("CREATE TABLE docs (caminho TEXT)")
    gravados = {}
    for pasta, ext in PASTAS_DOS_DADOS:
        conteudo = f"%PDF- conteudo de {pasta}".encode()
        rel = f"{pasta}/{hashlib.sha256(conteudo).hexdigest()}.{ext}"
        (dados / pasta).mkdir()
        (dados / rel).write_bytes(conteudo)
        conn.execute("INSERT INTO docs VALUES (?)", (rel,))
        gravados[rel] = conteudo
    (dados / "assinaturas").mkdir()
    (dados / "assinaturas" / "usuario-1").write_bytes(ASSINATURA)
    conn.execute("INSERT INTO docs VALUES ('assinaturas/usuario-1')")
    gravados["assinaturas/usuario-1"] = ASSINATURA
    # a auditoria que `correio.gravar_assinatura` grava: e' por ela que a restauracao sabe a assinatura vigente
    conn.execute("CREATE TABLE audit_log (id INTEGER PRIMARY KEY, acao TEXT, entidade TEXT, entidade_id TEXT, "
                 "depois TEXT)")
    _evento_assinatura(conn, 1, {"tamanho": len(ASSINATURA), "sha256": hashlib.sha256(ASSINATURA).hexdigest()})
    conn.commit(); conn.close()
    return origem, gravados


def _evento_assinatura(conn, uid, depois):
    conn.execute("INSERT INTO audit_log (acao, entidade, entidade_id, depois) VALUES ('correio.assinatura', "
                 "'usuario', ?, ?)", (str(uid), json.dumps(depois)))


def test_pastas_arquivos_cobre_toda_pasta_que_o_sistema_grava():
    """Issue #441: o backup levava so' notas, espelhos, modelos e evidencias; protocolos, pleitos, curvas e as outras
    sumiam numa restauracao. Confere no codigo: toda pasta de `dados` gravada pelo sistema esta' no backup."""
    import re
    gravadas = set()
    for arq in Path(backup.__file__).parent.glob("*.py"):
        texto = arq.read_text(encoding="utf-8")
        gravadas |= set(re.findall(r'(?:gravar_bytes|arquivos\.pasta|_no_disco)\(\s*"(\w+)"', texto))
        gravadas |= set(re.findall(r'^PASTA_\w+ = "(\w+)"', texto, re.M))   # curvas (pleitos.PASTA_CURVA_S)
    # a busca acha o que a issue lista (senao o teste nao prova nada)
    assert {"certidoes", "regularidades", "protocolos", "pleitos", "frc", "assinaturas", "curvas",
            "planilhas"} <= gravadas
    assert gravadas <= set(backup.PASTAS_ARQUIVOS), sorted(gravadas - set(backup.PASTAS_ARQUIVOS))
    assert {p for p, _ in PASTAS_DOS_DADOS} | {"assinaturas"} == set(backup.PASTAS_ARQUIVOS)


def _arquivos_no(pasta):
    return sorted(a for a in pasta.rglob("*") if a.is_file()) if pasta.exists() else []


def _rodar(origem, destino, fora=None):
    """O que as duas threads fazem a cada hora: snapshot e, em seguida, a passada dos arquivos."""
    backup.rodada(origem, destino, fora)
    backup.rodada_arquivos(origem, destino, fora)


def test_passada_copia_todas_as_pastas_para_o_backup(tmp_path):
    origem, gravados = _dados_com_arquivos(tmp_path)
    destino = tmp_path / "dados" / "backups"
    _rodar(origem, destino)
    for rel, conteudo in gravados.items():
        assert (destino / "arquivos" / rel).read_bytes() == conteudo, rel
    assert backup.ESTADO["ultima_copia_arquivos"] and backup.ESTADO["ultima_copia_arquivos_erro"] is None


def test_assinatura_trocada_por_outra_do_mesmo_tamanho_vai_ao_backup_na_passada_seguinte(tmp_path):
    """Issue #441 (/code-review): `assinaturas/usuario-<id>` nao e' o sha256; mesmo nome e tamanho nao provam o mesmo
    arquivo, e a passada de hora em hora (sem a releitura diaria) tem que levar a assinatura nova."""
    origem, _ = _dados_com_arquivos(tmp_path)
    destino = tmp_path / "dados" / "backups"
    _rodar(origem, destino)                                   # primeira passada: relê tudo
    nova = ASSINATURA.replace(b"assinatura", b"ASSINATURA")
    assert len(nova) == len(ASSINATURA)
    (tmp_path / "dados" / "assinaturas" / "usuario-1").write_bytes(nova)
    backup.rodada_arquivos(origem, destino, None)             # de hora em hora: sem releitura
    assert (destino / "arquivos" / "assinaturas" / "usuario-1").read_bytes() == nova


def test_copia_ignora_temporario_em_andamento(tmp_path):
    origem, _ = _dados_com_arquivos(tmp_path)
    (tmp_path / "dados" / "notas" / "upload-123-abc.tmp").write_bytes(b"parcial")
    destino = tmp_path / "dados" / "backups"
    _rodar(origem, destino)
    assert (destino / "arquivos" / "notas").is_dir()
    assert list((destino / "arquivos" / "notas").glob("*.tmp")) == []


def test_restaurar_snapshot_devolve_banco_e_arquivos_coerentes(tmp_path):
    origem, gravados = _dados_com_arquivos(tmp_path)
    dados = tmp_path / "dados"
    destino = dados / "backups"
    _rodar(origem, destino)
    snap = sorted(destino.glob("dashboard-*.db"))[-1]

    # o pior dia: banco perdido, pastas vazias e um PDF estragado no lugar (mesmo tamanho)
    origem.unlink()
    for pasta in [p for p, _ in PASTAS_DOS_DADOS] + ["assinaturas"]:   # todas, nao so' as que o backup leva
        for a in (dados / pasta).iterdir():
            a.unlink()
    rel_estragado = next(iter(gravados))
    (dados / rel_estragado).write_bytes(b"x" * len(gravados[rel_estragado]))

    # restauracao como o runbook manda: snapshot volta a ser o banco, arquivos conferidos voltam
    origem.write_bytes(snap.read_bytes())
    assert backup.restaurar_arquivos(destino / "arquivos", dados) == len(gravados)

    conn = sqlite3.connect(origem)
    citados = [r[0] for r in conn.execute("SELECT caminho FROM docs")]
    conn.close()
    assert sorted(citados) == sorted(gravados)
    for rel in citados:  # todo arquivo que o banco cita existe e e' o que foi gravado
        assert (dados / rel).read_bytes() == gravados[rel]


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _restaurar_com_eventos(tmp_path, eventos, ativos=None):
    """Backup feito com a assinatura A da pessoa 1; o banco restaurado ganha `eventos`; `dados/assinaturas` fica com
    `ativos` ({uid: bytes}; None = a pasta como estava). Devolve (dados, backup dos arquivos, erro ou None)."""
    origem, _ = _dados_com_arquivos(tmp_path)
    dados = tmp_path / "dados"
    destino = dados / "backups"
    _rodar(origem, destino)
    conn = sqlite3.connect(origem)
    for uid, depois in eventos:
        _evento_assinatura(conn, uid, depois)
    conn.commit(); conn.close()
    if ativos is not None:
        for a in (dados / "assinaturas").iterdir():
            a.unlink()
        for uid, b in ativos.items():
            (dados / "assinaturas" / f"usuario-{uid}").write_bytes(b)
    try:
        backup.restaurar_arquivos(destino / "arquivos", dados)
        return dados, destino / "arquivos", None
    except backup.ErroArquivo as e:
        return dados, destino / "arquivos", str(e)


def _quarentena(dados):
    return sorted(b.read_bytes() for q in (dados / "assinaturas").glob("quarentena-*") for b in q.iterdir())


def test_restauracao_troca_a_assinatura_ativa_pela_vigente_no_banco(tmp_path):
    """Gate Sol na PR #472 (#441): `dados` nao se perdeu e tem B; o banco restaurado diz que a vigente e' A (a do
    backup). B vai para a quarentena e A volta: nao basta deixar de copiar, B sairia nos e-mails."""
    dados, _, erro = _restaurar_com_eventos(tmp_path, [], ativos={1: b"B outra png"})
    assert erro is None
    assert (dados / "assinaturas" / "usuario-1").read_bytes() == ASSINATURA
    assert _quarentena(dados) == [b"B outra png"]


def test_restauracao_tira_a_assinatura_que_o_banco_diz_removida(tmp_path):
    """O ultimo evento e' a remocao: a ativa (que ainda estava em `dados`) vai para a quarentena e a do backup nao volta."""
    dados, arquivos_bkp, erro = _restaurar_com_eventos(tmp_path, [(1, {"removida": True})])
    assert erro is None
    assert not (dados / "assinaturas" / "usuario-1").exists()
    assert _quarentena(dados) == [ASSINATURA]
    assert (arquivos_bkp / "assinaturas" / "usuario-1").read_bytes() == ASSINATURA   # o backup nao perde


def test_restauracao_acusa_quem_ficou_sem_a_assinatura_vigente_e_segue_com_os_outros(tmp_path):
    """Parte do banco, nao dos arquivos: a pessoa 7 tem assinatura no banco e nenhuma copia dela existe, e a 1 trocou
    para C (o banco diz C) mas so' ha' A. As duas sao acusadas sem nome de arquivo; a 3, que o banco nao conhece, sai
    do nome ativo; e a 2, em ordem, volta do backup mesmo com as outras falhando."""
    dois = b"\x89PNG\r\n\x1a\n pessoa 2"
    origem, _ = _dados_com_arquivos(tmp_path)
    dados = tmp_path / "dados"
    destino = dados / "backups"
    (dados / "assinaturas" / "usuario-2").write_bytes(dois)
    _rodar(origem, destino)
    conn = sqlite3.connect(origem)
    for uid, depois in ((2, {"sha256": _sha(dois)}), (7, {"sha256": _sha(b"sete")}), (1, {"sha256": _sha(b"C")})):
        _evento_assinatura(conn, uid, depois)
    conn.commit(); conn.close()
    for a in (dados / "assinaturas").iterdir():
        a.unlink()
    (dados / "assinaturas" / "usuario-3").write_bytes(b"sem evento")
    with pytest.raises(backup.ErroArquivo) as e:
        backup.restaurar_arquivos(destino / "arquivos", dados)
    assert str(e.value) == ("2 assinatura(s) sem a vigente: usuário 1: nenhuma cópia tem a assinatura vigente no "
                            "banco; usuário 7: nenhuma cópia tem a assinatura vigente no banco")
    assert (dados / "assinaturas" / "usuario-2").read_bytes() == dois
    assert not (dados / "assinaturas" / "usuario-1").exists() and not (dados / "assinaturas" / "usuario-3").exists()
    assert _quarentena(dados) == [b"sem evento"]


def test_erro_de_disco_numa_assinatura_nao_para_as_outras(tmp_path, monkeypatch):
    """Revisor na PR #472 (#441): um try por pessoa; o motivo vai junto, em portugues."""
    dois = b"\x89PNG\r\n\x1a\n pessoa 2"
    origem, _ = _dados_com_arquivos(tmp_path)
    dados = tmp_path / "dados"
    destino = dados / "backups"
    (dados / "assinaturas" / "usuario-2").write_bytes(dois)
    _rodar(origem, destino)
    conn = sqlite3.connect(origem)
    _evento_assinatura(conn, 2, {"sha256": _sha(dois)})
    conn.commit(); conn.close()
    for a in (dados / "assinaturas").iterdir():
        a.unlink()
    real = backup._copiar_um

    def negado_na_1(arquivo, alvo, conferir=False):
        if alvo.name == "usuario-1":
            raise PermissionError("negado")
        return real(arquivo, alvo, conferir)

    monkeypatch.setattr(backup, "_copiar_um", negado_na_1)
    with pytest.raises(backup.ErroArquivo, match=r"^1 assinatura\(s\) sem a vigente: usuário 1: acesso negado$"):
        backup.restaurar_arquivos(destino / "arquivos", dados)
    assert (dados / "assinaturas" / "usuario-2").read_bytes() == dois


def test_restauracao_devolve_a_versao_da_assinatura_que_valia_no_snapshot(tmp_path):
    """Issue #479 (gate Sol na PR #472): o snapshot escolhido tem a assinatura A; depois a pessoa trocou para B e o
    backup ja' levou B. Cada versao fica no backup pelo sha256 (`usuario-<id>.<sha256>`): A volta ao nome ativo e B vai
    para a quarentena, sem erro."""
    origem, _ = _dados_com_arquivos(tmp_path)
    dados = tmp_path / "dados"
    destino = dados / "backups"
    _rodar(origem, destino)
    banco_com_a = origem.read_bytes()                     # o "snapshot escolhido": a vigente e' A
    b = b"\x89PNG\r\n\x1a\n assinatura B"
    (dados / "assinaturas" / "usuario-1").write_bytes(b)
    conn = sqlite3.connect(origem)
    _evento_assinatura(conn, 1, {"tamanho": len(b), "sha256": _sha(b)})
    conn.commit(); conn.close()
    backup.rodada_arquivos(origem, destino, None)
    arquivos_bkp = destino / "arquivos" / "assinaturas"
    assert (arquivos_bkp / "usuario-1").read_bytes() == b                  # o nome ativo continua sendo uma copia
    assert (arquivos_bkp / f"usuario-1.{_sha(ASSINATURA)}").read_bytes() == ASSINATURA
    assert (arquivos_bkp / f"usuario-1.{_sha(b)}").read_bytes() == b
    assert backup.ESTADO["ultima_copia_arquivos_erro"] is None

    origem.write_bytes(banco_com_a)
    backup.restaurar_arquivos(destino / "arquivos", dados)
    assert (dados / "assinaturas" / "usuario-1").read_bytes() == ASSINATURA
    assert _quarentena(dados) == [b]
    assert sorted(a.name for a in (dados / "assinaturas").iterdir() if a.is_file()) == ["usuario-1"]


def test_assinatura_tirada_no_meio_da_passada_nao_e_erro_e_a_antiga_continua_restauravel(tmp_path, monkeypatch):
    """#479 (/code-review e gate Sol S4): a pessoa tira a assinatura entre a listagem e a leitura; nao ha' o que
    guardar, a passada nao acusa falso alarme e o backup de A fica intacto. Depois ela sobe B, a passada leva B, e o
    banco que espera A ainda devolve A."""
    origem, _ = _dados_com_arquivos(tmp_path)
    dados = tmp_path / "dados"
    destino = dados / "backups"
    _rodar(origem, destino)
    banco_com_a = origem.read_bytes()
    ativa = dados / "assinaturas" / "usuario-1"
    real, disparou = Path.read_bytes, []

    def tirada(self):
        if self == ativa:
            disparou.append(self)
            raise FileNotFoundError(2, "No such file or directory", str(self))
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", tirada)
    backup.rodada_arquivos(origem, destino, None)
    monkeypatch.setattr(Path, "read_bytes", real)
    assert disparou and backup.ESTADO["ultima_copia_arquivos_erro"] is None
    assert (destino / "arquivos" / "assinaturas" / "usuario-1").read_bytes() == ASSINATURA

    b = b"\x89PNG\r\n\x1a\n assinatura B"
    ativa.write_bytes(b)
    backup.rodada_arquivos(origem, destino, None)
    assert backup.ESTADO["ultima_copia_arquivos_erro"] is None
    origem.write_bytes(banco_com_a)
    backup.restaurar_arquivos(destino / "arquivos", dados)
    assert ativa.read_bytes() == ASSINATURA and _quarentena(dados) == [b]


def test_backup_antigo_so_com_o_nome_ativo_nao_perde_a_assinatura_na_troca(tmp_path):
    """Gate Sol S1 na PR #496 (#479): o backup de antes das versoes so' tem `usuario-1` = A; os dados ja' estao em B.
    Antes de trocar o nome ativo do backup por B, A vira `usuario-1.<sha de A>`: o snapshot antigo que cita A continua
    restauravel."""
    origem, _ = _dados_com_arquivos(tmp_path)
    dados = tmp_path / "dados"
    destino = dados / "backups"
    _rodar(origem, destino)
    banco_com_a = origem.read_bytes()
    bkp = destino / "arquivos" / "assinaturas"
    for versao in bkp.glob("usuario-1.*"):         # como um backup feito antes das versoes
        versao.unlink()
    assert [a.name for a in bkp.iterdir()] == ["usuario-1"]
    b = b"\x89PNG\r\n\x1a\n assinatura B"
    (dados / "assinaturas" / "usuario-1").write_bytes(b)
    backup.rodada_arquivos(origem, destino, None)
    assert backup.ESTADO["ultima_copia_arquivos_erro"] is None
    assert (bkp / "usuario-1").read_bytes() == b
    assert (bkp / f"usuario-1.{_sha(ASSINATURA)}").read_bytes() == ASSINATURA
    origem.write_bytes(banco_com_a)
    backup.restaurar_arquivos(destino / "arquivos", dados)
    assert (dados / "assinaturas" / "usuario-1").read_bytes() == ASSINATURA


def test_falha_no_destino_depois_de_ler_a_assinatura_e_erro_da_passada(tmp_path, monkeypatch):
    """Gate Sol S2 na PR #496 (#479): so' a assinatura que sumiu dos dados antes da leitura e' pulada. Um
    FileNotFoundError ao gravar no backup (a pasta do backup sumiu no meio) e' erro da passada, nao "a pessoa tirou"."""
    origem, _ = _dados_com_arquivos(tmp_path)
    destino = tmp_path / "dados" / "backups"
    _rodar(origem, destino)
    (tmp_path / "dados" / "assinaturas" / "usuario-1").write_bytes(b"\x89PNG\r\n\x1a\n assinatura B")

    def pasta_sumiu(conteudo, sha, alvo):
        raise FileNotFoundError(2, "No such file or directory", str(alvo))

    monkeypatch.setattr(backup, "_gravar_conferido", pasta_sumiu)
    backup.rodada_arquivos(origem, destino, None)
    erro = backup.ESTADO["ultima_copia_arquivos_erro"]
    assert erro is not None and erro.endswith("1 arquivo(s) sem cópia: assinaturas 1 (arquivo ou pasta não encontrado)")


SUMIU_PLEITOS = "1 arquivo(s) de pleitos estão no backup e sumiram dos dados"


def test_erro_ao_listar_o_backup_e_falha_da_passada_e_nao_apaga_o_alarme(tmp_path, monkeypatch):
    """Issue #479 (gate Sol na PR #472): acesso negado ao listar a pasta do backup nao vale como "nada sumiu". A
    passada falha com o motivo em portugues e o alarme de antes (pleitos sumiu) continua aceso. So' a pasta do backup
    que nao existe vale como vazia."""
    import shutil
    origem, _ = _dados_com_arquivos(tmp_path)
    destino = tmp_path / "dados" / "backups"
    _rodar(origem, destino)
    shutil.rmtree(tmp_path / "dados" / "pleitos")
    backup.rodada_arquivos(origem, destino, None)
    assert backup.ESTADO["ultima_copia_arquivos_erro"].endswith(f": {SUMIU_PLEITOS}")
    pleitos_bkp = destino / "arquivos" / "pleitos"
    real = Path.iterdir

    def negado(self):
        if self == pleitos_bkp:
            raise PermissionError(13, "Acesso negado", str(self))
        return real(self)

    monkeypatch.setattr(Path, "iterdir", negado)
    backup.rodada_arquivos(origem, destino, None)
    erro = backup.ESTADO["ultima_copia_arquivos_erro"]
    assert erro is not None and erro.endswith(": não foi possível ler o backup de pleitos (acesso negado)"), erro
    assert str(tmp_path) not in erro


def test_passada_acusa_pasta_que_sumiu_dos_dados_e_nao_a_que_nunca_existiu(tmp_path):
    """Gate Sol e revisor na PR #472 (#441): `dados/pleitos` sumiu e o backup dela esta' cheio: a passada nao pode
    dizer que terminou bem (o snapshot cita arquivos que ela nao viu). O erro fica com a pasta recriada vazia (a proxima
    carta montada recria, `arquivos.pasta` faz mkdir) e na copia externa. Pasta em que nada foi gravado nao e' erro."""
    import shutil
    origem, _ = _dados_com_arquivos(tmp_path)
    destino, fora = tmp_path / "dados" / "backups", tmp_path / "fora"
    shutil.rmtree(tmp_path / "dados" / "boletins")     # nunca existiu: nem nos dados nem no backup
    _rodar(origem, destino, fora)
    assert backup.ESTADO["ultima_copia_arquivos_erro"] is None
    assert backup.ESTADO["ultima_copia_externa_arquivos_erro"] is None
    shutil.rmtree(tmp_path / "dados" / "pleitos")
    for _ in range(2):
        backup.rodada_arquivos(origem, destino, fora)
        assert backup.ESTADO["ultima_copia_arquivos_erro"].endswith(f": {SUMIU_PLEITOS}")
        assert backup.ESTADO["ultima_copia_externa_arquivos_erro"].endswith(f": {SUMIU_PLEITOS}")
        (tmp_path / "dados" / "pleitos").mkdir(exist_ok=True)       # recriada vazia: o acervo continua fora


def test_temporario_e_nome_alheio_no_backup_nao_contam_como_sumidos(tmp_path):
    """Gate Sol na PR #472 (#441): `.tmp`, `desktop.ini` e nome fora do padrao no backup nao sao arquivos dos dados."""
    origem, _ = _dados_com_arquivos(tmp_path)
    destino = tmp_path / "dados" / "backups"
    _rodar(origem, destino)
    pleitos = destino / "arquivos" / "pleitos"
    for nome in ("desktop.ini", f"{'a' * 64}.pdf.123-456-abcdef01.tmp", "Thumbs.db", f"{'b' * 63}.pdf"):
        (pleitos / nome).write_bytes(b"x")
    backup.rodada_arquivos(origem, destino, None)
    assert backup.ESTADO["ultima_copia_arquivos_erro"] is None


def test_arquivos_nao_se_multiplicam_por_snapshot(tmp_path):
    # 48 snapshots nao podem virar 48 copias dos PDFs: os nomes sao o sha256, uma copia basta
    origem, gravados = _dados_com_arquivos(tmp_path)
    destino = tmp_path / "dados" / "backups"
    _rodar(origem, destino)
    copia = destino / "arquivos" / next(iter(gravados))
    envelhecer(copia, 7200)
    antes = copia.stat().st_mtime
    time.sleep(1.1)
    _rodar(origem, destino)
    assert len(list(destino.glob("dashboard-*.db"))) == 2
    # cada arquivo uma vez, mais a versao da assinatura pelo sha256 (#479), tambem uma so'
    versao = destino / "arquivos" / "assinaturas" / f"usuario-1.{hashlib.sha256(ASSINATURA).hexdigest()}"
    assert _arquivos_no(destino / "arquivos") == sorted([destino / "arquivos" / rel for rel in gravados] + [versao])
    assert copia.stat().st_mtime == antes  # ja' estava la': nao foi copiado de novo


def test_arquivo_que_saiu_dos_dados_continua_no_backup(tmp_path):
    # um snapshot antigo pode citar o arquivo; o backup nunca apaga o que guardou, e acusa o que sumiu (#441)
    origem, gravados = _dados_com_arquivos(tmp_path)
    destino = tmp_path / "dados" / "backups"
    _rodar(origem, destino)
    rel = next(iter(gravados))
    (tmp_path / "dados" / rel).unlink()
    time.sleep(1.1)
    _rodar(origem, destino)
    assert (destino / "arquivos" / rel).exists()
    assert backup.ESTADO["ultima_copia_arquivos_erro"].endswith(": 1 arquivo(s) de notas estão no backup e sumiram "
                                                                 "dos dados")


def test_passada_leva_os_arquivos_para_fora(tmp_path):
    origem, gravados = _dados_com_arquivos(tmp_path)
    fora = tmp_path / "externo"
    backup.rodada_arquivos(origem, tmp_path / "dados" / "backups", fora)
    for rel, conteudo in gravados.items():
        assert (fora / "arquivos" / rel).read_bytes() == conteudo, rel
    assert backup.ESTADO["ultima_copia_externa_arquivos"]
    assert backup.ESTADO["ultima_copia_externa_arquivos_erro"] is None
    assert backup._arquivos_desde is None  # terminou: nao conta como em andamento


def test_copia_de_arquivo_corrompida_e_recusada(tmp_path, monkeypatch):
    # o nome e' o sha256: a copia so' conta se o que chegou ao destino bate com ele
    origem, _ = _dados_com_arquivos(tmp_path)
    destino = tmp_path / "dados" / "backups"
    monkeypatch.setattr(backup.shutil, "copyfileobj", lambda a, b, n=0: b.write(b"truncado"))
    _rodar(origem, destino)
    assert "cópia conferida diferente da original" in backup.ESTADO["ultima_copia_arquivos_erro"]
    assert backup.ESTADO["ultimo_snapshot_erro"] is None  # o banco foi salvo mesmo assim
    assert _arquivos_no(destino / "arquivos") == []


def test_arquivo_com_defeito_nao_impede_os_outros(tmp_path):
    # um PDF cujo conteudo nao bate com o sha256 do nome nao vai para o backup (copiaria o
    # defeito), mas tambem nao pode deixar sem copia os que vem depois dele
    origem, gravados = _dados_com_arquivos(tmp_path)
    estragado = tmp_path / "dados" / "notas" / f"{'0' * 64}.pdf"
    estragado.write_bytes(b"conteudo trocado")
    destino = tmp_path / "dados" / "backups"
    _rodar(origem, destino)
    erro = backup.ESTADO["ultima_copia_arquivos_erro"]
    # #441: o health e a tela mostram a pasta, a quantidade e o motivo; o nome (hash) fica no log
    assert erro and erro.endswith("1 arquivo(s) sem cópia: notas 1 (conteúdo não confere com o nome)"), erro
    assert estragado.stem not in erro
    assert not (destino / "arquivos" / "notas" / estragado.name).exists()
    for rel in gravados:
        assert (destino / "arquivos" / rel).exists(), rel


def test_arquivos_copiam_mesmo_com_snapshot_falhando(tmp_path, monkeypatch):
    origem, gravados = _dados_com_arquivos(tmp_path)
    destino = tmp_path / "dados" / "backups"
    monkeypatch.setattr(backup, "criar_snapshot",
                        lambda o, d: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")))
    _rodar(origem, destino)
    assert "banco ocupado" in backup.ESTADO["ultimo_snapshot_erro"]
    for rel in gravados:
        assert (destino / "arquivos" / rel).exists(), rel


def test_rodada_do_banco_nao_toca_os_arquivos(tmp_path, monkeypatch):
    # S1: a thread do banco so' faz snapshot (e a copia externa do banco); arquivos sao do worker
    origem, _ = _dados_com_arquivos(tmp_path)
    fora = tmp_path / "externo"
    monkeypatch.setattr(backup, "copiar_arquivos", lambda *a, **k: pytest.fail("copiou na thread do banco"))
    backup.rodada(origem, tmp_path / "dados" / "backups", fora)
    assert len(list(fora.glob("dashboard-*.db"))) == 1      # o banco saiu


def test_falha_dos_arquivos_la_fora_fica_registrada_sem_caminho(tmp_path, monkeypatch):
    # S5: o erro que vai ao health e a' tela nao leva caminho absoluto do servidor
    origem, _ = _dados_com_arquivos(tmp_path)
    fora = tmp_path / "externo"
    real = backup.copiar_arquivos

    def negado_fora(o, d, conferir=False, **kw):
        if fora in d.parents:
            raise PermissionError(13, "Acesso negado", str(d))
        return real(o, d, conferir, **kw)

    monkeypatch.setattr(backup, "copiar_arquivos", negado_fora)
    backup.rodada_arquivos(origem, tmp_path / "dados" / "backups", fora)
    erro = backup.ESTADO["ultima_copia_externa_arquivos_erro"]
    assert erro.endswith(": acesso negado")
    assert str(tmp_path) not in erro
    assert backup.ESTADO["ultima_copia_arquivos_erro"] is None  # a local passou
    assert backup._arquivos_desde is None


def test_motivo_de_arquivo_nao_leva_caminho(tmp_path, monkeypatch):
    origem, _ = _dados_com_arquivos(tmp_path)
    destino = tmp_path / "dados" / "backups"

    def disco_cheio(a, b, n=0):
        raise OSError(28, "No space left on device", str(tmp_path / "x"))

    monkeypatch.setattr(backup.shutil, "copyfileobj", disco_cheio)
    backup.rodada_arquivos(origem, destino, None)
    erro = backup.ESTADO["ultima_copia_arquivos_erro"]
    assert "disco cheio" in erro and str(tmp_path) not in erro


def test_health_acusa_passada_que_nao_termina(monkeypatch):
    # S1: calculado na leitura do health, nao pelo worker (que e' quem pode estar travado)
    monkeypatch.setattr(backup, "_arquivos_fase", "externa")
    monkeypatch.setattr(backup, "_arquivos_desde", time.monotonic() - 3 * 3600)
    e = backup.estado()
    assert e["ultima_copia_externa_arquivos_erro"] == "a cópia está rodando há 3 horas sem terminar"
    assert e["ultima_copia_arquivos_erro"] is None
    monkeypatch.setattr(backup, "_arquivos_fase", "local")
    assert "rodando há 3 horas" in backup.estado()["ultima_copia_arquivos_erro"]
    monkeypatch.setattr(backup, "_arquivos_desde", time.monotonic() - 60)
    assert backup.estado()["ultima_copia_arquivos_erro"] is None  # dentro do prazo: nada


class _ThreadMorta:
    def is_alive(self): return False


def test_worker_morto_aparece_e_e_reiniciado(tmp_path, monkeypatch):
    # S6: a referencia do worker fica guardada; morto, o health acusa e a thread do banco o sobe de novo
    monkeypatch.setattr(backup, "_thread_arquivos", _ThreadMorta())
    assert "parou" in backup.estado()["ultima_copia_arquivos_erro"]
    subidos = []
    monkeypatch.setattr(backup, "_iniciar_worker_arquivos", lambda *a: subidos.append(a) or True)
    backup._supervisionar_arquivos(tmp_path / "d.db", tmp_path / "b", None)
    assert len(subidos) == 1
    assert "foi reiniciada" in backup.ESTADO["ultima_copia_arquivos_erro"]


def test_agendar_sobe_worker_dos_arquivos_separado(tmp_path, monkeypatch):
    nomes = []

    class ThreadFalsa:
        def __init__(self, target, daemon, name, args=()): nomes.append(name)
        def start(self): pass
        def is_alive(self): return True

    monkeypatch.setattr(backup.threading, "Thread", ThreadFalsa)
    backup.agendar_backup_horario(tmp_path / "d.db", tmp_path / "b", tmp_path / "externo")
    assert nomes == ["backup-arquivos", "backup"]
    # 2a passada (gate Sol S3): agendar de novo no mesmo processo nao sobe um segundo worker
    backup.agendar_backup_horario(tmp_path / "d.db", tmp_path / "b", tmp_path / "externo")
    assert nomes.count("backup-arquivos") == 1


def test_worker_vivo_nao_e_substituido(tmp_path, monkeypatch):
    vivo = type("Viva", (), {"is_alive": lambda self: True})()
    monkeypatch.setattr(backup, "_thread_arquivos", vivo)
    assert backup._iniciar_worker_arquivos(tmp_path / "d.db", tmp_path / "b", None) is False
    assert backup._thread_arquivos is vivo


def test_conferencia_que_falha_nao_rele_o_acervo_toda_hora(tmp_path, monkeypatch):
    # 2a passada (gate Sol S1): vale a tentativa; so' o arquivo que falhou e' conferido de novo
    origem, gravados = _dados_com_arquivos(tmp_path)
    destino = tmp_path / "dados" / "backups"
    ruim = next(iter(gravados))
    chamadas, falhou = [], []
    real = backup._copiar_um

    def espia(arquivo, alvo, conferir=False):
        rel = f"{arquivo.parent.name}/{arquivo.name}"
        chamadas.append((rel, conferir))
        if rel == ruim and not falhou:
            falhou.append(rel)
            raise PermissionError(13, "Acesso negado", str(alvo))
        return real(arquivo, alvo, conferir)

    monkeypatch.setattr(backup, "_copiar_um", espia)
    backup.rodada_arquivos(origem, destino, None)          # conferencia do dia, uma falha
    assert all(c for _, c in chamadas)
    assert "acesso negado" in backup.ESTADO["ultima_copia_arquivos_erro"]
    chamadas.clear()
    backup.rodada_arquivos(origem, destino, None)          # hora seguinte
    # a assinatura vai ao backup por `_copiar_assinatura` (versao pelo sha256, #479), nao por `_copiar_um`
    assert dict(chamadas) == {rel: rel == ruim for rel in gravados if not rel.startswith("assinaturas/")}
    assert backup.ESTADO["ultima_copia_arquivos_erro"] is None
    assert backup._pendentes[str(destino / "arquivos")] == set()


def test_erros_do_banco_no_estado_sem_caminho(tmp_path, monkeypatch):
    # 2a passada (gate Sol S2): snapshot e copia externa do banco tambem passam por _motivo
    origem = _origem(tmp_path)
    caminho = str(tmp_path / "segredo")
    monkeypatch.setattr(backup, "criar_snapshot",
                        lambda o, d: (_ for _ in ()).throw(sqlite3.OperationalError(f"unable to open {caminho}")))
    backup.rodada(origem, tmp_path / "backups", None)
    assert backup.ESTADO["ultimo_snapshot_erro"].endswith(": erro do banco (detalhes no log do servidor)")
    monkeypatch.undo()
    monkeypatch.setattr(backup, "copiar_externo",
                        lambda s, p: (_ for _ in ()).throw(PermissionError(13, "Access is denied", caminho)))
    backup.rodada(origem, tmp_path / "backups", tmp_path / "externo")
    erro = backup.ESTADO["ultima_copia_externa_erro"]
    assert erro.endswith(": acesso negado") and caminho not in erro


def test_destino_estragado_do_mesmo_tamanho_e_trocado_na_conferencia(tmp_path):
    # S2: nome e tamanho iguais nao bastam; uma vez por dia o destino e' relido pelo sha256
    origem, gravados = _dados_com_arquivos(tmp_path)
    destino = tmp_path / "dados" / "backups"
    backup.rodada_arquivos(origem, destino, None)          # 1a passada: confere (nunca conferiu)
    rel = next(iter(gravados))
    copia = destino / "arquivos" / rel
    copia.write_bytes(b"x" * len(gravados[rel]))           # estraga sem mudar o tamanho
    backup.rodada_arquivos(origem, destino, None)          # dentro do dia: so' nome e tamanho
    assert copia.read_bytes() != gravados[rel]
    backup._conferido_em[str(destino / "arquivos")] -= backup.CONFERIR_DESTINO_SEG + 1
    backup.rodada_arquivos(origem, destino, None)          # passou um dia: rele e troca
    assert copia.read_bytes() == gravados[rel]
    assert backup.ESTADO["ultima_copia_arquivos_erro"] is None


def test_temporarios_de_copias_simultaneas_nao_colidem(tmp_path, monkeypatch):
    # S3: PID, thread e sufixo aleatorio no nome do parcial
    origem, gravados = _dados_com_arquivos(tmp_path)
    vistos = []
    real = backup.shutil.copyfileobj

    def espia(a, b, n=0):
        vistos.append(Path(b.name).name)
        return real(a, b, n)

    monkeypatch.setattr(backup.shutil, "copyfileobj", espia)
    rel = next(iter(gravados))
    for alvo in ("a", "b"):
        (tmp_path / alvo).mkdir()
        backup._copiar_um(origem.parent / rel, tmp_path / alvo / Path(rel).name)
    assert len(set(vistos)) == 2
    assert all(backup._PARCIAL_NOSSO.search(v) for v in vistos)


def test_parcial_abandonado_de_copia_e_limpo(tmp_path):
    origem, _ = _dados_com_arquivos(tmp_path)
    notas = tmp_path / "dados" / "backups" / "arquivos" / "notas"; notas.mkdir(parents=True)
    velho = notas / f"{'a' * 64}.pdf.4242-77-0123abcd.tmp"; velho.write_bytes(b"parcial")
    envelhecer(velho, 7200)
    recente = notas / f"{'b' * 64}.pdf.4343-77-0123abcd.tmp"; recente.write_bytes(b"em andamento")
    backup.rodada_arquivos(origem, tmp_path / "dados" / "backups", None)
    assert not velho.exists()
    assert recente.exists()


@pytest.mark.skipif(os.name != "nt", reason="trava de arquivo aberto e' do Windows (a producao)")
def test_parcial_velho_mas_aberto_nao_e_apagado(tmp_path):
    # S4: copia ativa ha mais de 1 h segura o parcial aberto; a limpeza nao o apaga
    notas = tmp_path / "notas"; notas.mkdir()
    vivo = notas / f"{'c' * 64}.pdf.4444-77-0123abcd.tmp"
    with open(vivo, "wb") as f:
        f.write(b"copiando")
        f.flush()
        envelhecer(vivo, 7200)
        backup._limpar_parciais_abandonados(notas, time.time())
        assert vivo.exists()


# --- saude do backup na tela de Administracao (issue #31) ----------------------

def _agora():
    import datetime
    return datetime.datetime(2026, 10, 13, 12, 0, tzinfo=datetime.timezone.utc)

def _snapshot_com_idade(pasta, nome, segundos, tamanho=10):
    pasta.mkdir(exist_ok=True)
    arq = pasta / nome
    arq.write_bytes(b"x" * tamanho)
    instante = _agora().timestamp() - segundos
    os.utime(arq, (instante, instante))
    return arq

def test_situacao_conta_guardados_e_le_o_ultimo_do_disco(tmp_path):
    # o ultimo backup vem do disco, nao da memoria: sobrevive ao servidor reiniciar
    local = tmp_path / "backups"
    _snapshot_com_idade(local, "dashboard-20261013-060000.db", 3 * 3600, tamanho=5)
    _snapshot_com_idade(local, "dashboard-20261013-070000.db", 1800, tamanho=2048)
    # nome que ordena depois mas foi gravado antes: o ultimo e' o mais recente pelo disco, nao pelo nome
    _snapshot_com_idade(local, "dashboard-20261013-090000.db", 4 * 3600, tamanho=7)
    (local / "dashboard-20261013-080000-pid9.db.tmp").write_bytes(b"parcial")  # nao conta
    s = backup.situacao(local, True, _agora())
    assert s["guardados"] == 3 and s["copia_externa_configurada"] is True
    assert s["tamanho_bytes"] == 2048
    assert s["ultimo_backup"] == "2026-10-13T07:30:00-04:00"  # hora de Cuiaba
    assert s["atrasado"] is False

def test_situacao_atrasado_acima_de_2h(tmp_path):
    local = tmp_path / "backups"
    arq = _snapshot_com_idade(local, "dashboard-20261013-060000.db", 2 * 3600 - 60)
    assert backup.situacao(local, False, _agora())["atrasado"] is False
    instante = _agora().timestamp() - (2 * 3600 + 60)
    os.utime(arq, (instante, instante))
    s = backup.situacao(local, False, _agora())
    assert s["atrasado"] is True and s["copia_externa_configurada"] is False

def test_situacao_sem_backup_e_atrasado(tmp_path):
    s = backup.situacao(tmp_path / "nao-existe", False, _agora())
    assert s["guardados"] == 0 and s["ultimo_backup"] is None and s["tamanho_bytes"] is None
    assert s["atrasado"] is True

def test_situacao_pasta_ilegivel_nao_derruba_e_fica_atrasado(tmp_path, monkeypatch):
    local = tmp_path / "backups"
    _snapshot_com_idade(local, "dashboard-20261013-070000.db", 1800)
    def negado(self, padrao):
        raise PermissionError("Acesso negado")
    monkeypatch.setattr(type(local), "glob", negado)
    s = backup.situacao(local, False, _agora())
    assert s["guardados"] == 0 and s["atrasado"] is True

def test_situacao_pre_migracao_recente_nao_esconde_o_horario_parado(tmp_path):
    # gate Sol S1: o dashboard-PRE-*.db do deploy casa com PADRAO, mas nao e' a rotina horaria
    local = tmp_path / "backups"
    _snapshot_com_idade(local, "dashboard-20261013-050000.db", 5 * 3600)
    _snapshot_com_idade(local, "dashboard-PRE-abc1234-20261013-115500.db", 300)
    s = backup.situacao(local, False, _agora())
    assert s["atrasado"] is True and s["guardados"] == 1
    assert s["ultimo_backup"] == "2026-10-13T03:00:00-04:00"

def test_situacao_traz_o_ultimo_erro_sem_caminho_nem_maquina(tmp_path, monkeypatch):
    # gate Sol S3: a excecao crua (caminho, compartilhamento, maquina) fica no log; a tela recebe frase fixa
    monkeypatch.setitem(backup.ESTADO, "ultimo_snapshot_erro",
                        r"2026-10-13T08:00:00-04:00: [Errno 28] No space left: 'C:\\dados\\backups\\x.db'")
    monkeypatch.setitem(backup.ESTADO, "ultima_copia_externa_erro",
                        r"2026-10-13T03:00:00-04:00: [WinError 53] \\\\servidor\\backup")
    s = backup.situacao(tmp_path / "backups", False, _agora())
    assert s["ultimo_snapshot_erro_em"] == "2026-10-13T08:00:00-04:00"
    assert s["ultimo_snapshot_erro"] == "não foi possível gravar o snapshot; o detalhe está no log do servidor"
    assert s["ultima_copia_externa_erro_em"] == "2026-10-13T03:00:00-04:00"
    assert "cópia externa" in s["ultima_copia_externa_erro"]
    assert not any("\\" in str(v) or "Errno" in str(v) for v in s.values())


def test_situacao_traz_a_copia_dos_arquivos(tmp_path, monkeypatch):
    # issue #55 sobre a #31: a tela de Administracao mostra tambem a copia dos arquivos (local e externa),
    # com a frase ja' limpa que a copia grava e o "sem terminar" calculado na leitura
    monkeypatch.setitem(backup.ESTADO, "ultima_copia_arquivos", "2026-10-13T08:00:00-04:00")
    monkeypatch.setitem(backup.ESTADO, "ultima_copia_arquivos_erro",
                        "2026-10-13T09:00:00-04:00: 1 arquivo(s) sem cópia: notas/x.pdf (acesso negado)")
    monkeypatch.setattr(backup, "_arquivos_fase", "externa")
    monkeypatch.setattr(backup, "_arquivos_desde", time.monotonic() - 3 * 3600)
    s = backup.situacao(tmp_path / "backups", True, _agora())
    assert s["ultima_copia_arquivos"] == "2026-10-13T08:00:00-04:00"
    assert s["ultima_copia_arquivos_erro_em"] == "2026-10-13T09:00:00-04:00"
    assert s["ultima_copia_arquivos_erro"] == "1 arquivo(s) sem cópia: notas/x.pdf (acesso negado)"
    assert s["ultima_copia_externa_arquivos_erro_em"] is None
    assert s["ultima_copia_externa_arquivos_erro"] == "a cópia está rodando há 3 horas sem terminar"
