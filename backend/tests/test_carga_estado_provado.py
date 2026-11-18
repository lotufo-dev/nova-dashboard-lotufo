"""docs/adr/0006 ("A carga cria no estado que a linha prova"): `cadastro carregar-medicoes` cria a medicao nova no
estado que as colunas sustentam. Dados ficticios (cadastro-exemplo), valores com centavo impar."""
import json

from app import carga_medicoes, cli, conciliacao, diretoria
from tests.test_cli_cadastro import _com_exemplo_aplicado, _foto

CABECALHO = ("nº;tipo;competência;valor pedido;valor aprovado;data da aprovação;meio;nº do processo no órgão;"
             "data do envio;data do protocolo da nota;data do recebimento;NF;fonte\n")


def _csv(tmp_path, *linhas):
    arq = tmp_path / "obra-propria.csv"
    arq.write_text(CABECALHO + "".join(li + "\n" for li in linhas), "utf-8")
    return arq


def _uid(conn):
    return conn.execute("SELECT id FROM usuarios WHERE email='leo@l.com'").fetchone()[0]


def _medicoes(conn, cid):
    return {(m["numero"], m["tipo"]): dict(m) for m in conn.execute("SELECT * FROM medicoes WHERE contrato_id=?", (cid,))}


def test_cada_linha_nova_nasce_no_estado_que_prova(tmp_path, monkeypatch):
    conn, cid = _com_exemplo_aplicado(tmp_path, monkeypatch)
    arq = _csv(tmp_path,
               "5;execucao;2025-08;312.074,03;;;;PROC-5;02/09/2025;;;;carta de exemplo 5",
               "5;reajuste;2025-08;19.023,55;;;;PROC-5R;02/09/2025;;;;carta de exemplo 5R",
               "6;execucao;2025-09;100.000,01;99.999,99;20/10/2025;SMO;PROC-6;;;;;boletim de exemplo 6",
               "7;execucao;2025-10;70.000,03;70.000,03;18/11/2025;SMO;PROC-7;;25/11/2025;;;boletim de exemplo 7",
               "8;execucao;2025-11;52.100,09;52.100,09;15/12/2025;SMO;PROC-8;;20/12/2025;15/01/2026;;extrato de exemplo 8")
    rel = carga_medicoes.ensaiar(conn, arq)
    assert [(li["categoria"], li["etapa"]) for li in rel["linhas"]] == [
        ("nova", "em_analise"), ("nova", "em_analise"), ("nova", "boletim_recebido"), ("nova", "protocolada"),
        ("nova", "recebida")]
    rel = carga_medicoes.gravar(conn, _uid(conn), arq)
    assert rel["criadas"] == 5
    ms = _medicoes(conn, cid)
    resumo = {k: (m["estado"], m["congelada"], m["planilha_enviada_em"], m["valor_protocolado_centavos"],
                  m["valor_atestado_centavos"], m["recebida_em"]) for k, m in ms.items()}
    assert resumo == {
        # so' o pedido: em analise, sem congelar (o pedido congela pelo estado); o reajuste fica previsto com o marcador
        (5, "execucao"): ("planilha_enviada", 0, "2025-09-02", 31_207_403, None, None),
        (5, "reajuste"): ("prevista", 0, "2025-09-02", 1_902_355, None, None),
        (6, "execucao"): ("boletim_recebido", 0, None, 10_000_001, 9_999_999, None),
        (7, "execucao"): ("protocolada", 1, None, 7_000_003, 7_000_003, None),
        (8, "execucao"): ("recebida", 1, None, 5_210_009, 5_210_009, "2026-01-15")}
    # antes da nota, o processo do orgao e' o da planilha/carta, na data do envio; o protocolo da nota so' na protocolada
    protocolos = {(r["medicao_id"], r["etapa"]): (r["data"], r["numero_processo"]) for r in conn.execute(
        "SELECT medicao_id, etapa, data, numero_processo FROM medicao_protocolos")}
    assert protocolos == {(ms[(5, "execucao")]["id"], "planilha"): ("2025-09-02", "PROC-5"),
                          (ms[(5, "reajuste")]["id"], "planilha"): ("2025-09-02", "PROC-5R"),
                          (ms[(7, "execucao")]["id"], "nota"): ("2025-11-25", "PROC-7"),
                          (ms[(8, "execucao")]["id"], "nota"): ("2025-12-20", "PROC-8")}
    # so' a protocolada espera o pagamento: o pedido em analise e o aprovado sem nota nao entram no a receber
    assert [x["numero"] for x in diretoria.a_receber_na_cota(conn)] == [7]
    # o recebimento da carga vai para a auditoria com a origem dela, e nao vale como registro a' mao do administrador
    recebida = ms[(8, "execucao")]["id"]
    depois = [json.loads(r[0]) for r in conn.execute("SELECT depois FROM audit_log WHERE acao='medicao.estado' "
                                                     "AND entidade_id=?", (str(recebida),))]
    assert depois[-1]["estado"] == "recebida" and depois[-1]["origem"] == "carga do histórico"
    assert depois[-1]["recebida_em"] == "2026-01-15" and "extrato de exemplo 8" in depois[-1]["motivo"]
    assert recebida not in conciliacao.recebidas_a_mao(conn)
    criar = json.loads(conn.execute("SELECT depois FROM audit_log WHERE acao='medicao.criar' AND entidade_id=?",
                                    (str(ms[(5, "execucao")]["id"]),)).fetchone()[0])
    assert criar["estado"] == "planilha_enviada" and criar["planilha_enviada_em"] == "2025-09-02"
    # rodar de novo nao muda nada
    antes = _foto(conn)
    rel = carga_medicoes.gravar(conn, _uid(conn), arq)
    assert rel["criadas"] == 0 and rel["totais"]["igual"] == 5 and _foto(conn) == antes


