"""Sentinela do log de seguranca do Windows (issue #423): eventos escritos a mao em tests/fixtures/sentinela/, com
contas e maquina ficticias. O Windows e' simulado em `_executar` (wevtutil, auditpol e a leitura da SACL)."""
import datetime
import json
import pathlib
import re

import pytest

from app import db, sentinela, seguranca

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "sentinela"
CONTA = "SRVFICT\\visitante.teste"
AUDITPOL_LIGADO = ("Máquina,Alvo da Política,Subcategoria,GUID da Subcategoria,Inclusão de Configuração,"
                   "Exclusão de Configuração\nSRVFICT,Sistema,Sistema de Arquivos,{guid},Êxito,\n")
AUDITPOL_DESLIGADO = AUDITPOL_LIGADO.replace("Êxito", "Sem auditoria")
SACL_OK = "S-1-5-4|Success|2032127\nS-1-5-2|Success|2032127\n"


class Windows:
    """O que a sentinela enxerga da maquina: o log (linhas de XML), a saida do auditpol e a SACL de cada pasta."""

    def __init__(self):
        self.log: list[str] = []
        self.auditoria = {sentinela.GUID_ARQUIVOS: True, sentinela.GUID_POLITICA: True}
        self.sacl = {p: SACL_OK for p in sentinela.PASTAS}
        self.wevtutil_falha = False
        self.consultas: list[str] = []

    def adicionar(self, nome: str, raiz: pathlib.Path):
        xml = (FIXTURES / nome).read_text(encoding="utf-8").replace("{RAIZ}", str(raiz).replace("/", "\\"))
        self.log += [linha for linha in xml.splitlines() if linha.strip()]

    def _registro(self, linha: str) -> int:
        return int(re.search(r"<EventRecordID>(\d+)<", linha).group(1))

    def __call__(self, args):
        if args[0] == "wevtutil":
            if self.wevtutil_falha:
                return 5, ""
            if "/c:1" in args:
                mais_novo = max(self.log, key=self._registro, default="")
                return 0, mais_novo
            consulta = next(a for a in args if a.startswith("/q:"))
            self.consultas.append(consulta)
            maior_que = int(re.search(r"EventRecordID>(\d+)", consulta).group(1))
            return 0, "\n".join(sorted((x for x in self.log if self._registro(x) > maior_que), key=self._registro))
        if args[0] == "auditpol":
            guid = args[2].split(":", 1)[1]
            texto = AUDITPOL_LIGADO if self.auditoria[guid] else AUDITPOL_DESLIGADO
            return 0, texto.format(guid=guid)
        if args[0] == "powershell":
            pasta = re.search(r"-LiteralPath '([^']+)'", args[-1]).group(1).replace("\\", "/").rsplit("/", 1)[-1]
            return 0, self.sacl[pasta]
        raise AssertionError(args)


@pytest.fixture
def maquina(tmp_path, monkeypatch):
    raiz = tmp_path / "raiz"
    for p in ("dados", "segredos", "cadastro"):
        (raiz / p).mkdir(parents=True)
    monkeypatch.setenv("DASH_DB_PATH", str(raiz / "dados" / "test.db"))
    win = Windows()
    win.raiz = raiz
    monkeypatch.setattr(sentinela, "_executar", win)
    return win


@pytest.fixture
def conn(maquina):
    c = db.get_conn()
    db.migrate(c)
    yield c
    c.close()


def _lista(maquina, contas=(), processos=()):
    (maquina.raiz / "segredos" / "sentinela.json").write_text(
        json.dumps({"contas": list(contas), "processos": list(processos)}), encoding="utf-8")


def _rodar(maquina, conn, *fixtures):
    """Uma rodada com o log acrescido das fixtures; devolve os achados gravados nela."""
    antes = conn.execute("SELECT COALESCE(MAX(id), 0) FROM audit_log").fetchone()[0]
    for f in fixtures:
        maquina.adicionar(f, maquina.raiz)
    sentinela.rodada(conn)
    return [json.loads(r["depois"]) for r in conn.execute(
        "SELECT depois FROM audit_log WHERE acao='seguranca.sentinela' AND id > ? ORDER BY id", (antes,))]


def _com_ponto_de_partida(maquina, conn):
    """A primeira rodada so' marca o ponto de partida do log e confere a maquina (tudo em ordem: sem achado)."""
    assert _rodar(maquina, conn) == []


def test_4663_de_fora_vira_um_item_por_conta_processo_pasta_e_hora(maquina, conn):
    _com_ponto_de_partida(maquina, conn)
    a = _rodar(maquina, conn, "4663_segredos_externo.xml")
    assert len(a) == 1       # tres acessos a dois arquivos em segredos + um fora das pastas
    assert a[0]["mensagem"] == f"Leitura de segredos por explorer.exe ({CONTA}), 2 arquivos"
    assert (a[0]["nivel"], a[0]["conta"], a[0]["processo"], a[0]["pasta"], a[0]["quantidade"]) == (
        "critico", CONTA, "explorer.exe", "segredos", 2)
    assert a[0]["evento"] == 4663 and a[0]["hora"].startswith("2026-11-05T14:03")


def test_4663_de_conta_e_processo_da_lista_nao_vira_item(maquina, conn):
    _lista(maquina, contas=["SRVFICT\\operador.fict"], processos=["explorer.exe"])
    _com_ponto_de_partida(maquina, conn)
    assert _rodar(maquina, conn, "4663_conta_e_processo_da_lista.xml") == []


