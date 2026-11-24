"""Criterio de encerramento do SIGA (issue #841): sobrestado, leitura vazia, encerrar e reabrir a' mao, vinculo com a
medicao pela tela (com a proposta pelo nome) e a pendencia do protocolo novo. O criterio do "Juntado" esta' em
`test_siga.py`, ao lado dos de arquivado.

Processos, obras, setores e datas sao ficticios (repositorio publico); pessoa, so' pelo papel."""
import pytest

from app import auth, siga, tempo
from app import avisos as registro_avisos
from tests.test_siga import (MOVS, SITUACAO_COFIN, SITUACAO_GABIN, _banco, _br, _conta, _cuiaba, _encerrado, _leitura,
                             _mov, _protocolo_enviado, conn, relogio)  # noqa: F401  (fixtures)

SOBRESTADO = "1º Volume - Aguardando Andamento [PROTOC, [Y]] | 2º Volume - Sobrestado [COFIN, [X]]"


def _painel_de(conn, agora, codigo="ABC123"):
    return next(p for p in siga.painel(conn, agora)["processos"] if p["codigo"] == codigo)


def _usuario(conn, perfil="engenharia"):
    return auth.criar_usuario(conn, "Pessoa de teste", f"{perfil}@exemplo.com.br", "senha-forte-123", perfil)


def _pid(conn, codigo="ABC123"):
    return conn.execute("SELECT id FROM siga_processos WHERE codigo=?", (codigo,)).fetchone()[0]


# --- criterio 5: sobrestado ---------------------------------------------------------------------------------

def test_sobrestado_sem_destaque_de_atraso_fora_dos_parados_e_do_aviso(conn):
    """O processo suspenso pelo orgao le "sobrestado" na leitura unica de `parado`: sem cor de atraso, fora da
    contagem de parados, sem aviso `siga_parado` e depois dos parados na ordem."""
    _protocolo_enviado(conn, "SINFRA-PRO-2026/00001")
    proc = _leitura(numero="SINFRA-PRO-2026/00001")
    proc[0]["situacao"] = SOBRESTADO
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 10), proc)
    agora = _cuiaba(2026, 11, 12, 10)                                  # 10 dias uteis sem movimentacao
    p = _painel_de(conn, agora)
    assert p["dias_sem_movimentacao"] >= siga.DIAS_ACAO               # o numero continua, so' nao e' atraso
    assert (p["situacao_tempo"], p["encerrado"], p["sobrestado"]) == ("sobrestado", None, True)
    painel = siga.painel(conn, agora)
    beta = next(x for x in painel["processos"] if x["codigo"] is None)
    assert beta["situacao_tempo"] == "critico"
    assert painel["numeros"]["parados"] == 1 and painel["numeros"]["acompanhados"] == 2
    assert [a for a in siga.avisos(conn, agora.date(), agora) if a["tipo"] == "siga_parado"] == []
    # na posicao da medicao a leitura e' a mesma, e o sobrestado vai depois do parado
    posicao = siga.posicao_das_medicoes(conn, [31], agora.date())[31]
    assert posicao["situacao_tempo"] == "sobrestado"
    assert siga.mais_parado([{**posicao, "processo_id": 1},
                             {**posicao, "processo_id": 2, "situacao_tempo": "breve", "dias_sem_movimentacao": 5}]
                            )["processo_id"] == 2
    # saindo do sobrestado, o mesmo processo volta a ser parado e a avisar
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 11), [{**proc[0], "situacao": SITUACAO_COFIN}])
    assert _painel_de(conn, agora)["situacao_tempo"] == "critico"
    assert [a["tipo"] for a in siga.avisos(conn, agora.date(), agora)] == ["siga_parado"]


# --- criterio 6: leitura vazia ------------------------------------------------------------------------------

