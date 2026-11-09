"""Motor do espelho de NF (spec 2026-09-21 §4): regra fiscal da obra + valores digitados -> uma
saida por nota. Puro: sem banco, sem arquivo. Cada parcela e cada tributo declara `trunc` ou
`round`, porque as planilhas-motor das obras diferem nisso e o espelho real e' a prova
(docs/espelho-regras-por-obra-2026-09-16.md §3, levantamento de 2026-09-22).

A conta IMITA A PLANILHA, inclusive o ponto flutuante do Excel (decisao do Leonardo em
2026-09-23: o espelho tem de sair igual ao da planilha). Cada celula e' um double; soma, produto
e divisao sao os do Excel, na ordem das formulas (`resto_de` subtrai as irmas uma a uma,
`fracao` divide antes de multiplicar). TRUNC/ROUND na celula (rateio, mao de obra) seguem o Excel,
que arredonda o double a 15 digitos significativos e so' depois corta ou arredonda (`_excel`,
conferido contra o Excel em 26.890 casos). O espelho le a celula como o motor antigo lia
(`_leitura`): tributo cru truncado com a folga de 1e-4 centavo, ou arredondado por Math.round
(em meio centavo exato o double pode ficar abaixo e o Math.round dar o centavo de baixo:
1,005 -> 1,00, como o motor antigo dava; o ISS truncado dos espelhos reais mostra que eles saiam
do motor e nao da tela do Excel, que arredondaria 1.425,1695 para 1.425,17).
Por isso a Rivoli em Varzea Grande (Oriundi 46a, 16.910,50) tem MO 6.764,19 e nao 6.764,20:
16.910,50 chega a celula como 16.910,4999... e o TRUNC do Excel corta ali. Tributo arredondado
NA CELULA (ROUND das MTPAR) declara `na_celula: true`: o ROUND do Excel vem antes da leitura.
"""
import calendar
import copy
import math
import re
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation

from app import extenso

NATUREZAS = ("medicao", "reajuste", "projeto")
TIPO_POR_NATUREZA = {"medicao": "execucao", "reajuste": "reajuste", "projeto": "projeto"}
ROTULO_NATUREZA = {"medicao": "Medição", "reajuste": "Reajuste", "projeto": "Projeto"}
SITUACOES = ("prova", "ativa")
ARREDONDAMENTOS = {"trunc": ROUND_DOWN, "round": ROUND_HALF_UP}
BASES = ("mao_de_obra", "material", "total")
TRIBUTOS = ("inss", "iss", "irrf", "ibs", "cbs")
CAMPOS_MODELO = ("valor", "mo", "material", "inss", "iss", "irrf", "valor_extenso", "medicao", "periodo", "mes_ano")
CAMPOS_OPCIONAIS = ("ibs", "cbs")
_CHAVE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
_CENT = Decimal("0.01")
# 13 digitos (R$ 99.999.999.999,99): o Excel guarda 15 significativos e o double conta centavos
# sem erro; acima disso a conta deixaria de imitar a planilha
TETO_CENTAVOS = 10**13 - 1


class RegraInvalida(Exception):
    def __init__(self, erros: list[str]):
        self.erros = erros
        super().__init__("\n".join(erros))


def _dec(v, onde, erros) -> str | None:
    """Numero do YAML como texto Decimal com ponto. Aceita '1,2' (virgula decimal) e '0.49'."""
    if v is None:
        erros.append(f"{onde}: obrigatório")
        return None
    texto = str(v).strip()
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        d = Decimal(texto)
    except InvalidOperation:
        erros.append(f"{onde}: número inválido: {v!r}")
        return None
    # NaN/Infinity passam pelo construtor e so' estouram no calculo; negativo nao e' percentual
    if not d.is_finite() or d < 0:
        erros.append(f"{onde}: número fora do domínio: {v!r}")
        return None
    return str(d)


def _excel(x: float, modo: str) -> float:
    """TRUNC(x;2) ou ROUND(x;2) do Excel: o double vai a 15 digitos significativos antes do corte."""
    return float(Decimal(format(x, ".15g")).quantize(_CENT, rounding=ARREDONDAMENTOS[modo]))


