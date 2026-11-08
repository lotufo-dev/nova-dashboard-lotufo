"""Leitor deterministico da NFS-e da Lotufo (spec §7.1). Puro: texto -> campos, sem banco nem arquivo.

Leiaute `cuiaba` = Prefeitura de Cuiaba / ISSNet online (serve tambem a Varzea Grande, que sai pelo
mesmo portal). Regras herdadas do leitor da FRC da dashboard antiga e conferidas em cinco notas
reais (tests/fixtures/nfse): INSS e' `Vl. CP Retido`; o numero vem SEMPRE do conteudo; lixo em
moeda e' None, nunca zero; totais impressos (retencao, CBS, IBS, liquido) sao lidos e conferidos
contra as parcelas -- diferenca vira aviso, nao recusa.

Leiaute `danfse` = DANFSe v2.0 do emissor nacional (notas de Cuiaba a partir de 09/2026; amostra:
nota 3106 da MT-402, tests/fixtures/nfse/3106-mt402-danfse.txt). Lido sobre o texto com os espacos
e quebras de linha NORMALIZADOS (o extrator pode por rotulo e valor na mesma linha ou em linhas
diferentes); o numero e o CNPJ do prestador sao conferidos contra a chave de acesso de 50 digitos.

Leiaute `centi` = NFS-e da Prefeitura de Tangara da Serra emitida pelo sistema da Centi Solucoes (as notas
da Guaxe, consorciada do Integra BRT, para a FRC; amostra: nota 20260000812 da 11a medicao,
tests/fixtures/nfse/2026812-integra-beta-vg.txt). INSS e IR vem da linha "RETENÇÕES FEDERAIS"; o ISS e' o
"ISS Retido pelo Tomador" do demonstrativo (a FRC soma retencoes); o numero e o CNPJ sao conferidos contra
a chave de acesso nacional, como no DANFSe.
Outro leiaute e' recusado com motivo: a pessoa digita numero, data e valor.
"""
import re

_MOEDA = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})")
_DATA = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
_CNPJ = re.compile(r"(\d{2})\.?(\d{3})\.?(\d{3})/?(\d{4})-?(\d{2})")

CAMPOS_OBRIGATORIOS = ("numero", "emissao", "prestador_cnpj", "valor_centavos")


def centavos(texto) -> int | None:
    """'R$4.075.275,90' | 'R$ 1.234,56' | '1.234,56' -> centavos. '-', vazio ou lixo -> None."""
    if texto is None:
        return None
    m = re.search(r"(\d{1,3}(?:\.\d{3})*|\d+),(\d{2})\b", str(texto))
    if not m:
        return None
    return int(m.group(1).replace(".", "")) * 100 + int(m.group(2))


def _iso(m) -> str:
    d, mes, a = m.groups()
    return f"{a}-{mes}-{d}"


def _apos(rotulo: str, texto: str, padrao: str, flags=0):
    """Primeiro `padrao` DEPOIS de `rotulo` (comparacao literal do rotulo, com acento)."""
    i = texto.find(rotulo)
    if i < 0:
        return None
    return re.search(padrao, texto[i + len(rotulo):], flags)


def _moeda_apos(rotulo: str, texto: str) -> int | None:
    m = _apos(rotulo, texto, r"^\s*(R\$\s*[\d\.]+,\d{2}|-)")
    return centavos(m.group(1)) if m else None


def _leiaute(texto: str) -> str | None:
    if "Número da Nota Fiscal" in texto and ("Vl. do Serviço" in texto or "ISSQN" in texto):
        return "cuiaba"
    plano = re.sub(r"\s+", " ", texto)
    if "Documento Auxiliar da NFS-e" in plano and "CHAVE DE ACESSO DA NFS-E" in plano:
        return "danfse"
    # A Guaxe trocou o quadro "RETENÇÕES FEDERAIS" por "TRIBUTAÇÃO FEDERAL" a partir da 15ª do Integra (09/10/2026)
    if "Centi Soluções" in plano and ("RETENÇÕES FEDERAIS" in plano or "TRIBUTAÇÃO FEDERAL" in plano) \
            and "Número da Nota" in plano:
        return "centi"
    return None


