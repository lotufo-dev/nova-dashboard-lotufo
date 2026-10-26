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
    assert "Total: nova 4, igual 0, valor diferente 0, incompleta 0, conflito 0, erro 0" in saida


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
    assert "linha 4: nº 3 execução 2025-07: conflito (banco tem competência 2025-06)" in saida
    assert "linha 5: nº 4 execução 2025-08: nova" in saida
    assert "linha 6: nº 5 execução: erro (valor pedido" in saida
    assert "linha 7: nº 6 aditivo: erro (tipo desconhecido" in saida
    assert "linha 8: nº 7 execução: erro (competência 2027-03 fora do contrato (2025-03 a 2026-12))" in saida
    assert "linha 9: nº 4 execução 2025-08: erro (nº 4 execução repetido (já na linha 5))" in saida
    assert "Total: nova 1, igual 1, valor diferente 1, incompleta 0, conflito 1, erro 4" in saida
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
    codigo, saida = _ensaio(tmp_path, ["N°;Tipo;Competência;Nº. do órgão;Valor pedido;Valor aprovado", "1;execucao;2025-04;1;;"], capsys)
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