def _leitura(x: float, modo: str) -> int:
    """Centavos que o espelho mostra a partir da celula (trunc2/round2 do motor antigo)."""
    return int(math.trunc(x * 100 + 1e-4) if modo == "trunc" else math.floor(x * 100 + 0.5))


def _taxa(percentual: str) -> float:
    """O double que a planilha usa: 40 -> 0,4; 1,2 -> 0,012."""
    return float(Decimal(percentual) / 100)


def _retencao(bruto, onde, erros, obrigatorio_base=True, parcial=False):
    """`parcial=True` e' a sobrescrita de uma saida: so' valida o que veio (o resto vem da obra)."""
    if bruto is None:
        return None
    if not isinstance(bruto, dict):
        erros.append(f"{onde}: esperado mapa ou null")
        return None
    r = {}
    if not parcial or "percentual" in bruto:
        r["percentual"] = _dec(bruto.get("percentual"), f"{onde}.percentual", erros)
        if r["percentual"] is not None and Decimal(r["percentual"]) > 100:
            erros.append(f"{onde}.percentual: acima de 100")
    if not parcial or "arredondamento" in bruto:
        r["arredondamento"] = bruto.get("arredondamento")
        if r["arredondamento"] not in ARREDONDAMENTOS:
            erros.append(f"{onde}.arredondamento: use trunc ou round")
    if obrigatorio_base and (not parcial or "base" in bruto):
        r["base"] = bruto.get("base")
        if r["base"] not in BASES:
            erros.append(f"{onde}.base: use uma de {BASES}")
    if "deduz_liquido" in bruto:
        r["deduz_liquido"] = bool(bruto["deduz_liquido"])
    if "vigente_desde" in bruto:
        r["vigente_desde"] = str(bruto["vigente_desde"])
    if "na_celula" in bruto:
        r["na_celula"] = bool(bruto["na_celula"])
    return r


def _retencoes(bruto: dict, onde: str, erros: list[str], parcial: bool = False) -> dict:
    """Bloco completo (padrao da obra) ou parcial (sobrescrita da saida): so' normaliza o que veio."""
    if not isinstance(bruto, dict):
        erros.append(f"{onde}: esperado mapa")
        return {}
    out = {}
    for k, v in bruto.items():
        if k == "mao_de_obra":
            out[k] = _retencao(v, f"{onde}.{k}", erros, obrigatorio_base=False, parcial=parcial)
        elif k == "material":
            if v is None:
                out[k] = None
            elif not isinstance(v, dict) or v.get("modo") not in ("diferenca", "produto"):
                erros.append(f"{onde}.material.modo: use diferenca ou produto")
            elif v["modo"] == "produto":
                out[k] = {"modo": "produto", **(_retencao(v, f"{onde}.material", erros, False, parcial) or {})}
            else:
                out[k] = {"modo": "diferenca"}
        elif k in TRIBUTOS:
            out[k] = _retencao(v, f"{onde}.{k}", erros, parcial=parcial)
        else:
            erros.append(f"{onde}.{k}: retenção desconhecida")
    return out


def _mesclar(padrao: dict, sobre: dict) -> dict:
    """Sobrescrita chave a chave: `iss: {base: material}` troca so' a base do ISS da obra."""
    out = copy.deepcopy(padrao)
    for k, v in sobre.items():
        if v is None or k not in out or out[k] is None or not isinstance(v, dict):
            out[k] = copy.deepcopy(v)
        else:
            out[k] = {**out[k], **v}
    return out