def test_4663_de_conta_da_lista_com_processo_fora_da_lista_vira_item(maquina, conn):
    _lista(maquina, contas=["operador.fict"], processos=["robocopy.exe"])
    _com_ponto_de_partida(maquina, conn)
    a = _rodar(maquina, conn, "4663_conta_e_processo_da_lista.xml")
    assert [x["processo"] for x in a] == ["explorer.exe"]


def test_4663_dados_e_segredos_sao_criticos_e_cadastro_e_acao(maquina, conn):
    _com_ponto_de_partida(maquina, conn)
    a = _rodar(maquina, conn, "4663_dados_pela_rede.xml")
    assert {(x["pasta"], x["nivel"], x["processo"]) for x in a} == {
        ("dados", "critico", "System"), ("cadastro", "acao", "System")}


def test_4670_permissao_trocada_e_critica(maquina, conn):
    _com_ponto_de_partida(maquina, conn)
    a = _rodar(maquina, conn, "4670_permissao.xml")
    assert [(x["evento"], x["nivel"], x["pasta"]) for x in a] == [(4670, "critico", "segredos")]


def test_4672_um_item_por_conta_por_dia_ignorando_lista_e_contas_de_sistema(maquina, conn):
    _lista(maquina, contas=["operador.fict"])
    _com_ponto_de_partida(maquina, conn)
    a = _rodar(maquina, conn, "4672_logon.xml")
    assert [(x["evento"], x["nivel"], x["conta"]) for x in a] == [(4672, "atencao", CONTA)]


def test_4672_da_mesma_conta_no_mesmo_dia_em_outra_rodada_nao_repete(maquina, conn):
    _lista(maquina, contas=["operador.fict"])
    _com_ponto_de_partida(maquina, conn)
    maquina.adicionar("4672_logon.xml", maquina.raiz)
    completo, maquina.log = maquina.log, [x for x in maquina.log if "<EventRecordID>1040<" in x]
    sentinela.rodada(conn)
    maquina.log = completo
    sentinela.rodada(conn)
    n = conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='seguranca.sentinela'").fetchone()[0]
    assert n == 1


def test_tarefa_da_dashboard_mexida_e_critica_e_de_outro_sistema_nao(maquina, conn):
    _com_ponto_de_partida(maquina, conn)
    a = _rodar(maquina, conn, "tarefas.xml")
    assert [x["evento"] for x in a] == [4698, 4699, 4700, 4701, 4702]
    assert {x["nivel"] for x in a} == {"critico"}
    assert a[3]["mensagem"] == f"Tarefa DashboardLotufo-Watchdog desabilitada por {CONTA}"


def test_log_limpo_e_politica_de_auditoria_alterada_sao_criticos(maquina, conn):
    _com_ponto_de_partida(maquina, conn)
    a = _rodar(maquina, conn, "auditoria.xml")
    assert [(x["evento"], x["nivel"], x["conta"]) for x in a] == [(1102, "critico", CONTA), (4719, "critico", CONTA)]


def test_retoma_pelo_ultimo_registro_lido(maquina, conn):
    maquina.adicionar("4670_permissao.xml", maquina.raiz)        # ja estava no log antes da sentinela: nao conta
    _com_ponto_de_partida(maquina, conn)
    estado = json.loads((maquina.raiz / "dados" / "sentinela.json").read_text(encoding="utf-8"))
    assert estado["ultimo_registro"] == 1030
    assert len(_rodar(maquina, conn, "auditoria.xml")) == 2
    assert _rodar(maquina, conn) == []
    assert maquina.consultas[-1].count("EventRecordID>1071") == 0     # a ultima rodada nem leu: nada novo
    assert len(maquina.consultas) == 1
    assert "EventRecordID>1030" in maquina.consultas[0]


def test_log_limpo_volta_a_ler_do_comeco(maquina, conn):
    maquina.adicionar("auditoria.xml", maquina.raiz)
    _com_ponto_de_partida(maquina, conn)
    maquina.log = []
    maquina.adicionar("4670_permissao.xml", maquina.raiz)         # o log reiniciou: registro 1030 < 1071 guardado
    sentinela.rodada(conn)
    n = conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='seguranca.sentinela'").fetchone()[0]
    assert n == 1


def test_auditoria_desligada_vira_item_uma_vez_ate_voltar(maquina, conn):
    _com_ponto_de_partida(maquina, conn)
    maquina.auditoria[sentinela.GUID_ARQUIVOS] = False
    a = _rodar(maquina, conn)
    assert [(x["nivel"], x["mensagem"]) for x in a] == [("critico", "Auditoria de arquivos desligada")]
    assert _rodar(maquina, conn) == []
    maquina.auditoria[sentinela.GUID_ARQUIVOS] = True
    assert _rodar(maquina, conn) == []
    maquina.auditoria[sentinela.GUID_ARQUIVOS] = False
    assert len(_rodar(maquina, conn)) == 1


def test_desligar_a_auditoria_gera_o_4719_e_na_rodada_seguinte_o_item_de_auditoria_desligada(maquina, conn):
    _com_ponto_de_partida(maquina, conn)
    maquina.auditoria[sentinela.GUID_ARQUIVOS] = False
    a = _rodar(maquina, conn, "auditoria.xml")
    assert {x["evento"] for x in a} == {1102, 4719, "auditoria-arquivos"}