def test_leitura_com_zero_movimentacao_nao_altera_historico_nem_leitura_de_tempo(conn):
    """O SIGA devolve a lista vazia para um processo que tem historico. A leitura fica gravada e marcada, o historico
    continua, os dias sem movimentacao nao mudam e nada encerra (nem a situacao vazia, nem a que diria arquivado ou
    juntado)."""
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 10), _leitura())
    agora = _cuiaba(2026, 11, 12, 10)
    antes = _painel_de(conn, agora)
    movs = _conta(conn, "siga_movimentacoes")
    for lido, situacao in ((_cuiaba(2026, 10, 28, 11), None),
                           (_cuiaba(2026, 10, 28, 12), "1º Volume - Arquivado [ARQUIVO GERAL, [X]]"),
                           (_cuiaba(2026, 10, 28, 13), "1º Volume - Juntado [PROTOC, [X]]")):
        siga.gravar_leitura(conn, lido, [{"codigo": "ABC123", "numero": "ORGAO-PRO-2026/00010", "nome": "Processo Alfa",
                                          "situacao": situacao, "movimentacoes": []}])
    depois = _painel_de(conn, agora)
    assert _conta(conn, "siga_movimentacoes") == movs
    assert conn.execute("SELECT COUNT(*) FROM siga_leituras WHERE sem_movimentacoes=1").fetchone()[0] == 3
    for campo in ("situacao", "setor", "dias_sem_movimentacao", "situacao_tempo", "ultima", "movimentacoes",
                  "encerrado", "desde", "dias_uteis"):
        assert depois[campo] == antes[campo], campo
    assert depois["encerrado"] is None and siga.encerrados(conn) == {}
    # o robo leu: a leitura vazia conta como leitura feita (nao vira atraso)
    assert siga.painel(conn, agora)["lido_em"] == tempo.iso_utc(_banco(_cuiaba(2026, 10, 28, 13)))
    # processo novo, sem historico, que chega sem movimentacao: leitura comum (a situacao vale)
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 14), [{"codigo": "NOVO99", "numero": None, "nome": "Novo",
                                                           "situacao": SITUACAO_GABIN, "movimentacoes": []}])
    assert _painel_de(conn, agora, "NOVO99")["setor"] == "GABIN"


def test_leitura_vazia_nao_reabre_o_encerrado_a_mao(conn):
    uid = _usuario(conn)
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 10), _leitura())
    siga.encerrar(conn, uid, _pid(conn), "aditivo publicado")
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 16, 5), [{**_leitura()[0], "movimentacoes": []}])
    assert _painel_de(conn, _cuiaba(2026, 10, 28, 16, 9))["encerrado"] == "manual"


# --- criterio 3: encerrar e reabrir a' mao ------------------------------------------------------------------

def test_encerrar_e_reabrir_a_mao_com_motivo_autor_e_data(conn):
    """Encerrar a' mao guarda motivo, quem e quando; o processo vai para Encerrados, continua na lista do robo e
    reabre a' mao. O automatico nao reabre por aqui, e o que ja' esta' encerrado nao encerra de novo."""
    uid = _usuario(conn)
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 10), _leitura())
    pid = _pid(conn)
    with pytest.raises(ValueError, match="motivo"):
        siga.encerrar(conn, uid, pid, "   ")
    with pytest.raises(ValueError, match="mais de 200"):
        siga.encerrar(conn, uid, pid, "x" * 201)
    with pytest.raises(siga.NaoEncerradoAMao):
        siga.reabrir(conn, uid, pid)
    siga.encerrar(conn, uid, pid, " aditivo publicado ")
    p = _painel_de(conn, _cuiaba(2026, 10, 28, 16, 30))
    assert p["encerrado"] == "manual" and p["situacao_tempo"] is None
    assert p["encerramento"] == {"motivo": "aditivo publicado", "por": "Pessoa de teste",
                                 "em": "2026-10-28T20:00:00+00:00"}
    assert "ABC123" in [x["codigo"] for x in siga.processos_para_o_robo(conn)]    # o robo continua lendo
    with pytest.raises(siga.JaEncerrado):
        siga.encerrar(conn, uid, pid, "outro")
    siga.reabrir(conn, uid, pid)
    assert _painel_de(conn, _cuiaba(2026, 10, 28, 16, 30))["encerrado"] is None
    linha = conn.execute("SELECT motivo, encerrado_por, encerrado_em, reaberto_em, reaberto_por, "
                         "reaberto_pela_movimentacao FROM siga_encerramentos").fetchone()
    assert tuple(linha) == ("aditivo publicado", uid, "2026-10-28 20:00:00", "2026-10-28 20:00:00", uid, None)
    acoes = [r[0] for r in conn.execute("SELECT acao FROM audit_log WHERE entidade='siga_processo' AND entidade_id=? "
                                        "ORDER BY id", (str(pid),))]
    assert acoes == ["siga.encerramento", "siga.reabertura"]
    # o arquivado (automatico) nao se reabre a' mao nem se encerra de novo
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 11),
                        [{**_leitura()[0], "situacao": "1º Volume - Arquivado [PROTOC, [X]]"}])
    with pytest.raises(siga.JaEncerrado):
        siga.encerrar(conn, uid, pid, "x")
    with pytest.raises(siga.NaoEncerradoAMao):
        siga.reabrir(conn, uid, pid)