def normalizar(bruto: dict) -> dict:
    erros: list[str] = []
    if not isinstance(bruto, dict):
        raise RegraInvalida(["regra não é um mapa YAML"])
    r = {"contrato": str(bruto.get("contrato") or ""), "situacao": bruto.get("situacao")}
    # como o modelo da obra escreve o numero ("01ª" x "1ª") e o extenso (CAIXA ALTA x minusculas)
    texto = bruto.get("texto") or {}
    if not isinstance(texto, dict) or set(texto) - {"numero_com_zero", "extenso_minusculo"}:
        erros.append("texto: use numero_com_zero e/ou extenso_minusculo")
        texto = {}
    if texto:           # so' quando declarado: a regra das outras obras (e o sha256 dela) nao muda
        r["texto"] = {k: bool(v) for k, v in texto.items()}
    if not r["contrato"]:
        erros.append("contrato: obrigatório")
    if r["situacao"] not in SITUACOES:
        erros.append(f"situacao: use uma de {SITUACOES}")
    conhecidas: dict[str, str] = {}      # chave -> 'entrada' | 'parcela'
    r["entradas"] = []
    for i, e in enumerate(bruto.get("entradas") or []):
        onde = f"entradas[{i}]"
        e = e or {}
        if not _CHAVE.match(str(e.get("chave") or "")) or e["chave"] in conhecidas:
            erros.append(f"{onde}.chave: inválida ou repetida: {e.get('chave')!r}")
            continue
        if e.get("natureza") not in NATUREZAS:
            erros.append(f"{onde}.natureza: use uma de {NATUREZAS}")
        conhecidas[e["chave"]] = e.get("natureza")      # natureza de quem alimenta a saida
        r["entradas"].append({"chave": e["chave"], "rotulo": str(e.get("rotulo") or e["chave"]),
                              "natureza": e.get("natureza")})
    if not r["entradas"]:
        erros.append("entradas: ao menos uma")
    r["parcelas"] = []
    for i, p in enumerate(bruto.get("parcelas") or []):
        onde = f"parcelas[{i}]"
        p = p or {}
        if not _CHAVE.match(str(p.get("chave") or "")) or p["chave"] in conhecidas:
            erros.append(f"{onde}.chave: inválida ou repetida: {p.get('chave')!r}")
            continue
        if p.get("de") not in conhecidas:
            erros.append(f"{onde}.de: referencia {p.get('de')!r}, que não foi declarada antes")
            continue
        modos = [k for k in ("fator", "fracao", "resto_de") if k in p]
        if len(modos) != 1:
            erros.append(f"{onde}: declare exatamente um de fator, fracao ou resto_de")
            continue
        n = {"chave": p["chave"], "de": p["de"]}
        if "fator" in p:
            n["fator"] = _dec(p["fator"], f"{onde}.fator", erros)
            if n["fator"] is not None and not 0 < Decimal(n["fator"]) <= 1:
                erros.append(f"{onde}.fator: rateio tem que estar entre 0 e 1 (exclusivo, inclusivo)")
        elif "fracao" in p:
            f = p["fracao"]
            if not (isinstance(f, list) and len(f) == 2 and all(isinstance(x, int) and x > 0 for x in f)):
                erros.append(f"{onde}.fracao: use [numerador, denominador] inteiros positivos")
                n["fracao"] = None
            else:
                n["fracao"] = list(f)
        else:
            irmas = p["resto_de"] if isinstance(p["resto_de"], list) else []
            for q in irmas:
                par = next((x for x in r["parcelas"] if x["chave"] == q), None)
                if par is None or par["de"] != p["de"]:
                    erros.append(f"{onde}.resto_de: {q!r} não é parcela irmã (mesmo `de`) já declarada")
            n["resto_de"] = irmas
        if "resto_de" not in n:
            if p.get("arredondamento") not in ARREDONDAMENTOS:
                erros.append(f"{onde}.arredondamento: use trunc ou round")
            n["arredondamento"] = p.get("arredondamento")
        conhecidas[p["chave"]] = conhecidas[p["de"]]    # parcela herda a natureza da origem
        r["parcelas"].append(n)
    padrao = _retencoes(bruto.get("retencoes") or {}, "retencoes", erros)
    for k in ("mao_de_obra", "material", "inss", "iss", "irrf"):
        padrao.setdefault(k, None)
    r["saidas"] = []
    chaves_saida = set()
    for i, s in enumerate(bruto.get("saidas") or []):
        onde = f"saidas[{i}]"
        s = s or {}
        if not _CHAVE.match(str(s.get("chave") or "")) or s["chave"] in chaves_saida:
            erros.append(f"{onde}.chave: inválida ou repetida: {s.get('chave')!r}")
            continue
        chaves_saida.add(s["chave"])
        if s.get("natureza") not in NATUREZAS:
            erros.append(f"{onde}.natureza: use uma de {NATUREZAS}")
        valor = s.get("valor") if isinstance(s.get("valor"), list) else [s.get("valor")]
        for v in valor:
            if v not in conhecidas:
                erros.append(f"{onde}.valor: referencia {v!r}, que não existe")
            elif conhecidas[v] != s.get("natureza"):
                # a nota vai para a MEDICAO da natureza da saida; um valor de outra natureza
                # criaria nota sem medicao correspondente (KeyError na geracao)
                erros.append(f"{onde}.valor: {v!r} é de natureza {conhecidas[v]!r}, a saída é "
                             f"{s.get('natureza')!r}")
        for campo in ("emissor", "municipio", "modelo"):
            if not s.get(campo):
                erros.append(f"{onde}.{campo}: obrigatório")
        ret = _mesclar(padrao, _retencoes(s.get("retencoes") or {}, f"{onde}.retencoes", erros, parcial=True))
        # uma sobrescrita parcial de tributo que a obra nao tem (ex.: so' `base`) ficaria incompleta
        for t in TRIBUTOS:
            if ret.get(t) is not None and not all(k in ret[t] for k in ("percentual", "arredondamento", "base")):
                erros.append(f"{onde}.retencoes.{t}: incompleto (percentual, base e arredondamento)")
        if ret.get("mao_de_obra") is not None and not all(k in ret["mao_de_obra"] for k in ("percentual", "arredondamento")):
            erros.append(f"{onde}.retencoes.mao_de_obra: incompleto (percentual e arredondamento)")
        if ret.get("mao_de_obra") is None:
            if ret.get("material") is not None:
                erros.append(f"{onde}: sem mão de obra não há material (declare material: null)")
            for t in TRIBUTOS:
                if ret.get(t) and ret[t].get("base") in ("mao_de_obra", "material"):
                    erros.append(f"{onde}.retencoes.{t}.base: {ret[t]['base']} exige mão de obra")
        elif ret.get("material") is None:
            erros.append(f"{onde}: com mão de obra o material é obrigatório (diferenca ou produto)")
        if ret.get("iss") is not None:
            ret["iss"].setdefault("deduz_liquido", True)
        r["saidas"].append({"chave": s["chave"], "natureza": s.get("natureza"), "rotulo": s.get("rotulo"),
                            "valor": valor, "emissor": str(s.get("emissor") or ""),
                            "municipio": str(s.get("municipio") or ""), "modelo": str(s.get("modelo") or ""),
                            "retencoes": ret})
    if not r["saidas"]:
        erros.append("saidas: ao menos uma")
    if erros:
        raise RegraInvalida(erros)
    return r