def test_sacl_ausente_vira_item_critico(maquina, conn):
    _com_ponto_de_partida(maquina, conn)
    maquina.sacl["segredos"] = "S-1-5-4|Success|2032127\n"          # falta REDE
    maquina.sacl["dados"] = ""
    a = _rodar(maquina, conn)
    assert sorted(x["mensagem"] for x in a) == ["SACL ausente em dados", "SACL ausente em segredos"]
    assert {x["nivel"] for x in a} == {"critico"}


def test_pasta_inexistente_nao_acusa_sacl(maquina, conn):
    (maquina.raiz / "cadastro").rmdir()
    maquina.sacl.pop("cadastro")
    assert _rodar(maquina, conn) == []


def test_falha_ao_ler_o_log_vira_item_de_atencao_uma_vez(maquina, conn):
    _com_ponto_de_partida(maquina, conn)
    maquina.wevtutil_falha = True
    a = _rodar(maquina, conn)
    assert [(x["nivel"], x["mensagem"]) for x in a] == [("atencao", "Sentinela não conseguiu ler o log de segurança")]
    assert _rodar(maquina, conn) == []


def test_achados_entram_no_bloco_seguranca_com_leituras_da_mesma_hora_somadas(maquina, conn):
    _com_ponto_de_partida(maquina, conn)
    _rodar(maquina, conn, "4663_segredos_externo.xml")
    maquina.log.append(maquina.log[0].replace("<EventRecordID>1001<", "<EventRecordID>1005<")
                       .replace("instalacao.json", "terceiro.json"))
    sentinela.rodada(conn)
    # a hora de verdade: o achado e' gravado com o relogio do sistema, e uma hora fixa (06/11/2026 12:00 UTC) passou a
    # deixar o achado "no futuro", fora do bloco, depois desse instante
    agora = datetime.datetime.now(datetime.timezone.utc)
    its = [i for i in seguranca.itens(conn, agora) if i["mensagem"].startswith("Leitura")]
    assert [i["mensagem"] for i in its] == [f"Leitura de segredos por explorer.exe ({CONTA}), 3 arquivos"]
    assert its[0]["nivel"] == "critico"


def test_achado_da_sentinela_sai_do_bloco_depois_de_7_dias(maquina, conn):
    _com_ponto_de_partida(maquina, conn)
    _rodar(maquina, conn, "4670_permissao.xml")
    agora = tempo_agora = datetime.datetime.now(datetime.timezone.utc)
    assert len(seguranca.itens(conn, agora)) == 1
    assert seguranca.itens(conn, tempo_agora + datetime.timedelta(days=8)) == []


def test_fora_do_windows_ou_em_dev_nao_roda(monkeypatch):
    monkeypatch.setattr(sentinela.sys, "platform", "darwin")
    monkeypatch.delenv("DASH_DEV", raising=False)
    assert sentinela.agendar() is None
    assert sentinela.situacao() == {"roda": False, "mensagem": "Sentinela não roda neste ambiente"}
    monkeypatch.setattr(sentinela.sys, "platform", "win32")
    monkeypatch.setenv("DASH_DEV", "1")
    assert sentinela.agendar() is None
    assert sentinela.situacao()["roda"] is False


def test_no_windows_fora_de_dev_roda(monkeypatch):
    monkeypatch.setattr(sentinela.sys, "platform", "win32")
    monkeypatch.delenv("DASH_DEV", raising=False)
    assert sentinela.situacao() == {"roda": True, "mensagem": None}


def test_saude_diz_que_a_sentinela_nao_roda_neste_ambiente(client_admin):
    r = client_admin.get("/api/admin/saude")
    assert r.status_code == 200
    assert r.json()["sentinela"] == {"roda": False, "mensagem": "Sentinela não roda neste ambiente"}


def test_estado_apagado_depois_de_ja_ter_rodado_acusa_e_segue_do_ponto_gravado_no_banco(maquina, conn):
    _com_ponto_de_partida(maquina, conn)
    _rodar(maquina, conn, "4670_permissao.xml")
    (maquina.raiz / "dados" / "sentinela.json").unlink()
    a = _rodar(maquina, conn, "tarefas.xml")
    assert a[0]["mensagem"].startswith("Estado da sentinela apagado, ilegível ou alterado")
    assert a[0]["nivel"] == "critico"
    assert any(x["evento"] == 4698 for x in a)       # nada foi pulado
    assert "EventRecordID>1030" in maquina.consultas[-1]
    assert _rodar(maquina, conn) == []               # copia refeita: volta ao normal


def test_estado_editado_para_frente_nao_esconde_a_leitura(maquina, conn):
    _com_ponto_de_partida(maquina, conn)
    arquivo = maquina.raiz / "dados" / "sentinela.json"
    estado = json.loads(arquivo.read_text(encoding="utf-8"))
    estado["ultimo_registro"] = 999999
    arquivo.write_text(json.dumps(estado), encoding="utf-8")
    a = _rodar(maquina, conn, "4663_segredos_externo.xml")
    assert a[0]["evento"] == "estado-perdido" and any(x["evento"] == 4663 for x in a)


def test_primeira_instalacao_sem_conseguir_ler_o_log_nao_acusa_estado_perdido(maquina, conn):
    maquina.wevtutil_falha = True
    assert [x["evento"] for x in _rodar(maquina, conn)] == ["leitura-log"]
    maquina.wevtutil_falha = False
    assert _rodar(maquina, conn) == []