def test_encerrado_a_mao_volta_sozinho_com_movimentacao_posterior_e_fica_registrado(conn, monkeypatch):
    """Movimentacao depois do encerramento (fora Marcacao e Anotacao) devolve o processo ao quadro; a linha do
    encerramento guarda a reabertura e a movimentacao, e a auditoria, o ato sem usuario."""
    uid = _usuario(conn)
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 10), _leitura())
    pid = _pid(conn)
    siga.encerrar(conn, uid, pid, "pedido respondido")              # 16h de Cuiaba (o relogio dos testes)
    proc = _leitura()[0]
    # Marcacao e Anotacao depois do encerramento, e movimentacao antiga lida so' agora, nao devolvem
    proc["movimentacoes"] += [{**_mov("", "Marcação", at_lotacao="COFIN/ORGAO"), "data": "28/10/2026 16:20:00"},
                              {**_mov("", "Anotação", at_lotacao="COFIN/ORGAO"), "data": "28/10/2026 16:25:00"},
                              {**_mov("", "Despacho", at_lotacao="COFIN/ORGAO"), "data": "28/10/2026 15:00:00"}]
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 16, 5), [proc])
    assert _painel_de(conn, _cuiaba(2026, 10, 28, 16, 9))["encerrado"] == "manual"
    proc["movimentacoes"].append({**_mov("", "Transferência", at_lotacao="GABIN/ORGAO"), "data": "28/10/2026 16:40:00"})
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 16, 6), [proc])
    assert _painel_de(conn, _cuiaba(2026, 10, 28, 16, 9))["encerrado"] is None
    linha = conn.execute("SELECT reaberto_em, reaberto_por, reaberto_pela_movimentacao FROM siga_encerramentos"
                         ).fetchone()
    assert tuple(linha) == ("2026-10-28 20:00:00", None, "2026-10-28 16:40:00")
    reg = conn.execute("SELECT usuario_id, depois FROM audit_log WHERE acao='siga.reabertura'").fetchone()
    assert reg["usuario_id"] is None and "2026-10-28 16:40:00" in reg["depois"]
    # encerrado de novo depois dessa movimentacao (17h), sem nada novo: fica encerrado
    monkeypatch.setattr(tempo, "agora_utc", lambda: _cuiaba(2026, 10, 28, 17))
    siga.encerrar(conn, uid, pid, "pedido respondido de novo")
    assert _painel_de(conn, _cuiaba(2026, 10, 28, 17, 5))["encerrado"] == "manual"


# --- criterio 2: vinculo processo <-> medicao, com a proposta ------------------------------------------------

def _obra_exemplo(conn):
    """Duas obras (nº do instrumento e nome curto ficticios) e as medicoes 7 (execucao e reajuste) e 8 da primeira."""
    for cid, instrumento, curto in ((9, "517/2031/00/00-EXEMPLO", "Ponte do Exemplo"),
                                    (10, "518/2031/00/00-EXEMPLO", "Outra Obra")):
        conn.execute("INSERT INTO contratos (id, orgao, numero_instrumento, objeto, valor_original_centavos, nome_curto) "
                     "VALUES (?, 'SECRETARIA DE EXEMPLO', ?, 'Obra', 100, ?)", (cid, instrumento, curto))
    for mid, cid, numero, tipo, estado in ((71, 9, 7, "execucao", "protocolada"), (72, 9, 7, "reajuste", "recebida"),
                                           (81, 9, 8, "execucao", "protocolada"), (91, 10, 7, "execucao", "recebida")):
        conn.execute("INSERT INTO medicoes (id, contrato_id, numero, tipo, competencia, estado) VALUES (?,?,?,?,?,?)",
                     (mid, cid, numero, tipo, "2026-08", estado))
    conn.commit()