def _valores(regra: dict, entradas: dict[str, int]) -> dict[str, float]:
    """Celulas de rateio da planilha, em double: o valor digitado, TRUNC/ROUND(base*fator) e o
    resto por subtracoes sucessivas (E4-G5-I5), sem arredondar."""
    c = {e["chave"]: int(entradas.get(e["chave"]) or 0) for e in regra["entradas"]}
    if any(abs(x) > TETO_CENTAVOS for x in c.values()):
        raise ValueError("valor acima de R$ 99.999.999.999,99")
    # issue #589: so' o reajuste tem sinal (apostilamento ou previsao negativos); medicao e projeto nao
    for e in regra["entradas"]:
        if c[e["chave"]] < 0 and e["natureza"] != "reajuste":
            raise ValueError(f"{e['rotulo']}: valor negativo só no reajuste")
    v = {k: x / 100 for k, x in c.items()}
    for p in regra["parcelas"]:
        base = v[p["de"]]
        if "resto_de" in p:
            for q in p["resto_de"]:
                base -= v[q]
            v[p["chave"]] = base
        elif "fator" in p:
            v[p["chave"]] = _excel(base * float(Decimal(p["fator"])), p["arredondamento"])
        else:
            n, d = p["fracao"]
            v[p["chave"]] = _excel(base * (n / d), p["arredondamento"])     # D29 = C29/C30; B4*D29
    return v