def test_estado_perdido_com_leitura_falhando_acusa_uma_vez_so(maquina, conn, monkeypatch):
    _com_ponto_de_partida(maquina, conn)
    _rodar(maquina, conn, "4670_permissao.xml")
    (maquina.raiz / "dados" / "sentinela.json").unlink()
    maquina.wevtutil_falha = True
    n = [sum(1 for x in _rodar(maquina, conn) if x["evento"] == "estado-perdido") for _ in range(3)]
    assert n == [1, 0, 0]


def test_sacl_sem_o_direito_de_apagar_conta_como_ausente(maquina, conn):
    _com_ponto_de_partida(maquina, conn)
    maquina.sacl["dados"] = "S-1-5-4|Success|131209\nS-1-5-2|Success|131209\n"      # leitura e gravacao, sem Delete
    assert [x["mensagem"] for x in _rodar(maquina, conn)] == ["SACL ausente em dados"]


def test_estado_corrompido_conta_como_apagado(maquina, conn):
    _com_ponto_de_partida(maquina, conn)
    _rodar(maquina, conn, "4670_permissao.xml")
    (maquina.raiz / "dados" / "sentinela.json").write_text("{nao e json", encoding="utf-8")
    a = _rodar(maquina, conn)
    assert a[0]["evento"] == "estado-perdido"


def test_falha_que_continua_e_regravada_uma_vez_por_dia(maquina, conn, monkeypatch):
    _com_ponto_de_partida(maquina, conn)
    maquina.auditoria[sentinela.GUID_ARQUIVOS] = False
    dia = [datetime.date(2026, 11, 5)]
    monkeypatch.setattr(sentinela.tempo, "hoje_local", lambda: dia[0])
    assert len(_rodar(maquina, conn)) == 1
    assert _rodar(maquina, conn) == []
    dia[0] = datetime.date(2026, 11, 6)
    assert len(_rodar(maquina, conn)) == 1
    assert _rodar(maquina, conn) == []


def test_verificacao_que_nao_roda_usa_nome_legivel(maquina, conn):
    _com_ponto_de_partida(maquina, conn)
    antigo = maquina.auditoria
    maquina.auditoria = {}          # KeyError no auditpol simulado
    msgs = sorted(x["mensagem"] for x in _rodar(maquina, conn))
    maquina.auditoria = antigo
    assert msgs == ["Sentinela não conseguiu conferir a auditoria da alteração da política",
                    "Sentinela não conseguiu conferir a auditoria de arquivos"]


# --- issue #456: ponto de leitura fora da auditoria e restauracao de backup ---------------------------------------

def _ponto(conn):
    r = conn.execute("SELECT ultimo_registro FROM sentinela_ponto WHERE id = 1").fetchone()
    return None if r is None else r[0]


def test_rodadas_sem_achado_nao_gravam_na_auditoria(maquina, conn):
    _lista(maquina, contas=["SRVFICT\\operador.fict"], processos=["explorer.exe"])
    antes = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    _com_ponto_de_partida(maquina, conn)
    for _ in range(3):
        assert _rodar(maquina, conn) == []
    assert _rodar(maquina, conn, "4663_conta_e_processo_da_lista.xml") == []     # o log andou, sem achado
    assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == antes
    assert _ponto(conn) == 1010


def test_ponto_de_leitura_fica_na_tabela_propria_e_e_lido_dela(maquina, conn):
    maquina.adicionar("4670_permissao.xml", maquina.raiz)
    _com_ponto_de_partida(maquina, conn)
    assert _ponto(conn) == 1030
    with db.mutacao(conn):
        conn.execute("UPDATE sentinela_ponto SET ultimo_registro = 1000 WHERE id = 1")
    maquina.adicionar("tarefas.xml", maquina.raiz)
    sentinela.rodada(conn)
    assert "EventRecordID>1000" in maquina.consultas[-1]
    assert _ponto(conn) == 1060


def test_migracao_parte_do_ultimo_ponto_gravado_na_auditoria(maquina, conn):
    from app import auditoria
    with db.mutacao(conn):
        conn.execute("DELETE FROM sentinela_ponto")
        for n in (1010, 1030):
            auditoria.registrar(conn, None, "seguranca.sentinela.ponto", "sentinela", None, None,
                                {"ultimo_registro": n})
    migracao = (db.MIGRATIONS_DIR / "063_sentinela_ponto.sql").read_text(encoding="utf-8")
    conn.executescript(migracao)
    assert _ponto(conn) == 1030
    conn.executescript(migracao)                                   # idempotente
    assert conn.execute("SELECT COUNT(*) FROM sentinela_ponto").fetchone()[0] == 1
    maquina.adicionar("tarefas.xml", maquina.raiz)
    sentinela.rodada(conn)
    assert "EventRecordID>1030" in maquina.consultas[-1]


