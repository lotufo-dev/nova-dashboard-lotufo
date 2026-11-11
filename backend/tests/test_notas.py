"""Bloco 3: nota lida do PDF avanca a medicao; conferencia contra o espelho; vinculo manual com o RM."""
import datetime
import json
import pathlib

import pytest

from app import (auth, avisos, cadastro_aplicar, cadastro_arquivos, contratos, db, documentos, espelho,
                 espelhos, medicoes, notas, notas_envio)
from tests import ficticios
from tests.conftest import CADASTRO_EXEMPLO, _pdf_com_texto

FIX = pathlib.Path(__file__).parent / "fixtures" / "nfse"
# O cadastro-exemplo usa os CNPJs ficticios das fixtures (tests/ficticios.py): alfa (empresa propria), beta
# (consorciada) e o orgao A.
CNPJ_PROPRIA, CNPJ_BETA = ficticios.mascara(ficticios.LOTUFO), ficticios.mascara(ficticios.GUAXE)
PDF = _pdf_com_texto("nota")   # qualquer PDF valido: o TEXTO lido e' injetado por `_texto` (monkeypatch)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    c.execute("UPDATE certidao_tipos SET aplicavel_por_padrao=0"); c.commit()
    # A fixture `integra` aplica o cadastro de exemplo, e a lista do orgao exige documentos (bloco 4):
    # este modulo e' sobre notas, entao a exigencia fica vazia.
    monkeypatch.setattr(documentos, "exigidos",
                        lambda conn, cid, natureza: {"entidades": [], "tipos": [], "regularidade": None})
    auth.criar_usuario(c, "U", "u@l.com", "senha-forte-123", "engenharia")
    yield c
    c.close()


@pytest.fixture
def usuario():
    return {"id": 1, "email": "u@l.com"}


@pytest.fixture
def _texto(monkeypatch):
    """Troca a extracao do PDF (pypdf em subprocesso) pelo texto dado. O PDF de mentira do conftest
    e' Helvetica/latin-1 e nao devolve acentos como o pypdf devolve numa nota real; o que se testa
    aqui e' o servico, e a extracao ja' tem teste proprio (test_leitura_pdf)."""
    def fixar(texto: str):
        monkeypatch.setattr(notas.leitura_pdf, "texto_de_pdf_com_limite", lambda pdf: texto)
    return fixar


def _fixture(nome):
    return (FIX / nome).read_text(encoding="utf-8")


def _nota_como(saida: dict, numero: int, base: str = "3102-integra-vg.txt") -> str:
    """Texto de nota real com numero, municipio e valores trocados pelos de uma SAIDA do espelho,
    para a conferencia bater ao centavo (a regra do espelho trunca o ISS onde a nota real arredonda; o teste
    do servico nao pode depender disso)."""
    t = _fixture(base)
    fmt = espelho._fmt
    ret = saida["iss"] + saida["inss"] + saida["irrf"]
    t = t.replace("Número da Nota Fiscal\n3102", f"Número da Nota Fiscal\n{numero}")
    t = t.replace("Várzea Grande", saida["municipio"])
    t = t.replace("R$846.788,31", "R$" + fmt(saida["valor"])).replace("R$ 846.788,31", "R$ " + fmt(saida["valor"]))
    t = t.replace("Vl. ISSQN: R$16.935,77", "Vl. ISSQN: R$" + fmt(saida["iss"]))
    t = t.replace("Vl. IRRF: R$10.161,45", "Vl. IRRF: R$" + fmt(saida["irrf"]))
    t = t.replace("Vl. CP Retido: R$37.258,68", "Vl. CP Retido: R$" + fmt(saida["inss"]))
    t = t.replace("R$64.355,90 R$2.876,20 R$319,58 R$782.432,41 R$782.432,41",
                  f"R${fmt(ret)} R$2.876,20 R$319,58 R${fmt(saida['valor'] - ret)} R${fmt(saida['valor'] - ret)}")
    return t


@pytest.fixture
def integra(conn, usuario):
    """Cadastro de exemplo aplicado, espelho da 12a medicao da Obra Consorcio gerado com o cheio do consorcio.
    Devolve (contrato_id, medicao_execucao_id, saidas_da_empresa_propria) -- duas saidas (Cuiaba e Varzea Grande)."""
    cadastro_aplicar.aplicar(conn, 1, cadastro_arquivos.preparar(CADASTRO_EXEMPLO), ensaio=False)
    cid = conn.execute("SELECT id FROM contratos WHERE nome_curto='Obra Consórcio'").fetchone()[0]
    eid = espelhos.gerar(conn, usuario, cid, 12, "2026-06", {"medicao": 1000000007})      # R$ 10.000.000,07 cheio
    mid = conn.execute("SELECT m.id FROM espelho_medicoes em JOIN medicoes m ON m.id=em.medicao_id "
                       "WHERE em.espelho_id=? AND m.tipo='execucao'", (eid,)).fetchone()[0]
    medicoes.marcar_espelho_enviado(conn, 1, mid)
    saidas = [s for s in espelhos.detalhe(conn, eid)["saidas"] if s["emissor"] == "lotufo" and s["natureza"] == "medicao"]
    assert [(s["municipio"], s["valor"]) for s in saidas] == [("Cuiabá", 300000002), ("Várzea Grande", 200000002)]
    return cid, mid, saidas


def test_esperadas_sao_as_saidas_lotufo_do_espelho(conn, integra):
    _, mid, saidas = integra
    esp = notas.esperadas(conn, mid)
    assert {e["emissor"] for e in esp} == {"lotufo"}
    assert sorted(e["valor"] for e in esp) == sorted(s["valor"] for s in saidas)
    assert all(e["nota_id"] is None for e in esp) and notas.faltam(conn, mid) == 2
    assert notas.coligada_esperada(conn, mid) == 1        # a nota esperada e' da empresa propria, nao do consorcio (90)


def _nf_alocada(conn, mid, coligada, idmov, valor, municipio):
    """NF do RM (coligada dada) ja' alocada a' medicao, sem passar pelo casador (o que se testa e' o casamento)."""
    from app import sincronizacao_rm
    nid = conn.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, valor_centavos, municipio) VALUES (?,?,?,?,?)",
                       (coligada, idmov, f"{idmov:09d}", valor, municipio)).lastrowid
    conn.commit()
    sincronizacao_rm.alocar(conn, 1, nid, mid, "manual", None, "teste")
    return nid


