import json
import os
from pathlib import Path

import pytest
import yaml
from app import auth, cli, db
from tests import ficticios

ORGAOS = [{"chave": "sinfra-suef1", "nome": "SINFRA - SUEF I", "familia": "sinfra"}]
ENTS = [{"chave": "lotufo", "nome": "Lotufo", "cnpj": "31.200.101/0001-30", "papel": "lotufo",
         "coligada_rm": 1, "sigla_oficio": "LT"}]
CONTRATO = {"nome_curto": "MT-402", "numero_instrumento": "019/2024/00/00-SINFRA", "orgao": "sinfra-suef1",
            "entidade": "lotufo", "objeto": "MT-402", "valor_original": "15.127.200,00", "status": "ativo"}


def _cadastro(raiz, contrato=CONTRATO):
    (raiz / "contratos").mkdir(parents=True)
    (raiz / "orgaos.yaml").write_text(yaml.safe_dump(ORGAOS), "utf-8")
    (raiz / "entidades.yaml").write_text(yaml.safe_dump(ENTS), "utf-8")
    (raiz / "contratos" / "mt-402.yaml").write_text(yaml.safe_dump(contrato, allow_unicode=True), "utf-8")
    return raiz


def _banco(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    auth.criar_usuario(c, "Leo", "leo@l.com", "senha-forte-123", "admin")
    return c


def test_validar_ok_sai_zero(tmp_path, capsys):
    assert cli.main(["cadastro", "validar", "--raiz", str(_cadastro(tmp_path / "cad"))]) == 0
    assert "1 contrato" in capsys.readouterr().out


def test_validar_com_erro_sai_um_e_lista_os_erros(tmp_path, capsys):
    raiz = _cadastro(tmp_path / "cad", {**CONTRATO, "orgao": "nao-existe"})
    assert cli.main(["cadastro", "validar", "--raiz", str(raiz)]) == 1
    assert "nao-existe" in capsys.readouterr().out


def test_aplicar_grava_e_ensaio_nao(tmp_path, monkeypatch, capsys):
    conn = _banco(tmp_path, monkeypatch)
    raiz = str(_cadastro(tmp_path / "cad"))
    assert cli.main(["cadastro", "aplicar", "--raiz", raiz, "--usuario", "leo@l.com", "--ensaio"]) == 0
    assert conn.execute("SELECT COUNT(*) FROM contratos").fetchone()[0] == 0
    assert cli.main(["cadastro", "aplicar", "--raiz", raiz, "--usuario", "leo@l.com"]) == 0
    assert conn.execute("SELECT nome_curto FROM contratos").fetchone()[0] == "MT-402"
    assert "ENSAIO" in capsys.readouterr().out


def test_ensaio_lista_as_versoes_de_cronograma_por_obra(tmp_path, monkeypatch, capsys):
    """Issue #256: `cadastro aplicar --ensaio` diz quais versoes de cronograma entrariam, por obra."""
    conn = _banco(tmp_path, monkeypatch)
    cron = [{"chave": "contratual", "origem": "contratual", "data": "2024-03-11",
             "itens": [{"competencia": "2024-04", "valor": "1.000,01"}]},
            {"chave": "ta-01", "origem": "aditivo", "data": "2025-02-10", "instrumento": "ta-01",
             "itens": [{"competencia": "2025-03", "valor": "2.000,00"}]}]
    raiz = str(_cadastro(tmp_path / "cad", {**CONTRATO, "cronograma": cron}))
    assert cli.main(["cadastro", "aplicar", "--raiz", raiz, "--usuario", "leo@l.com", "--ensaio"]) == 0
    saida = capsys.readouterr().out
    assert "cronograma: 2 criados" in saida
    assert "+ MT-402/contratual (11/03/2024)" in saida and "+ MT-402/ta-01 (10/02/2025)" in saida
    assert conn.execute("SELECT COUNT(*) FROM cronograma_versoes").fetchone()[0] == 0


def test_aplicar_com_usuario_inexistente_sai_um(tmp_path, monkeypatch):
    _banco(tmp_path, monkeypatch)
    raiz = str(_cadastro(tmp_path / "cad"))
    assert cli.main(["cadastro", "aplicar", "--raiz", raiz, "--usuario", "ninguem@l.com"]) == 1


def test_validar_conta_regras_do_espelho(tmp_path, capsys):
    from tests.test_cadastro_arquivos import _com_espelho
    raiz = _com_espelho(_cadastro(tmp_path / "cad"))
    assert cli.main(["cadastro", "validar", "--raiz", str(raiz)]) == 0
    saida = capsys.readouterr().out
    assert "espelho: 1 regra(s) (1 ativa)" in saida and "geral.yaml" in saida


# --- DASH_CADASTRO_DIR e cadastro-exemplo/ (issue #103) ---

def test_raiz_padrao_sem_variavel_e_o_cadastro_exemplo(monkeypatch):
    monkeypatch.delenv("DASH_CADASTRO_DIR", raising=False)
    assert cli.raiz_padrao() == cli.REPOSITORIO / "cadastro-exemplo" and cli.raiz_padrao().is_dir()


def test_raiz_padrao_vem_da_variavel(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_CADASTRO_DIR", str(tmp_path / "outro"))
    assert cli.raiz_padrao() == tmp_path / "outro"
    monkeypatch.setenv("DASH_CADASTRO_DIR", "")          # vazia vale como ausente
    assert cli.raiz_padrao() == cli.REPOSITORIO / "cadastro-exemplo"


def test_validar_sem_raiz_le_a_pasta_da_variavel(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DASH_CADASTRO_DIR", str(_cadastro(tmp_path / "cad")))
    assert cli.main(["cadastro", "validar"]) == 0
    assert "1 contrato," in capsys.readouterr().out


def test_raiz_explicita_vence_a_variavel(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DASH_CADASTRO_DIR", str(tmp_path / "nao-existe"))
    assert cli.main(["cadastro", "validar", "--raiz", str(_cadastro(tmp_path / "cad"))]) == 0
    assert "1 contrato," in capsys.readouterr().out


def test_variavel_para_pasta_inexistente_sai_um_e_diz_onde(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DASH_CADASTRO_DIR", str(tmp_path / "nao-existe"))
    assert cli.main(["cadastro", "validar"]) == 1
    assert "nao-existe" in capsys.readouterr().out


def test_cadastro_exemplo_valida_e_aplica_em_banco_vazio(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("DASH_CADASTRO_DIR", raising=False)
    conn = _banco(tmp_path, monkeypatch)
    assert cli.main(["cadastro", "validar"]) == 0
    assert "2 contratos" in capsys.readouterr().out
    assert cli.main(["cadastro", "aplicar", "--usuario", "leo@l.com"]) == 0
    assert [r[0] for r in conn.execute("SELECT nome_curto FROM contratos ORDER BY nome_curto")] == [
        "Obra Consórcio", "Obra Própria"]
    assert conn.execute("SELECT COUNT(*) FROM espelho_regras").fetchone()[0] == 2
    # issue #256: a obra de exemplo traz duas versoes de cronograma, cada uma com a data do documento
    assert [tuple(r) for r in conn.execute("SELECT chave, data_documento FROM cronograma_versoes_cadastro "
                                           "ORDER BY data_documento")] == [("contratual", "2025-03-10"),
                                                                           ("ta-01", "2026-02-02")]
    capsys.readouterr()
    assert cli.main(["cadastro", "aplicar", "--usuario", "leo@l.com"]) == 0     # de novo: nada muda
    assert "contratos: 0 criados, 0 alterados" in capsys.readouterr().out


def test_exemplo_nao_se_aplica_em_banco_com_contrato_de_outro_cadastro(tmp_path, monkeypatch, capsys):
    """Esquecer DASH_CADASTRO_DIR na producao faria a raiz cair no exemplo: o CLI recusa, em `aplicar` e no ensaio."""
    monkeypatch.delenv("DASH_CADASTRO_DIR", raising=False)
    conn = _banco(tmp_path, monkeypatch)
    real = str(_cadastro(tmp_path / "real"))
    assert cli.main(["cadastro", "aplicar", "--raiz", real, "--usuario", "leo@l.com"]) == 0
    capsys.readouterr()
    for extra in ([], ["--ensaio"], ["--raiz", str(cli.REPOSITORIO / "cadastro-exemplo")]):
        assert cli.main(["cadastro", "aplicar", "--usuario", "leo@l.com", *extra]) == 1
        assert "Defina DASH_CADASTRO_DIR" in capsys.readouterr().out
    assert [r[0] for r in conn.execute("SELECT nome_curto FROM contratos")] == ["MT-402"]
    assert conn.execute("SELECT COUNT(*) FROM orgaos").fetchone()[0] == 1
    # banco sem contrato, mas com orgao de outro cadastro, tambem e' de outro cadastro
    conn.execute("DELETE FROM contratos"); conn.commit()
    assert cli.main(["cadastro", "aplicar", "--usuario", "leo@l.com"]) == 1
    assert "1 órgãos" in capsys.readouterr().out
    # com o cadastro certo apontado pela variavel, segue normal
    monkeypatch.setenv("DASH_CADASTRO_DIR", real)
    assert cli.main(["cadastro", "aplicar", "--usuario", "leo@l.com"]) == 0


def test_exemplo_nao_se_aplica_em_banco_com_entidade_de_outro_cadastro(tmp_path, monkeypatch, capsys):
    """Sem contrato nem orgao de fora, so' uma entidade (com chave) que o exemplo nao conhece ja' basta para recusar."""
    monkeypatch.delenv("DASH_CADASTRO_DIR", raising=False)
    conn = _banco(tmp_path, monkeypatch)
    raiz = tmp_path / "outro"
    raiz.mkdir()
    (raiz / "orgaos.yaml").write_text(yaml.safe_dump([{"chave": "secretaria-exemplo", "nome": "S", "familia": "sinfra"}]), "utf-8")
    ents = [{"chave": "lotufo", "nome": "Construtora Exemplo Ltda", "cnpj": "12.345.678/0001-95", "papel": "lotufo",
             "coligada_rm": 1, "sigla_oficio": "EX"},
            {"chave": "rival", "nome": "Rival", "cnpj": "98.765.432/0001-98", "papel": "consorciada",
             "coligada_rm": None, "sigla_oficio": None}]
    (raiz / "entidades.yaml").write_text(yaml.safe_dump(ents), "utf-8")
    assert cli.main(["cadastro", "aplicar", "--raiz", str(raiz), "--usuario", "leo@l.com"]) == 0
    capsys.readouterr()
    assert cli.main(["cadastro", "aplicar", "--usuario", "leo@l.com"]) == 1
    saida = capsys.readouterr().out
    assert "1 entidades" in saida and "contratos" not in saida.split("Defina")[0].split("já tem")[1]
    assert conn.execute("SELECT COUNT(*) FROM contratos").fetchone()[0] == 0


def test_banco_que_recebeu_o_exemplo_recusa_o_cadastro_real_em_portugues(tmp_path, monkeypatch, capsys):
    """O CNPJ da empresa propria semeada foi reivindicado pelo exemplo; outro cadastro com outro CNPJ para ela
    colide na coligada 1. O CLI diz isso em portugues, sem despejar o erro cru do SQLite, e nao grava nada."""
    monkeypatch.delenv("DASH_CADASTRO_DIR", raising=False)
    conn = _banco(tmp_path, monkeypatch)
    assert cli.main(["cadastro", "aplicar", "--usuario", "leo@l.com"]) == 0
    capsys.readouterr()
    real = str(_cadastro(tmp_path / "real"))
    ents = [{**ENTS[0], "cnpj": "12.345.678/0001-95"}]         # outro CNPJ para a empresa propria
    (tmp_path / "real" / "entidades.yaml").write_text(yaml.safe_dump(ents), "utf-8")
    assert cli.main(["cadastro", "aplicar", "--raiz", real, "--usuario", "leo@l.com"]) == 1
    saida = capsys.readouterr().out
    assert saida.startswith(f"Cadastro lido de: {real}") and "UNIQUE" not in saida
    assert "Cadastro recusado, nada foi gravado" in saida and "entidades.coligada_rm" in saida
    assert conn.execute("SELECT COUNT(*) FROM contratos WHERE nome_curto='MT-402'").fetchone()[0] == 0


def test_validar_e_aplicar_dizem_qual_pasta_leram(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("DASH_CADASTRO_DIR", raising=False)
    assert cli.main(["cadastro", "validar"]) == 0
    assert capsys.readouterr().out.startswith(f"Cadastro lido de: {cli.EXEMPLO} (exemplo fictício)")
    outra = _cadastro(tmp_path / "cad")
    monkeypatch.setenv("DASH_CADASTRO_DIR", str(outra))
    assert cli.main(["cadastro", "validar"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == f"Cadastro lido de: {outra}"
    _banco(tmp_path, monkeypatch)
    assert cli.main(["cadastro", "aplicar", "--usuario", "leo@l.com", "--ensaio"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == f"Cadastro lido de: {outra}"


# --- o exemplo nao copia o cadastro real (que sai do repositorio no corte) ---------------------------------
# Pode repetir, de proposito: as aliquotas de lei (ISS, IRRF, INSS) com o modo de arredondamento (`retencoes`),
# os nomes dos campos e as chaves de configuracao. Nao pode repetir: texto de carta ou de e-mail, linha longa de
# YAML, nem a estrutura de uma regra de espelho (entradas, parcelas e saidas).

def _cadastro_real() -> Path | None:
    """O cadastro real a comparar: `DASH_CADASTRO_DIR` (depois do corte ele mora fora do repositorio) quando existe e
    nao e' o exemplo; senao o `cadastro/` do proprio repositorio (antes do corte)."""
    pasta = os.environ.get("DASH_CADASTRO_DIR")
    if pasta and Path(pasta).is_dir() and Path(pasta).resolve() != cli.EXEMPLO.resolve():
        return Path(pasta)
    antigo = cli.REPOSITORIO / "cadastro"
    return antigo if antigo.is_dir() else None


@pytest.fixture
def real():
    pasta = _cadastro_real()
    if pasta is None:
        pytest.skip("sem cadastro real para comparar: DASH_CADASTRO_DIR ausente, inexistente ou igual ao exemplo, "
                    "e sem cadastro/ no repositorio")
    return pasta


def _canon(v):
    """Forma canonica sem ordem: chaves de mapa e itens de lista em qualquer ordem dao o mesmo resultado."""
    if isinstance(v, dict):
        return {k: _canon(x) for k, x in sorted(v.items())}
    if isinstance(v, list):
        return sorted((_canon(x) for x in v), key=lambda x: json.dumps(x, sort_keys=True, default=str))
    return v


def _textos(v):
    if isinstance(v, str):
        yield v.strip()
    elif isinstance(v, dict):
        for x in v.values():
            yield from _textos(x)
    elif isinstance(v, list):
        for x in v:
            yield from _textos(x)


def _forma(regra: dict):
    """A estrutura da regra, sem rotulos, chaves, modelos e retencoes: naturezas das entradas, (natureza, emissor,
    municipio) de cada saida e como cada parcela reparte."""
    return _canon([[e.get("natureza") for e in regra.get("entradas") or []],
                   [[s.get("natureza"), s.get("emissor"), s.get("municipio")] for s in regra.get("saidas") or []],
                   [[p.get("fracao"), p.get("fator"), p.get("arredondamento"), bool(p.get("resto_de"))]
                    for p in regra.get("parcelas") or []]])


def _sem_retencoes(regra: dict) -> dict:
    return _canon({k: v for k, v in regra.items() if k not in ("contrato", "situacao", "retencoes")})


def test_comparacao_ignora_a_ordem_dos_campos():
    a = {"entradas": [{"chave": "m", "natureza": "medicao"}], "saidas": [{"emissor": "x", "municipio": "A"}, {"emissor": "y"}]}
    b = {"saidas": [{"emissor": "y"}, {"municipio": "A", "emissor": "x"}], "entradas": [{"natureza": "medicao", "chave": "m"}]}
    assert _canon(a) == _canon(b) and _forma(a) == _forma(b)


def test_exemplo_nao_copia_linhas_longas_do_cadastro_real(real):
    def linhas(pasta, so_yaml=False):
        out = {}
        for p in pasta.rglob("*"):
            if p.suffix in (".yaml", ".md") and not (so_yaml and p.suffix != ".yaml") and "espelho" not in p.relative_to(pasta).parts[:1]:
                for l in p.read_text("utf-8").splitlines():
                    if len(l.strip()) > 40:
                        out.setdefault(l.strip(), p.name)
        return out
    reais = linhas(real, so_yaml=True)
    assert sorted((nome, l) for l, nome in linhas(cli.EXEMPLO).items() if l in reais) == []


def test_exemplo_nao_copia_texto_de_carta_nem_de_faturamento(real):
    def textos(raiz):
        out = set()
        for nome in ("cartas.yaml", "geral.yaml"):
            if (raiz / nome).is_file():
                out |= {t for t in _textos(yaml.safe_load((raiz / nome).read_text("utf-8"))) if len(t) > 20 and " " in t}
        return out
    assert textos(cli.EXEMPLO) & textos(real) == set()


def test_regras_de_espelho_do_exemplo_diferem_de_todas_as_reais(real):
    reais = [yaml.safe_load(p.read_text("utf-8")) for p in sorted((real / "espelho").glob("*.yaml"))]
    assert reais, "o cadastro real nao tem regras de espelho para comparar"
    regras = sorted((cli.EXEMPLO / "espelho").glob("*.yaml"))
    assert len(regras) == 2
    for arq in regras:
        regra = yaml.safe_load(arq.read_text("utf-8"))
        for r in reais:
            assert _sem_retencoes(regra) != _sem_retencoes(r), f"{arq.name} igual a regra de {r['contrato']}"
            assert _forma(regra) != _forma(r), f"{arq.name} tem a mesma estrutura da regra de {r['contrato']}"


def test_cadastro_exemplo_so_tem_dado_ficticio():
    """O exemplo nasce para ir a um repositorio publico: e-mail so' dos dominios de exemplo e CNPJ inventado."""
    import re
    from app import entidades
    raiz = cli.REPOSITORIO / "cadastro-exemplo"
    texto = "\n".join(p.read_text("utf-8") for p in raiz.rglob("*") if p.suffix in (".yaml", ".md"))
    emails = set(re.findall(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", texto))
    assert emails and all(e.endswith(("@exemplo.gov.br", "@exemplo.com.br")) for e in emails), emails
    cnpjs = {re.sub(r"\D", "", c) for c in re.findall(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", texto)}
    assert cnpjs == {ficticios.ORGAO_A, ficticios.LOTUFO, ficticios.INTEGRA, ficticios.GUAXE}     # os de tests/ficticios.py
    assert all(entidades.cnpj_valido(c) for c in cnpjs)


# --- carregar-medicoes --ensaio (issue #258) ---

CAB = ("nº;nº do órgão;tipo;competência;período;valor pedido;valor aprovado;data da aprovação;meio;"
       "nº do processo no órgão;data do protocolo da nota;NF;fonte")


def _com_exemplo_aplicado(tmp_path, monkeypatch):
    monkeypatch.delenv("DASH_CADASTRO_DIR", raising=False)
    conn = _banco(tmp_path, monkeypatch)
    assert cli.main(["cadastro", "aplicar", "--usuario", "leo@l.com"]) == 0
    return conn, conn.execute("SELECT id FROM contratos WHERE nome_curto='Obra Própria'").fetchone()[0]


def _foto(conn):
    return [conn.execute(f"SELECT COUNT(*), COALESCE(SUM(id), 0) FROM {t}").fetchone()[:]
            for t in ("medicoes", "medicao_atestos", "audit_log", "contrato_eventos")] + [
        [tuple(r) for r in conn.execute("SELECT * FROM medicoes ORDER BY id")]]


def test_carregar_medicoes_ensaio_com_o_csv_de_exemplo_relata_e_totaliza(tmp_path, monkeypatch, capsys):
    conn, _ = _com_exemplo_aplicado(tmp_path, monkeypatch)
    capsys.readouterr()
    csv_ = cli.EXEMPLO / "medicoes" / "obra-propria.csv"
    assert cli.main(["cadastro", "carregar-medicoes", str(csv_), "--ensaio"]) == 0
    saida = capsys.readouterr().out
    assert "ENSAIO (nada foi gravado): Obra Própria" in saida
    assert "linha 2: nº 1 execução 2025-04: nova" in saida
    assert "linha 5: nº 1 reajuste 2025-06: nova" in saida
    assert "Total: nova 4, igual 0, valor diferente 0, incompleta 0, cancelamento 0, correção 0, conflito 0, erro 0" in saida


def test_carregar_medicoes_ensaio_classifica_e_nao_grava(tmp_path, monkeypatch, capsys):
    conn, cid = _com_exemplo_aplicado(tmp_path, monkeypatch)
    for numero, tipo, comp, pedido, aprovado in ((1, "execucao", "2025-04", 41234567, 41234567),
                                                 (2, "execucao", "2025-05", 53890010, 52000000),
                                                 (3, "execucao", "2025-06", 60125000, None)):
        conn.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos,"
                     " valor_atestado_centavos) VALUES (?,?,?,?,'protocolada',?,?)", (cid, numero, tipo, comp, pedido, aprovado))
    conn.commit()
    linhas = [CAB,
              "1;1;execucao;2025-04;;412.345,67;412.345,67;20/05/2025;e-mail;P1;;;boletim",       # igual
              "2;2;execução;2025-05;;538.900,10;530.000,00;18/06/2025;e-mail;P2;;;boletim",       # aprovado difere
              "3;3;execucao;2025-07;;601.250,00;;;;;;;planilha",                                  # conflito
              "4;4;execucao;2025-08;;1.234,56;;;;;;;planilha",                                    # nova
              "5;5;execucao;2025-09;;12.34;;;;;;;planilha",                                       # valor inválido
              "6;6;aditivo;2025-09;;1,00;;;;;;;planilha",                                         # tipo desconhecido
              "7;7;execucao;2027-03;;1,00;;;;;;;planilha",                                        # fora do contrato
              "4;4;execucao;2025-08;;1,00;;;;;;;planilha"]                                        # chave repetida
    arq = tmp_path / "obra-propria.csv"
    arq.write_text("\n".join(linhas) + "\n", "utf-8")
    antes = _foto(conn)
    capsys.readouterr()
    assert cli.main(["cadastro", "carregar-medicoes", str(arq), "--ensaio"]) == 0
    saida = capsys.readouterr().out
    assert "linha 2: nº 1 execução 2025-04: igual" in saida
    assert "linha 3: nº 2 execução 2025-05: valor diferente (aprovado: banco R$ 520.000,00, CSV R$ 530.000,00)" in saida
    assert "linha 4: nº 3 execução 2025-07: conflito (banco tem competência 2025-06 (se o banco está errado" in saida
    assert "linha 5: nº 4 execução 2025-08: nova" in saida
    assert "linha 6: nº 5 execução: erro (valor pedido" in saida
    assert "linha 7: nº 6 aditivo: erro (tipo desconhecido" in saida
    assert "linha 8: nº 7 execução: erro (competência 2027-03 fora do contrato (2025-03 a 2026-12))" in saida
    assert "linha 9: nº 4 execução 2025-08: erro (nº 4 execução repetido (já na linha 5))" in saida
    assert "Total: nova 1, igual 1, valor diferente 1, incompleta 0, cancelamento 0, correção 0, conflito 1, erro 4" in saida
    assert _foto(conn) == antes


def test_carregar_medicoes_sem_ensaio_recusa_e_nao_grava(tmp_path, monkeypatch, capsys):
    conn, _ = _com_exemplo_aplicado(tmp_path, monkeypatch)
    antes = _foto(conn)
    assert cli.main(["cadastro", "carregar-medicoes", str(cli.EXEMPLO / "medicoes" / "obra-propria.csv")]) == 1
    assert "--ensaio" in capsys.readouterr().out
    assert _foto(conn) == antes


def test_carregar_medicoes_obra_desconhecida_ou_cabecalho_errado_sai_um(tmp_path, monkeypatch, capsys):
    _com_exemplo_aplicado(tmp_path, monkeypatch)
    arq = tmp_path / "nao-existe.csv"
    arq.write_text(CAB + "\n", "utf-8")
    assert cli.main(["cadastro", "carregar-medicoes", str(arq), "--ensaio"]) == 1
    assert "obra 'nao-existe' não encontrada" in capsys.readouterr().out
    arq = tmp_path / "obra-propria.csv"
    arq.write_text("nº;tipo;valor\n1;execucao;1,00\n", "utf-8")
    assert cli.main(["cadastro", "carregar-medicoes", str(arq), "--ensaio"]) == 1
    assert "coluna desconhecida no cabeçalho: 'valor'" in capsys.readouterr().out


@pytest.mark.parametrize("texto,centavos", [("1.234,56", 123456), ("R$ 1.234,56", 123456), ("0,5", 50),
                                            ("4.075.275,90", 407527590)])
def test_carregar_medicoes_converte_reais_com_virgula_em_centavos(texto, centavos):
    from app import carga_medicoes
    assert carga_medicoes._valor(texto, "valor pedido") == centavos


def _ensaio(tmp_path, linhas, capsys, nome="obra-propria.csv"):
    arq = tmp_path / nome
    arq.write_text("\n".join(linhas) + "\n", "utf-8")
    capsys.readouterr()
    codigo = cli.main(["cadastro", "carregar-medicoes", str(arq), "--ensaio"])
    return codigo, capsys.readouterr().out


def test_carregar_medicoes_linha_com_colunas_a_mais_e_erro_e_nao_valor(tmp_path, monkeypatch, capsys):
    """Valor com vírgula sem aspas num CSV separado por vírgula desloca as colunas: erro, nunca R$ 412.345,00."""
    _com_exemplo_aplicado(tmp_path, monkeypatch)
    codigo, saida = _ensaio(tmp_path, ["nº,tipo,competência,valor pedido,valor aprovado", "1,execucao,2025-04,412.345,67,"], capsys)
    assert codigo == 0
    assert "linha 2: nº 1 execução: erro (a linha tem 6 colunas e o cabeçalho tem 5)" in saida


def test_carregar_medicoes_cabecalho_com_grau_e_coluna_repetida(tmp_path, monkeypatch, capsys):
    _com_exemplo_aplicado(tmp_path, monkeypatch)
    codigo, saida = _ensaio(tmp_path, ["N°;Tipo;Competência;Nº. do órgão;Valor pedido;Valor aprovado", "1;execucao;2025-04;1;1,00;"], capsys)
    assert codigo == 0 and "linha 2: nº 1 execução 2025-04: nova" in saida
    codigo, saida = _ensaio(tmp_path, ["nº;tipo;competência;valor pedido;Valor Pedido;valor aprovado"], capsys)
    assert codigo == 1 and "coluna repetida no cabeçalho: 'Valor Pedido'" in saida


def test_carregar_medicoes_competencia_vale_ate_o_fim_do_aditivo_de_prazo(tmp_path, monkeypatch, capsys):
    conn, cid = _com_exemplo_aplicado(tmp_path, monkeypatch)
    conn.execute("INSERT INTO aditivos (contrato_id, tipo, nova_vigencia_fim, status, data_assinatura) "
                 "VALUES (?, 'prazo', '2027-06-30', 'assinado', '2026-11-01')", (cid,))
    conn.commit()
    codigo, saida = _ensaio(tmp_path, [CAB, "7;7;execucao;2027-03;;1,00;;;;;;;planilha"], capsys)
    assert "linha 2: nº 7 execução 2027-03: nova" in saida


def test_carregar_medicoes_valor_vazio_no_csv_com_valor_no_banco_e_incompleta_nunca_igual(tmp_path, monkeypatch, capsys):
    conn, cid = _com_exemplo_aplicado(tmp_path, monkeypatch)
    conn.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos,"
                 " valor_atestado_centavos) VALUES (?,1,'execucao','2025-04','protocolada',100,90)", (cid,))
    conn.commit()
    codigo, saida = _ensaio(tmp_path, [CAB, "1;1;execucao;2025-04;;1,00;;;;;;;planilha"], capsys)
    assert "linha 2: nº 1 execução 2025-04: incompleta (aprovado vazio no CSV, banco R$ 0,90)" in saida
    assert "igual 0" in saida and "incompleta 1" in saida


def test_carregar_medicoes_celula_com_quebra_de_linha_numera_pelo_inicio(tmp_path, monkeypatch, capsys):
    _com_exemplo_aplicado(tmp_path, monkeypatch)
    codigo, saida = _ensaio(tmp_path, [CAB, '1;1;execucao;2025-04;;1,00;;;;;;;"fonte em', 'duas linhas"',
                                       "2;2;aditivo;2025-05;;1,00;;;;;;;planilha"], capsys)
    assert "linha 2: nº 1 execução 2025-04: nova" in saida
    assert "linha 4: nº 2 aditivo: erro" in saida


def test_aplicar_com_arquivo_por_engano_recusa_sem_gravar(tmp_path, monkeypatch, capsys):
    conn = _banco(tmp_path, monkeypatch)
    monkeypatch.delenv("DASH_CADASTRO_DIR", raising=False)
    assert cli.main(["cadastro", "aplicar", "obra-propria.csv", "--usuario", "leo@l.com"]) == 1
    assert "não recebe arquivo" in capsys.readouterr().out
    assert conn.execute("SELECT COUNT(*) FROM contratos").fetchone()[0] == 0


def test_carregar_medicoes_abre_o_banco_so_para_leitura(tmp_path, monkeypatch, capsys):
    conn, _ = _com_exemplo_aplicado(tmp_path, monkeypatch)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.close()
    codigo, saida = _ensaio(tmp_path, [CAB, "1;1;execucao;2025-04;;1,00;;;;;;;planilha"], capsys)
    assert codigo == 0 and "nova 1" in saida
    import sqlite3
    c = sqlite3.connect(tmp_path / "t.db")
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "delete"


# --- rodada 1 dos gates da PR #307 ---

def test_carregar_medicoes_exige_as_colunas_de_valor(tmp_path, monkeypatch, capsys):
    """Um CSV exportado sem valores não pode "aprovar" a conferência."""
    _com_exemplo_aplicado(tmp_path, monkeypatch)
    codigo, saida = _ensaio(tmp_path, ["nº;tipo;competência", "1;execucao;2025-04"], capsys)
    assert codigo == 1 and "faltam colunas no cabeçalho: valor pedido, valor aprovado" in saida


def test_carregar_medicoes_medicao_cancelada_ou_desistida_no_banco_e_conflito(tmp_path, monkeypatch, capsys):
    conn, cid = _com_exemplo_aplicado(tmp_path, monkeypatch)
    for numero, estado in ((1, "cancelada"), (2, "desistida")):
        conn.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos,"
                     " valor_atestado_centavos) VALUES (?,?,'execucao','2025-04',?,100,100)", (cid, numero, estado))
    conn.commit()
    codigo, saida = _ensaio(tmp_path, [CAB, "1;1;execucao;2025-04;;1,00;1,00;;;;;;x",
                                       "2;2;execucao;2025-04;;1,00;1,00;;;;;;x"], capsys)
    assert "linha 2: nº 1 execução 2025-04: conflito (no banco a medição está cancelada)" in saida
    assert "linha 3: nº 2 execução 2025-04: conflito (no banco a medição está desistida)" in saida
    assert "igual 0" in saida


def test_carregar_medicoes_mesmo_numero_no_csv_com_outra_competencia_e_conflito(tmp_path, monkeypatch, capsys):
    _com_exemplo_aplicado(tmp_path, monkeypatch)
    codigo, saida = _ensaio(tmp_path, [CAB, "1;1;execucao;2025-04;;1,00;;;;;;;x",
                                       "1;1;execução;2025-05;;1,00;;;;;;;x",
                                       "1;1;execucao;2025-04;;2,00;;;;;;;x"], capsys)
    assert ("linha 2: nº 1 execução 2025-04: conflito (o mesmo nº tem outra competência no CSV "
            "(linha 3 2025-05))") in saida   # so' as linhas de OUTRA competencia, nao a 4 (mesma)
    assert "conflito (o mesmo nº tem outra competência no CSV (linha 2 2025-04, linha 4 2025-04))" in saida
    assert "linha 3: nº 1 execução 2025-05: conflito" in saida and "linha 4: nº 1 execução 2025-04: conflito" in saida
    assert "igual 0" in saida and "conflito 3" in saida
    codigo, saida = _ensaio(tmp_path, [CAB, "1;1;execucao;2025-04;;1,00;;;;;;;x",
                                       "1;1;execucao;2025-04;;2,00;;;;;;;x"], capsys)
    assert "linha 2: nº 1 execução 2025-04: nova" in saida
    assert "linha 3: nº 1 execução 2025-04: erro (nº 1 execução repetido (já na linha 2))" in saida


def test_carregar_medicoes_le_o_banco_numa_transacao_so_e_desfaz(tmp_path, monkeypatch, capsys):
    from app import carga_medicoes
    _com_exemplo_aplicado(tmp_path, monkeypatch)
    vistas = []
    original = carga_medicoes.ensaiar

    def espiao(conn, caminho):
        vistas.append(conn.in_transaction)
        return original(conn, caminho)
    monkeypatch.setattr(carga_medicoes, "ensaiar", espiao)
    codigo, _ = _ensaio(tmp_path, [CAB], capsys)
    assert codigo == 0 and vistas == [True]


def test_carregar_medicoes_tipo_invalido_sugere_rotulos_em_portugues(tmp_path, monkeypatch, capsys):
    _com_exemplo_aplicado(tmp_path, monkeypatch)
    codigo, saida = _ensaio(tmp_path, [CAB, "1;1;aditivo;2025-04;;1,00;;;;;;;x"], capsys)
    assert "(use execução, projeto, reajuste)" in saida and "execucao" not in saida


def test_carregar_medicoes_banco_inexistente_e_arquivo_ilegivel_falam_portugues(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "nao-existe.db"))
    codigo, saida = _ensaio(tmp_path, [CAB], capsys)
    assert codigo == 1 and "Banco não encontrado:" in saida and "Traceback" not in saida
    _com_exemplo_aplicado(tmp_path, monkeypatch)
    for nome, conteudo in (("nulo", (CAB + "\n1;1;exec\x00ucao;2025-04;;;;;;;;;\n").encode()),
                           ("codificacao", CAB.encode() + b"\n1;1;execucao;2025-04;;\x81;;;;;;;\n")):
        arq = tmp_path / nome / "obra-propria.csv"
        arq.parent.mkdir()
        arq.write_bytes(conteudo)
        capsys.readouterr()
        assert cli.main(["cadastro", "carregar-medicoes", str(arq), "--ensaio"]) == 1
        assert "CSV recusado, nada foi lido:" in capsys.readouterr().out



# --- rodada 2 dos gates da PR #307 ---

def test_carregar_medicoes_valor_diferente_com_o_outro_vazio_mostra_a_celula_vazia(tmp_path, monkeypatch, capsys):
    conn, cid = _com_exemplo_aplicado(tmp_path, monkeypatch)
    conn.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos,"
                 " valor_atestado_centavos) VALUES (?,1,'execucao','2025-04','protocolada',100,90)", (cid,))
    conn.commit()
    codigo, saida = _ensaio(tmp_path, [CAB, "1;1;execucao;2025-04;;2,00;;;;;;;x"], capsys)
    assert ("linha 2: nº 1 execução 2025-04: valor diferente (pedido: banco R$ 1,00, CSV R$ 2,00; "
            "aprovado vazio no CSV, banco R$ 0,90)") in saida
    assert "igual 0" in saida


def test_carregar_medicoes_aspas_nao_fechadas_recusam_o_arquivo(tmp_path, monkeypatch, capsys):
    _com_exemplo_aplicado(tmp_path, monkeypatch)
    codigo, saida = _ensaio(tmp_path, [CAB, '1;1;execucao;2025-04;;1,00;1,00;;;;;;"fonte sem fim'], capsys)
    assert codigo == 1 and "CSV recusado, nada foi lido: o arquivo não se lê como CSV (linha 2): aspas sem fechar" in saida
    assert "unexpected" not in saida
    assert "igual" not in saida.split("CSV recusado")[0]


def test_carregar_medicoes_aspas_nao_fechadas_citam_a_linha_onde_abriram(tmp_path, monkeypatch, capsys):
    # O leitor vai ate' o fim do arquivo procurando o fechamento: a mensagem cita onde a aspa abriu, nao o fim
    _com_exemplo_aplicado(tmp_path, monkeypatch)
    codigo, saida = _ensaio(tmp_path, [CAB, "1;1;execucao;2025-04;;1,00;1,00;;;;;;",
                                       '2;2;execucao;2025-05;;1,00;1,00;;;;;;"fonte sem fim',
                                       "3;3;execucao;2025-06;;1,00;1,00;;;;;;",
                                       "4;4;execucao;2025-07;;1,00;1,00;;;;;;"], capsys)
    assert codigo == 1 and "o arquivo não se lê como CSV (linha 3): aspas sem fechar" in saida


def test_carregar_medicoes_aceita_csv_do_excel_do_mac(tmp_path, monkeypatch, capsys):
    # "CSV (Macintosh)" termina as linhas so' com \r: tem de ler, nao acusar aspas na linha 1
    _com_exemplo_aplicado(tmp_path, monkeypatch)
    arq = tmp_path / "obra-propria.csv"
    arq.write_bytes("\r".join([CAB, "1;1;execucao;2025-04;;1,00;1,00;;;;;;", ""]).encode("utf-8"))
    capsys.readouterr()
    codigo = cli.main(["cadastro", "carregar-medicoes", str(arq), "--ensaio"])
    saida = capsys.readouterr().out
    assert codigo == 0 and "linha 2: nº 1 execução 2025-04: nova" in saida


def test_carregar_medicoes_arquivo_sem_leitura_fala_portugues(tmp_path, monkeypatch, capsys):
    from pathlib import Path as _P
    _com_exemplo_aplicado(tmp_path, monkeypatch)

    def nega(self):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(_P, "read_bytes", nega)
    codigo, saida = _ensaio(tmp_path, [CAB], capsys)
    assert codigo == 1
    assert "CSV recusado, nada foi lido: não foi possível ler o arquivo obra-propria.csv" in saida


# ---- issue #259: carregar-medicoes sem --ensaio grava as novas

def _gravar(capsys, arquivo=None, usuario="leo@l.com"):
    capsys.readouterr()
    args = ["cadastro", "carregar-medicoes", str(arquivo or cli.EXEMPLO / "medicoes" / "obra-propria.csv")]
    codigo = cli.main(args + (["--usuario", usuario] if usuario else []))
    return codigo, capsys.readouterr().out


def _nf_no_rm(conn, numero, idmov, valor, titulo, baixado, status, data_baixa=None, coligada=1, centro=None):
    if centro is None:      # padrao: o centro de custo da Obra Própria no cadastro de exemplo
        centro = conn.execute("SELECT centro_custo_rm FROM contratos WHERE nome_curto='Obra Própria'").fetchone()[0]
    nid = conn.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, numero_int, emissao, valor_centavos, "
                       "centro_custo) VALUES (?,?,?,?,?,?,?)",
                       (coligada, idmov, str(numero), numero, "2025-05-28", valor, centro)).lastrowid
    conn.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos, "
                 "status_lan, data_baixa) VALUES (?,?,?,?,?,?,?,?)",
                 (coligada, idmov, nid, idmov, titulo, baixado, status, data_baixa))
    conn.commit()
    return nid


def test_carregar_medicoes_grava_as_novas_com_pedido_aprovado_e_evento(tmp_path, monkeypatch, capsys):
    conn, cid = _com_exemplo_aplicado(tmp_path, monkeypatch)
    codigo, saida = _gravar(capsys)
    assert codigo == 0, saida
    assert "GRAVADO: Obra Própria (obra-propria.csv), 4 medição(ões) criada(s)" in saida
    ms = {(m["numero"], m["tipo"]): m for m in conn.execute("SELECT * FROM medicoes WHERE contrato_id=?", (cid,))}
    assert len(ms) == 4 and all(m["estado"] == "protocolada" and m["congelada"] == 1 for m in ms.values())
    m2 = ms[(2, "execucao")]
    assert (m2["valor_protocolado_centavos"], m2["valor_atestado_centavos"], m2["atestado_em"]) == (53890010, 53000000,
                                                                                                    "2025-06-18")
    assert (m2["numero_orgao"], m2["periodo_inicio"], m2["periodo_fim"]) == (2, "2025-05-01", "2025-05-31")
    m3 = ms[(3, "execucao")]
    assert (m3["valor_protocolado_centavos"], m3["valor_atestado_centavos"]) == (60125000, None)
    ev = conn.execute("SELECT * FROM medicao_atestos WHERE medicao_id=?", (m2["id"],)).fetchall()
    assert [(e["valor_centavos"], e["atestado_em"], e["meio"], e["numero_orgao"], e["observacao"]) for e in ev] == [
        (53000000, "2025-06-18", "email", "PROC-EXEMPLO-0002", "boletim de exemplo 2")]
    reaj = conn.execute("SELECT meio FROM medicao_atestos WHERE medicao_id=?", (ms[(1, "reajuste")]["id"],)).fetchone()
    assert reaj["meio"] == "carimbo"
    assert conn.execute("SELECT COUNT(*) FROM medicao_atestos").fetchone()[0] == 3
    prot = conn.execute("SELECT data, numero_processo FROM medicao_protocolos WHERE medicao_id=?", (m2["id"],)).fetchall()
    assert [tuple(p) for p in prot] == [("2025-06-25", "PROC-EXEMPLO-0002")]
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='medicao.carga_historico'").fetchone()[0] == 1
    # o painel da obra soma o aprovado, senao o pedido
    from app import paineis
    assert paineis.medido_execucao_por_contrato(conn)[cid] == 41234567 + 53000000 + 60125000


def test_carregar_medicoes_segunda_carga_nao_muda_nada(tmp_path, monkeypatch, capsys):
    conn, _ = _com_exemplo_aplicado(tmp_path, monkeypatch)
    assert _gravar(capsys)[0] == 0
    antes = _foto(conn)
    codigo, saida = _gravar(capsys)
    assert codigo == 0 and "0 medição(ões) criada(s)" in saida
    assert "Total: nova 0, igual 4, valor diferente 0, incompleta 0, cancelamento 0, correção 0, conflito 0, erro 0" in saida
    assert _foto(conn) == antes


def test_carregar_medicoes_nf_baixada_entra_recebida_e_sem_baixa_protocolada(tmp_path, monkeypatch, capsys):
    conn, cid = _com_exemplo_aplicado(tmp_path, monkeypatch)
    _nf_no_rm(conn, 101, 9001, 41234567, 38000000, 38000000, 1, "2025-07-10")    # titulo quitado
    _nf_no_rm(conn, 108, 9002, 53000000, 49000000, 0, 0)                          # titulo em aberto
    codigo, saida = _gravar(capsys)
    assert codigo == 0, saida
    m1, m2 = (conn.execute("SELECT * FROM medicoes WHERE contrato_id=? AND numero=? AND tipo='execucao'",
                           (cid, n)).fetchone() for n in (1, 2))
    assert (m1["estado"], m1["recebida_em"]) == ("recebida", "2025-07-10")
    assert m2["estado"] == "protocolada"
    assert "NF 101 vinculada; recebida (baixa no RM)" in saida and "NF 108 vinculada" in saida
    assert conn.execute("SELECT COUNT(*) FROM nf_alocacoes WHERE regra='carga_historico'").fetchone()[0] == 2


def test_carregar_medicoes_nf_fora_do_rm_ou_ja_vinculada_nao_impede(tmp_path, monkeypatch, capsys):
    conn, cid = _com_exemplo_aplicado(tmp_path, monkeypatch)
    nid = _nf_no_rm(conn, 108, 9002, 53000000, 49000000, 0, 0)
    outra = conn.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado) "
                         "VALUES (?, 9, 'execucao', '2025-09', 'protocolada')", (cid,)).lastrowid
    conn.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem) "
                 "VALUES (?,?,1,'manual')", (outra, nid))
    conn.commit()
    codigo, saida = _gravar(capsys)
    assert codigo == 0, saida
    assert "NF 101 não vinculada (NF 101 não encontrada no RM)" in saida
    assert "NF 108 não vinculada (NF 108 já está em outra medição)" in saida


def test_carregar_medicoes_com_erro_ou_conflito_nao_grava_nada(tmp_path, monkeypatch, capsys):
    conn, _ = _com_exemplo_aplicado(tmp_path, monkeypatch)
    antes = _foto(conn)
    arq = tmp_path / "obra-propria.csv"
    arq.write_text("\n".join([CAB, "1;1;execucao;2025-04;;1,00;1,00;;;;;;", "2;2;aditivo;2025-05;;1,00;;;;;;;"]) + "\n",
                   "utf-8")
    codigo, saida = _gravar(capsys, arq)
    assert codigo == 1 and "Recusado, nada foi gravado: 1 linha(s) com erro ou conflito" in saida
    assert _foto(conn) == antes


def _existente(conn, cid, numero, comp, pedido, aprovado, estado="protocolada", tipo="execucao"):
    mid = conn.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, congelada, "
                       "valor_protocolado_centavos, valor_atestado_centavos, atestado_em) VALUES (?,?,?,?,?,1,?,?,?)",
                       (cid, numero, tipo, comp, estado, pedido, aprovado, "2025-06-01" if aprovado else None)).lastrowid
    if aprovado is not None:
        conn.execute("INSERT INTO medicao_atestos (medicao_id, valor_centavos, origem, atestado_em) "
                     "VALUES (?,?,'manual','2025-06-01')", (mid, aprovado))
    conn.commit()
    return mid


def test_carregar_medicoes_aprovado_diferente_vira_evento_novo_e_nao_sobrescreve(tmp_path, monkeypatch, capsys):
    # issue #260: o vigente e' o ultimo evento; o anterior continua na linha do tempo; o pedido nao muda
    from app import medicoes
    conn, cid = _com_exemplo_aplicado(tmp_path, monkeypatch)
    mid = _existente(conn, cid, 2, "2025-05", 53890011, 52000001)        # pedido difere em 1 centavo (impar)
    codigo, saida = _gravar(capsys)
    assert codigo == 0 and "3 medição(ões) criada(s)" in saida, saida
    assert ("linha 3: nº 2 execução 2025-05: valor diferente" in saida
            and "aprovado registrado como evento novo; pedido diferente não alterado (congelado no protocolo)" in saida)
    m = conn.execute("SELECT * FROM medicoes WHERE id=?", (mid,)).fetchone()
    assert (m["valor_protocolado_centavos"], m["valor_atestado_centavos"], m["atestado_em"]) == (53890011, 53000000,
                                                                                                 "2025-06-18")
    ev = conn.execute("SELECT valor_centavos, observacao FROM medicao_atestos WHERE medicao_id=? ORDER BY id",
                      (mid,)).fetchall()
    assert [tuple(e) for e in ev] == [(52000001, None), (53000000, "boletim de exemplo 2")]
    textos = [e["texto"] for e in medicoes.edicoes_valor(conn, [mid])[mid]]
    assert any("Atestado alterado de R$ 520.000,01 para R$ 530.000,00" in t for t in textos)
    # rodar de novo nao cria outro evento
    assert _gravar(capsys)[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM medicao_atestos WHERE medicao_id=?", (mid,)).fetchone()[0] == 2


def test_carregar_medicoes_protocolada_sem_valor_recebe_o_pedido_uma_vez(tmp_path, monkeypatch, capsys):
    conn, cid = _com_exemplo_aplicado(tmp_path, monkeypatch)
    mid = _existente(conn, cid, 3, "2025-06", None, None)
    codigo, saida = _gravar(capsys)
    assert codigo == 0 and "pedido preenchido" in saida, saida
    assert conn.execute("SELECT valor_protocolado_centavos FROM medicoes WHERE id=?", (mid,)).fetchone()[0] == 60125000


def _csv(tmp_path, linhas, cab=CAB + ";cancelar;corrige competência"):
    arq = tmp_path / "obra-propria.csv"
    arq.write_text("\n".join([cab, *linhas]) + "\n", "utf-8")
    return arq


def test_carregar_medicoes_duplicata_cancelada_com_motivo_fica_no_banco_e_sai_do_painel(tmp_path, monkeypatch, capsys):
    from app import medicoes, paineis
    conn, cid = _com_exemplo_aplicado(tmp_path, monkeypatch)
    _existente(conn, cid, 4, "2025-07", 100001, 100001)
    dup = _existente(conn, cid, 5, "2025-07", 100001, 100001)
    antes, saldo_antes = paineis.medido_execucao_por_contrato(conn)[cid], paineis.saldo(conn, cid)["saldo_centavos"]
    arq = _csv(tmp_path, ["5;;execucao;2025-07;;;;;;;;;CI da prefeitura;4;"])
    codigo, saida = _gravar(capsys, arq)
    assert codigo == 0, saida
    assert "linha 2: nº 5 execução 2025-07: cancelamento (duplicata da 4ª execução)" in saida
    m = conn.execute("SELECT estado, motivo_represamento FROM medicoes WHERE id=?", (dup,)).fetchone()
    assert m["estado"] == "cancelada"
    assert m["motivo_represamento"] == "Duplicata da medição 4 de execução (carga do histórico: CI da prefeitura)"
    assert paineis.medido_execucao_por_contrato(conn)[cid] == antes - 100001
    assert paineis.saldo(conn, cid)["saldo_centavos"] == saldo_antes + 100001
    textos = [e["texto"] for e in medicoes.edicoes_valor(conn, [dup])[dup]]
    assert any("Cancelada: Duplicata da medição 4 de execução" in t for t in textos), textos
    # de novo: ja' cancelada, nada muda
    codigo, saida = _gravar(capsys, arq)
    assert codigo == 0 and "igual (já cancelada)" in saida


def test_carregar_medicoes_cancelar_recusa_recebida_e_substituta_inexistente(tmp_path, monkeypatch, capsys):
    conn, cid = _com_exemplo_aplicado(tmp_path, monkeypatch)
    _existente(conn, cid, 4, "2025-07", 100001, 100001)
    _existente(conn, cid, 5, "2025-07", 100001, 100001, estado="recebida")
    _existente(conn, cid, 6, "2025-07", 100001, 100001)
    antes = _foto(conn)
    codigo, saida = _gravar(capsys, _csv(tmp_path, ["5;;execucao;2025-07;;;;;;;;;x;4;", "6;;execucao;2025-07;;;;;;;;;x;9;",
                                                    "7;;execucao;2025-07;;;;;;;;;x;4;"]))
    assert codigo == 1 and "Recusado, nada foi gravado" in saida
    assert _foto(conn) == antes
    codigo, saida = _ensaio(tmp_path, [CAB + ";cancelar;corrige competência", "5;;execucao;2025-07;;;;;;;;;x;4;",
                                       "6;;execucao;2025-07;;;;;;;;;x;9;", "7;;execucao;2025-07;;;;;;;;;x;4;",
                                       "8;;execucao;2025-07;;1,00;;;;;;;x;8;"], capsys)
    assert "linha 2: nº 5 execução 2025-07: conflito (no banco a medição está recebida: não se cancela pela carga)" in saida
    assert "linha 3: nº 6 execução 2025-07: erro (cancelar: a 9ª execução que a substitui não está no banco nem no CSV)" in saida
    assert "linha 4: nº 7 execução 2025-07: erro (cancelar: não há 7ª execução no banco)" in saida
    assert "linha 5: nº 8 execução: erro (cancelar: a medição não substitui a si mesma)" in saida


def test_carregar_medicoes_competencia_errada_se_corrige_com_auditoria(tmp_path, monkeypatch, capsys):
    import json
    conn, cid = _com_exemplo_aplicado(tmp_path, monkeypatch)
    mid = _existente(conn, cid, 3, "2025-07", 60125000, None)
    linha = "3;3;execucao;2025-06;;601.250,00;;;;;;;planilha;;"
    codigo, saida = _gravar(capsys, _csv(tmp_path, [linha]))
    assert codigo == 1 and "1 linha(s) com erro ou conflito" in saida       # sem a marca: conflito
    codigo, saida = _gravar(capsys, _csv(tmp_path, [linha + "sim"]))
    assert codigo == 0, saida
    assert "correção (competência: banco 2025-07, CSV 2025-06)" in saida
    assert "competência corrigida de 2025-07 para 2025-06" in saida
    assert conn.execute("SELECT competencia FROM medicoes WHERE id=?", (mid,)).fetchone()[0] == "2025-06"
    a = conn.execute("SELECT antes, depois FROM audit_log WHERE acao='medicao.competencia' AND entidade_id=?",
                     (str(mid),)).fetchone()
    assert json.loads(a["antes"]) == {"competencia": "2025-07"} and json.loads(a["depois"])["competencia"] == "2025-06"


def test_carregar_medicoes_gravar_exige_usuario_e_recusa_meio_ou_periodo_invalidos(tmp_path, monkeypatch, capsys):
    conn, _ = _com_exemplo_aplicado(tmp_path, monkeypatch)
    codigo, saida = _gravar(capsys, usuario=None)
    assert codigo == 1 and "Gravar exige --usuario" in saida
    codigo, saida = _ensaio(tmp_path, [CAB, "1;1;execucao;2025-04;30/04/2025 a 01/04/2025;1,00;;;;;;;",
                                       "2;2;execucao;2025-05;;1,00;1,00;;pombo;;;;"], capsys)
    assert "linha 2: nº 1 execução: erro (período invertido" in saida
    assert "linha 3: nº 2 execução: erro (meio desconhecido: 'pombo'" in saida


def test_carregar_medicoes_nf_de_outra_obra_pelo_centro_de_custo_nao_entra(tmp_path, monkeypatch, capsys):
    conn, cid = _com_exemplo_aplicado(tmp_path, monkeypatch)
    outro = conn.execute("SELECT id FROM contratos WHERE id<>? AND COALESCE(entidade_id, 1)="
                         "(SELECT COALESCE(entidade_id, 1) FROM contratos WHERE id=?)", (cid, cid)).fetchone()
    if outro is not None:
        conn.execute("UPDATE contratos SET centro_custo_rm='CC-OUTRA' WHERE id=?", (outro[0],))
    conn.execute("UPDATE contratos SET centro_custo_rm='CC-PROPRIA' WHERE id=?", (cid,))
    _nf_no_rm(conn, 101, 9001, 41234567, 38000000, 38000000, 1, "2025-07-10", centro="CC-OUTRA")   # quitada, outra obra
    _nf_no_rm(conn, 108, 9002, 53000000, 49000000, 49000000, 1, "2025-07-11", centro="CC-PROPRIA")
    codigo, saida = _gravar(capsys)
    assert codigo == 0, saida
    assert "NF 101 não vinculada (NF 101 é de outra obra no RM, pelo centro de custo)" in saida
    estados = dict(conn.execute("SELECT numero, estado FROM medicoes WHERE contrato_id=? AND tipo='execucao'", (cid,)))
    assert estados[1] == "protocolada" and estados[2] == "recebida"


def test_carregar_medicoes_nf_que_nao_cobre_o_valor_nao_da_como_recebida(tmp_path, monkeypatch, capsys):
    # MT-388: a medicao sai em duas notas; so' uma quitada (e a outra fora do CSV) nao fecha a medicao
    conn, cid = _com_exemplo_aplicado(tmp_path, monkeypatch)
    _nf_no_rm(conn, 101, 9001, 20617283, 19000000, 19000000, 1, "2025-07-10")     # metade de 412.345,67 (impar)
    codigo, saida = _gravar(capsys)
    assert codigo == 0, saida
    assert ("NF 101 não vinculada (as notas somam R$ 206.172,83 e a medição vale R$ 412.345,67: falta nota no CSV)"
            in saida)
    assert conn.execute("SELECT COUNT(*) FROM nf_alocacoes").fetchone()[0] == 0
    # nem a sincronizacao seguinte com o RM a da' como recebida (revisor da #259)
    from app import sincronizacao_rm
    sincronizacao_rm._recebimentos(conn)
    m = conn.execute("SELECT estado FROM medicoes WHERE contrato_id=? AND numero=1 AND tipo='execucao'", (cid,)).fetchone()
    assert m[0] == "protocolada"


def test_carregar_medicoes_duas_notas_da_mesma_medicao_quitadas_dao_recebida(tmp_path, monkeypatch, capsys):
    conn, cid = _com_exemplo_aplicado(tmp_path, monkeypatch)
    _nf_no_rm(conn, 101, 9001, 20617283, 19000000, 19000000, 1, "2025-07-10")
    _nf_no_rm(conn, 102, 9003, 20617284, 19000000, 19000000, 1, "2025-07-12")     # 20.617.283 + 20.617.284 = cheio
    arq = tmp_path / "obra-propria.csv"
    arq.write_text("\n".join([CAB, "1;1;execucao;2025-04;;412.345,67;412.345,67;20/05/2025;e-mail;;;101/102;x"]) + "\n",
                   "utf-8")
    codigo, saida = _gravar(capsys, arq)
    assert codigo == 0 and "NF 101/102 vinculada; recebida (baixa no RM)" in saida, saida
    m = conn.execute("SELECT estado, recebida_em FROM medicoes WHERE contrato_id=? AND numero=1", (cid,)).fetchone()
    assert tuple(m) == ("recebida", "2025-07-12")


def test_carregar_medicoes_nova_sem_pedido_e_numero_gigante_sao_erro(tmp_path, monkeypatch, capsys):
    _com_exemplo_aplicado(tmp_path, monkeypatch)
    codigo, saida = _ensaio(tmp_path, [CAB, "1;1;execucao;2025-04;;;1,00;;;;;;",
                                       "99999999999999999999;1;execucao;2025-05;;1,00;;;;;;;",
                                       "3;99999999999999999999;execucao;2025-06;;1,00;;;;;;;"], capsys)
    assert codigo == 0
    assert "linha 2: nº 1 execução 2025-04: erro (medição nova sem valor pedido)" in saida
    assert "erro (nº inválido: '99999999999999999999')" in saida
    assert "erro (nº do órgão inválido: '99999999999999999999')" in saida


def test_carregar_medicoes_nf_com_o_centro_de_custo_anterior_da_obra_entra(tmp_path, monkeypatch, capsys):
    # O RM trocou os centros em 2024: a NF antiga da propria obra traz o centro anterior
    conn, cid = _com_exemplo_aplicado(tmp_path, monkeypatch)
    conn.execute("UPDATE contratos SET centros_custo_anteriores_rm='[\"1.234.000\"]' WHERE id=?", (cid,))
    _nf_no_rm(conn, 108, 9002, 53000000, 49000000, 49000000, 1, "2025-07-11", centro="1.234.000")
    codigo, saida = _gravar(capsys)
    assert codigo == 0 and "NF 108 vinculada; recebida (baixa no RM)" in saida, saida


def _linha_nf(tmp_path, nfs, aprovado="412.345,67"):
    arq = tmp_path / "obra-propria.csv"
    arq.write_text("\n".join([CAB, f"1;1;execucao;2025-04;;412.345,67;{aprovado};20/05/2025;e-mail;;;{nfs};x"]) + "\n",
                   "utf-8")
    return arq


def test_carregar_medicoes_nf_um_centavo_abaixo_da_medicao_nao_cobre(tmp_path, monkeypatch, capsys):
    conn, _ = _com_exemplo_aplicado(tmp_path, monkeypatch)
    _nf_no_rm(conn, 101, 9001, 41234566, 38000000, 38000000, 1, "2025-07-10")     # R$ 0,01 a menos
    codigo, saida = _gravar(capsys, _linha_nf(tmp_path, "101"))
    assert codigo == 0 and "falta nota no CSV" in saida, saida
    assert conn.execute("SELECT COUNT(*) FROM nf_alocacoes").fetchone()[0] == 0


def test_carregar_medicoes_nf_repetida_na_celula_nao_vincula_nem_quebra(tmp_path, monkeypatch, capsys):
    conn, _ = _com_exemplo_aplicado(tmp_path, monkeypatch)
    _nf_no_rm(conn, 101, 9001, 41234567, 38000000, 38000000, 1, "2025-07-10")
    codigo, saida = _gravar(capsys, _linha_nf(tmp_path, "101/000101"))
    assert codigo == 0 and "NF 000101 repetida na linha" in saida, saida
    assert conn.execute("SELECT COUNT(*) FROM nf_alocacoes").fetchone()[0] == 0


def test_carregar_medicoes_centro_de_custo_de_duas_obras_nao_serve(tmp_path, monkeypatch, capsys):
    conn, cid = _com_exemplo_aplicado(tmp_path, monkeypatch)
    centro = conn.execute("SELECT centro_custo_rm FROM contratos WHERE id=?", (cid,)).fetchone()[0]
    outro = conn.execute("SELECT id FROM contratos WHERE id<>? AND COALESCE(entidade_id, 1)="
                         "(SELECT COALESCE(entidade_id, 1) FROM contratos WHERE id=?)", (cid, cid)).fetchone()
    if outro is None:       # o exemplo nao tem outra obra da mesma empresa: cria uma
        outro = [conn.execute("INSERT INTO contratos (orgao, orgao_id, numero_instrumento, objeto, valor_original_centavos) "
                              "SELECT orgao, orgao_id, 'IC OUTRA', 'outra', 1 FROM contratos WHERE id=?", (cid,)).lastrowid]
    conn.execute("UPDATE contratos SET centros_custo_anteriores_rm=? WHERE id=?", (f'["{centro}"]', outro[0]))
    _nf_no_rm(conn, 101, 9001, 41234567, 38000000, 38000000, 1, "2025-07-10")
    codigo, saida = _gravar(capsys, _linha_nf(tmp_path, "101"))
    assert codigo == 0 and "NF 101 tem centro de custo de mais de uma obra no cadastro" in saida, saida


def test_carregar_medicoes_contrato_sem_centro_na_empresa_de_varias_obras_nao_vincula(tmp_path, monkeypatch, capsys):
    conn, cid = _com_exemplo_aplicado(tmp_path, monkeypatch)
    conn.execute("UPDATE contratos SET centro_custo_rm=NULL WHERE id=?", (cid,))
    _nf_no_rm(conn, 101, 9001, 41234567, 38000000, 38000000, 1, "2025-07-10", centro="")
    codigo, saida = _gravar(capsys, _linha_nf(tmp_path, "101"))
    assert codigo == 0 and "o contrato não tem centro de custo do RM no cadastro" in saida, saida


def test_carregar_medicoes_banco_ocupado_fala_portugues(tmp_path, monkeypatch, capsys):
    import sqlite3 as _sql
    from app import carga_medicoes
    _com_exemplo_aplicado(tmp_path, monkeypatch)

    def ocupado(*a, **k):
        raise _sql.OperationalError("database is locked")
    monkeypatch.setattr(carga_medicoes, "gravar", ocupado)
    codigo, saida = _gravar(capsys)
    assert codigo == 1 and "o banco está ocupado por outra gravação" in saida and "locked" not in saida