def test_backup_restaurado_com_ponto_mais_velho_nao_acusa_estado_alterado(maquina, conn, tmp_path):
    import sqlite3
    maquina.adicionar("4670_permissao.xml", maquina.raiz)
    _com_ponto_de_partida(maquina, conn)
    copia_do_banco = sqlite3.connect(tmp_path / "snapshot.db")
    conn.backup(copia_do_banco)                                    # snapshot horario, com o ponto em 1030
    assert len(_rodar(maquina, conn, "tarefas.xml")) == 5          # sentinela.json passa a dizer 1060
    copia_do_banco.backup(conn)                                    # restauracao: o banco volta a 1030
    copia_do_banco.close()
    a = _rodar(maquina, conn)
    assert "estado-perdido" not in [x["evento"] for x in a]
    assert (a[0]["evento"], a[0]["nivel"], a[0]["mensagem"]) == (
        "banco-restaurado", "atencao", "Banco restaurado de uma cópia de segurança; log de segurança relido desde o registro 1030")
    assert [x["evento"] for x in a[1:]] == [4698, 4699, 4700, 4701, 4702]   # relidos: o banco restaurado nao os tinha
    assert "EventRecordID>1030" in maquina.consultas[-1]
    assert _rodar(maquina, conn) == []                              # uma vez so'