def test_nota_de_outra_coligada_nao_ocupa_a_vaga_da_saida_da_lotufo(conn, integra):
    """Issue #556: a fatura do consorcio (coligada 90) no municipio da saida da Lotufo, ou com o valor exato dela, nao
    atende a saida: as duas continuam faltando ate' chegar a nota da coligada da Lotufo."""
    _, mid, saidas = integra
    cuiaba = next(s for s in saidas if s["municipio"] == "Cuiabá")
    _nf_alocada(conn, mid, 90, 501, 1000000007, "Várzea Grande")         # mesmo municipio da saida de VG
    _nf_alocada(conn, mid, 90, 502, cuiaba["valor"], None)                  # mesmo valor da saida de Cuiaba
    assert notas.faltam(conn, mid) == 2
    assert medicoes.detalhe(conn, mid)["notas_faltam"] == 2
    assert {n["da_cota"] for n in medicoes.detalhe(conn, mid)["notas"]} == {False}


def test_da_cota_so_nas_notas_que_atendem_as_saidas_da_lotufo(conn, integra):
    """Issue #556: a nota da Lotufo que atende a saida entra na cota; a extra (sem saida) fica fora."""
    _, mid, saidas = integra
    vg = next(s for s in saidas if s["municipio"] == "Várzea Grande")
    certa = _nf_alocada(conn, mid, 1, 601, vg["valor"], "Várzea Grande")
    extra = _nf_alocada(conn, mid, 1, 602, 12345, "Sinop")
    d = medicoes.detalhe(conn, mid)
    assert d["notas_faltam"] == 1                                           # falta a de Cuiaba
    assert {n["nota_id"]: n["da_cota"] for n in d["notas"]} == {certa: True, extra: False}


def _titulo(conn, nota_id, idlan, original, baixado, status=1):
    """Titulo a receber do RM (liquido) da nota; status 1 baixado, 4 parcial, 0 aberto."""
    conn.execute("INSERT INTO baixas (coligada, idlan, nota_id, valor_original_centavos, valor_baixado_centavos, status_lan, "
                 "data_baixa) VALUES (1,?,?,?,?,?,?)", (idlan, nota_id, original, baixado, status, "2026-09-01" if baixado else None))
    conn.commit()


def _cota(conn, mid):
    from app import sincronizacao_rm
    return sincronizacao_rm.pagamento_cota(conn, mid)


def test_pagamento_cota_consorcio_com_nota_extra_de_outra_coligada(conn, integra):
    """(a) A fatura do consorcio (coligada 90), paga, nao entra: so' as duas notas da Lotufo que atendem as saidas,
    contra os titulos (liquidos, com centavo impar)."""
    _, mid, saidas = integra
    cuiaba, vg = (next(s for s in saidas if s["municipio"] == m) for m in ("Cuiabá", "Várzea Grande"))
    n1 = _nf_alocada(conn, mid, 1, 701, cuiaba["valor"], "Cuiabá")
    n2 = _nf_alocada(conn, mid, 1, 702, vg["valor"], "Várzea Grande")
    fatura = _nf_alocada(conn, mid, 90, 703, 1000000007, "Várzea Grande")
    _titulo(conn, n1, 1, 276000001, 276000001)
    _titulo(conn, n2, 2, 184000001, 0, 0)
    conn.execute("INSERT INTO baixas (coligada, idlan, nota_id, valor_original_centavos, valor_baixado_centavos, status_lan) "
                 "VALUES (90, 3, ?, 920000007, 920000007, 1)", (fatura,)); conn.commit()
    assert _cota(conn, mid) == {"notas_faltam": 0, "completo": True, "total_centavos": 460000002,
                                "recebido_centavos": 276000001, "falta_centavos": 184000001, "parcial": True, "falta_divergente_centavos": 0}
    assert medicoes.detalhe(conn, mid)["pagamento_cota"]["falta_centavos"] == 184000001


def test_pagamento_cota_e_notas_coerentes_com_titulo_baixado_sem_valor(conn, integra):
    """Issue #563: titulo com baixa total (status 1) e valor baixado zero nao e' recebimento na pagina da medicao: o
    resumo da cota e a linha da nota dizem o mesmo (recebido 0, falta o titulo inteiro), com centavo impar."""
    _, mid, saidas = integra
    cuiaba, vg = (next(s for s in saidas if s["municipio"] == m) for m in ("Cuiabá", "Várzea Grande"))
    n1 = _nf_alocada(conn, mid, 1, 741, cuiaba["valor"], "Cuiabá")
    n2 = _nf_alocada(conn, mid, 1, 742, vg["valor"], "Várzea Grande")
    _titulo(conn, n1, 41, 276000001, 0, 1)                  # baixa total sem valor
    _titulo(conn, n2, 42, 184000001, 184000001)
    assert _cota(conn, mid) == {"notas_faltam": 0, "completo": True, "total_centavos": 460000002,
                                "recebido_centavos": 184000001, "falta_centavos": 276000001, "parcial": True, "falta_divergente_centavos": 0}
    linhas = {n["nota_id"]: (n["recebido_centavos"], n["falta_centavos"]) for n in medicoes.detalhe(conn, mid)["notas"]}
    assert linhas == {n1: (0, 276000001), n2: (184000001, 0)}
    assert sum(r for r, _ in linhas.values()) == 184000001 and sum(f for _, f in linhas.values()) == 276000001


def test_pagamento_cota_espelho_sem_saida_da_lotufo_e_zero_e_nao_traco(conn, integra):
    """(b) Espelho vigente sem saida da Lotufo nesta natureza: nada a esperar dela (zero), e nenhuma nota alocada
    entra na cota nem conta como esperada (antes caia no caso "sem espelho")."""
    _, mid, _ = integra
    row = conn.execute("SELECT e.id, e.saidas FROM espelhos e JOIN espelho_medicoes em ON em.espelho_id=e.id "
                       "WHERE em.medicao_id=? AND e.situacao='vigente'", (mid,)).fetchone()
    saidas = [{**sd, "emissor": "beta"} for sd in json.loads(row["saidas"])]
    conn.execute("UPDATE espelhos SET saidas=? WHERE id=?", (json.dumps(saidas), row["id"])); conn.commit()
    extra = _nf_alocada(conn, mid, 1, 711, 12345, "Cuiabá")
    _titulo(conn, extra, 11, 11000, 11000)
    assert _cota(conn, mid) == {"notas_faltam": 0, "completo": True, "total_centavos": 0, "recebido_centavos": 0,
                                "falta_centavos": 0, "parcial": False, "falta_divergente_centavos": 0}
    assert notas.faltam(conn, mid) == 0
    assert [n["da_cota"] for n in medicoes.detalhe(conn, mid)["notas"]] == [False]