def _vigente(cfg: dict | None, competencia: str | None) -> bool:
    """Tributo com `vigente_desde` (IBS/CBS) so' existe a partir daquela data; sem competencia
    informada (testes do motor) vale sempre."""
    if not cfg:
        return False
    desde = cfg.get("vigente_desde")
    if not desde or not competencia:
        return True
    return f"{competencia[:7]}-01" >= desde[:10]


NOTA_NEGATIVA = "A nota não sai com valor negativo; inclua a execução do mesmo número"


def _valores_das_saidas(regra: dict, v: dict[str, float]) -> tuple[dict[str, float], dict[str, float]]:
    """O valor (double) de cada saida e o reajuste negativo abatido em cada uma. Issue #589 (decisao do Leo de
    08/11/2026, item 1): nao existe nota com valor negativo. O reajuste negativo (apostilamento ou previsao negativos)
    abate na nota de medicao do mesmo emissor e municipio deste espelho, que soma com o sinal; a saida de reajuste
    negativa nao vira nota. Sem a medicao no espelho (espelho so' de reajuste negativo), ou com o reajuste que zera
    ou passa dela, a geracao e' recusada. Duas notas de medicao do mesmo emissor e municipio (obra com mais de uma
    fonte) tambem recusam: o sistema nao escolhe em qual abater."""
    valores = {}
    for s in regra["saidas"]:
        valor = 0.0
        for k in s["valor"]:
            valor += v[k]
        valores[s["chave"]] = valor
    abatido: dict[str, float] = {}
    for s in regra["saidas"]:
        valor = valores[s["chave"]]
        if s["natureza"] != "reajuste" or round(valor * 100) >= 0:
            continue
        alvos = [x["chave"] for x in regra["saidas"]
                 if x["natureza"] == "medicao" and (x["emissor"], x["municipio"]) == (s["emissor"], s["municipio"])]
        if len(alvos) > 1:
            raise ValueError("O reajuste negativo tem mais de uma nota de medição do mesmo emissor e município para "
                             "abater: a regra do espelho desta obra não diz em qual")
        if not alvos or round(valores[alvos[0]] * 100) <= 0:
            raise ValueError(NOTA_NEGATIVA)
        valores[alvos[0]] += valor
        abatido[alvos[0]] = abatido.get(alvos[0], 0.0) + valor
        valores[s["chave"]] = 0.0
        if _leitura(valores[alvos[0]], "trunc") <= 0:
            raise ValueError(f"O reajuste negativo (R$ {_fmt(round(valor * 100))}) zera a nota de medição: "
                             "a nota não sai com valor negativo")
    return valores, abatido