def test_backup_restaurado_regrava_logon_e_falha_que_o_snapshot_nao_tinha(maquina, conn, tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.setattr(sentinela.tempo, "hoje_local", lambda: datetime.date(2026, 11, 5))
    _lista(maquina, contas=["operador.fict"])
    maquina.adicionar("4670_permissao.xml", maquina.raiz)
    _com_ponto_de_partida(maquina, conn)
    copia_do_banco = sqlite3.connect(tmp_path / "snapshot.db")
    conn.backup(copia_do_banco)
    maquina.auditoria[sentinela.GUID_ARQUIVOS] = False
    depois = {x["evento"] for x in _rodar(maquina, conn, "4672_logon.xml")}
    assert depois == {4672, "auditoria-arquivos"}        # sentinela.json: conta avisada hoje e falha em aberto
    copia_do_banco.backup(conn)
    copia_do_banco.close()
    assert {x["evento"] for x in _rodar(maquina, conn)} == depois | {"banco-restaurado"}
    assert _rodar(maquina, conn) == []


def test_copia_alem_do_ultimo_evento_do_log_continua_acusada(maquina, conn):
    _com_ponto_de_partida(maquina, conn)
    arquivo = maquina.raiz / "dados" / "sentinela.json"
    estado = json.loads(arquivo.read_text(encoding="utf-8"))
    maquina.adicionar("4670_permissao.xml", maquina.raiz)
    estado["ultimo_registro"] = 1031                               # um alem do maior registro do log
    arquivo.write_text(json.dumps(estado), encoding="utf-8")
    a = _rodar(maquina, conn)
    assert a[0]["evento"] == "estado-perdido"
    assert any(x["evento"] == 4670 for x in a)                      # nada pulado


def test_rodada_que_perde_a_corrida_para_outra_nao_regride_o_ponto_nem_duplica(maquina, conn, monkeypatch):
    _com_ponto_de_partida(maquina, conn)
    outra = db.get_conn()                                          # outro processo, mesmo banco
    original = sentinela.verificacoes
    vez = [0]

    def no_meio(base):
        vez[0] += 1
        if vez[0] == 1:
            maquina.adicionar("auditoria.xml", maquina.raiz)       # 1070-1071: so' a outra rodada enxerga
            sentinela.rodada(outra)
        return original(base)

    monkeypatch.setattr(sentinela, "verificacoes", no_meio)
    a = _rodar(maquina, conn, "4670_permissao.xml")                # esta leu ate' 1030 e chegou depois
    outra.close()
    assert sorted(x["evento"] for x in a) == [1102, 4670, 4719]   # cada evento uma vez, gravado pela outra
    assert _ponto(conn) == 1071
    assert json.loads((maquina.raiz / "dados" / "sentinela.json").read_text(encoding="utf-8"))["ultimo_registro"] == 1071


def test_rodada_que_perde_a_corrida_sem_o_log_andar_nao_duplica_falha(maquina, conn, monkeypatch):
    # revisor, rodada 2: com o log parado o ponto nao muda, e a falha nova saia duas vezes
    _com_ponto_de_partida(maquina, conn)
    maquina.auditoria[sentinela.GUID_ARQUIVOS] = False      # falha nova, sem evento novo no log
    outra = db.get_conn()
    original = sentinela.verificacoes
    vez = [0]

    def no_meio(base):
        vez[0] += 1
        if vez[0] == 1:
            sentinela.rodada(outra)
        return original(base)

    monkeypatch.setattr(sentinela, "verificacoes", no_meio)
    a = _rodar(maquina, conn)
    outra.close()
    assert [x["evento"] for x in a] == ["auditoria-arquivos"]
    assert _rodar(maquina, conn) == []                     # a copia que ficou e' a da rodada que gravou


def test_ponto_da_sentinela_nao_muda_fora_da_aplicacao(maquina, conn):
    import sqlite3
    _com_ponto_de_partida(maquina, conn)
    crua = sqlite3.connect(db.db_path())                           # como o sqlite3.exe ou o DB Browser
    for sql in ("UPDATE sentinela_ponto SET ultimo_registro = 999999", "DELETE FROM sentinela_ponto",
                "INSERT OR REPLACE INTO sentinela_ponto (id, ultimo_registro) VALUES (1, 999999)"):
        with pytest.raises(sqlite3.OperationalError, match="dash_conexao_app"):
            crua.execute(sql)
    crua.close()


def test_gatilho_do_ponto_apagado_vira_alerta_de_seguranca(maquina, conn, monkeypatch):
    import sqlite3
    monkeypatch.setattr(seguranca, "_conferencia", [])
    assert seguranca.conferir(conn) == []
    crua = sqlite3.connect(db.db_path())
    crua.execute("DROP TRIGGER sentinela_ponto_protecao_update"); crua.commit(); crua.close()
    assert [i["mensagem"] for i in seguranca.conferir(conn)] == ["Proteção do ponto da sentinela removida"]


def _comando_do_rollback_456():
    """Os argumentos do comando do runbook (secao "Rollback para um commit anterior a' issue #456") depois de `-m`."""
    texto = (pathlib.Path(__file__).resolve().parents[2] / "docs" / "runbook.md").read_text(encoding="utf-8")
    achados = re.findall(r"`\.venv\\Scripts\\python -m (app\.cli sentinela antes-da-456 [^`]*)`", texto)
    assert len(achados) == 1
    return achados[0].split()


def _rodar_o_comando_do_runbook(capsys) -> str:
    from app import cli
    args = _comando_do_rollback_456()
    assert args[:3] == ["app.cli", "sentinela", "antes-da-456"]
    args = [str(db.db_path()) if a == r"C:\DashboardLotufo\dados\dashboard.db" else a for a in args[1:]]
    capsys.readouterr()
    assert cli.main(args) == 0
    return capsys.readouterr().out


def _codigo_de_antes_da_456(maquina):
    """A rodada da sentinela como ela era antes da #456 (copia em tests/fixtures/sentinela)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("sentinela_antes_456", FIXTURES / "sentinela_antes_456.py")
    antigo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(antigo)
    antigo._executar = maquina
    return antigo


def test_rollback_para_antes_da_456_com_o_comando_do_runbook_nao_acusa_nem_repete_e_o_deploy_seguinte_reimporta(
        maquina, conn, monkeypatch, capsys):
    """Issue #478 (revisor e gate Sol da PR #470): o comando do runbook grava o ponto da tabela na auditoria antes de
    apaga'-la; sem isso o codigo antigo partia do ponto de antes do deploy da #456, acusava estado alterado e repetia
    os achados."""
    from app import auditoria
    _com_ponto_de_partida(maquina, conn)
    with db.mutacao(conn):                                  # o ponto que o codigo antigo deixou antes do deploy da #456
        auditoria.registrar(conn, None, sentinela.ACAO_PONTO, "sentinela", None, None,
                            {"ultimo_registro": _ponto(conn)})
    assert len(_rodar(maquina, conn, "4663_segredos_externo.xml")) == 1     # o codigo da #456 avanca o ponto
    ponto = _ponto(conn)
    saida = _rodar_o_comando_do_runbook(capsys)
    assert saida.strip().splitlines()[-1] == "sentinela_ponto: 0 migracao 063: 0"
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE tbl_name = 'sentinela_ponto'").fetchone()[0] == 0
    assert auditoria.verificar_cadeia(conn)
    antigo = _codigo_de_antes_da_456(maquina)
    antes = conn.execute("SELECT MAX(id) FROM audit_log").fetchone()[0]
    consultas = len(maquina.consultas)
    antigo.rodada(conn)                                     # a primeira rodada do codigo antigo
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao = ? AND id > ?",
                        (sentinela.ACAO, antes)).fetchone()[0] == 0
    assert len(maquina.consultas) == consultas              # o log nao andou: nada relido
    maquina.adicionar("tarefas.xml", maquina.raiz)
    antigo.rodada(conn)                                     # o codigo antigo grava o ponto na auditoria
    assert f"EventRecordID>{ponto}" in maquina.consultas[-1]
    db.migrate(conn)                                        # o deploy seguinte, de volta para a #456
    assert _ponto(conn) == 1060
    monkeypatch.setattr(seguranca, "_conferencia", [])
    assert seguranca.conferir(conn) == []                   # gatilhos de volta
    assert _rodar(maquina, conn) == []


def test_comando_do_rollback_456_repetido_ou_sem_a_tabela_nao_grava_de_novo(maquina, conn, capsys):
    _com_ponto_de_partida(maquina, conn)
    _rodar_o_comando_do_runbook(capsys)
    linhas = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    assert _rodar_o_comando_do_runbook(capsys).strip().splitlines()[-1] == "sentinela_ponto: 0 migracao 063: 0"
    assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == linhas


def test_comando_do_rollback_456_sem_ponto_gravado_so_apaga(maquina, conn, capsys):
    assert _ponto(conn) is None                              # a sentinela nunca leu o log
    _rodar_o_comando_do_runbook(capsys)
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao = ?", (sentinela.ACAO_PONTO,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM schema_migrations WHERE nome = '063_sentinela_ponto.sql'").fetchone()[0] == 0


def _tabela_mudou_em(conn, quando: str):
    with db.mutacao(conn):
        conn.execute("UPDATE sentinela_ponto SET atualizado_em = ? WHERE id = 1", (quando,))


def _ultimo_ponto_na_auditoria(conn):
    r = conn.execute("SELECT depois FROM audit_log WHERE acao = ? ORDER BY id DESC LIMIT 1",
                     (sentinela.ACAO_PONTO,)).fetchone()
    return json.loads(r[0])["ultimo_registro"]


def test_rollback_que_ja_subiu_o_codigo_antigo_mantem_o_ponto_que_ele_gravou_depois(maquina, conn, capsys):
    """/code-review da #478: o codigo antigo ja' rodou (ponto 1060 na auditoria, gravado depois da ultima mudanca da
    tabela, parada em 1004); o comando nao pode gravar o ponto velho por cima."""
    from app import auditoria
    _com_ponto_de_partida(maquina, conn)
    _rodar(maquina, conn, "4663_segredos_externo.xml")
    assert _ponto(conn) == 1004
    _tabela_mudou_em(conn, "2000-01-01 00:00:00")
    with db.mutacao(conn):
        auditoria.registrar(conn, None, sentinela.ACAO_PONTO, "sentinela", None, None, {"ultimo_registro": 1060})
    _rodar_o_comando_do_runbook(capsys)
    assert _ultimo_ponto_na_auditoria(conn) == 1060


def test_rollback_depois_de_o_log_recomecar_grava_o_ponto_da_tabela_mesmo_menor(maquina, conn, capsys):
    """Gate Sol e revisor, rodada 1 da PR #499: o EventRecordID recomeca quando o log e' limpo. Com a auditoria em 5000
    (de antes do deploy da #456) e a tabela em 1004 (depois da limpeza), comparar pelo numero mantinha 5000: o codigo
    antigo partiria de 5000 e pularia os eventos ate' la', ou, com o log abaixo disso, releria tudo."""
    from app import auditoria
    _com_ponto_de_partida(maquina, conn)
    with db.mutacao(conn):                                  # o ponto que o codigo antigo deixou, antes do deploy
        auditoria.registrar(conn, None, sentinela.ACAO_PONTO, "sentinela", None, None, {"ultimo_registro": 5000})
    _rodar(maquina, conn, "4663_segredos_externo.xml")     # log recomecado: a tabela vai a 1004
    assert _ponto(conn) == 1004
    _rodar_o_comando_do_runbook(capsys)
    assert _ultimo_ponto_na_auditoria(conn) == 1004
    antigo = _codigo_de_antes_da_456(maquina)
    antes = conn.execute("SELECT MAX(id) FROM audit_log").fetchone()[0]
    maquina.adicionar("tarefas.xml", maquina.raiz)
    antigo.rodada(conn)
    novos = [json.loads(r[0])["evento"] for r in conn.execute(
        "SELECT depois FROM audit_log WHERE acao = ? AND id > ? ORDER BY id", (sentinela.ACAO, antes))]
    assert novos == [4698, 4699, 4700, 4701, 4702]          # so' o que veio depois de 1004, sem crítico
    assert "EventRecordID>1004" in maquina.consultas[-1]


def test_comando_do_runbook_que_so_tira_a_tabela_depois_do_codigo_antigo_ja_ter_subido(maquina, conn, monkeypatch):
    """O caso "o codigo antigo ja' subiu sem este passo": ele ja' grava o ponto na auditoria; o `python -c` do runbook
    (sem a CLI nova, que o codigo antigo nao tem) so' tira a tabela, os gatilhos e a linha da 063."""
    import subprocess
    import sys
    from app import auditoria
    texto = (pathlib.Path(__file__).resolve().parents[2] / "docs" / "runbook.md").read_text(encoding="utf-8")
    comandos = [m.group(1) for m in re.finditer(r'python -c "([^"]*)"', texto) if "063_sentinela_ponto.sql" in m.group(1)]
    assert len(comandos) == 1
    assert '"' not in comandos[0] and "$" not in comandos[0]   # o PowerShell repassa sem mexer
    _com_ponto_de_partida(maquina, conn)
    with db.mutacao(conn):                                  # o codigo antigo, depois do rollback
        auditoria.registrar(conn, None, sentinela.ACAO_PONTO, "sentinela", None, None, {"ultimo_registro": 1071})
    comando = comandos[0].replace(r"C:\DashboardLotufo\dados\dashboard.db", str(db.db_path()))
    saida = subprocess.run([sys.executable, "-I", "-c", comando], capture_output=True, text=True, check=True).stdout
    assert saida.strip() == "sentinela_ponto: 0 migracao 063: 0"
    db.migrate(conn)                                        # o deploy seguinte
    assert _ponto(conn) == 1071


def test_deploy_ps1_passa_o_ponto_para_a_auditoria_antes_de_voltar_para_antes_da_456():
    texto = (pathlib.Path(__file__).resolve().parents[2] / "scripts" / "deploy.ps1").read_text(encoding="utf-8")
    principal = texto[texto.index("$anterior = (& git -C $AppDir rev-parse HEAD).Trim()"):]
    # rollback por saude: com o codigo novo, antes do checkout do anterior
    rollback = principal[principal.index("ROLLBACK para $anterior"):]
    assert rollback.index("SentinelaAntesDa456 $novo $anterior") < rollback.index("Construir $anterior")
    # revisor, rodada 1 da PR #499: deploy com -Ref de um commit antigo, antes do checkout do alvo; e o catch do
    # build religa o anterior quando o servico foi parado para isso
    assert principal.index("SentinelaAntesDa456 $anterior $alvo") < principal.index("try { Construir $alvo")
    catch_build = principal[principal.index("try { Construir $alvo"):principal.index("$novo = (& git")]
    assert "if ($script:sentinelaParou)" in catch_build and "Reiniciar" in catch_build
    assert "app.cli sentinela antes-da-456 --banco $banco" in texto
    assert "backend/migrations/063_sentinela_ponto.sql" in texto


def test_runbook_cria_o_sentinela_do_watchdog_antes_do_rollback_456_a_mao():
    texto = (pathlib.Path(__file__).resolve().parents[2] / "docs" / "runbook.md").read_text(encoding="utf-8")
    item = texto[texto.index("- **Rollback para um commit anterior à issue #456**"):texto.index("## Variáveis de ambiente")]
    assert item.index("watchdog.pause") < item.index("parar o serviço") < item.index("app.cli sentinela antes-da-456")


def test_estado_da_sentinela_e_gravado_sob_o_lock_antes_do_commit(maquina, conn, monkeypatch):
    """Gate Sol, rodada 1 da PR #499: gravado depois de soltar o lock, uma rodada atrasada sobrescrevia o arquivo de
    uma mais nova (recolocando uma falha ja' normalizada), e quem lia a marca nova ainda lia o arquivo velho."""
    _com_ponto_de_partida(maquina, conn)
    maquina.auditoria[sentinela.GUID_ARQUIVOS] = False
    outra = db.get_conn()
    original = sentinela._gravar_estado
    visto = []

    def conferir(estado):
        visto.append((conn.in_transaction, outra.execute(
            "SELECT COUNT(*) FROM audit_log WHERE acao = ?", (sentinela.ACAO,)).fetchone()[0]))
        original(estado)

    monkeypatch.setattr(sentinela, "_gravar_estado", conferir)
    assert [x["evento"] for x in _rodar(maquina, conn)] == ["auditoria-arquivos"]
    outra.close()
    assert visto == [(True, 0)]                             # sob o BEGIN IMMEDIATE, antes de o achado ficar visivel


def test_rodada_que_comeca_enquanto_a_outra_grava_nao_repete_a_falha_nem_sobrescreve_o_arquivo(maquina, conn,
                                                                                               monkeypatch):
    """Issue #478, 3o criterio, com o arquivo gravado sob o lock: A grava a falha e para no arquivo (antes do commit);
    B comeca nesse meio, ja' com a maquina normal, e fica esperando o lock. B descarta o que leu: a falha sai uma vez
    e o arquivo que fica e' o de A. Corrigida e falhando de novo, a falha avisa outra vez."""
    import threading
    _com_ponto_de_partida(maquina, conn)
    maquina.auditoria[sentinela.GUID_ARQUIVOS] = False
    a_no_arquivo, b_leu = threading.Event(), threading.Event()
    original_gravar, original_verificacoes = sentinela._gravar_estado, sentinela.verificacoes

    def gravar(estado):
        if threading.current_thread().name == "rodada-a":
            a_no_arquivo.set()
            assert b_leu.wait(5)
        original_gravar(estado)

    def verificacoes(base):
        r = original_verificacoes(base)
        if threading.current_thread().name == "rodada-b":
            b_leu.set()                                     # B ja' leu a marca e o arquivo; vai pedir o lock
        return r

    monkeypatch.setattr(sentinela, "_gravar_estado", gravar)
    monkeypatch.setattr(sentinela, "verificacoes", verificacoes)
    erros = []

    def rodar(nome_conn):
        c = db.get_conn()
        try:
            sentinela.rodada(c)
        except Exception as e:                              # noqa: BLE001 - o teste confere abaixo
            erros.append(e)
        finally:
            c.close()

    antes = conn.execute("SELECT MAX(id) FROM audit_log").fetchone()[0] or 0
    a = threading.Thread(target=rodar, args=("a",), name="rodada-a")
    a.start()
    assert a_no_arquivo.wait(5)
    maquina.auditoria[sentinela.GUID_ARQUIVOS] = True       # B enxerga a maquina ja' normal
    b = threading.Thread(target=rodar, args=("b",), name="rodada-b")
    b.start()
    a.join(10)
    b.join(10)
    assert erros == []
    gravados = [json.loads(r[0])["evento"] for r in conn.execute(
        "SELECT depois FROM audit_log WHERE acao = ? AND id > ?", (sentinela.ACAO, antes))]
    assert gravados == ["auditoria-arquivos"]
    estado = json.loads((maquina.raiz / "dados" / "sentinela.json").read_text(encoding="utf-8"))
    assert list(estado["pendencias"]) == ["auditoria-arquivos"]   # o arquivo de A, que gravou no banco
    assert _rodar(maquina, conn) == []                      # normal: a pendencia sai
    maquina.auditoria[sentinela.GUID_ARQUIVOS] = False
    assert [x["evento"] for x in _rodar(maquina, conn)] == ["auditoria-arquivos"]   # episodio novo avisa


def test_arquivo_de_estado_que_nao_grava_nao_impede_os_achados(maquina, conn, monkeypatch):
    _com_ponto_de_partida(maquina, conn)

    def falha(estado):
        raise PermissionError("sem permissao")

    monkeypatch.setattr(sentinela, "_gravar_estado", falha)
    assert [x["evento"] for x in _rodar(maquina, conn, "4670_permissao.xml")] == [4670]
    assert _ponto(conn) == 1030


def test_copia_a_frente_do_banco_sem_conseguir_ler_o_log_acusa(maquina, conn):
    maquina.adicionar("4670_permissao.xml", maquina.raiz)
    _com_ponto_de_partida(maquina, conn)
    with db.mutacao(conn):
        conn.execute("UPDATE sentinela_ponto SET ultimo_registro = 1000 WHERE id = 1")
    maquina.wevtutil_falha = True
    assert [x["evento"] for x in _rodar(maquina, conn)] == ["estado-perdido", "leitura-log"]