def test_pagamento_cota_sem_espelho_nao_se_sabe(conn, usuario, _texto):
    """(c) Medicao sem espelho vigente: None (a tela mostra "—")."""
    cid = contratos.criar(conn, 1, {"orgao": "SINFRA", "numero_instrumento": "IC 1/2026", "objeto": "Obra",
                                    "valor_original_centavos": 10_000_000_00})
    mid = medicoes.criar(conn, 1, {"contrato_id": cid, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    assert _cota(conn, mid) is None


def test_pagamento_cota_nota_sem_titulo_no_rm(conn, integra):
    """(d) Nota da cota ainda sem titulo no RM: os valores nao fecham (None), notas_faltam zero; a baixa ja' conhecida
    da outra nota deixa `parcial`."""
    _, mid, saidas = integra
    cuiaba, vg = (next(s for s in saidas if s["municipio"] == m) for m in ("Cuiabá", "Várzea Grande"))
    n1 = _nf_alocada(conn, mid, 1, 721, cuiaba["valor"], "Cuiabá")
    _nf_alocada(conn, mid, 1, 722, vg["valor"], "Várzea Grande")
    _titulo(conn, n1, 21, 276000001, 276000001)
    assert _cota(conn, mid) == {"notas_faltam": 0, "completo": False, "total_centavos": None, "recebido_centavos": None,
                                "falta_centavos": None, "parcial": True, "falta_divergente_centavos": None}


def test_pagamento_cota_nota_extra_paga_nao_faz_parcial(conn, integra):
    """(e) Nota extra da Lotufo (sem saida) paga, com as notas da cota em aberto: nada recebido da cota, sem parcial."""
    _, mid, saidas = integra
    cuiaba, vg = (next(s for s in saidas if s["municipio"] == m) for m in ("Cuiabá", "Várzea Grande"))
    n1 = _nf_alocada(conn, mid, 1, 731, cuiaba["valor"], "Cuiabá")
    n2 = _nf_alocada(conn, mid, 1, 732, vg["valor"], "Várzea Grande")
    extra = _nf_alocada(conn, mid, 1, 733, 12345, "Sinop")
    _titulo(conn, n1, 31, 276000001, 0, 0)
    _titulo(conn, n2, 32, 184000001, 0, 0)
    _titulo(conn, extra, 33, 11000, 11000)
    assert _cota(conn, mid) == {"notas_faltam": 0, "completo": True, "total_centavos": 460000002, "recebido_centavos": 0,
                                "falta_centavos": 460000002, "parcial": False, "falta_divergente_centavos": 0}


def test_pagamento_cota_par_com_a_metade_cancelada(conn, integra):
    """(f) O resumo cobre a medicao e a irma valida do par: o reajuste ainda sem espelho deixa os valores em "—", mas a
    baixa ja' recebida na execucao aparece como `parcial` (revisor, rodada 4: antes o bloco inteiro vinha nulo e a tela
    dizia "Aguardando o órgão" com dinheiro recebido); cancelado, sai do grupo e o resumo e' so' o da execucao (o mesmo
    pela pagina de qualquer das duas que esteja valida)."""
    cid, mid, saidas = integra
    for s, idmov, idlan in zip(saidas, (741, 742), (41, 42)):
        n = _nf_alocada(conn, mid, 1, idmov, s["valor"], s["municipio"])
        _titulo(conn, n, idlan, s["valor"] - 1001, s["valor"] - 1001)
    reaj = medicoes.criar(conn, 1, {"contrato_id": cid, "numero": 12, "tipo": "reajuste", "competencia": "2026-06"})
    incompleto = {"notas_faltam": 0, "completo": False, "total_centavos": None, "recebido_centavos": None,
                  "falta_centavos": None, "parcial": True, "falta_divergente_centavos": None}
    assert _cota(conn, mid) == incompleto                                 # irma valida sem espelho: valores nao fecham
    assert _cota(conn, reaj) == incompleto                                # pela pagina do reajuste, o mesmo resumo
    medicoes.mudar_estado(conn, 1, reaj, "cancelada", "teste")
    total = sum(s["valor"] - 1001 for s in saidas)
    assert _cota(conn, mid) == {"notas_faltam": 0, "completo": True, "total_centavos": total, "recebido_centavos": total,
                                "falta_centavos": 0, "parcial": False, "falta_divergente_centavos": 0}


def _espelho_sem_saida_da_lotufo(conn, mid):
    row = conn.execute("SELECT e.id, e.saidas FROM espelhos e JOIN espelho_medicoes em ON em.espelho_id=e.id "
                       "WHERE em.medicao_id=? AND e.situacao='vigente'", (mid,)).fetchone()
    saidas = [{**sd, "emissor": "beta"} for sd in json.loads(row["saidas"])]
    conn.execute("UPDATE espelhos SET saidas=? WHERE id=?", (json.dumps(saidas), row["id"])); conn.commit()


def test_espelho_sem_saida_da_lotufo_espera_a_fatura_e_fecha_com_a_data_dela(conn, integra):
    """Rodada 5 da PR #555 (revisor + Sol): com espelho vigente sem saida da Lotufo nesta natureza, a medicao nao fecha
    sem nota (`faltam` dava zero, `nota_emitida_em` saia nulo e a medicao sumia do faturado do mes; e sem ninguem chamar
    o fechamento ela ficava em `espelho_enviado`): fecha quando a fatura do consorcio e' alocada, com a emissao dela,
    e a cota da Lotufo segue zero, sem nota `da_cota`."""
    _, mid, _ = integra
    _espelho_sem_saida_da_lotufo(conn, mid)
    assert notas.faltam(conn, mid) == 1
    assert notas.fechar_se_completa(conn, 1, mid) is False
    assert medicoes.detalhe(conn, mid)["estado"] == "espelho_enviado"
    conn.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, valor_centavos, emissao) VALUES (90, 761, '22', 1000000007, '2026-08-30')")
    conn.commit()
    from app import sincronizacao_rm
    fatura = conn.execute("SELECT id FROM notas_fiscais WHERE idmov=761").fetchone()[0]
    sincronizacao_rm.alocar(conn, 1, fatura, mid, "manual", None, "teste")
    m = medicoes.detalhe(conn, mid)
    assert (m["estado"], m["nota_emitida_em"], m["notas_faltam"]) == ("nota_emitida", "2026-08-30", 0)
    assert [n["da_cota"] for n in m["notas"]] == [False]
    assert m["pagamento_cota"] == {"notas_faltam": 0, "completo": True, "total_centavos": 0, "recebido_centavos": 0,
                                   "falta_centavos": 0, "parcial": False, "falta_divergente_centavos": 0}


def test_sem_coligada_da_lotufo_no_cadastro_nenhuma_nota_atende_a_saida(conn, integra):
    """Gate Sol, rodada 4 da PR #555: sem a coligada da Lotufo no cadastro nao da' para separar a nota dela da fatura
    do consorcio; falha fechado (saidas faltando, valores em "—", nenhuma nota na cota), em vez de aceitar qualquer
    coligada e somar a fatura paga como recebido da Lotufo."""
    _, mid, saidas = integra
    cuiaba = next(s for s in saidas if s["municipio"] == "Cuiabá")
    n = _nf_alocada(conn, mid, 1, 771, cuiaba["valor"], "Cuiabá")
    _nf_alocada(conn, mid, 90, 772, 1000000007, "Cuiabá")
    _titulo(conn, n, 71, cuiaba["valor"] - 1, cuiaba["valor"] - 1)
    assert notas.faltam(conn, mid) == 1 and _cota(conn, mid)["parcial"] is True
    conn.execute("UPDATE entidades SET coligada_rm=NULL WHERE coligada_rm=1"); conn.commit()
    assert notas._coligada_lotufo(conn) is None
    assert notas.faltam(conn, mid) == 2
    assert _cota(conn, mid) == {"notas_faltam": 2, "completo": False, "total_centavos": None, "recebido_centavos": None,
                                "falta_centavos": None, "parcial": False, "falta_divergente_centavos": None}
    assert {x["da_cota"] for x in medicoes.detalhe(conn, mid)["notas"]} == {False}


def test_nota_emitida_tem_a_data_das_notas_da_cota(conn, usuario, integra, _texto):
    """Gate Sol, PR #555: a fatura do consorcio emitida depois nao muda a data de "nota emitida"."""
    _, mid, saidas = integra
    conn.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, valor_centavos, emissao) VALUES (90, 751, '21', 1000000007, '2026-08-30')")
    conn.commit()
    from app import sincronizacao_rm
    fatura = conn.execute("SELECT id FROM notas_fiscais WHERE idmov=751").fetchone()[0]
    sincronizacao_rm.alocar(conn, 1, fatura, mid, "manual", None, "teste")
    for s, numero in zip(saidas, (3101, 3102)):
        _texto(_nota_como(s, numero))
        notas.anexar_pdf(conn, usuario, mid, PDF, f"NFS {numero}.pdf")
    m = medicoes.detalhe(conn, mid)
    assert m["estado"] == "nota_emitida"
    emissoes = [n["emissao"] for n in m["notas"] if n["da_cota"]]
    assert m["nota_emitida_em"] == max(emissoes) and m["nota_emitida_em"] < "2026-08-30"