@pytest.mark.parametrize("nome,esperada", [
    ("7ª Medição - Ponte do Exemplo - IC 517/2031 (ORGAO-PRO-2026/00020)", 71),
    ("7ª Medição/Reajuste - Ponte do Exemplo (ORGAO-PRO-2026/00020)", 71),     # o processo leva os dois: a medicao
    ("Reajuste da 7ª Medição - IC 517/2031 (ORGAO-PRO-2026/00020)", 72),
    ("CT-099 - 8ª Medição - Ponte do Exemplo (ORGAO)", 81),
    ("7ª Medição - IC 518/2031", 91),
    ("9ª Medição - Ponte do Exemplo", None),                                  # a medicao nao existe
    ("7ª Medição - Obra que nao existe (ORGAO-PRO-2026/00020)", None),        # sem obra
    ("7ª Medição - Ponte do Exemplo e Outra Obra", None),                    # duas obras: ninguem adivinha
    ("Aditivo de prazo - Ponte do Exemplo", None),
])
def test_proposta_de_medicao_pela_obra_e_pelo_numero_do_nome(conn, nome, esperada):
    _obra_exemplo(conn)
    proc = [{"id": 1, "nome": nome, "contrato_id": None, "medicao_id": None, "protocolo_id": None}]
    proposta = siga.propostas_de_medicao(conn, proc).get(1)
    assert (proposta["id"] if proposta else None) == esperada


@pytest.mark.parametrize("nome,esperado", [
    ("Processo 2026 Medição da obra", None),             # #880: o fim do ano nao e' a 26ª
    ("IC 517/2031 medicao final", None),                  # #880: o fim do instrumento nao e' a 31ª
    ("Processo 2026 - 3ª Medição", (3, "execucao")),      # o ano antes nao atrapalha o numero que vem depois
    ("7ª Medição - IC 517/2031", (7, "execucao")),
    ("7 medicao", (7, "execucao")),
    ("12ª Medição", (12, "execucao")),
    ("Reajuste da 15ª Medição", (15, "reajuste")),
    ("Reajuste do 15º medicao", (15, "reajuste")),
    ("3ª Medição de Projeto", (3, "projeto")),
    ("CT-099 - 8ª Medição", (8, "execucao")),
    ("Aditivo de prazo", None),
])
def test_numero_da_medicao_no_nome_nao_le_numero_colado_a_outro(nome, esperado):
    assert siga._medicao_do_nome(nome) == esperado


def test_proposta_usa_a_obra_ja_escolhida_no_processo(conn):
    _obra_exemplo(conn)
    proc = [{"id": 1, "nome": "8ª Medição", "contrato_id": 9, "medicao_id": None, "protocolo_id": None}]
    assert siga.propostas_de_medicao(conn, proc)[1]["id"] == 81