def test_medicao_que_ja_existe_continua_igual_e_nao_muda_de_estado(tmp_path, monkeypatch):
    """O CSV ja' aplicado: a medicao que a carga antiga criou como protocolada, com so' o pedido, nasceria hoje em
    analise. O ensaio diz "igual" e a gravacao nao mexe nela (devolver e' ato da correcao de cadastro)."""
    conn, cid = _com_exemplo_aplicado(tmp_path, monkeypatch)
    conn.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, congelada, "
                 "valor_protocolado_centavos, valor_protocolado_origem) VALUES (?, 5, 'execucao', '2025-08', "
                 "'protocolada', 1, 31207403, 'manual')", (cid,))
    conn.commit()
    arq = _csv(tmp_path, "5;execucao;2025-08;312.074,03;;;;PROC-5;02/09/2025;;;;carta de exemplo 5")
    rel = carga_medicoes.ensaiar(conn, arq)
    assert [li["categoria"] for li in rel["linhas"]] == ["igual"] and "entra_como" not in rel["linhas"][0]
    antes = _foto(conn)
    assert carga_medicoes.gravar(conn, _uid(conn), arq)["criadas"] == 0
    assert _foto(conn) == antes and _medicoes(conn, cid)[(5, "execucao")]["estado"] == "protocolada"


def test_csv_sem_as_colunas_novas_continua_carregando(tmp_path, monkeypatch):
    conn, cid = _com_exemplo_aplicado(tmp_path, monkeypatch)
    arq = tmp_path / "obra-propria.csv"
    arq.write_text("nº;tipo;competência;valor pedido;valor aprovado;NF\n"
                   "5;execucao;2025-08;1.000,01;;\n6;execucao;2025-09;2.000,03;2.000,03;999\n", "utf-8")
    rel = carga_medicoes.gravar(conn, _uid(conn), arq)
    assert rel["criadas"] == 2
    ms = _medicoes(conn, cid)
    assert ms[(5, "execucao")]["estado"] == "planilha_enviada" and ms[(5, "execucao")]["planilha_enviada_em"] is None
    assert ms[(6, "execucao")]["estado"] == "protocolada"        # tem nota na linha (mesmo sem acha-la no RM)


def test_recebimento_sem_fonte_e_data_futura_sao_erro_da_linha(tmp_path, monkeypatch):
    conn, _ = _com_exemplo_aplicado(tmp_path, monkeypatch)
    arq = _csv(tmp_path,
               "8;execucao;2025-11;52.100,09;;;;;;;15/01/2026;;",
               "9;execucao;2025-12;1.000,01;;;;;;;01/01/2999;;fonte",
               "10;execucao;2025-12;1.000,01;;;;;01/01/2999;;;;fonte")
    rel = carga_medicoes.ensaiar(conn, arq)
    assert [li["categoria"] for li in rel["linhas"]] == ["erro", "erro", "erro"]
    assert "recebimento sem fonte" in rel["linhas"][0]["detalhe"]
    assert "data do recebimento não pode ser futura" in rel["linhas"][1]["detalhe"]
    assert "data do envio não pode ser futura" in rel["linhas"][2]["detalhe"]


def test_ensaio_pela_cli_diz_como_a_medicao_nova_entra(tmp_path, monkeypatch, capsys):
    _com_exemplo_aplicado(tmp_path, monkeypatch)
    arq = _csv(tmp_path, "5;execucao;2025-08;312.074,03;;;;;;;;;carta de exemplo 5",
               "6;execucao;2025-09;100.000,01;99.999,99;20/10/2025;SMO;;;;;;boletim de exemplo 6",
               "7;execucao;2025-10;70.000,03;;;;;;25/11/2025;;;protocolo de exemplo 7")
    capsys.readouterr()
    assert cli.main(["cadastro", "carregar-medicoes", str(arq), "--ensaio"]) == 0
    saida = capsys.readouterr().out
    assert "entra como: em análise no órgão (sem a data do envio)" in saida
    assert "entra como: aprovada, à espera da nota" in saida
    assert saida.count("entra como") == 2            # a protocolada entra como sempre entrou