def test_esperadas_trazem_o_rotulo_da_saida(conn, integra):
    _, mid, _ = integra
    esp = notas.esperadas(conn, mid)
    assert esp and all(e["rotulo"] == "Medição" for e in esp)       # sem rotulo no espelho, o da natureza
    # rotulo proprio da saida (espelho) vence o da natureza
    row = conn.execute("SELECT e.id, e.saidas FROM espelhos e JOIN espelho_medicoes em ON em.espelho_id=e.id "
                       "WHERE em.medicao_id=? AND e.situacao='vigente'", (mid,)).fetchone()
    saidas = json.loads(row["saidas"])
    for sd in saidas:
        sd["rotulo"] = "Medição 12"
    conn.execute("UPDATE espelhos SET saidas=? WHERE id=?", (json.dumps(saidas), row["id"]))
    assert all(e["rotulo"] == "Medição 12" for e in notas.esperadas(conn, mid))


def test_pdf_lido_vincula_confere_e_nao_fecha_enquanto_falta_nota(conn, usuario, integra, _texto):
    _, mid, saidas = integra
    vg = next(s for s in saidas if s["municipio"] == "Várzea Grande")
    _texto(_nota_como(vg, 3102))
    r = notas.anexar_pdf(conn, usuario, mid, PDF, "15-07-26 NFS 3102 12° MED INTEGRA BRT VG LOTUFO.pdf")
    assert r["leitura"]["ok"] and r["nota_id"] is not None
    assert r["conferencia"] == []                    # valor, ISS, INSS, IRRF, municipio e tomador batem
    assert r["faltam"] == 1 and r["estado"] == "espelho_enviado"
    nf = conn.execute("SELECT * FROM notas_fiscais WHERE id=?", (r["nota_id"],)).fetchone()
    assert (nf["origem"], nf["idmov"], nf["coligada"], nf["numero_int"], nf["confirmacao"]) == ("pdf", None, 1, 3102, "aguardando_rm")
    assert nf["valor_centavos"] == vg["valor"] and nf["valor_pdf_centavos"] == vg["valor"]
    assert nf["tomador_cnpj"] == "31300101000101" and nf["leitura"] == "cuiaba"
    doc = conn.execute("SELECT tipo_doc, fonte, numero_nf, municipio, arquivo FROM medicao_documentos WHERE id=?", (r["documento_id"],)).fetchone()
    assert (doc["tipo_doc"], doc["fonte"], doc["numero_nf"], doc["municipio"]) == ("nfs", "operacao", "3102", "Várzea Grande")
    assert doc["arquivo"].startswith("notas/")
    assert medicoes.detalhe(conn, mid)["notas"][0]["confirmacao"] == "aguardando_rm"


def test_segunda_nota_fecha_nota_emitida_com_a_maior_emissao(conn, usuario, integra, _texto):
    _, mid, saidas = integra
    vg = next(s for s in saidas if s["municipio"] == "Várzea Grande")
    cba = next(s for s in saidas if s["municipio"] == "Cuiabá")
    _texto(_nota_como(vg, 3102))
    notas.anexar_pdf(conn, usuario, mid, PDF, "a.pdf")
    # a nota de Cuiaba com o ISS errado em um centavo: vincula, fecha a medicao e registra o arredondamento
    t = _nota_como(cba, 2222).replace("Vl. ISSQN: R$" + espelho._fmt(cba["iss"]), "Vl. ISSQN: R$" + espelho._fmt(cba["iss"] + 1))
    _texto(t.replace("15/07/2026 17:43:46", "16/07/2026 09:00:00"))
    r = notas.anexar_pdf(conn, usuario, mid, _pdf_com_texto("outra"), "b.pdf")
    assert r["faltam"] == 0 and r["estado"] == "nota_emitida"
    assert medicoes.detalhe(conn, mid)["nota_emitida_em"] == "2026-07-16"
    assert [(d["campo"], d["grau"]) for d in r["conferencia"]] == [("iss", "arredondamento")]


def test_execucao_fecha_sem_esperar_o_reajuste_da_mesma_competencia(conn, usuario, integra, _texto):
    """Issue #188 (opcao A): cada medicao fecha com as notas dela e a data delas; a espera pelo reajuste fica no envio."""
    cid, mid, saidas = integra
    conn.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado) "
                 "VALUES (?, 12, 'reajuste', '2026-06', 'espelho_enviado')", (cid,))
    conn.commit()
    reaj = conn.execute("SELECT MAX(id) FROM medicoes").fetchone()[0]
    _texto(_nota_como(saidas[0], 2221))
    notas.anexar_pdf(conn, usuario, mid, PDF, "a.pdf")
    _texto(_nota_como(saidas[1], 2222))
    r = notas.anexar_pdf(conn, usuario, mid, _pdf_com_texto("outra"), "b.pdf")
    assert r["faltam"] == 0 and r["estado"] == "nota_emitida"
    assert medicoes.detalhe(conn, mid)["nota_emitida_em"] == "2026-07-15"
    assert medicoes.detalhe(conn, reaj)["estado"] == "espelho_enviado"
    # o orgao do exemplo (SINFRA) junta medicao e reajuste: a execucao pronta espera as notas do reajuste
    assert notas_envio.espera(conn, medicoes.detalhe(conn, mid))["medicao_id"] == reaj