def test_processo_no_quadro_ganha_proposta_e_ligado_a_medicao_recebida_encerra(conn):
    """O processo que ja' esta' no quadro (Medicoes pelo nome) traz a proposta; ligado (a funcao da rota da tela), com
    quem e quando, encerra quando a medicao e' recebida. Desfeito, volta, fica em Medicoes, nao ganha de novo a mesma
    medicao como proposta (#881) e o robo nao o religa pelo numero igual. O teste pela rota esta' em test_api_siga.py."""
    uid = _usuario(conn)
    _obra_exemplo(conn)
    proc = {"codigo": "PRC777", "numero": "ORGAO-PRO-2026/00020", "nome": "7ª Medição - Ponte do Exemplo - IC 517/2031",
            "situacao": SITUACAO_COFIN, "movimentacoes": [{**m, "data": _br(m["data"])} for m in MOVS]}
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 10), [proc])
    agora = _cuiaba(2026, 10, 28, 11)
    p = _painel_de(conn, agora, "PRC777")
    assert (p["categoria"], p["categoria_sugerida"], p["medicao_id"]) == ("medicoes", True, None)
    assert p["medicao_proposta"] == {"id": 71, "contrato_id": 9, "titulo": "7ª Medição", "obra": "Ponte do Exemplo",
                                     "estado": "protocolada"}
    siga.vincular_medicao(conn, uid, p["id"], 71)
    p = _painel_de(conn, agora, "PRC777")
    assert (p["medicao_id"], p["contrato_id"], p["categoria"], p["encerrado"], p["medicao_proposta"]) == (
        71, 9, "medicoes", None, None)
    assert p["vinculo"] == {"por": "Pessoa de teste", "em": "2026-10-28T20:00:00+00:00"}
    conn.execute("UPDATE medicoes SET estado='recebida' WHERE id=71"); conn.commit()
    assert _painel_de(conn, agora, "PRC777")["encerrado"] == "recebida"
    assert siga.processos_para_o_robo(conn) == []
    siga.desfazer_vinculo(conn, uid, p["id"])
    p = _painel_de(conn, agora, "PRC777")
    assert (p["medicao_id"], p["categoria"], p["encerrado"], p["vinculo"]) == (None, "medicoes", None, None)
    assert p["medicao_proposta"] is None                                      # #881: a desfeita nao volta
    assert p["o_que_e"] == "7ª Medição"                                       # #881: o nome nao perde o numero
    with pytest.raises(ValueError, match="não está ligado"):
        siga.desfazer_vinculo(conn, uid, p["id"])
    # o numero do processo passa a ser o de um envio por fora da medicao 81: o robo nao religa o que a pessoa desfez
    conn.execute("INSERT INTO medicao_protocolos (medicao_id, data, etapa, numero_processo, origem) "
                 "VALUES (81, '2026-10-01', 'nota', 'ORGAO-PRO-2026/00020', 'manual')"); conn.commit()
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 11), [proc])
    assert _painel_de(conn, agora, "PRC777")["medicao_id"] is None
    acoes = [r[0] for r in conn.execute("SELECT acao FROM audit_log WHERE entidade='siga_processo' ORDER BY id")]
    assert acoes == ["siga.vinculo_medicao", "siga.vinculo_desfeito"]


def _processo_da_7a(conn, codigo="PRC777", numero="ORGAO-PRO-2026/00020"):
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 10), [
        {"codigo": codigo, "numero": numero, "nome": "7ª Medição - Ponte do Exemplo - IC 517/2031",
         "situacao": SITUACAO_COFIN, "movimentacoes": []}])
    return _pid(conn, codigo)


def test_vinculo_desfeito_tira_so_o_par_processo_e_medicao_da_proposta(conn):
    """#881: a exclusao vale para o par. O mesmo processo, com o nome passando a dizer a 8ª, ganha a 8ª; outro
    processo com a 7ª no nome ainda ganha a 7ª como proposta."""
    uid = _usuario(conn)
    _obra_exemplo(conn)
    pid = _processo_da_7a(conn)
    _processo_da_7a(conn, "PRC888", "ORGAO-PRO-2026/00021")
    siga.vincular_medicao(conn, uid, pid, 71)
    siga.desfazer_vinculo(conn, uid, pid)
    agora = _cuiaba(2026, 10, 28, 11)
    assert _painel_de(conn, agora, "PRC777")["medicao_proposta"] is None
    assert _painel_de(conn, agora, "PRC888")["medicao_proposta"]["id"] == 71         # a mesma em outro processo
    conn.execute("UPDATE siga_processos SET nome='8ª Medição - Ponte do Exemplo' WHERE id=?", (pid,)); conn.commit()
    p = _painel_de(conn, agora, "PRC777")
    assert (p["medicao_proposta"]["id"], p["o_que_e"]) == (81, "8ª Medição")          # outra da mesma obra