def calcular(regra: dict, entradas: dict[str, int], competencia: str | None = None) -> list[dict]:
    v = _valores(regra, entradas)
    valores, abatido = _valores_das_saidas(regra, v)
    saidas = []
    for s in regra["saidas"]:
        valor = valores[s["chave"]]
        if _leitura(valor, "trunc") <= 0:
            continue
        ret = s["retencoes"]
        mo = mat = None
        if ret["mao_de_obra"]:
            mo = _excel(valor * _taxa(ret["mao_de_obra"]["percentual"]), ret["mao_de_obra"]["arredondamento"])
            m = ret["material"]
            mat = (valor - mo if m["modo"] == "diferenca"
                   else _excel(valor * _taxa(m["percentual"]), m["arredondamento"]))
        bases = {"mao_de_obra": mo, "material": mat, "total": valor}
        trib = {}
        for t in TRIBUTOS:
            cfg = ret.get(t)
            if not _vigente(cfg, competencia):
                trib[t] = None
                continue
            bruto = bases[cfg["base"]] * _taxa(cfg["percentual"])
            # `na_celula`: a planilha ja' arredonda o tributo na celula (ROUND das MTPAR); sem ela a
            # celula e' crua e quem corta ou arredonda e' a leitura do espelho
            trib[t] = (_leitura(_excel(bruto, cfg["arredondamento"]), "trunc") if cfg.get("na_celula")
                       else _leitura(bruto, cfg["arredondamento"]))
        cent = {"valor": _leitura(valor, "trunc"),
                "mo": None if mo is None else _leitura(mo, "trunc"),
                "material": None if mat is None else _leitura(mat, "trunc")}
        liquido = cent["valor"] - (trib["inss"] or 0) - (trib["irrf"] or 0)
        if trib["iss"] is not None and ret["iss"].get("deduz_liquido", True):
            liquido -= trib["iss"]
        saidas.append({"chave": s["chave"], "natureza": s["natureza"],
                       "rotulo": s["rotulo"] or ROTULO_NATUREZA[s["natureza"]],
                       "emissor": s["emissor"], "municipio": s["municipio"], "modelo": s["modelo"],
                       **cent, **trib, "liquido": liquido, "extenso": extenso.reais(cent["valor"]),
                       # issue #589: o reajuste negativo abatido nesta nota de medicao (so' quando houve)
                       **({"reajuste_abatido": round(abatido[s["chave"]] * 100)} if s["chave"] in abatido else {})})
    return saidas


def valor_por_natureza(regra: dict, entradas: dict[str, int]) -> dict[str, int]:
    """Valor de cada MEDICAO (tipo do banco) = soma das entradas daquela natureza (o cheio, em
    consorcio que emite so' a cota), com o sinal no reajuste (issue #589)."""
    soma: dict[str, int] = {}
    for e in regra["entradas"]:
        c = int(entradas.get(e["chave"]) or 0)
        # issue #589: o reajuste negativo tambem e' medicao deste espelho (abatido na nota da medicao)
        if c > 0 or (c < 0 and e["natureza"] == "reajuste"):
            t = TIPO_POR_NATUREZA[e["natureza"]]
            soma[t] = soma.get(t, 0) + c
    return soma


def entradas_pela_medicao(regra: dict, entradas: dict[str, int], travados: dict[str, tuple[int, str]],
                          opcionais: frozenset[str] | set[str] = frozenset()) -> dict[str, int]:
    """Issue #284 (decisao do Leo de 03/11/2026): o espelho deixa de ser digitado onde a medicao ja' tem valor.
    `travados` e' {tipo: (centavos, fonte)}, com o aprovado, senao o pedido (`fonte` = "boletim" para o aprovado do
    boletim do orgao, "atestado" para o digitado sem boletim, ou "pedido"). Natureza com um campo so': o valor vem preenchido e nao muda (digitado diferente recusa). Com mais de
    um campo: a divisao e' digitada e tem de somar o valor. Devolve as entradas com o preenchido.
    `opcionais` sao os tipos que podem ficar fora deste espelho (a medicao ainda sem boletim, que so' entra com
    "seguir sem boletim"): nada digitado = fora; digitado, tem de ser o valor travado."""
    saida = dict(entradas)
    for tipo, (valor, fonte) in travados.items():
        campos = [e for e in regra["entradas"] if TIPO_POR_NATUREZA[e["natureza"]] == tipo]
        if not campos:
            continue
        natureza = ROTULO_NATUREZA[campos[0]["natureza"]].lower()
        origem = {"boletim": "aprovado do boletim", "atestado": "aprovado"}.get(fonte, "pedido")
        soma = sum(int(saida.get(e["chave"]) or 0) for e in campos)
        if tipo in opcionais and soma == 0:
            continue
        if len(campos) == 1:
            if soma and soma != valor:
                raise ValueError(f"{campos[0]['rotulo']}: o valor de {natureza} é o {origem} (R$ {_fmt(valor)}); "
                                 f"foi digitado R$ {_fmt(soma)}")
            saida[campos[0]["chave"]] = valor
            continue
        if soma != valor:
            raise ValueError(f"A divisão dos valores de {natureza} soma R$ {_fmt(soma)} e não bate com o {origem} "
                             f"(R$ {_fmt(valor)})")
    return saida