def _descricao(n: dict, desc: str) -> None:
    """Natureza, numero da medicao, periodo e competencia a partir da descricao do servico (maiusculas,
    espacos normalizados). Igual nos dois leiautes: o texto e' o que a Lotufo escreve na nota."""
    if re.search(r"REAJUST", desc):            # REAJUSTE DA / REAJUSTAMENTO / REAJUSTE REFERENTE
        n["natureza"] = "reajuste"
    # "EXECUÇÃO DE PROJETO DAS OBRAS" e' execucao de obra (Estacoes BRT, com INSS), nao projeto (#564)
    elif re.search(r"ELABORAÇÃO DE PROJETO|EXECUÇÃO DE PROJETO(?! DAS OBRAS)|(?<!EXECUÇÃO )DE PROJETO DAS OBRAS",
                   desc):
        n["natureza"] = "projeto"
    else:
        n["natureza"] = "medicao"
    m = re.search(r"(\d{1,3})\s*[ªº°]\s*MEDI", desc)
    n["numero_medicao"] = int(m.group(1)) if m else None
    m = re.search(r"PERÍODO DE (\d{2}/\d{2}/\d{4}) A (\d{2}/\d{2}/\d{4})", desc)
    n["periodo"] = None
    if m:
        ini, fim = _iso(_DATA.search(m.group(1))), _iso(_DATA.search(m.group(2)))
        if fim >= ini:
            n["periodo"] = (ini, fim)
    n["competencia"] = (n["periodo"][0][:7] if n["periodo"] else (n["emissao"][:7] if n["emissao"] else None))


def _autoconferir(n: dict) -> None:
    partes = [n["iss_centavos"], n["inss_centavos"], n["irrf_centavos"]]
    if n["retencao_total_centavos"] is not None and all(p is not None for p in partes) \
            and sum(partes) != n["retencao_total_centavos"]:
        n["avisos"].append("ISS + INSS + IRRF não fecham com a retenção total impressa na nota")
    if None not in (n["valor_centavos"], n["retencao_total_centavos"], n["liquido_centavos"]) \
            and n["valor_centavos"] - n["retencao_total_centavos"] != n["liquido_centavos"]:
        n["avisos"].append("bruto menos retenção não fecha com o líquido impresso na nota")


def _cuiaba(texto: str) -> dict:
    n: dict = {"leiaute": "cuiaba", "avisos": []}
    m = _apos("Número da Nota Fiscal", texto, r"(\d+)")
    n["numero"] = int(m.group(1)) if m and int(m.group(1)) > 0 else None
    m = _apos("Data de Geração da NFS-e", texto, r"\d{2}/\d{2}/\d{4}")
    n["emissao"] = _iso(_DATA.search(m.group(0))) if m else None

    i_tom = texto.find("IDENTIFICAÇÃO DO TOMADOR")
    prest, tom = (texto[:i_tom], texto[i_tom:]) if i_tom > 0 else (texto, "")
    for chave, trecho in (("prestador", prest), ("tomador", tom)):
        m = _apos("CNPJ/CPF/NIF:", trecho, r"\s*([\d\./-]{14,18})")
        c = _CNPJ.search(m.group(1)) if m else None
        n[f"{chave}_cnpj"] = "".join(c.groups()) if c else None
        m = _apos("Nome/Razão Social:", trecho, r"\s*([^\n]+)")
        n[f"{chave}_nome"] = m.group(1).strip() if m else None

    m = _apos("Local da Prestação:", texto, r"\s*([^\n]+?)\s+-\s+MT\b")
    n["municipio"] = m.group(1).strip() if m else None
    n["valor_centavos"] = _moeda_apos("Vl. do Serviço:", texto)
    n["iss_centavos"] = _moeda_apos("Vl. ISSQN:", texto)
    n["irrf_centavos"] = _moeda_apos("Vl. IRRF:", texto)
    n["inss_centavos"] = _moeda_apos("Vl. CP Retido:", texto)

    # Totais impressos: a linha depois de "Total de Retenção ... IBS/CBS" traz 5 valores
    # (retencao, CBS, IBS, liquido, total da nota).
    m = _apos("Total de Retenção", texto, r"IBS/CBS\s*\n([^\n]+)")
    tot = [centavos(x) for x in _MOEDA.findall(m.group(1))] if m else []
    n["retencao_total_centavos"], n["cbs_centavos"], n["ibs_centavos"], n["liquido_centavos"] = (
        (tot + [None] * 4)[:4])

    desc = ""
    m = _apos("Descrição do Serviço:", texto, r"([\s\S]*?)(?:\nIMPOSTO SOBRE SERVIÇO|\Z)")
    if m:
        desc = re.sub(r"\s+", " ", m.group(1)).upper()
    _descricao(n, desc)
    _autoconferir(n)
    return n


_VALOR = r"\s*(R\$\s*[\d\.]+,\d{2}|-)"


def _danfse_moeda(rotulo_regex: str, plano: str) -> int | None:
    m = re.search(rotulo_regex + _VALOR, plano)
    return centavos(m.group(1)) if m else None