def test_nota_repetida_nao_duplica(conn, usuario, integra, _texto):
    _, mid, saidas = integra
    _texto(_nota_como(saidas[1], 3102))
    a = notas.anexar_pdf(conn, usuario, mid, PDF, "a.pdf")
    b = notas.anexar_pdf(conn, usuario, mid, PDF, "a (1).pdf")
    assert b["repetido"] and b["nota_id"] == a["nota_id"]
    assert conn.execute("SELECT COUNT(*) FROM notas_fiscais").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM nf_alocacoes WHERE desfeita_em IS NULL").fetchone()[0] == 1


def test_pdf_sem_texto_pede_digitacao_e_manual_vincula(conn, usuario, integra, _texto):
    _, mid, saidas = integra
    _texto("")
    r = notas.anexar_pdf(conn, usuario, mid, PDF, "sem-texto.pdf")
    assert r["leitura"]["ok"] is False and r["leitura"]["motivo"] == "sem-texto" and r["nota_id"] is None
    with pytest.raises(ValueError):
        notas.registrar_manual(conn, usuario, mid, r["documento_id"], 0, "2026-07-15", 1)
    r2 = notas.registrar_manual(conn, usuario, mid, r["documento_id"], 3102, "2026-07-15", saidas[1]["valor"])
    nf = conn.execute("SELECT origem, leitura, numero_int, valor_centavos FROM notas_fiscais WHERE id=?", (r2["nota_id"],)).fetchone()
    assert tuple(nf) == ("pdf", "manual", 3102, saidas[1]["valor"])
    assert r2["conferencia"] == [] and r2["faltam"] == 1          # manual so' confere o valor (bate)
    assert conn.execute("SELECT numero_nf FROM medicao_documentos WHERE id=?", (r["documento_id"],)).fetchone()[0] == "3102"


def test_nota_de_consorciada_e_so_documento(conn, usuario, integra, _texto):
    _, mid, _ = integra
    _texto(_fixture("3102-integra-vg.txt").replace(CNPJ_PROPRIA, CNPJ_BETA))
    r = notas.anexar_pdf(conn, usuario, mid, PDF, "NFS 202681 - GRUPO GUAXE.pdf")
    assert r["nota_id"] is None and r["leitura"]["ok"]
    doc = conn.execute("SELECT consorciada, numero_nf FROM medicao_documentos WHERE id=?", (r["documento_id"],)).fetchone()
    assert (doc["consorciada"], doc["numero_nf"]) == ("Engenharia Beta S.A.", "3102")
    assert notas.faltam(conn, mid) == 2


def test_frc_e_documento_sem_leitura(conn, usuario, integra, _texto):
    _, mid, _ = integra
    _texto("qualquer coisa")
    # issue #169: com a FRC pela dashboard, a assinada so' entra sobre a FRC gerada (test_frc); aqui, sem ela
    with pytest.raises(ValueError, match="Gere a FRC na etapa 3"):
        notas.anexar_pdf(conn, usuario, mid, PDF, "FRC 19.pdf", tipo_doc="fatura")
    # rodada 3 da PR #179 (decisao de produto): consorcio sem a FRC no cadastro nao aceita a feita a' mao
    conn.execute("DELETE FROM frc_consorcios"); conn.commit()
    with pytest.raises(ValueError, match="A FRC deste consórcio não está no cadastro"):
        notas.anexar_pdf(conn, usuario, mid, PDF, "FRC 19 - CONSÓRCIO INTEGRA BRT (12° MEDIÇÃO).pdf", tipo_doc="fatura")
    assert conn.execute("SELECT COUNT(*) FROM medicao_documentos WHERE tipo_doc='fatura'").fetchone()[0] == 0
    with pytest.raises(ValueError):
        notas.anexar_pdf(conn, usuario, mid, PDF, "x.pdf", tipo_doc="espelho")


def test_declarar_completa_exige_nota_e_justificativa(conn, usuario, integra, _texto):
    _, mid, saidas = integra
    with pytest.raises(ValueError):
        notas.declarar_completa(conn, usuario, mid, "so' uma nota este mes")
    _texto(_nota_como(saidas[1], 3102))
    notas.anexar_pdf(conn, usuario, mid, PDF, "a.pdf")
    with pytest.raises(ValueError):
        notas.declarar_completa(conn, usuario, mid, "  ")
    notas.declarar_completa(conn, usuario, mid, "Cuiabá não teve serviço em junho")
    m = medicoes.detalhe(conn, mid)
    assert m["estado"] == "nota_emitida" and m["nota_emitida_em"] == "2026-07-15"
    assert m["motivo_represamento"].startswith("notas declaradas completas")


def test_avisos_divergente_ausente_do_rm_e_cancelada(conn, usuario, integra, _texto):
    _, mid, saidas = integra
    vg = saidas[1]
    # 1 centavo no ISS e' arredondamento do portal: fica na conferencia, nao vira aviso
    _texto(_nota_como(vg, 3102).replace("Vl. ISSQN: R$" + espelho._fmt(vg["iss"]), "Vl. ISSQN: R$" + espelho._fmt(vg["iss"] + 1)))
    r = notas.anexar_pdf(conn, usuario, mid, PDF, "a.pdf")
    assert [d["grau"] for d in r["conferencia"]] == ["arredondamento"]
    assert notas.avisos(conn, datetime.date(2026, 9, 22)) == []
    # 2 reais no ISS e' divergencia de verdade
    _texto(_nota_como(vg, 3102).replace("Vl. ISSQN: R$" + espelho._fmt(vg["iss"]), "Vl. ISSQN: R$" + espelho._fmt(vg["iss"] + 200)))
    conn.execute("UPDATE nf_alocacoes SET desfeita_em=datetime('now'), motivo_desfazer='teste' WHERE medicao_id=?", (mid,)); conn.commit()
    r = notas.anexar_pdf(conn, usuario, mid, _pdf_com_texto("de novo"), "b.pdf")
    av = notas.avisos(conn, datetime.date(2026, 9, 22))
    assert [a["tipo"] for a in av] == ["nota_divergente"] and av[0]["mensagem"] == "nota 3102 diverge do espelho: ISS"
    assert [a["nivel"] for a in avisos._de_notas(conn, datetime.date(2026, 9, 22))] == ["critico"]   # D10
    notas.justificar(conn, usuario, r["nota_id"], "ISS arredondado pela prefeitura")
    assert notas.avisos(conn, datetime.date(2026, 9, 22)) == []
    medicoes.registrar_protocolo(conn, 1, mid, "2026-09-10", "CT-1", None, "manual")
    av = notas.avisos(conn, datetime.date(2026, 9, 22))
    assert [a["tipo"] for a in av] == ["nota_ausente_rm"] and av[0]["dias"] == 12
    assert notas.avisos(conn, datetime.date(2026, 9, 14)) == []       # 4 dias: ainda nao
    # nota cancelada no RM sem substituta: aviso proprio
    conn.execute("UPDATE nf_alocacoes SET desfeita_em=datetime('now', '+1 second'), motivo_desfazer=? "
                 "WHERE medicao_id=? AND desfeita_em IS NULL", (notas.MOTIVO_CANCELADA_RM, mid)); conn.commit()
    assert [a["tipo"] for a in notas.avisos(conn, datetime.date(2026, 9, 22))] == ["nota_cancelada_rm"]


