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
SACL_OK = "S-1-5-4|Success\nS-1-5-2|Success\n"


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
    maquina.sacl["segredos"] = "S-1-5-4|Success\n"          # falta REDE
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
    agora = datetime.datetime(2026, 11, 6, 12, 0, tzinfo=datetime.timezone.utc)
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


def test_estado_apagado_depois_de_ja_ter_rodado_acusa_e_rele_a_janela(maquina, conn):
    _com_ponto_de_partida(maquina, conn)
    _rodar(maquina, conn, "4670_permissao.xml")
    (maquina.raiz / "dados" / "sentinela.json").unlink()
    a = _rodar(maquina, conn, "4663_segredos_externo.xml")
    assert a[0]["mensagem"].startswith("Estado da sentinela apagado ou ilegível") and a[0]["nivel"] == "critico"
    assert any(x["evento"] == 4663 for x in a)
    assert "timediff(@SystemTime) <= 600000" in maquina.consultas[-1]
    assert _rodar(maquina, conn) == []       # estado refeito: volta ao normal


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