def _danfse(texto: str) -> dict:
    n: dict = {"leiaute": "danfse", "avisos": []}
    plano = re.sub(r"\s+", " ", texto)
    m = re.search(r"CHAVE DE ACESSO DA NFS-E\s*(\d{50})", plano)
    chave = m.group(1) if m else None
    # Chave de acesso: municipio(7) ambiente(1) tipo de inscricao(1) CNPJ(14) numero(13) AAMM(4) codigo(9) DV(1)
    numero_chave = int(chave[23:36]) if chave else None
    cnpj_chave = chave[9:23] if chave else None

    m = re.search(r"NÚMERO DA NFS-E\s*(\d+)", plano)
    n["numero"] = int(m.group(1)) if m and int(m.group(1)) > 0 else (numero_chave or None)
    if numero_chave and n["numero"] and numero_chave != n["numero"]:
        n["avisos"].append("número da nota não confere com a chave de acesso")
    m = re.search(r"DATA E HORA DA EMISSÃO DA NFS-E\s*(\d{2}/\d{2}/\d{4})", plano)
    n["emissao"] = _iso(_DATA.search(m.group(1))) if m else None

    i_prest = plano.find("PRESTADOR / FORNECEDOR")
    i_tom = plano.find("TOMADOR / ADQUIRENTE")
    i_serv = plano.find("SERVIÇO PRESTADO")
    trechos = {"prestador": plano[i_prest:i_tom] if 0 <= i_prest < i_tom else "",
               "tomador": plano[i_tom:i_serv] if 0 <= i_tom < i_serv else ""}
    for chave_parte, trecho in trechos.items():
        m = re.search(r"CNPJ / CPF / NIF\s*([\d\./-]{14,18})", trecho)
        c = _CNPJ.search(m.group(1)) if m else None
        n[f"{chave_parte}_cnpj"] = "".join(c.groups()) if c else None
        m = re.search(r"Nome / Nome Empresarial\s*(.+?)\s+Município / Sigla UF", trecho)
        n[f"{chave_parte}_nome"] = m.group(1).strip() if m else None
    if n["prestador_cnpj"] is None:
        n["prestador_cnpj"] = cnpj_chave
    elif cnpj_chave and cnpj_chave != n["prestador_cnpj"]:
        n["avisos"].append("CNPJ do prestador não confere com a chave de acesso")

    m = re.search(r"Local da Prestação / Sigla UF / País\s*(.+?)\s*/\s*MT\b", plano)
    n["municipio"] = m.group(1).strip() if m else None
    n["valor_centavos"] = _danfse_moeda(r"VALOR DA OPERAÇÃO / SERVIÇO", plano)
    n["iss_centavos"] = _danfse_moeda(r"ISSQN Apurado", plano)
    n["irrf_centavos"] = _danfse_moeda(r"\bIRRF", plano)
    n["inss_centavos"] = _danfse_moeda(r"Contribuição Previdenciária\s*[–-]\s*Retida", plano)
    n["retencao_total_centavos"] = _danfse_moeda(r"Total das Retenções \(ISSQN / Federais\)", plano)
    n["liquido_centavos"] = _danfse_moeda(r"VALOR LÍQUIDO DA NFS-e", plano)
    n["cbs_centavos"] = _danfse_moeda(r"Valor Total Apuração\s*[–-]\s*CBS", plano)
    n["ibs_centavos"] = _danfse_moeda(r"Valor Total Apurado\s*[–-]\s*IBS", plano)

    m = re.search(r"Descrição do Serviço\s*(.*?)\s*TRIBUTAÇÃO MUNICIPAL", plano)
    _descricao(n, (m.group(1) if m else "").upper())
    _autoconferir(n)
    return n


_NUM = r"\s*(\d{1,3}(?:\.\d{3})*,\d{2})"
_MINUSCULAS = ("da", "das", "de", "do", "dos", "e")


def _municipio_legivel(nome: str) -> str:
    """'VÁRZEA GRANDE' -> 'Várzea Grande' (o Centi imprime ora em maiusculas, ora nao)."""
    if not nome.isupper():
        return nome
    return " ".join(p if p in _MINUSCULAS else p.capitalize() for p in nome.lower().split())


