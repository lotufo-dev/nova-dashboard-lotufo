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