def test_medicao_sem_espelho_so_confere_o_valor(conn, usuario, _texto):
    cid = contratos.criar(conn, 1, {"orgao": "SINFRA", "numero_instrumento": "IC 099/2025", "objeto": "Obra",
                                    "valor_original_centavos": 10_000_000_00})
    mid = medicoes.criar(conn, 1, {"contrato_id": cid, "numero": 3, "tipo": "execucao", "competencia": "2026-06"})
    medicoes.definir_valor(conn, 1, mid, "protocolado", 84678831, "manual")
    _texto(_fixture("3102-integra-vg.txt"))
    r = notas.anexar_pdf(conn, usuario, mid, PDF, "a.pdf")
    assert r["nota_id"] is not None and r["conferencia"] == [] and r["estado"] == "prevista"
    assert notas.faltam(conn, mid) == 0
    # valor diferente: divergencia de valor, sem espelho
    medicoes.definir_valor(conn, 1, mid, "atestado", 84678830, "manual")
    _texto(_fixture("3102-integra-vg.txt"))
    conn.execute("UPDATE nf_alocacoes SET desfeita_em=datetime('now'), motivo_desfazer='teste'"); conn.commit()
    r = notas.anexar_pdf(conn, usuario, mid, _pdf_com_texto("outro"), "b.pdf")
    assert [(d["campo"], d["grau"]) for d in r["conferencia"]] == [("valor", "divergente")]


def test_danfse_3106_confere_com_o_espelho_da_obra_propria(conn, usuario, _texto):
    """Nota do emissor nacional (DANFSe) contra a regra da Obra Propria do cadastro de exemplo: valor, ISS,
    INSS, IRRF, municipio e tomador (CNPJ do orgao no cadastro) batem ao centavo; a medicao fecha
    `nota_emitida` com a emissao."""
    cadastro_aplicar.aplicar(conn, 1, cadastro_arquivos.preparar(CADASTRO_EXEMPLO), ensaio=False)
    cid = conn.execute("SELECT id FROM contratos WHERE nome_curto='Obra Própria'").fetchone()[0]
    eid = espelhos.gerar(conn, usuario, cid, 27, "2026-08", {"medicao": 71919072})
    mid = conn.execute("SELECT m.id FROM espelho_medicoes em JOIN medicoes m ON m.id=em.medicao_id "
                       "WHERE em.espelho_id=? AND m.tipo='execucao'", (eid,)).fetchone()[0]
    _texto(_fixture("3106-mt402-danfse.txt").replace("Cuiabá", "Rondonópolis"))     # o municipio da saida do exemplo
    r = notas.anexar_pdf(conn, usuario, mid, PDF, "14-09-26 NFS 3106 27° MED PAVIMENTAÇÃO MT-402.pdf")
    assert r["leitura"]["leiaute"] == "danfse" and r["conferencia"] == []
    assert (r["faltam"], r["estado"]) == (0, "nota_emitida")
    assert medicoes.detalhe(conn, mid)["nota_emitida_em"] == "2026-09-14"
    assert conn.execute("SELECT leitura, cbs_centavos, ibs_centavos FROM notas_fiscais WHERE id=?",
                        (r["nota_id"],)).fetchone()[:] == ("danfse", 244280, 27142)


def test_do_contrato_traz_as_saidas_com_a_nota_de_cada_uma(conn, usuario, integra, _texto):
    cid, mid, saidas = integra
    vg = next(s for s in saidas if s["municipio"] == "Várzea Grande")
    _texto(_nota_como(vg, 3102))
    notas.anexar_pdf(conn, usuario, mid, PDF, "NFS 3102.pdf")
    linha = next(x for x in notas.do_contrato(conn, cid) if x["medicao_id"] == mid)
    por_municipio = {s["municipio"]: s["nota"] for s in linha["saidas"]}
    assert por_municipio["Várzea Grande"]["numero"] == 3102 and por_municipio["Várzea Grande"]["situacao"] == "aguardando_rm"
    assert por_municipio["Cuiabá"] is None and linha["titulo"] == "12ª Medição"


def test_do_contrato_diz_qual_campo_diverge_com_esperado_e_lido(conn, usuario, integra, _texto):
    """G3-11: a nota divergente traz SO' o campo que diverge (ISS 2 reais a mais), com o do espelho e o lido;
    o arredondamento de 1 centavo no ISS nao e' divergencia e nao aparece."""
    cid, mid, saidas = integra
    cba, vg = saidas
    iss = lambda s, mais: "Vl. ISSQN: R$" + espelho._fmt(s["iss"] + mais)    # noqa: E731
    _texto(_nota_como(vg, 3102).replace(iss(vg, 0), iss(vg, 200)))
    notas.anexar_pdf(conn, usuario, mid, PDF, "NFS 3102.pdf")
    _texto(_nota_como(cba, 2224).replace(iss(cba, 0), iss(cba, 1)))
    notas.anexar_pdf(conn, usuario, mid, _pdf_com_texto("cba"), "NFS 2224.pdf")
    linha = next(x for x in notas.do_contrato(conn, cid) if x["medicao_id"] == mid)
    por_municipio = {s["municipio"]: s["nota"] for s in linha["saidas"]}
    assert por_municipio["Várzea Grande"]["situacao"] == "divergente"
    assert por_municipio["Várzea Grande"]["divergencias"] == [{"campo": "iss", "esperado": vg["iss"], "lido": vg["iss"] + 200}]
    assert por_municipio["Cuiabá"]["situacao"] == "aguardando_rm" and por_municipio["Cuiabá"]["divergencias"] == []


def _com_liquido(texto: str, saida: dict, liquido: int) -> str:
    """Troca o liquido impresso (linha de totais do leiaute Cuiaba) pelo dado."""
    fmt = espelho._fmt
    antes = saida["valor"] - saida["iss"] - saida["inss"] - saida["irrf"]
    return texto.replace(f"R$319,58 R${fmt(antes)} R${fmt(antes)}", f"R$319,58 R${fmt(liquido)} R${fmt(liquido)}")