def test_medicao_desfeita_ainda_se_liga_a_mao_e_desfeita_de_novo_continua_fora(conn):
    """#881: a recusa e' so' da proposta. Ligar a' mao a medicao desfeita funciona; desfeita outra vez, a proposta
    continua sem ela, e o nome sem medicao continua com o numero do SIGA."""
    uid = _usuario(conn)
    _obra_exemplo(conn)
    pid = _processo_da_7a(conn)
    agora = _cuiaba(2026, 10, 28, 11)
    siga.vincular_medicao(conn, uid, pid, 71)
    siga.desfazer_vinculo(conn, uid, pid)
    siga.vincular_medicao(conn, uid, pid, 71)
    p = _painel_de(conn, agora, "PRC777")
    assert (p["medicao_id"], p["medicao_proposta"], p["o_que_e"]) == (71, None, "7ª Medição")
    siga.desfazer_vinculo(conn, uid, pid)
    p = _painel_de(conn, agora, "PRC777")
    assert (p["medicao_id"], p["medicao_proposta"], p["o_que_e"]) == (None, None, "7ª Medição")
    acoes = [r[0] for r in conn.execute("SELECT acao FROM audit_log WHERE entidade='siga_processo' ORDER BY id")]
    assert acoes == ["siga.vinculo_medicao", "siga.vinculo_desfeito"] * 2


def test_processo_de_medicoes_sem_numero_no_nome_continua_medicao(conn):
    """Sem numero no nome do SIGA, o processo de Medicoes sem medicao continua "<obra> · Medição"."""
    _obra_exemplo(conn)
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 10), [{"codigo": "PRC777", "numero": None, "nome": "Pleito da obra",
                                                           "situacao": SITUACAO_COFIN, "movimentacoes": []}])
    conn.execute("UPDATE siga_processos SET contrato_id=9, categoria='medicoes'"); conn.commit()
    assert _painel_de(conn, _cuiaba(2026, 10, 28, 11), "PRC777")["o_que_e"] == "Medição"


def test_classificar_em_medicoes_grava_quem_e_quando_ligou(conn):
    """A medicao escolhida em "Confirmar categoria" e' o mesmo vinculo (uma definicao so')."""
    uid = _usuario(conn)
    _obra_exemplo(conn)
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 10), [{"codigo": "PRC777", "numero": None, "nome": "Nome do robô",
                                                           "situacao": SITUACAO_COFIN, "movimentacoes": []}])
    siga.classificar(conn, uid, _pid(conn, "PRC777"), "medicoes", 9, 81, None)
    assert _painel_de(conn, _cuiaba(2026, 10, 28, 11), "PRC777")["vinculo"]["por"] == "Pessoa de teste"
    siga.classificar(conn, uid, _pid(conn, "PRC777"), "aditivos", 9, None, "de prazo")
    assert tuple(conn.execute("SELECT medicao_id, medicao_vinculada_por, medicao_vinculada_em FROM siga_processos"
                              ).fetchone()) == (None, None, None)


def test_processo_de_protocolo_enviado_nao_muda_o_vinculo_pela_tela(conn):
    uid = _usuario(conn, "admin")
    _protocolo_enviado(conn, "SINFRA-PRO-2026/00001")
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 10), _leitura(numero="SINFRA-PRO-2026/00001"))
    pid = _pid(conn)
    for funcao, args in ((siga.vincular_medicao, (31,)), (siga.desfazer_vinculo, ())):
        with pytest.raises(ValueError, match="protocolo enviado pelo sistema"):
            funcao(conn, uid, pid, *args)
    with pytest.raises(LookupError):
        siga.vincular_medicao(conn, uid, 9999, 31)
    beta = conn.execute("SELECT id FROM siga_processos WHERE codigo IS NULL").fetchone()[0]
    with pytest.raises(ValueError, match="Medição não encontrada"):
        siga.vincular_medicao(conn, uid, beta, 9999)


# --- criterio 4: pendencia do protocolo novo -----------------------------------------------------------------