def _fmt(centavos: int) -> str:
    inteiro, cent = divmod(abs(centavos), 100)
    return ("-" if centavos < 0 else "") + f"{inteiro:,}".replace(",", ".") + f",{cent:02d}"


def periodo_do_mes(competencia: str) -> tuple[str, str]:
    """(inicio, fim) ISO do mes civil da competencia."""
    ano, mes = int(competencia[:4]), int(competencia[5:7])
    return f"{ano}-{mes:02d}-01", f"{ano}-{mes:02d}-{calendar.monthrange(ano, mes)[1]:02d}"


def periodo(competencia: str, datas: tuple[str, str] | None = None) -> str:
    """'01/05/2026 A 31/05/2026'; `datas` (ISO) quando o periodo nao e' o mes civil."""
    ini, fim = datas or periodo_do_mes(competencia)
    br = lambda d: f"{d[8:10]}/{d[5:7]}/{d[:4]}"
    return f"{br(ini)} A {br(fim)}"


MESES = ("JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO", "JULHO", "AGOSTO", "SETEMBRO",
         "OUTUBRO", "NOVEMBRO", "DEZEMBRO")


def mes_ano(competencia: str) -> str:
    """'PERÍODO: MAIO/2026' da Região Oeste (controle `mes_ano`, alternativo a `periodo`)."""
    return f"{MESES[int(competencia[5:7]) - 1]}/{competencia[:4]}"


def formatar_controles(saida: dict, numero: int, competencia: str, texto: dict | None = None,
                       datas: tuple[str, str] | None = None) -> dict[str, str]:
    """Texto de cada content control do modelo (moeda sem R$, extenso em caixa alta salvo
    `texto.extenso_minusculo`, numero sem zero a' esquerda salvo `texto.numero_com_zero`, periodo
    do mes civil salvo `datas`)."""
    texto = texto or {}
    c = {"medicao": f"{numero:02d}ª" if texto.get("numero_com_zero") else f"{numero}ª",
         "periodo": periodo(competencia, datas), "mes_ano": mes_ano(competencia), "valor": _fmt(saida["valor"]),
         "valor_extenso": saida["extenso"] if texto.get("extenso_minusculo") else saida["extenso"].upper()}
    for k in ("mo", "material", "inss", "iss", "irrf", "ibs", "cbs"):
        if saida.get(k) is not None:
            c[k] = _fmt(saida[k])
    return c


def campos_da_saida(saida_normalizada: dict) -> set[str]:
    """Controles que o modelo desta saida PRECISA ter (os opcionais ibs/cbs ficam fora)."""
    ret = saida_normalizada["retencoes"]
    campos = {"valor", "valor_extenso", "medicao", "periodo"}
    if ret["mao_de_obra"]:
        campos |= {"mo", "material"}
    campos |= {t for t in ("inss", "iss", "irrf") if ret.get(t)}
    return campos


def nome_arquivo(regra: dict, saida: dict, obra: str, numero: int, competencia: str,
                 nome_emissor: str, ext: str = "docx") -> str:
    """Padrao unico dos arquivos gerados (spec §4.4): consorciada e municipio so' quando a obra
    tem mais de um."""
    emissores = {s["emissor"] for s in regra["saidas"]}
    municipios = {s["municipio"] for s in regra["saidas"]}
    nome = (f"ESPELHO - {obra} - {numero:02d}ª {saida.get('rotulo') or ROTULO_NATUREZA[saida['natureza']]} "
            f"({competencia[5:7]}.{competencia[:4]})")
    if len(emissores) > 1:
        nome += f" - {nome_emissor}"
    if len(municipios) > 1:
        nome += f" - {saida['municipio']}"
    return f"{nome}.{ext}"