def test_liquido_diferente_sozinho_e_divergencia(conn, usuario, integra, _texto):
    """Revisao da PR #97: ISS nao retido na nota (o espelho o retem) deixa valor e tributos iguais e so' o
    liquido R$ 50,00 maior -- tem que aparecer como divergencia do liquido."""
    cid, mid, saidas = integra
    vg = saidas[1]
    _texto(_com_liquido(_nota_como(vg, 3102), vg, vg["liquido"] + 5000))
    r = notas.anexar_pdf(conn, usuario, mid, PDF, "NFS 3102.pdf")
    assert r["conferencia"] == [{"campo": "liquido", "espelho": vg["liquido"], "nota": vg["liquido"] + 5000,
                                 "grau": "divergente"}]
    linha = next(x for x in notas.do_contrato(conn, cid) if x["medicao_id"] == mid)
    nota = next(s["nota"] for s in linha["saidas"] if s["municipio"] == "Várzea Grande")
    assert nota["divergencias"] == [{"campo": "liquido", "esperado": vg["liquido"], "lido": vg["liquido"] + 5000}]


def test_liquido_tolera_a_soma_dos_arredondamentos_dos_tributos(conn, usuario, integra, _texto):
    """1 centavo a mais no ISS e no IRRF tira 2 centavos do liquido: arredondamento, nao divergencia.
    Um centavo alem disso no liquido ja' e' divergencia."""
    _, mid, saidas = integra
    vg = saidas[1]
    fmt = espelho._fmt
    t = (_nota_como(vg, 3102).replace("Vl. ISSQN: R$" + fmt(vg["iss"]), "Vl. ISSQN: R$" + fmt(vg["iss"] + 1))
         .replace("Vl. IRRF: R$" + fmt(vg["irrf"]), "Vl. IRRF: R$" + fmt(vg["irrf"] + 1)))
    _texto(_com_liquido(t, vg, vg["liquido"] - 2))
    r = notas.anexar_pdf(conn, usuario, mid, PDF, "a.pdf")
    assert [(d["campo"], d["grau"]) for d in r["conferencia"]] == [
        ("iss", "arredondamento"), ("irrf", "arredondamento"), ("liquido", "arredondamento")]
    conn.execute("UPDATE nf_alocacoes SET desfeita_em=datetime('now'), motivo_desfazer='teste' WHERE medicao_id=?", (mid,)); conn.commit()
    _texto(_com_liquido(t, vg, vg["liquido"] - 3))
    r = notas.anexar_pdf(conn, usuario, mid, _pdf_com_texto("de novo"), "b.pdf")
    assert [(d["campo"], d["grau"]) for d in r["conferencia"]][-1] == ("liquido", "divergente")
    av = notas.avisos(conn, datetime.date(2026, 9, 22))
    assert [a["mensagem"] for a in av] == ["nota 3102 diverge do espelho: líquido"]     # nome na tela, nao o do banco


# saida de espelho com ISS descontado do liquido (100.000,00 - 20,00 - 30,00 - 10,00) e sem (o ISS nao desconta)
_SAIDA = {"valor": 10000000, "iss": 2000, "inss": 3000, "irrf": 1000, "ibs": None, "cbs": None, "liquido": 9994000}
_SAIDA_ISS_NAO_DESCONTA = {**_SAIDA, "liquido": 9996000}


@pytest.mark.parametrize("saida, iss, irrf, liquido, grau", [
    (_SAIDA, +1, +1, -2, "arredondamento"),          # tributos 2 centavos acima: liquido 2 abaixo
    (_SAIDA, +1, +1, +2, "divergente"),              # liquido 2 ACIMA nao e' efeito dos tributos
    (_SAIDA, +1, -1, +2, "divergente"),              # ISS e IRRF se anulam: liquido fora e' divergencia
    (_SAIDA, +1, -1, 0, None),                       # ...e liquido igual confere
    (_SAIDA_ISS_NAO_DESCONTA, +1, 0, -1, "divergente"),   # ISS que nao desconta nao da' tolerancia
    (_SAIDA_ISS_NAO_DESCONTA, +1, +1, -1, "arredondamento"),
])
def test_liquido_tolera_so_o_efeito_com_sinal_dos_tributos(saida, iss, irrf, liquido, grau):
    """Gate Sol S4 (PR #97): o liquido aceita exatamente o efeito dos arredondamentos de ISS (se ele desconta o
    liquido), INSS e IRRF, com sinal -- nem a soma dos modulos, nem o ISS que nao desconta."""
    nota = {"valor_centavos": saida["valor"], "iss_centavos": saida["iss"] + iss, "inss_centavos": saida["inss"],
            "irrf_centavos": saida["irrf"] + irrf, "liquido_centavos": saida["liquido"] + liquido}
    difs = {d["campo"]: d["grau"] for d in notas.conferir(saida, nota, None)}
    assert difs.get("liquido") == grau


# --- issue #562: nota divergente do espelho no envio da nota e no a receber -----------------------------------------

def _envio_da(conn, mid):
    return next(e for e in notas_envio.a_enviar(conn)["envios"] if mid in e["medicao_ids"])


def test_nota_de_outra_medicao_marca_a_etapa_de_envio_como_divergente(conn, usuario, integra, _texto):
    """Issue #562: a nota de outra medicao (valor e tributos diferentes) no municipio da saida casa, fecha a medicao e
    a etapa "Envio da nota" traz cada campo divergente com o valor do espelho e o da nota; o a receber diz que vem
    de nota divergente."""
    _, mid, saidas = integra
    cba, vg = saidas
    _texto(_nota_como(cba, 2224))
    notas.anexar_pdf(conn, usuario, mid, PDF, "NFS 2224.pdf")
    outra = {**vg, "valor": vg["valor"] + 3000001, "iss": vg["iss"] + 60001, "inss": vg["inss"] + 3301,
             "irrf": vg["irrf"] + 4501}
    _texto(_nota_como(outra, 2275))
    r = notas.anexar_pdf(conn, usuario, mid, _pdf_com_texto("outra"), "NFS 2275.pdf")
    assert r["estado"] == "nota_emitida"
    env = _envio_da(conn, mid)
    div = {d["campo"]: (d["espelho"], d["nota"], d["grau"]) for d in env["divergencias"] if d["numero"] == 2275}
    assert div["valor"] == (vg["valor"], outra["valor"], "divergente")
    assert div["iss"] == (vg["iss"], outra["iss"], "divergente")
    assert {"valor", "iss", "inss", "irrf", "liquido"} <= set(div)
    assert not [d for d in env["divergencias"] if d["numero"] == 2224]
    # o a receber que sai da nota divergente (titulos liquidos, centavo impar): so' ele conta; a conforme paga nao
    n2224 = conn.execute("SELECT id FROM notas_fiscais WHERE numero_int=2224").fetchone()[0]
    _titulo(conn, n2224, 11, 276000001, 276000001)
    _titulo(conn, r["nota_id"], 12, 184000001, 0, 0)
    cota = _cota(conn, mid)
    assert (cota["falta_centavos"], cota["falta_divergente_centavos"]) == (184000001, 184000001)
    # a divergente paga, a conforme em aberto: o a receber nao sai de nota divergente
    conn.execute("UPDATE baixas SET valor_baixado_centavos=valor_original_centavos, status_lan=1, data_baixa='2026-09-02' "
                 "WHERE idlan=12"); conn.execute("UPDATE baixas SET valor_baixado_centavos=0, status_lan=0 WHERE idlan=11")
    conn.commit()
    cota = _cota(conn, mid)
    assert (cota["falta_centavos"], cota["falta_divergente_centavos"]) == (276000001, 0)