@pytest.mark.parametrize("situacao", ["1º Volume - Arquivado [PROTOC, [X]]", "1º Volume - Juntado [PROTOC, [X]]"])
def test_processo_de_medicao_nao_recebida_arquivado_ou_juntado_pede_o_protocolo_novo(conn, situacao):
    """O processo ligado a' medicao ainda nao recebida e' arquivado ou juntado: sai do quadro e a medicao ganha a
    pendencia do protocolo novo. Some com outro processo vivo ligado a ela ou com a medicao recebida."""
    _protocolo_enviado(conn, "SINFRA-PRO-2026/00001")
    proc = _leitura(numero="SINFRA-PRO-2026/00001")[:1]
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 10), proc)
    assert siga.protocolo_novo_pendente(conn, [31]) == set()                 # vivo: nada a pedir
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 11), [{**proc[0], "situacao": situacao}])
    assert _encerrado(conn) in ("arquivado", "juntado")
    assert siga.protocolo_novo_pendente(conn, [31]) == {31}
    # o processo novo da medicao, vivo, resolve
    novo = conn.execute("INSERT INTO siga_processos (codigo, nome, medicao_id, contrato_id, categoria) "
                        "VALUES ('NOVO11', 'Novo', 31, 7, 'medicoes')").lastrowid
    conn.commit()
    assert siga.protocolo_novo_pendente(conn, [31]) == set()
    conn.execute("DELETE FROM siga_processos WHERE id=?", (novo,)); conn.commit()
    assert siga.protocolo_novo_pendente(conn, [31]) == {31}
    conn.execute("UPDATE medicoes SET estado='recebida' WHERE id=31"); conn.commit()
    assert siga.protocolo_novo_pendente(conn, [31]) == set()                 # recebida: nao ha' o que pedir


@pytest.mark.parametrize("situacao,houve", [("1º Volume - Arquivado [PROTOC, [X]]", "arquivado"),
                                            ("1º Volume - Juntado [PROTOC, [X]]", "juntado a outro processo")])
def test_pendencia_do_protocolo_novo_tambem_aparece_em_avisos(conn, situacao, houve):
    """#881: a medicao que pede o protocolo novo ganha o aviso `siga_protocolo_novo` na fila, com a data do ultimo
    andamento do processo (o cancelado nao conta) e o clique na pagina da medicao. Some com o processo novo vivo e
    com a medicao recebida, como a caixa da pagina."""
    _protocolo_enviado(conn, "SINFRA-PRO-2026/00001")
    proc = _leitura(numero="SINFRA-PRO-2026/00001")[:1]
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 10), proc)
    hoje = _cuiaba(2026, 10, 30, 10)

    def novos():
        return [a for a in siga.avisos(conn, hoje.date(), hoje) if a["tipo"] == "siga_protocolo_novo"]

    assert novos() == []                                                     # vivo: nada a pedir
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 11), [{**proc[0], "situacao": situacao}])
    [aviso] = novos()
    assert aviso["mensagem"] == f"3ª Medição: processo do SIGA {houve}, falta o protocolo novo"
    assert (aviso["nivel"], aviso["publico"], aviso["contrato_id"], aviso["obra"], aviso["medicao_id"]) == (
        "atencao", ["operacao"], 7, "Obra Alfa", 31)
    assert aviso["destino"] == {"tela": "contrato", "id": 7, "aba": "medicao"}
    assert (aviso["data"], aviso["sentido"]) == ("2026-10-28", "desde")     # o Despacho; o cancelado depois nao conta
    # na fila do registro unico, com os dias pela data
    [na_fila] = [a for a in registro_avisos.listar(conn, hoje.date()) if a["tipo"] == "siga_protocolo_novo"]
    assert na_fila["dias"] == 2
    assert [a for a in registro_avisos.listar(conn, hoje.date(), com_siga=False) if a["tipo"].startswith("siga")] == []
    # o processo novo da medicao, vivo, resolve; a medicao recebida tambem
    novo = conn.execute("INSERT INTO siga_processos (codigo, nome, medicao_id, contrato_id, categoria) "
                        "VALUES ('NOVO11', 'Novo', 31, 7, 'medicoes')").lastrowid
    conn.commit()
    assert novos() == []
    conn.execute("DELETE FROM siga_processos WHERE id=?", (novo,)); conn.commit()
    assert len(novos()) == 1
    conn.execute("UPDATE medicoes SET estado='recebida' WHERE id=31"); conn.commit()
    assert novos() == []