def _centi(texto: str) -> dict:
    n: dict = {"leiaute": "centi", "avisos": []}
    m = re.search(r"Chave de acesso Nota Nacional:\s*(\d{50})", texto)
    chave = m.group(1) if m else None
    numero_chave = int(chave[23:36]) if chave else None      # mesma estrutura da chave do DANFSe
    cnpj_chave = chave[9:23] if chave else None

    m = re.search(r"Número da Nota\s*\n\s*(\d+)", texto)
    n["numero"] = int(m.group(1)) if m and int(m.group(1)) > 0 else None
    if numero_chave and n["numero"] and numero_chave != n["numero"]:
        n["avisos"].append("número da nota não confere com a chave de acesso")
    m = re.search(r"(\d{2}/\d{2}/\d{4}) \d{2}:\d{2}:\d{2}", texto)      # "Data e Hora de Emissão"
    n["emissao"] = _iso(_DATA.search(m.group(1))) if m else None

    # O extrator cola o CNPJ no rotulo seguinte: "31.200.202/0001-00CNPJ:" (prestador) e
    # "31.300.101/0001-01CNPJ/CPF:" (tomador).
    m = re.search(r"([\d\./-]{18})CNPJ:\s", texto)
    c = _CNPJ.search(m.group(1)) if m else None
    n["prestador_cnpj"] = "".join(c.groups()) if c else cnpj_chave
    if cnpj_chave and n["prestador_cnpj"] != cnpj_chave:
        n["avisos"].append("CNPJ do prestador não confere com a chave de acesso")
    m = re.search(r"CNPJ/CPF:\s*\n([^\n]+)", texto)
    n["prestador_nome"] = m.group(1).strip() if m else None
    m = re.search(r"([\d\./-]{18})CNPJ/CPF:", texto)
    c = _CNPJ.search(m.group(1)) if m else None
    n["tomador_cnpj"] = "".join(c.groups()) if c else None
    n["tomador_nome"] = None

    m = re.search(r"Serviço prestado em\s*\n\s*(.+?)\s+-\s+MT\b", texto)
    n["municipio"] = _municipio_legivel(m.group(1).strip()) if m else None
    m = re.search(r"Valor dos Serviços" + _NUM + r"\s+Desconto", texto)
    n["valor_centavos"] = centavos(m.group(1)) if m else None

    # "RETENÇÕES FEDERAIS COFINS INSS IR CSLL PIS" e os cinco valores na linha de baixo
    m = re.search(r"RETENÇÕES FEDERAIS COFINS INSS IR CSLL\s*PIS" + _NUM * 5, texto)
    if m is None:
        # Modelo novo (09/10/2026): "TRIBUTAÇÃO FEDERAL COFINS - Débito Apuração Própria | Contrib. Previdenciária
        # - Retida | IRRF | Contribuições Sociais - Retidas | PIS - Débito Apuração Própria", mesma ordem
        # COFINS, INSS, IR, CSLL, PIS e os cinco valores depois do ultimo rotulo.
        m = re.search(r"TRIBUTAÇÃO FEDERAL\s*COFINS[\s\S]{0,300}?PIS\s*-\s*Débito Apuração Própria" + _NUM * 5, texto)
    federais = [centavos(x) for x in m.groups()] if m else [None] * 5
    n["inss_centavos"], n["irrf_centavos"] = federais[1], federais[2]
    # Demonstrativo: desconto incondicionado, retencoes federais, ISS retido pelo tomador e valor liquido
    m = re.search(r"Demonstrativo\s+Valor dos Serviços" + _NUM * 4, texto)
    desconto, ret_federais, iss_retido, liquido = ([centavos(x) for x in m.groups()] if m else [None] * 4)
    n["iss_centavos"] = iss_retido
    n["liquido_centavos"] = liquido
    n["retencao_total_centavos"] = (ret_federais + iss_retido
                                    if ret_federais is not None and iss_retido is not None else None)
    n["cbs_centavos"] = n["ibs_centavos"] = None          # o extrator embaralha a linha do IBS/CBS
    if None not in federais and ret_federais is not None and sum(federais) != ret_federais:
        n["avisos"].append("COFINS + INSS + IR + CSLL + PIS não fecham com as retenções federais da nota")
    if desconto:
        n["avisos"].append("nota com desconto incondicionado")

    m = re.search(r"Descrição:\s*([\s\S]*?)(?:\nMÃO DE OBRA|\nTOMADOR DE SERVIÇOS|\Z)", texto)
    _descricao(n, re.sub(r"\s+", " ", m.group(1)).upper() if m else "")
    _autoconferir(n)
    return n


def ler(texto: str) -> dict:
    """{ok, motivo, leiaute, ...campos}. `ok=False` com motivo `sem-texto`, `leiaute-desconhecido`,
    `sem-numero` (rascunho) ou `campos-ausentes:<lista>`."""
    if not (texto or "").strip():
        return {"ok": False, "motivo": "sem-texto", "leiaute": None}
    leiaute = _leiaute(texto)
    if leiaute is None:
        return {"ok": False, "motivo": "leiaute-desconhecido", "leiaute": None}
    n = {"cuiaba": _cuiaba, "danfse": _danfse, "centi": _centi}[leiaute](texto)
    if n["numero"] is None:
        return {"ok": False, "motivo": "sem-numero", "leiaute": leiaute}
    faltando = [c for c in CAMPOS_OBRIGATORIOS if n.get(c) is None]
    if faltando:
        return {"ok": False, "motivo": "campos-ausentes:" + ",".join(faltando), "leiaute": leiaute}
    return {"ok": True, "motivo": None, **n}