def test_arredondamento_de_um_centavo_aparece_mas_nao_e_divergente(conn, usuario, integra, _texto):
    _, mid, saidas = integra
    cba, vg = saidas
    _texto(_nota_como(cba, 2224))
    notas.anexar_pdf(conn, usuario, mid, PDF, "NFS 2224.pdf")
    _texto(_nota_como(vg, 3102).replace("Vl. ISSQN: R$" + espelho._fmt(vg["iss"]), "Vl. ISSQN: R$" + espelho._fmt(vg["iss"] + 1)))
    notas.anexar_pdf(conn, usuario, mid, _pdf_com_texto("vg"), "NFS 3102.pdf")
    env = _envio_da(conn, mid)
    assert [(d["campo"], d["grau"]) for d in env["divergencias"]] == [("iss", "arredondamento")]
    assert env["acima_da_medicao"] == []
    for idlan, nid in enumerate(r[0] for r in conn.execute("SELECT id FROM notas_fiscais ORDER BY id")):
        _titulo(conn, nid, 20 + idlan, 100001, 0, 0)
    assert _cota(conn, mid)["falta_divergente_centavos"] == 0          # arredondamento nao e' divergencia


def test_nota_maior_que_a_medicao_gera_aviso_na_medicao(conn, usuario, _texto):
    """Issue #562: nota de R$ 846.788,31 numa medicao de R$ 1.480,01 (centavo impar): aviso critico ligado a' medicao."""
    cid = contratos.criar(conn, 1, {"orgao": "SINFRA", "numero_instrumento": "IC 098/2025", "objeto": "Obra",
                                    "valor_original_centavos": 10_000_000_00})
    mid = medicoes.criar(conn, 1, {"contrato_id": cid, "numero": 5, "tipo": "execucao", "competencia": "2026-06"})
    medicoes.definir_valor(conn, 1, mid, "protocolado", 148001, "manual")
    _texto(_fixture("3102-integra-vg.txt"))
    r = notas.anexar_pdf(conn, usuario, mid, PDF, "a.pdf")
    assert [(d["campo"], d["grau"]) for d in r["conferencia"]] == [("valor", "divergente")]
    assert notas.acima_da_medicao(conn, mid) == [{"medicao_id": mid, "nota_id": r["nota_id"], "numero": 3102,
                                                  "alocado_centavos": 84678831, "medicao_centavos": 148001}]
    av = [a for a in notas.avisos(conn, datetime.date(2026, 9, 22)) if a["tipo"] == "nota_acima_da_medicao"]
    assert [(a["medicao_id"], a["mensagem"]) for a in av] == [
        (mid, "nota 3102 de R$ 846.788,31 é maior que a medição (R$ 1.480,01)")]
    assert [a["nivel"] for a in avisos._de_notas(conn, datetime.date(2026, 9, 22))
            if a["tipo"] == "nota_acima_da_medicao"] == ["critico"]
    # nota igual ao valor da medicao nao avisa
    medicoes.definir_valor(conn, 1, mid, "atestado", 84678831, "manual")
    assert notas.acima_da_medicao(conn, mid) == []
    assert not [a for a in notas.avisos(conn, datetime.date(2026, 9, 22)) if a["tipo"] == "nota_acima_da_medicao"]


def _desconsiderar(conn, nf):
    from app import correcao_medicoes
    correcao_medicoes.executar(conn, 1, [{"operacao": "desconsiderar_nf", "nf": nf, "motivo": "cancelada na prefeitura",
                                          "fonte": "comprovante da prefeitura"}], ensaio=False)


def test_nota_desconsiderada_nao_gera_pendencia_nem_aviso(conn, integra):
    """Issue #638: a correcao e' silenciosa. A nota do RM ativa, sem medicao e com titulo aberto, depois de
    desconsiderada, nao acrescenta aviso (os de notas e a lista geral) nem pendencia na medicao da obra."""
    cid, mid, saidas = integra
    hoje = datetime.date(2026, 9, 22)
    nid = conn.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, numero_int, emissao, valor_centavos, codtmv) "
                       "VALUES (1, 7102, '7102', 7102, '2026-07-15', ?, '2.2.01')", (saidas[1]["valor"],)).lastrowid
    _titulo(conn, nid, 71021, saidas[1]["valor"] - 7_001, 0, status=0)

    def retrato():
        d = medicoes.detalhe(conn, mid)
        return (notas.avisos(conn, hoje), avisos.listar(conn, hoje), avisos.listar(conn, hoje, "diretoria"),
                d["estado"], d["notas"], d["notas_faltam"], notas.do_contrato(conn, cid))
    antes = retrato()
    _desconsiderar(conn, 7102)
    assert retrato() == antes
    assert conn.execute("SELECT COUNT(*) FROM nf_alocacoes").fetchone()[0] == 0


def test_tela_de_vincular_nota_recusa_a_nota_desconsiderada(conn, usuario, integra, _texto):
    """Issue #638: o PDF (lido ou digitado) da nota desconsiderada nao a liga a' medicao nem cria uma nota nova no
    lugar dela; a recusa e' em portugues e nao fala da correcao."""
    _, mid, saidas = integra
    vg = saidas[1]
    conn.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, numero_int, emissao, valor_centavos, codtmv) "
                 "VALUES (1, 7102, '3102', 3102, '2026-07-15', ?, '2.2.01')", (vg["valor"],))
    conn.commit()
    _desconsiderar(conn, 3102)
    _texto("")
    r = notas.anexar_pdf(conn, usuario, mid, PDF, "sem-texto.pdf")
    with pytest.raises(ValueError, match="Nota fiscal 3102 está cancelada"):
        notas.registrar_manual(conn, usuario, mid, r["documento_id"], 3102, "2026-07-15", vg["valor"])
    _texto(_nota_como(vg, 3102))
    with pytest.raises(ValueError, match="Nota fiscal 3102 está cancelada"):
        notas.anexar_pdf(conn, usuario, mid, _pdf_com_texto("a nota"), "a.pdf")
    assert conn.execute("SELECT COUNT(*) FROM notas_fiscais").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM nf_alocacoes").fetchone()[0] == 0
    assert medicoes.detalhe(conn, mid)["notas"] == []
