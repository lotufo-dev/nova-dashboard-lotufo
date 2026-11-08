"""Leitura, validacao e normalizacao do cadastro versionado (spec 2026-09-21 §8).

O cadastro e' editado pelo Leonardo com o Claude, em YAML, no repositorio. Este modulo
NAO toca o banco: devolve a estrutura que `cadastro_aplicar` grava. Todos os erros sao
acumulados (um cadastro com tres problemas mostra os tres) e levantados de uma vez.
"""
import datetime
import hashlib
import json
import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

import yaml

from app import dinheiro, entidades, espelho, espelho_docx, reajuste, tempo

FAMILIAS = ("mtpar", "sinfra", "ses", "prefeitura")
LEIS = ("8.666", "14.133", "13.303")
STATUS = ("ativo", "suspenso", "em_encerramento", "encerrado")
PAPEIS = ("lotufo", "consorcio", "consorciada")
# tipo do cadastro -> tipo da tabela `aditivos` (o que altera valor e prazo)
TIPOS_ADITIVO = {"aditivo_valor": "valor", "aditivo_prazo": "prazo", "aditivo_misto": "misto",
                 "apostilamento_prazo": "prazo"}
TIPOS_OUTROS = ("apostilamento_reajuste", "paralisacao", "reinicio", "marco_encerramento",
                "endosso_garantia")
_MES = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")  # A-14 (10/10/2026): \d casa "٢٠٢٤"
# tabela do orcamento, nunca indice de reajuste (#257): como palavra ("Tabela SINAPI", "SICRO/DNIT"), nao so' o texto inteiro
_TABELAS_DE_PRECOS = re.compile(r"\b(SINAPI|SICRO)\b", re.IGNORECASE)
# Bloco 4: o que um orgao (ou a excecao de um contrato) pode exigir no protocolo.
DOCUMENTOS = ("federal", "fgts", "trabalhista", "estadual", "municipal", "falencia", "regularidade")
# Bloco 5: pecas tecnicas que o orgao pede no protocolo (feitas fora e arrastadas pela operacao).
TIPOS_PECA = ("boletim", "planilha", "diario", "fotos", "cronograma", "art", "ensaios", "memorial", "diagrama",
              "pluviometria", "croqui", "outro")
FAMILIAS_CARTA = ("mtpar", "ses", "sinfra", "prefeitura")
TRATAMENTOS = ("Senhor", "Senhora")
TIPOS_CONTRATANTE = ("PÚBLICO", "PRIVADO")
# Bloco 7: marcos do encerramento (aba Prazos) e tipos de pleito enviados antes do sistema.
MARCOS = ("conclusao", "provisorio", "definitivo", "baixa_garantia")
TIPOS_PLEITO = ("reajuste", "prazo", "conclusao", "valor")   # valor: pedido de aditivo de valor (#398)
# Pecas que o orgao pode pedir no pleito de reajuste (mesma lista de `pleitos.PECAS_ORGAO`).
PECAS_PLEITO = ("falencia", "contrato_social", "documento_representante", "balanco")
_CICLO = re.compile(r"^([0-9]{4})(-[0-9]{2})?$")
_CICLO_ADITIVO = re.compile(r"^[0-9]{4}$")       # o aditivo de reajuste (issue #390) diz so' o ano: 2025-99 e' erro
# Issue #256 (spec 2026-10-20 §2.4): de que documento veio cada versao do cronograma.
ORIGENS_CRONOGRAMA = ("contratual", "aditivo", "carta", "smo")
# Mesmo teto de itens por versao da rota do cronograma (api_cronograma.MAX_ITENS): 50 anos de competencias.
_MAX_ITENS_CRONOGRAMA = 600
_CAMPOS_CRONOGRAMA = {"chave", "origem", "data", "instrumento", "itens"}
_CAMPOS_ITEM_CRONOGRAMA = {"competencia", "valor"}


def _lista_documentos(valor, onde: str, erros: list[str]) -> list[str] | None:
    """Lista de documentos exigidos (orgao ou excecao do contrato). None = campo ausente."""
    if valor is None:
        return None
    if not isinstance(valor, list) or any(v not in DOCUMENTOS for v in valor) or len(set(valor)) != len(valor):
        erros.append(f"{onde}: use uma lista, sem repetição, de {', '.join(DOCUMENTOS)}")
        return None
    return list(valor)
_CHAVE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
_CAMPOS_INSTRUMENTO = {"chave", "tipo", "data", "numero", "objeto", "corrige", "delta_valor",
                       "nova_execucao_fim", "nova_vigencia_fim", "pdf", "ordinal", "natureza"}
# #262 (spec 2026-10-20 §3.2): o aditivo de valor e' de execucao ou de reajuste (SES: reajuste por termo aditivo)
NATUREZAS = ("execucao", "reajuste")
TIPOS_COM_NATUREZA = ("aditivo_valor", "aditivo_misto")


def _reajuste_com_valor(inst: dict) -> bool:
    """O instrumento do cadastro que `reajuste.aditivo_de_reajuste` conta: aditivo de valor ou misto, natureza
    reajuste, delta diferente de zero."""
    return bool(inst["tipo"] in TIPOS_COM_NATUREZA and inst.get("natureza") == "reajuste"
                and inst.get("delta_valor_centavos"))


def _corretor_de_valor(inst: dict) -> bool:
    """Issue #410: o aditivo de reajuste com valor que corrige outro termo; ele substitui o corrigido no vigente
    (`contratos.vigente`, pelo criterio de `reajuste.aditivo_de_reajuste`), entao cada termo tem no maximo um."""
    return bool(inst.get("corrige") and _reajuste_com_valor(inst))


class CadastroInvalido(Exception):
    def __init__(self, erros: list[str]):
        self.erros = erros
        super().__init__("\n".join(erros))


def _textos(v) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) and x.strip() for x in v)


def _por_que_nao_vai_no_oficio(o: dict, p: dict) -> list[str]:
    """Issue #462 (gate Sol): por que a peca `p` do orgao `o` nao pode ir dentro do oficio assinado. A marca e' por
    tipo, entao o tipo repetido (dois `outro`, um de execucao e outro de reajuste) dispensaria os dois."""
    out = []
    if o.get("familia") != "sinfra":
        out.append("só vale na família sinfra, que manda as peças dentro do ofício da planilha/carta")
    if p.get("tipo") == "planilha":
        out.append("a planilha editável vai sempre solta, fora do ofício")
    elif p.get("solto") is True:
        out.append("a peça marcada solto: true vai fora do ofício; use uma das duas marcas")
    if [x.get("tipo") for x in o.get("pecas") or [] if isinstance(x, dict)].count(p.get("tipo")) > 1:
        out.append(f"o tipo {p.get('tipo')} aparece mais de uma vez nas peças do órgão; a marca vale por tipo")
    return out


def _pecas_no_oficio_do_contrato(tipos: list[str], chave: str, o: dict, onde: str, erros: list[str]) -> None:
    """Issue #462: cada tipo da excecao do contrato e' uma peca que o orgao pede e que pode ir no oficio."""
    pecas = {p.get("tipo"): p for p in o["pecas"] if isinstance(p, dict)}
    fora = [t for t in tipos if t not in pecas]
    if fora:
        erros.append(f"{onde}: o órgão {chave} não pede {', '.join(fora)}")
    motivos = {m: None for t in tipos if t in pecas for m in _por_que_nao_vai_no_oficio(o, pecas[t])}
    erros += [f"{onde}: {m}" for m in motivos]


def _protocolo_do_orgao(o: dict, onde: str, erros: list[str]) -> None:
    """Bloco 5: chaves do protocolo no orgao (ficam em `orgaos.regras`)."""
    if o.get("carta_destinatario") is not None and not _textos(o["carta_destinatario"]):
        erros.append(f"{onde}: carta_destinatario: use uma lista de linhas de texto")
    for i, p in enumerate(o.get("pecas") or []):
        if not isinstance(p, dict) or p.get("tipo") not in TIPOS_PECA:
            erros.append(f"{onde}: pecas[{i}].tipo: use um de {TIPOS_PECA}")
            continue
        if not str(p.get("rotulo") or "").strip():
            erros.append(f"{onde}: pecas[{i}].rotulo: obrigatório")
        # no_oficio (issue #462): a peca vai dentro do PDF assinado do oficio da planilha/carta, nao cobra nem se anexa
        for campo in ("exigida", "solto", "no_oficio"):
            if campo in p and not isinstance(p[campo], bool):
                erros.append(f"{onde}: pecas[{i}].{campo}: use true ou false")
        if p.get("no_oficio") is True:
            for motivo in _por_que_nao_vai_no_oficio(o, p):
                erros.append(f"{onde}: pecas[{i}].no_oficio: {motivo}")
        nat = p.get("naturezas")
        if nat is not None and (not isinstance(nat, list) or not nat
                                or any(x not in ("execucao", "reajuste", "projeto") for x in nat)):
            erros.append(f"{onde}: pecas[{i}].naturezas: use uma lista de execucao, reajuste, projeto")
    # Bloco 7 (issue #50): pecas que o pleito de reajuste leva alem da memoria de calculo e do cronograma.
    pp = o.get("pecas_pleito_reajuste")
    if pp is not None and (not isinstance(pp, list) or any(x not in PECAS_PLEITO for x in pp) or len(set(pp)) != len(pp)):
        erros.append(f"{onde}: pecas_pleito_reajuste: use uma lista, sem repetição, de {', '.join(PECAS_PLEITO)}")
    ordem = o.get("ordem_certidoes")
    if ordem is not None and (not isinstance(ordem, list) or any(x not in DOCUMENTOS[:6] for x in ordem)):
        erros.append(f"{onde}: ordem_certidoes: use uma lista de {DOCUMENTOS[:6]}")


def _dentro(raiz: Path, rel) -> Path | None:
    """Arquivo citado no cadastro, so' se ficar DENTRO da pasta do cadastro (sem `..` nem caminho absoluto):
    o que o cadastro aponta e' copiado para a pasta de dados (gate Sol do bloco 5)."""
    p = (raiz / str(rel)).resolve()
    return p if p.is_file() and p.is_relative_to(raiz.resolve()) else None


def _ler(arquivo: Path):
    with arquivo.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def slug(nome: str) -> str:
    """Nome do arquivo de um contrato: ASCII, minusculas e hifens ('Coxipó 3ª Etapa' -> 'coxipo-3a-etapa')."""
    ascii_ = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")


def _data(v) -> str | None:
    """Aceita date (o YAML ja' converte 2026-08-28) ou texto ISO. Devolve ISO ou None."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime.datetime):
        raise ValueError("use data sem hora (AAAA-MM-DD)")
    if isinstance(v, datetime.date):
        return v.isoformat()
    return datetime.date.fromisoformat(str(v)).isoformat()


def _bp(v) -> int:
    try:
        d = Decimal(str(v).replace(",", "."))
    except InvalidOperation:
        raise ValueError(f"percentual inválido: {v!r}") from None
    bp = int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if not 0 < bp <= 10000:
        raise ValueError(f"percentual fora de 0–100: {v!r}")
    return bp


def _instrumento(bruto: dict, onde: str, erros: list[str]) -> dict | None:
    def falha(campo, msg):
        erros.append(f"{onde}: {campo}: {msg}")

    chave, tipo = bruto.get("chave"), bruto.get("tipo")
    if not isinstance(chave, str) or not _CHAVE.match(chave.lower()) or chave != chave.strip():
        falha("chave", f"chave inválida: {chave!r}")
        return None
    if tipo not in TIPOS_ADITIVO and tipo not in TIPOS_OUTROS:
        falha("tipo", f"tipo desconhecido: {tipo!r}")
        return None
    inst = {"chave": chave, "tipo": tipo, "numero": bruto.get("numero"), "objeto": bruto.get("objeto"),
            "corrige": bruto.get("corrige"), "pdf": bruto.get("pdf"), "delta_valor_centavos": 0,
            "nova_execucao_fim": None, "nova_vigencia_fim": None, "ordinal": None,
            "dados": {k: v for k, v in bruto.items() if k not in _CAMPOS_INSTRUMENTO}}
    try:
        inst["data"] = _data(bruto.get("data"))
        inst["nova_execucao_fim"] = _data(bruto.get("nova_execucao_fim"))
        inst["nova_vigencia_fim"] = _data(bruto.get("nova_vigencia_fim"))
    except ValueError as e:
        falha("data", str(e))
        return None
    if not inst["data"]:
        falha("data", "obrigatória")
    # issue #278: o oficio de reajuste da MT-PAR e da Prefeitura cita o numero do termo que cobre a competencia
    if tipo == "apostilamento_reajuste" and not str(inst["numero"] or "").strip():
        falha("numero", "obrigatório no apostilamento de reajuste (o ofício de reajuste cita o número do termo)")
    if bruto.get("delta_valor") not in (None, ""):
        texto = str(bruto["delta_valor"]).strip()
        sinal = -1 if texto.startswith("-") else 1
        try:
            inst["delta_valor_centavos"] = sinal * dinheiro.parse_brl(texto.lstrip("-").strip())
        except ValueError as e:
            falha("delta_valor", str(e))
    natureza = bruto.get("natureza")
    inst["natureza"] = None       # sem o campo: nao classificado, conta como execucao (`contratos.vigente`)
    if natureza is not None:
        if tipo not in TIPOS_COM_NATUREZA:
            falha("natureza", f"só vale para instrumento de valor ({', '.join(TIPOS_COM_NATUREZA)})")
        elif natureza not in NATUREZAS:
            falha("natureza", f"use {' ou '.join(NATUREZAS)}")
        else:
            inst["natureza"] = natureza
    if tipo in ("aditivo_valor",) and inst["delta_valor_centavos"] == 0:
        falha("delta_valor", "aditivo de valor sem delta")
    if tipo in ("aditivo_prazo", "apostilamento_prazo") and not (
            inst["nova_execucao_fim"] or inst["nova_vigencia_fim"]):
        falha("nova_execucao_fim", "instrumento de prazo sem data nova")
    if tipo in TIPOS_OUTROS and (inst["delta_valor_centavos"] or inst["nova_execucao_fim"]
                                 or inst["nova_vigencia_fim"]):
        falha("tipo", f"{tipo} não altera valor nem prazo; use aditivo ou apostilamento de prazo")
    # Issue #261: ordinal do termo ("14º termo aditivo") quando o numero nao traz o sufixo /14.
    if bruto.get("ordinal") is not None:
        if tipo not in TIPOS_ADITIVO:
            falha("ordinal", f"{tipo} não tem ordinal; o campo vale para aditivo ou apostilamento de prazo")
        elif _inteiro(bruto["ordinal"], 1) is None:
            falha("ordinal", f"use um número inteiro a partir de 1 (ex.: 14): {bruto['ordinal']!r}")
        else:
            inst["ordinal"] = bruto["ordinal"]
    # `dados` de data viram ISO para o JSON canonico nao depender do parser
    for k, v in list(inst["dados"].items()):
        if isinstance(v, datetime.date):
            inst["dados"][k] = v.isoformat()
    return inst


def _inteiro(v, minimo: int) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= minimo else None


_CAMPOS_COMPETENCIA_APOSTILADA = {"competencia", "valor", "medicao"}
_CAMPOS_PERIODO = {"de", "ate"}


def _mes_br(mes: str) -> str:
    return f"{mes[5:7]}/{mes[:4]}"


def _periodo_e_competencias(d: dict) -> tuple[list[dict], list[tuple[str, str]]]:
    """Issue #271 (spec 2026-10-20 §2.2): `periodo: {de, ate}` e `competencias: [{competencia, valor, medicao}]`
    do apostilamento de reajuste. Devolve as competencias em centavos e os problemas como (campo, mensagem).
    O valor aceita sinal: indice deflacionario da' reajuste negativo (migracao 043 nao limita o sinal)."""
    problemas: list[tuple[str, str]] = []
    de = ate = None
    per = d.get("periodo")
    if per is not None:
        if (not isinstance(per, dict) or set(per) != _CAMPOS_PERIODO
                or not all(_MES.match(str(per[k] or "")) for k in _CAMPOS_PERIODO)):
            problemas.append(("periodo", "use {de: AAAA-MM, ate: AAAA-MM}"))
        elif str(per["de"]) > str(per["ate"]):
            problemas.append(("periodo", f"o início ({_mes_br(str(per['de']))}) é depois do fim "
                                         f"({_mes_br(str(per['ate']))})"))
        else:
            de, ate = str(per["de"]), str(per["ate"])
    lista = d.get("competencias")
    if lista is None:
        return [], problemas
    if not isinstance(lista, list) or not lista:
        problemas.append(("competencias", "use uma lista de {competencia, valor, medicao} com ao menos uma competência"))
        return [], problemas
    out, vistas = [], set()
    for j, it in enumerate(lista):
        aqui = f"competencias[{j}]"
        if not isinstance(it, dict):
            problemas.append((aqui, "use {competencia, valor, medicao}"))
            continue
        sobra = sorted(str(k) for k in it if k not in _CAMPOS_COMPETENCIA_APOSTILADA)
        if sobra:
            problemas.append((aqui, f"campo desconhecido: {', '.join(sobra)} (use competencia, valor e medicao)"))
            continue
        comp = str(it.get("competencia") or "")
        if not _MES.match(comp):
            problemas.append((f"{aqui}.competencia", f"use AAAA-MM: {comp!r}"))
            continue
        if comp in vistas:
            problemas.append((aqui, f"competência repetida: {_mes_br(comp)}"))
            continue
        vistas.add(comp)
        if de and not de <= comp <= ate:
            problemas.append((aqui, f"competência {_mes_br(comp)} fora do período do apostilamento "
                                    f"({_mes_br(de)} a {_mes_br(ate)})"))
            continue
        bruto = it.get("valor")
        texto = "" if bruto is None or isinstance(bruto, bool) else str(bruto).strip()
        sinal = -1 if texto.startswith("-") else 1
        try:
            centavos = sinal * dinheiro.parse_brl(texto[1:].strip() if sinal < 0 else texto)     # um sinal so'
        except ValueError as e:
            problemas.append((f"{aqui}.valor", str(e)))
            continue
        medicao = it.get("medicao")
        if medicao is not None and _inteiro(medicao, 1) is None:
            problemas.append((f"{aqui}.medicao", f"use o nº da medição do órgão, inteiro a partir de 1: {medicao!r}"))
            continue
        out.append({"competencia": comp, "valor_centavos": centavos, "medicao": medicao})
    return out, problemas


def competencias_do_apostilamento(dados: dict) -> list[dict]:
    """As competencias apostiladas em centavos ({competencia, valor_centavos, medicao}), do `dados` ja' validado."""
    out, problemas = _periodo_e_competencias(dados)
    if problemas:
        raise ValueError("; ".join(f"{campo}: {msg}" for campo, msg in problemas))
    return out


def _dados_instrumentos(c: dict, falha, avisos: list[str]) -> None:
    """Bloco 7: campos de `dados` que reajuste e prazos leem, validados e normalizados."""
    meses = {d["mes"] for d in c["datas_base"]}
    de_prazo = {i["chave"] for i in c["instrumentos"]
                if i["tipo"] in ("aditivo_prazo", "apostilamento_prazo", "aditivo_misto")}
    for inst in c["instrumentos"]:
        d, onde = inst["dados"], f"instrumentos[{inst['chave']}]"
        if inst["tipo"] in TIPOS_COM_NATUREZA:
            # issue #390 (revisor, PR #407): no aditivo de reajuste, `ciclo` diz o ciclo que ele atende (o termo
            # assinado depois do aniversario seguinte) e o aplicar liga o pleito desse ciclo; nada fica engolido
            base_ok = None
            if d.get("data_base") is not None:
                if inst.get("natureza") != "reajuste":
                    falha(f"{onde}.data_base", "só vale no aditivo de natureza reajuste")
                elif str(d["data_base"]) not in meses:
                    falha(f"{onde}.data_base", "use AAAA-MM de uma das datas_base do contrato")
                else:
                    base_ok = str(d["data_base"])
            elif len(meses) == 1:
                base_ok = next(iter(meses))
            if d.get("ciclo") is not None:
                if inst.get("natureza") != "reajuste":
                    falha(f"{onde}.ciclo", "só vale no aditivo de natureza reajuste")
                elif not _CICLO_ADITIVO.match(str(d["ciclo"])):
                    falha(f"{onde}.ciclo", f"use o ano do ciclo, com quatro dígitos (ex.: 2026): {d['ciclo']!r}")
                elif base_ok is not None:
                    # gate Sol (rodada extra, PR #407): o ciclo vai do ano seguinte ao da base ao ciclo da assinatura
                    primeiro, ultimo = int(base_ok[:4]) + 1, reajuste.ciclo_do_aditivo(base_ok, str(inst["data"]))
                    if ultimo is None:
                        falha(f"{onde}.ciclo", f"o aditivo foi assinado antes do primeiro aniversário da data-base "
                                               f"{base_ok}; não atende ciclo nenhum")
                    elif not primeiro <= int(d["ciclo"]) <= ultimo:
                        falha(f"{onde}.ciclo", f"use um ciclo de {primeiro} a {ultimo} (do ano seguinte ao da "
                                               f"data-base {base_ok} ao do último aniversário até a assinatura)")
            # a base guardada no aditivo (migracao 058) vale com qualquer numero de bases; sem ela, com mais de uma, o
            # aditivo novo nao tem base (o ja' aplicado segue na que guardou quando a base era unica)
            if inst.get("natureza") == "reajuste" and len(meses) != 1 and d.get("data_base") is None:
                avisos.append(f"{c['nome_curto']}: {onde}: o contrato não tem uma data-base só e o aditivo de "
                              "reajuste não diz a dele (data_base, AAAA-MM); se ainda não foi aplicado, ele não fecha "
                              "ciclo nem atende pleito")
        if inst["tipo"] == "apostilamento_reajuste":
            if d.get("data_base") is not None and str(d["data_base"]) not in meses:
                falha(f"{onde}.data_base", "use AAAA-MM de uma das datas_base do contrato")
            # "2026-06" (Granito) vale: o reajuste le so' o ano. Nao normaliza: instrumento aplicado nao muda.
            if d.get("ciclo") is not None and not _CICLO.match(str(d["ciclo"])):
                falha(f"{onde}.ciclo", "use o ano do ciclo (ex.: 2026)")
            # Issue #271: a eficacia decide o ciclo quando `ciclo` falta; data invalida faria o termo sumir do ciclo
            if d.get("eficacia") is not None:
                try:
                    if not _data(d["eficacia"]):
                        raise ValueError("vazia")
                except ValueError:
                    falha(f"{onde}.eficacia", f"use a data da eficácia (AAAA-MM-DD): {d['eficacia']!r}")
            # Issue #391: sem `ciclo` o termo cai no ano da eficacia (ou da data) e instrumento aplicado nao muda
            if d.get("ciclo") is None:
                ano = reajuste.ciclo_do_apostilamento(d, inst["data"])
                if ano is not None:
                    pelo = "eficacia" if d.get("eficacia") else "data"
                    avisos.append(f"{c['nome_curto']}: {onde}: apostilamento sem ciclo; vai contar no ciclo {ano} "
                                  f"(pelo campo {pelo}). Diga ciclo: AAAA")
            # Issue #271: competencias e periodo; cada competencia vira previsao da data-base dele
            for campo, msg in _periodo_e_competencias(d)[1]:
                falha(f"{onde}.{campo}", msg)
            # gate Sol (PR #317, S2 e rodada 3): o validar nao sabe se o termo ja' foi aplicado (quando o contrato tinha
            # uma base so'; instrumento aplicado nao muda); o aplicar recusa o termo novo, com ou sem competencias, e
            # mantem a base guardada do antigo (migracao 055)
            if d.get("data_base") is None and len(meses) != 1:
                avisos.append(f"{c['nome_curto']}: {onde}: o contrato não tem uma data-base só e o apostilamento não "
                              "diz a dele; se ainda não foi aplicado, o aplicar recusa (diga data_base, AAAA-MM)")
        elif inst["tipo"] == "endosso_garantia":
            if d.get("vigencia_fim") is not None:      # issue #65: o endosso traz a nova vigencia da garantia
                try:
                    d["vigencia_fim"] = _data(d["vigencia_fim"])
                except ValueError as e:
                    falha(f"{onde}.vigencia_fim", str(e))
                if not str(d.get("apolice") or "").strip():
                    falha(f"{onde}.apolice", "endosso com vigencia_fim precisa dizer de qual apólice é (campo apolice)")
                else:
                    d["apolice"] = str(d["apolice"]).strip()
                    if not c.get("garantia_apolice"):
                        falha(f"{onde}.apolice", "o contrato não tem garantia.apolice no cadastro; o endosso não "
                                                 "teria a quem se aplicar. Informe garantia: {apolice, vigencia_fim}")
                    elif d["apolice"] != c["garantia_apolice"]:
                        avisos.append(f"{c['nome_curto']}: {onde}: o endosso é da apólice {d['apolice']!r}, "
                                      f"diferente da apólice do contrato ({c['garantia_apolice']!r}); "
                                      "só vale como histórico, não muda a vigência da garantia")
            if d.get("referente") is not None and d["referente"] not in de_prazo:
                falha(f"{onde}.referente", "use a chave de um instrumento de prazo deste contrato")
        elif inst["tipo"] == "marco_encerramento":
            if d.get("marco") not in MARCOS:
                falha(f"{onde}.marco", f"use um de {MARCOS}")


def _pleitos_anteriores(lista, c: dict, falha) -> list[dict]:
    """Bloco 7: pleitos enviados antes do sistema, para o aviso nao acusar "nao enviado" o que ja' foi."""
    meses = {d["mes"] for d in c["datas_base"]}
    out = []
    for i, p in enumerate(lista or []):
        onde = f"pleitos_anteriores[{i}]"
        if not isinstance(p, dict) or p.get("tipo") not in TIPOS_PLEITO:
            falha(f"{onde}.tipo", f"use um de {TIPOS_PLEITO}")
            continue
        try:
            data = _data(p.get("data"))
        except ValueError as e:
            falha(f"{onde}.data", str(e))
            continue
        if not str(p.get("oficio") or "").strip() or not data:
            falha(onde, "oficio e data são obrigatórios")
            continue
        item = {"tipo": p["tipo"], "oficio": str(p["oficio"]).strip(), "data": data, "data_base": None,
                "ciclo": None, "dias": None, "valor_centavos": None, "objeto": None}
        for campo in ("valor", "objeto"):
            if p["tipo"] != "valor" and p.get(campo) is not None:
                falha(f"{onde}.{campo}", "só vale no pedido de valor (tipo: valor)")
        if p["tipo"] == "valor":
            # issue #398: pedido de aditivo de valor (RPFO, readequacao); so' o valor pedido e o objeto
            for campo in ("dias", "data_base", "ciclo"):
                if p.get(campo) is not None:
                    falha(f"{onde}.{campo}", "não vale no pedido de valor")
            try:
                item["valor_centavos"] = dinheiro.parse_brl(str(p.get("valor") or ""))
            except ValueError as e:
                falha(f"{onde}.valor", f"obrigatório no pedido de valor: {e}")
            else:
                if item["valor_centavos"] <= 0:
                    falha(f"{onde}.valor", "use um valor maior que zero")
            item["objeto"] = str(p.get("objeto") or "").strip() or None
        elif p["tipo"] == "reajuste":
            if str(p.get("data_base") or "") not in meses:
                falha(f"{onde}.data_base", "use uma das datas_base do contrato (AAAA-MM)")
            if _inteiro(p.get("ciclo"), 2000) is None:
                falha(f"{onde}.ciclo", "obrigatório no reajuste (ano, ex.: 2026)")
            item["data_base"], item["ciclo"] = str(p.get("data_base") or ""), p.get("ciclo")
        elif p["tipo"] == "prazo" and p.get("dias") is not None:
            if _inteiro(p["dias"], 1) is None:
                falha(f"{onde}.dias", "use um inteiro > 0")
            item["dias"] = p["dias"]
        # issue #399: `corrige: {oficio, data?}` corrige a data e/ou o oficio de um pleito ja' aplicado
        item["corrige"] = _corrige_pleito(p.get("corrige"), f"{onde}.corrige", falha)
        out.append(item)
    # um oficio pode cobrir duas datas-base (migracao 026): a chave do pleito leva a data-base
    alvos = [(x["tipo"], x["corrige"]["oficio"], x["data_base"]) for x in out if x["corrige"]]
    if len(alvos) != len(set(alvos)):
        falha("pleitos_anteriores", "dois itens corrigem o mesmo pleito")
    for i, x in enumerate(out):
        if not x["corrige"] and (x["tipo"], x["oficio"], x["data_base"]) in alvos:
            falha(f"pleitos_anteriores[{i}]", f"o pleito {x['oficio']} é corrigido por outro item: tire este da "
                  "lista (o item com corrige o substitui)")
    return out


def _corrige_pleito(v, onde: str, falha) -> dict | None:
    """Issue #399: identifica o pleito gravado pelo oficio (obrigatorio) e, se vier, confere a data gravada."""
    if v is None:
        return None
    if not isinstance(v, dict) or set(v) - {"oficio", "data"}:
        falha(onde, "use {oficio: <ofício gravado>, data: <data gravada, opcional>}")
        return None
    oficio = str(v.get("oficio") or "").strip()
    if not oficio:
        falha(f"{onde}.oficio", "obrigatório: o número do ofício do pleito gravado")
        return None
    try:
        data = _data(v.get("data"))
    except ValueError as e:
        falha(f"{onde}.data", str(e))
        return None
    return {"oficio": oficio, "data": data}


# Gate Sol (PR #406): acima do int64 o `aplicar` estourava com OverflowError ao consultar o numero no SQLite.
# 1.000.000 de versoes e' folga larga sobre qualquer contrato real.
MAX_VERSAO_SUPERADA = 1_000_000


def _cronograma_superadas(lista, falha) -> list[int]:
    """Issue #395: `cronograma_superadas: [<numero da versao>]`, versoes ja gravadas sem linha no cadastro (a carga
    de 04/09/2026, as manuais) que deixam de valer. Se o numero existe e nao veio do cadastro, quem confere e' o
    `aplicar` (precisa do banco)."""
    if lista is None:
        return []
    if not isinstance(lista, list):
        falha("cronograma_superadas", "use uma lista de números de versão (ex.: [1])")
        return []
    out: list[int] = []
    for i, n in enumerate(lista):
        if _inteiro(n, 1) is None or n > MAX_VERSAO_SUPERADA:
            falha(f"cronograma_superadas[{i}]", f"número de versão inválido: {n!r} (use um inteiro de 1 a {MAX_VERSAO_SUPERADA})")
        elif n in out:
            falha("cronograma_superadas", f"versão {n} repetida")
        else:
            out.append(n)
    return sorted(out)


def _cronograma(lista, falha) -> list[dict]:
    """Issue #256: `cronograma: [{chave, origem, data, instrumento, itens: [{competencia, valor}]}]`.

    Cada entrada vira uma versao com criado_em = data do documento. Itens em centavos (parse_brl), sem
    competencia repetida nem valor negativo; chave repetida e' erro (a mesma chave com outro conteudo
    seria uma versao aplicada mudando)."""
    if lista is None:
        return []
    if not isinstance(lista, list):
        falha("cronograma", "use uma lista de versões ({chave, origem, data, instrumento, itens})")
        return []
    out, vistas = [], set()
    datas: dict[str, str] = {}     # data do documento -> chave da versao que ja a usa
    hoje = tempo.hoje_local().isoformat()
    for i, v in enumerate(lista):
        if not isinstance(v, dict):
            falha(f"cronograma[{i}]", "use {chave, origem, data, instrumento, itens}")
            continue
        chave = v.get("chave")
        if not isinstance(chave, str) or not _CHAVE.match(chave):
            falha(f"cronograma[{i}].chave", f"chave inválida: {chave!r} (minúsculas, números e hífen)")
            continue
        onde = f"cronograma[{chave}]"
        if chave in vistas:
            falha("cronograma", f"chave repetida: {chave} (cada versão tem a sua chave; versão aplicada não muda)")
            continue
        vistas.add(chave)
        ok = True
        # Gate Sol (PR #311): campo com erro de digitacao (`instrumentoo`) seria ignorado e a versao aplicada
        # sem ele, imutavel depois.
        sobra = sorted(str(k) for k in v if k not in _CAMPOS_CRONOGRAMA)
        if sobra:
            falha(onde, f"campo desconhecido: {', '.join(sobra)} (use {', '.join(sorted(_CAMPOS_CRONOGRAMA))})")
            ok = False
        if v.get("origem") not in ORIGENS_CRONOGRAMA:
            falha(f"{onde}.origem", f"use uma de {', '.join(ORIGENS_CRONOGRAMA)}")
            ok = False
        try:
            data = _data(v.get("data"))
        except ValueError as e:
            falha(f"{onde}.data", f"data inválida ({e}); use AAAA-MM-DD")
            data, ok = None, False
        else:
            if not data:
                falha(f"{onde}.data", "obrigatória (data do documento, AAAA-MM-DD)")
                ok = False
            elif data > hoje:
                falha(f"{onde}.data", f"{data} está no futuro; use a data do documento")
                ok = False
            elif data in datas:
                # Gate Sol (PR #311): duas versoes no mesmo dia empatariam no criado_em, e o desempate seria a
                # ordem de aplicacao (o numero), nao a do YAML.
                falha(f"{onde}.data", f"mesma data da versão {datas[data]} ({data}); uma versão por data de "
                                      "documento")
                ok = False
            else:
                datas[data] = chave
        instrumento = v.get("instrumento")
        if instrumento is not None and (not isinstance(instrumento, str) or not instrumento.strip()):
            falha(f"{onde}.instrumento", "use um texto (ex.: a chave do termo aditivo) ou deixe sem")
            ok = False
        itens_brutos = v.get("itens")
        if not isinstance(itens_brutos, list) or not itens_brutos:
            falha(f"{onde}.itens", "informe ao menos uma competência ({competencia, valor})")
            continue
        if len(itens_brutos) > _MAX_ITENS_CRONOGRAMA:
            falha(f"{onde}.itens", f"máximo de {_MAX_ITENS_CRONOGRAMA} competências por versão")
            continue
        itens, comps = [], set()
        for j, it in enumerate(itens_brutos):
            aqui = f"{onde}.itens[{j}]"
            if not isinstance(it, dict):
                falha(aqui, "use {competencia, valor}")
                ok = False
                continue
            sobra = sorted(str(k) for k in it if k not in _CAMPOS_ITEM_CRONOGRAMA)
            if sobra:
                falha(aqui, f"campo desconhecido: {', '.join(sobra)} (use competencia e valor)")
                ok = False
            comp = str(it.get("competencia") or "")
            if not _MES.match(comp):
                falha(f"{aqui}.competencia", f"use AAAA-MM: {comp!r}")
                ok = False
                continue
            if comp in comps:
                falha(f"{aqui}.competencia", f"competência repetida: {comp}")
                ok = False
                continue
            comps.add(comp)
            bruto = it.get("valor")
            texto = "" if bruto is None or isinstance(bruto, bool) else str(bruto).strip()
            if texto.startswith("-"):
                falha(f"{aqui}.valor", f"valor negativo em {comp}; o previsto é zero ou mais")
                ok = False
                continue
            try:
                itens.append((comp, dinheiro.parse_brl(texto)))
            except ValueError as e:
                falha(f"{aqui}.valor", str(e))
                ok = False
        if ok:
            out.append({"chave": chave, "origem": v["origem"], "data": data,
                        "instrumento": instrumento.strip() if instrumento else None, "itens": itens})
    return out


def _arquivo_do_cadastro(raiz: Path, rel, campo: str, falha) -> str | None:
    if not rel:
        return None
    p = _dentro(raiz, rel)
    if p is None:
        falha(campo, f"arquivo não encontrado na pasta do cadastro: {rel}")
        return None
    return str(p)


def _garantia(bruto: dict, raiz: Path, c: dict, falha) -> None:
    """Issue #65: `garantia` e' `{apolice, vigencia_fim, arquivo}`; o endosso a substitui. A ART saiu do
    contrato (#239): `art: null` ainda passa, com valor e' recusada."""
    if bruto.get("art") is not None:
        falha("art", "a ART saiu do contrato; tire a linha art do cadastro (a peça ART do protocolo continua nas peças do órgão)")
    gar = bruto.get("garantia")
    if gar is None:
        return
    if not isinstance(gar, dict):
        falha("garantia", "use {apolice, vigencia_fim, arquivo}")
        return
    try:
        c["garantia_vigencia_fim"] = _data(gar.get("vigencia_fim"))
    except ValueError as e:
        falha("garantia.vigencia_fim", str(e))
    if not c["garantia_vigencia_fim"]:
        falha("garantia.vigencia_fim", "obrigatória (data de fim da apólice)")
    c["garantia_apolice"] = str(gar["apolice"]).strip() if gar.get("apolice") not in (None, "") else None
    c["garantia_caminho"] = _arquivo_do_cadastro(raiz, gar.get("arquivo"), "garantia.arquivo", falha)


def _contrato(bruto: dict, arquivo: Path, raiz: Path, orgaos: set, ents: set,
              erros: list[str], avisos: list[str]) -> dict | None:
    onde = f"contratos/{arquivo.name}"

    def falha(campo, msg):
        erros.append(f"{onde}: {campo}: {msg}")

    if not isinstance(bruto, dict):
        falha("arquivo", "conteúdo não é um mapa YAML")
        return None
    for campo in ("nome_curto", "numero_instrumento", "orgao", "entidade", "objeto",
                  "valor_original", "status"):
        if bruto.get(campo) in (None, ""):
            falha(campo, "obrigatório")
    nome = str(bruto.get("nome_curto") or "")
    if nome and arquivo.stem != slug(nome):
        falha("nome_curto", f"arquivo {arquivo.name} não corresponde a nome_curto {nome!r} "
                            f"(esperado {slug(nome)}.yaml)")
    if bruto.get("orgao") and bruto["orgao"] not in orgaos:
        falha("orgao", f"órgão não cadastrado: {bruto['orgao']}")
    if bruto.get("entidade") and bruto["entidade"] not in ents:
        falha("entidade", f"entidade não cadastrada: {bruto['entidade']}")
    if bruto.get("lei") is not None and str(bruto["lei"]) not in LEIS:
        falha("lei", f"use uma de {LEIS}")
    if bruto.get("status") not in STATUS:
        falha("status", f"use um de {STATUS}")
    copia_extras = bruto.get("copia_extras")
    if copia_extras is None:
        copia_extras = []
    if not isinstance(copia_extras, list):
        falha("copia_extras", "use uma lista de e-mails (um por linha, com hífen)")
        copia_extras = []
    copia_extras = list(dict.fromkeys(str(e).strip().lower() for e in copia_extras))
    for em in copia_extras:
        if not _EMAIL.match(em):
            falha("copia_extras", f"e-mail inválido: {em!r}")

    c = {"nome_curto": nome, "numero_instrumento": str(bruto.get("numero_instrumento") or ""),
         "orgao": bruto.get("orgao"), "entidade": bruto.get("entidade"),
         "objeto": bruto.get("objeto"), "municipio": bruto.get("municipio"),
         "lei": None if bruto.get("lei") is None else str(bruto["lei"]),
         "cno": bruto.get("cno"),
         "numero_processo": bruto.get("numero_processo"),
         "centro_custo_rm": bruto.get("centro_custo_rm"), "status": bruto.get("status"),
         # 2026-09-25: centros que a obra usou antes do atual (notas antigas; so' a conciliacao do legado olha)
         "centros_custo_anteriores_rm": [str(x).strip() for x in bruto.get("centros_custo_anteriores_rm") or []
                                         if str(x).strip()],
         "sem_reajuste": bool(bruto.get("sem_reajuste", False)),
         "destinatarios_extras": [str(e).strip().lower() for e in bruto.get("destinatarios_extras") or []],
         # 2026-10-14: copia que muda por obra (engenheiro da obra); soma-se a protocolo_copia do orgao
         "copia_extras": copia_extras,
         "valor_original_centavos": 0, "percentual_direito_bp": 10000,
         # bloco 5: objeto por extenso (carta e QDOP) e comprovante do CNO (entra no pacote)
         "objeto_completo": (str(bruto["objeto_completo"]).strip() or None) if bruto.get("objeto_completo") else None,
         # 2026-10-07: objeto como as cartas reais o escrevem (vazio = o do QDOP)
         "objeto_carta": (str(bruto["objeto_carta"]).strip() or None) if bruto.get("objeto_carta") else None,
         "cno_caminho": None, "garantia_apolice": None, "garantia_vigencia_fim": None,
         "garantia_caminho": None}
    _garantia(bruto, raiz, c, falha)
    if bruto.get("cno_pdf"):
        cno = _dentro(raiz, bruto["cno_pdf"])
        if cno:
            c["cno_caminho"] = str(cno)
        else:
            falha("cno_pdf", f"arquivo não encontrado na pasta do cadastro: {bruto['cno_pdf']}")
    try:
        c["valor_original_centavos"] = dinheiro.parse_brl(str(bruto.get("valor_original") or ""))
    except ValueError as e:
        falha("valor_original", str(e))
    try:
        c["percentual_direito_bp"] = _bp(bruto.get("percentual_lotufo", "100"))
    except ValueError as e:
        falha("percentual_lotufo", str(e))
    for campo in ("execucao_inicio", "execucao_fim", "vigencia_inicio", "vigencia_fim", "status_desde"):
        try:
            c[campo] = _data(bruto.get(campo))
        except ValueError as e:
            c[campo] = None
            falha(campo, str(e))
    if c["status"] == "em_encerramento" and not c["status_desde"]:
        falha("status_desde", "obrigatório quando status é em_encerramento (data da medição final)")
    if c["execucao_fim"] and c["vigencia_fim"] and c["vigencia_fim"] < c["execucao_fim"]:
        avisos.append(f"{onde}: vigência ({c['vigencia_fim']}) termina antes da execução "
                      f"({c['execucao_fim']})")

    c["datas_base"] = []
    for i, db_ in enumerate(bruto.get("datas_base") or []):
        mes = str((db_ or {}).get("mes") or "")
        if not _MES.match(mes):
            falha(f"datas_base[{i}].mes", f"use AAAA-MM: {mes!r}")
            continue
        # Issue #257 (spec 2026-10-20 §2.4): indice obrigatorio, e e' o do reajuste, nao a tabela de precos
        indice = str(db_.get("indice") or "").strip()
        if not indice:
            falha(f"datas_base[{i}].indice", "obrigatório: diga o índice do reajuste desta data-base "
                                              "(ex.: INCC-DI, FGV/DNIT)")
        elif _TABELAS_DE_PRECOS.search(indice):
            falha(f"datas_base[{i}].indice", f"{indice!r} é a tabela de preços do orçamento, não o índice do "
                                              "reajuste; use o índice que corrige a data-base (ex.: INCC-DI, "
                                              "FGV/DNIT) e, se o contrato tem uma base por tabela, diga a parte "
                                              "em aplica_a (ex.: aplica_a: itens SICRO)")
        c["datas_base"].append({"mes": mes, "indice": indice, "aplica_a": str(db_.get("aplica_a") or "").strip()})
    if len({d["mes"] for d in c["datas_base"]}) != len(c["datas_base"]):
        falha("datas_base", "mês repetido")

    c["fiscais"] = []
    for i, f in enumerate(bruto.get("fiscais") or []):
        try:
            desde = _data((f or {}).get("desde"))
        except ValueError as e:
            falha(f"fiscais[{i}].desde", str(e))
            continue
        if not (f or {}).get("email") or not desde:
            falha(f"fiscais[{i}]", "email e desde são obrigatórios")
            continue
        if f.get("tratamento") is not None and f["tratamento"] not in TRATAMENTOS:
            falha(f"fiscais[{i}].tratamento", f"use {' ou '.join(TRATAMENTOS)}")
        if not str(f.get("nome") or "").strip():
            avisos.append(f"Contrato {c['nome_curto']}: fiscal {str(f['email']).strip().lower()} sem nome")
        c["fiscais"].append({"nome": str(f.get("nome") or ""), "email": str(f["email"]).strip().lower(),
                             "desde": desde, "cargo": f.get("cargo"), "tratamento": f.get("tratamento"),
                             "portaria": f.get("portaria")})

    c["instrumentos"] = []
    vistos: set[str] = set()
    for i, bruto_i in enumerate(bruto.get("instrumentos") or []):
        inst = _instrumento(bruto_i or {}, f"{onde}: instrumentos[{i}]", erros)
        if inst is None:
            continue
        if inst["chave"] in vistos:
            falha("instrumentos", f"chave repetida: {inst['chave']}")
        vistos.add(inst["chave"])
        if inst["pdf"] and not (raiz / inst["pdf"]).is_file():
            falha(f"instrumentos[{i}].pdf", f"arquivo não encontrado: {inst['pdf']}")
        c["instrumentos"].append(inst)
    for inst in c["instrumentos"]:
        if inst["corrige"] and inst["corrige"] not in vistos:
            falha("instrumentos", f"{inst['chave']} corrige {inst['corrige']!r}, que não existe")
    # Gates da PR #317: corrige para si mesmo, ou em roda (a corrige b, b corrige a), tiraria todos da conta
    corrige_de = {i["chave"]: i["corrige"] for i in c["instrumentos"] if i["corrige"]}
    for inst in c["instrumentos"]:
        caminho, k = [inst["chave"]], inst["corrige"]
        while k and k not in caminho:
            caminho.append(k)
            k = corrige_de.get(k)
        if k:
            falha("instrumentos", f"{inst['chave']}: a cadeia de correção volta a {k} "
                                  f"({' → '.join([*caminho, k])}); um termo não corrige a si mesmo")
    # Issue #410 (gate Sol, rodada 1, PR #452): duas correcoes de reajuste do mesmo termo somariam as duas no vigente
    corretores: dict[str, str] = {}
    for inst in c["instrumentos"]:
        if _corretor_de_valor(inst):
            if inst["corrige"] in corretores:
                falha("instrumentos", f"{inst['chave']} e {corretores[inst['corrige']]} corrigem {inst['corrige']}; "
                                      f"a correção da correção corrige a correção (corrige: "
                                      f"{corretores[inst['corrige']]})")
            corretores.setdefault(inst["corrige"], inst["chave"])
    # Bloco 7: folga propria do contrato (vence a do orgao; na MTPAR varia por contrato), campos dos
    # instrumentos e pleitos enviados antes do sistema.
    c["folga_vigencia_dias"] = None
    if bruto.get("folga_vigencia_dias") is not None:
        c["folga_vigencia_dias"] = _inteiro(bruto["folga_vigencia_dias"], 0)
        if c["folga_vigencia_dias"] is None:
            falha("folga_vigencia_dias", "use um inteiro ≥ 0")
    _dados_instrumentos(c, falha, avisos)
    c["pleitos_anteriores"] = _pleitos_anteriores(bruto.get("pleitos_anteriores"), c, falha)
    c["cronograma"] = _cronograma(bruto.get("cronograma"), falha)
    c["cronograma_superadas"] = _cronograma_superadas(bruto.get("cronograma_superadas"), falha)
    chaves_inst = {i["chave"] for i in c["instrumentos"]}
    for v in c["cronograma"]:
        if v["instrumento"] and v["instrumento"] not in chaves_inst:
            avisos.append(f"{c['nome_curto']}: cronograma[{v['chave']}].instrumento: {v['instrumento']!r} não é chave "
                          "de nenhum instrumento deste contrato; confira antes de aplicar (versão aplicada não muda)")
    # Bloco 4: excecao por contrato a lista de documentos do orgao.
    docs = {}
    for chave, campo in (("medicao", "documentos_medicao"), ("reajuste", "documentos_reajuste")):
        lista = _lista_documentos(bruto.get(campo), f"{onde}: {campo}", erros)
        if lista is not None:
            docs[chave] = lista
    c["documentos"] = docs or None
    # Issue #462: excecao por contrato as pecas que vao no oficio assinado (substitui a marca do orgao; [] desliga).
    # Que o orgao pede cada tipo, `preparar` confere (aqui so' se conhece a chave do orgao).
    c["pecas_no_oficio"] = None
    pno = bruto.get("pecas_no_oficio")
    if pno is not None:
        tipos = [t for t in TIPOS_PECA if t != "planilha"]      # a planilha editavel vai sempre solta
        if not isinstance(pno, list) or any(x not in tipos for x in pno) or len(set(pno)) != len(pno):
            falha("pecas_no_oficio", f"use uma lista, sem repetição, de {', '.join(tipos)}")
        else:
            c["pecas_no_oficio"] = list(pno)
    c["custo"] = _custo(bruto.get("custo"), falha)
    return c


# Issue #489: custo por obra. Naturezas orcamentarias fora do custo quando o yaml nao diz: 2.02 (nao operacional) e
# 2.01.22 (adiantamento a fornecedor). Regra do custo sem tarefa: so' `proporcional` (decisao do Leo de 06/11/2026).
NAO_E_CUSTO_PADRAO = ("2.02", "2.01.22")
REGRAS_SEM_TAREFA = ("proporcional",)
_PREFIXOS = 'use uma lista de códigos entre aspas (ex.: "001.03"); sem aspas o YAML lê o código como número'


_CHAVES_CUSTO = frozenset({"projeto_rm", "grupos", "nao_e_custo", "sem_tarefa"})
_CHAVES_GRUPO = frozenset({"nome", "tarefas", "itens_planilha", "item_chave"})


def _segmentos(codigo: str) -> list[str]:
    """`2.` e `2` sao o mesmo prefixo; `001.1` nao contem `001.10` (compara por segmento, nao por letra)."""
    return codigo.rstrip(".").split(".")


def _dentro_do_prefixo(codigo: str, prefixo: str) -> bool:
    s, p = _segmentos(codigo), _segmentos(prefixo)
    return s[:len(p)] == p


def _sobrepoe(a: str, b: str) -> bool:
    return _dentro_do_prefixo(a, b) or _dentro_do_prefixo(b, a)


def _prefixos(valor, campo: str, falha) -> list[str] | None:
    """Lista de prefixos de codigo (tarefa, item, natureza). Texto obrigatorio: `001.03` sem aspas vira 1.03."""
    if valor is None:
        return []
    if not isinstance(valor, list) or any(not isinstance(x, str) or not x.strip() for x in valor):
        falha(campo, _PREFIXOS)
        return None
    return [x.strip() for x in valor]


def _custo(bruto, falha) -> dict | None:
    """Secao `custo:` do contrato: projeto do Solum, grupos da planilha do orgao (ordem do yaml), naturezas fora do
    custo e regra do custo sem tarefa. Ausente: None (a obra fica sem cadastro de custo)."""
    if bruto is None:
        return None
    if not isinstance(bruto, dict):
        falha("custo", "use um mapa com projeto_rm, grupos, nao_e_custo e sem_tarefa")
        return None
    for k in sorted(set(bruto) - _CHAVES_CUSTO, key=str):
        falha(f"custo.{k}", f"campo desconhecido; use {', '.join(sorted(_CHAVES_CUSTO))}")
    projeto = str(bruto.get("projeto_rm") or "").strip()
    if not projeto:
        falha("custo.projeto_rm", "obrigatório (código do projeto no Solum, ex.: GL.C01.P704)")
    nao_e_custo = bruto.get("nao_e_custo")
    nao_e_custo = list(NAO_E_CUSTO_PADRAO) if nao_e_custo is None else _prefixos(nao_e_custo, "custo.nao_e_custo", falha)
    regra = bruto.get("sem_tarefa")
    regra = "proporcional" if regra is None else regra
    if regra not in REGRAS_SEM_TAREFA:
        falha("custo.sem_tarefa", f"use {' ou '.join(REGRAS_SEM_TAREFA)}: {regra!r}")
    lista = bruto.get("grupos")
    if not isinstance(lista, list) or not lista:
        falha("custo.grupos", "use uma lista com ao menos um grupo (nome, tarefas, itens_planilha)")
        lista = []
    grupos: list[dict] = []
    donos: dict[str, list[tuple[str, str]]] = {"tarefas": [], "itens_planilha": []}
    nomes: set[str] = set()
    for i, g in enumerate(lista):
        onde = f"custo.grupos[{i}]"
        if not isinstance(g, dict):
            falha(onde, "use um mapa com nome, tarefas, itens_planilha e, se houver, item_chave")
            continue
        for k in sorted(set(g) - _CHAVES_GRUPO, key=str):
            falha(f"{onde}.{k}", f"campo desconhecido; use {', '.join(sorted(_CHAVES_GRUPO))}")
        nome = g["nome"].strip() if isinstance(g.get("nome"), str) else ""
        if not nome:
            falha(f"{onde}.nome", "obrigatório, em texto (o nome do grupo na planilha do órgão)")
        elif nome in nomes:
            falha(f"{onde}.nome", f"grupo repetido: {nome}")
        nomes.add(nome)
        tarefas = _prefixos(g.get("tarefas"), f"{onde}.tarefas", falha)
        itens = _prefixos(g.get("itens_planilha"), f"{onde}.itens_planilha", falha)
        for campo, valores, rotulo in (("tarefas", tarefas, "a tarefa"), ("itens_planilha", itens, "o item")):
            for v in valores or []:
                for outro, dono in donos[campo]:
                    if v == outro:
                        lugar = "aparece duas vezes" if dono == nome else f"já está no grupo {dono}"
                        falha(f"{onde}.{campo}", f"{rotulo} {v} do grupo {nome} {lugar}")
                        break
                    if dono != nome and _sobrepoe(v, outro):
                        falha(f"{onde}.{campo}", f"{rotulo} {v} do grupo {nome} se sobrepõe a {outro} do grupo "
                                                 f"{dono}; um código só pode cair em um grupo")
                        break
                donos[campo].append((v, nome))
        chave = g.get("item_chave")
        if chave is not None:
            if (not isinstance(chave, dict) or not isinstance(chave.get("codigo"), str) or not chave["codigo"].strip()
                    or not isinstance(chave.get("unidade"), str) or not chave["unidade"].strip()):
                falha(f"{onde}.item_chave", 'use {codigo: "2.1", unidade: "m³"}, os dois entre aspas')
                chave = None
            else:
                chave = {"codigo": chave["codigo"].strip(), "unidade": chave["unidade"].strip()}
                if itens is not None and not any(_dentro_do_prefixo(chave["codigo"], p) for p in itens):
                    falha(f"{onde}.item_chave", f"o item {chave['codigo']} não está nos itens_planilha do grupo {nome}")
        grupos.append({"nome": nome, "tarefas": tarefas or [], "itens_planilha": itens or [], "item_chave": chave})
    return {"projeto_rm": projeto, "nao_e_custo": nao_e_custo or [], "sem_tarefa": regra, "grupos": grupos}


def preparar(raiz: Path) -> dict:
    raiz = Path(raiz)
    erros: list[str] = []
    avisos: list[str] = []
    for nome in ("orgaos.yaml", "entidades.yaml"):
        if not (raiz / nome).is_file():
            raise CadastroInvalido([f"{nome}: arquivo não encontrado em {raiz}"])

    orgaos = []
    for i, o in enumerate(_ler(raiz / "orgaos.yaml") or []):
        onde = f"orgaos.yaml[{i}]"
        if not isinstance(o, dict) or not _CHAVE.match(str(o.get("chave") or "")):
            erros.append(f"{onde}: chave: inválida ou ausente")
            continue
        if o.get("familia") not in FAMILIAS:
            erros.append(f"{onde}: familia: use uma de {FAMILIAS}")
        if not o.get("nome"):
            erros.append(f"{onde}: nome: obrigatório")
        # Bloco 3: CNPJ do orgao (opcional) e' o tomador esperado na nota fiscal; sem ele a
        # conferencia do tomador nao roda. Normalizado a 14 digitos, com DV conferido.
        cnpj = None
        if o.get("cnpj") is not None:
            cnpj = re.sub(r"\D", "", str(o.get("cnpj")))
            if not entidades.cnpj_valido(cnpj):
                erros.append(f"{onde}: cnpj: CNPJ inválido")
        for campo in ("documentos_medicao", "documentos_reajuste"):
            _lista_documentos(o.get(campo), f"{onde}: {campo}", erros)
        _protocolo_do_orgao(o, onde, erros)
        # Bloco 8: nome e tipo do contratante no QDOP (GL.SGI.FRP.DE.250)
        if o.get("tipo_contratante") is not None and o["tipo_contratante"] not in TIPOS_CONTRATANTE:
            erros.append(f"{onde}: tipo_contratante: use {' ou '.join(TIPOS_CONTRATANTE)}")
        if o.get("nome_qdop") is not None and not str(o["nome_qdop"]).strip():
            erros.append(f"{onde}: nome_qdop: texto vazio")
        orgaos.append({"chave": o["chave"], "nome": o.get("nome"), "familia": o.get("familia"), "cnpj": cnpj,
                       "regras": {k: v for k, v in o.items() if k not in ("chave", "nome", "familia", "cnpj")}})
    if len({o["chave"] for o in orgaos}) != len(orgaos):
        erros.append("orgaos.yaml: chave repetida")

    ents = []
    for i, e in enumerate(_ler(raiz / "entidades.yaml") or []):
        onde = f"entidades.yaml[{i}]"
        if not isinstance(e, dict) or not _CHAVE.match(str(e.get("chave") or "")):
            erros.append(f"{onde}: chave: inválida ou ausente")
            continue
        cnpj = re.sub(r"\D", "", str(e.get("cnpj") or ""))
        if not entidades.cnpj_valido(cnpj):
            erros.append(f"{onde}: cnpj: CNPJ inválido: {e.get('cnpj')!r}")
        if e.get("papel") not in PAPEIS:
            erros.append(f"{onde}: papel: use um de {PAPEIS}")
        if not e.get("nome"):
            erros.append(f"{onde}: nome: obrigatório")
        emails = [str(x).strip().lower() for x in (e.get("emails_faturamento") or [])]
        for em in emails:
            if not _EMAIL.match(em):
                erros.append(f"{onde}: emails_faturamento: e-mail inválido: {em!r}")
        ents.append({"chave": e["chave"], "nome": e.get("nome"), "cnpj": cnpj, "papel": e.get("papel"),
                     "coligada_rm": e.get("coligada_rm"), "sigla_oficio": e.get("sigla_oficio"),
                     "emails_faturamento": emails,
                     # bloco 4: nome dos arquivos do ZIP, composicao do consorcio, folha propria
                     "nome_curto": str(e.get("nome_curto") or e.get("nome") or "").strip(),
                     "consorciadas": [str(x) for x in (e.get("consorciadas") or [])],
                     "regularidade_propria": bool(e.get("regularidade_propria", False))})
    for campo in ("chave", "cnpj"):
        if len({x[campo] for x in ents}) != len(ents):
            erros.append(f"entidades.yaml: {campo} repetido")
    por_chave = {x["chave"]: x for x in ents}
    for x in ents:
        if not x["consorciadas"]:
            continue
        onde = f"entidades.yaml[{x['chave']}]: consorciadas"
        if x["papel"] != "consorcio":
            erros.append(f"{onde}: só consórcio tem composição")
        for ch in x["consorciadas"]:
            alvo = por_chave.get(ch)
            if alvo is None or alvo["papel"] not in ("lotufo", "consorciada"):
                erros.append(f"{onde}: {ch!r} não é a Lotufo nem uma consorciada cadastrada")
        if len(set(x["consorciadas"])) != len(x["consorciadas"]):
            erros.append(f"{onde}: repetida")

    chaves_orgao = {o["chave"] for o in orgaos}
    chaves_ent = {e["chave"] for e in ents}
    por_chave_orgao = {o["chave"]: {"familia": o["familia"], "pecas": o["regras"].get("pecas") or []} for o in orgaos}
    contratos = []
    for arquivo in sorted((raiz / "contratos").glob("*.yaml")):
        c = _contrato(_ler(arquivo), arquivo, raiz, chaves_orgao, chaves_ent, erros, avisos)
        if c is not None:
            contratos.append(c)
            o = por_chave_orgao.get(c["orgao"])
            if c["pecas_no_oficio"] and o is not None:
                _pecas_no_oficio_do_contrato(c["pecas_no_oficio"], c["orgao"], o,
                                             f"contratos/{arquivo.name}: pecas_no_oficio", erros)
    for campo in ("nome_curto", "numero_instrumento"):
        valores = [c[campo] for c in contratos if c[campo]]
        if len(set(valores)) != len(valores):
            erros.append(f"contratos: {campo} repetido")

    geral = _geral(raiz, erros)
    cartas = _cartas(raiz, chaves_ent, erros)
    if cartas is not None:
        geral = {**(geral or {}), "cartas": cartas}
    esp = _espelhos(raiz, contratos, chaves_ent, erros, avisos)
    frcs = _frcs(raiz, ents, erros)

    if erros:
        raise CadastroInvalido(erros)
    return {"orgaos": orgaos, "entidades": ents, "contratos": contratos, "avisos": avisos,
            "geral": geral, "espelho": esp, "frc": frcs}


_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _geral(raiz: Path, erros: list[str]) -> dict | None:
    """geral.yaml (spec §8): destinatarios e texto fixo do e-mail do espelho ao faturamento.
    Opcional na raiz (cadastros antigos e testes sem espelho)."""
    arq = raiz / "geral.yaml"
    if not arq.is_file():
        return None
    g = _ler(arq) or {}
    f = g.get("faturamento") if isinstance(g, dict) else None
    if not isinstance(f, dict):
        erros.append("geral.yaml: faturamento: obrigatório")
        return None
    para = [str(x).strip().lower() for x in (f.get("para") or [])]
    copia = [str(x).strip().lower() for x in (f.get("copia") or [])]
    if not para:
        erros.append("geral.yaml: faturamento.para: ao menos um destinatário")
    for e in para + copia:
        if not _EMAIL.match(e):
            erros.append(f"geral.yaml: e-mail inválido: {e!r}")
    for campo in ("assunto", "corpo"):
        if not str(f.get(campo) or "").strip():
            erros.append(f"geral.yaml: faturamento.{campo}: obrigatório")
    for ph in ("{medicao}", "{obra}"):
        if ph not in str(f.get("assunto") or ""):
            erros.append(f"geral.yaml: faturamento.assunto: precisa conter {ph}")
    out = {"faturamento": {"para": para, "copia": copia, "assunto": str(f.get("assunto") or "").strip(),
                           "corpo": str(f.get("corpo") or "").strip()}}
    # Bloco 8: o total a receber so' vai para a tela da diretoria depois de conciliado; modelo do QDOP.
    d = g.get("diretoria")
    if d is not None:
        if not isinstance(d, dict) or not isinstance(d.get("total_a_receber_liberado"), bool):
            erros.append("geral.yaml: diretoria.total_a_receber_liberado: use true ou false")
        else:
            out["diretoria"] = {"total_a_receber_liberado": d["total_a_receber_liberado"]}
    q = g.get("qdop")
    if q is not None:
        modelo = _dentro(raiz, q.get("modelo")) if isinstance(q, dict) and q.get("modelo") else None
        if modelo is None or modelo.suffix.lower() != ".xlsx":
            erros.append("geral.yaml: qdop.modelo: planilha .xlsx na pasta do cadastro")
        else:
            out["qdop"] = {"modelo_caminho": str(modelo)}
    # Issue #110: quem recebe a cobranca de certidao e o login de quem a envia (sai da conta Microsoft dele).
    # Issue #420: a copia cifrada do dono, no mesmo formato.
    for chave in ("cobranca_certidoes", "copia_dono"):
        cob = g.get(chave)
        if cob is None:
            continue
        listas = {c: [str(x).strip().lower() for x in ((cob.get(c) if isinstance(cob, dict) else None) or [])]
                  for c in ("para", "enviada_por")}
        for campo, emails in listas.items():
            if not emails or not all(_EMAIL.match(e) for e in emails):
                erros.append(f"geral.yaml: {chave}.{campo}: use uma lista de e-mails")
        out[chave] = listas
    return out


# Issue #110: a FRC de cada consorcio vem do cadastro (antes, semente da migracao 032).
FORMULARIOS_FRC = ("A",)
_CAMPOS_PARTE_FRC = ("razao_social", "endereco", "municipio", "cep", "cnpj", "inscricao_municipal", "telefone",
                     "email")


def _frcs(raiz: Path, ents: list[dict], erros: list[str]) -> list[dict]:
    """frc.yaml: por consorcio, o formulario, a ultima FRC emitida antes do sistema, o logo (arquivo da pasta do
    cadastro), prestador e tomador (impressos na FRC, com os e-mails), a descricao por natureza e as consorciadas.
    Opcional na raiz. Os CNPJs ficam como escritos (a FRC os imprime assim), com o digito conferido."""
    arq = raiz / "frc.yaml"
    if not arq.is_file():
        return []
    g = _ler(arq) or {}
    if not isinstance(g, dict):
        erros.append("frc.yaml: conteúdo não é um mapa YAML")
        return []
    papel = {e["chave"]: e["papel"] for e in ents}
    out = []
    for chave, f in g.items():
        onde = f"frc.yaml: {chave}"
        if papel.get(chave) != "consorcio":
            erros.append(f"{onde}: não é um consórcio de entidades.yaml")
            continue
        if not isinstance(f, dict):
            erros.append(f"{onde}: use um mapa")
            continue
        if f.get("formulario") not in FORMULARIOS_FRC:
            erros.append(f"{onde}.formulario: use um de {FORMULARIOS_FRC}")
        ultimo = _inteiro(f.get("ultimo_anterior"), 0)
        if ultimo is None:
            erros.append(f"{onde}.ultimo_anterior: número inteiro, zero ou mais")
        logo = None
        if f.get("logo"):
            logo = _dentro(raiz, f["logo"])
            if logo is None or logo.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                erros.append(f"{onde}.logo: imagem .jpg ou .png na pasta do cadastro")
        dados = {}
        for parte in ("prestador", "tomador"):
            p = f.get(parte) if isinstance(f.get(parte), dict) else {}
            dados[parte] = {c: str(p.get(c) or "").strip() for c in _CAMPOS_PARTE_FRC}
            dados[parte]["email"] = dados[parte]["email"].lower()
            for c, v in dados[parte].items():
                if not v:
                    erros.append(f"{onde}.{parte}.{c}: obrigatório")
            if dados[parte]["email"] and not _EMAIL.match(dados[parte]["email"]):
                erros.append(f"{onde}.{parte}.email: e-mail inválido")
            if dados[parte]["cnpj"] and not entidades.cnpj_valido(re.sub(r"\D", "", dados[parte]["cnpj"])):
                erros.append(f"{onde}.{parte}.cnpj: CNPJ inválido")
        desc = f.get("descricao")
        if not isinstance(desc, dict) or not desc or any(
                k not in ("execucao", "reajuste", "projeto") or not str(v or "").strip() for k, v in desc.items()):
            erros.append(f"{onde}.descricao: um texto por natureza usada (execucao, reajuste, projeto)")
            desc = {}
        for k, v in desc.items():              # a FRC preenche so' estes tres: outro placeholder estouraria ao gerar
            try:
                str(v).format(n=1, inicio="01/01/2026", fim="31/01/2026")
            except (KeyError, IndexError, ValueError):
                erros.append(f"{onde}.descricao.{k}: use só os placeholders {{n}}, {{inicio}} e {{fim}}")
        dados["descricao"] = {k: str(v).strip() for k, v in desc.items()}
        dados["rotulo_empresa"] = str(f.get("rotulo_empresa") or "").strip() or None
        cons = f.get("consorciadas")
        if not isinstance(cons, list) or not cons or any(
                not isinstance(c, dict) or papel.get(c.get("chave")) not in ("lotufo", "consorciada")
                or not str(c.get("razao_social") or "").strip()
                or not entidades.cnpj_valido(re.sub(r"\D", "", str(c.get("cnpj") or ""))) for c in cons):
            erros.append(f"{onde}.consorciadas: lista de chave (entidade cadastrada), cnpj e razao_social")
            cons = []
        dados["consorciadas"] = [{k: str(c[k]).strip() for k in ("chave", "cnpj", "razao_social")} for c in cons]
        out.append({"consorcio": chave, "formulario": f.get("formulario"), "ultimo_anterior": ultimo,
                    "dados": dados, "logo_caminho": str(logo) if logo else None})
    return out


def _cartas(raiz: Path, ents: set[str], erros: list[str]) -> dict | None:
    """cartas.yaml (bloco 5; spec §5.2, §6): textos das cartas e dos e-mails de protocolo por familia,
    assinatura e emitentes (timbre). Opcional na raiz (cadastros antigos e testes)."""
    arq = raiz / "cartas.yaml"
    if not arq.is_file():
        return None
    g = _ler(arq) or {}
    if not isinstance(g, dict):
        erros.append("cartas.yaml: conteúdo não é um mapa YAML")
        return None
    if g.get("signatario") is not None and not _textos(g["signatario"]):
        erros.append("cartas.yaml: signatario: use uma lista de linhas de texto")
    emitentes = {}
    for chave, e in (g.get("emitentes") or {}).items():
        if chave not in ents:
            erros.append(f"cartas.yaml: emitentes.{chave}: entidade não cadastrada")
        if not isinstance(e, dict) or not str(e.get("razao_social") or "").strip():
            erros.append(f"cartas.yaml: emitentes.{chave}.razao_social: obrigatório")
            continue
        e = dict(e)
        if e.get("rodape") is not None and not isinstance(e["rodape"], bool):
            erros.append(f"cartas.yaml: emitentes.{chave}.rodape: use true ou false")
        larg = e.get("logo_largura_mm")
        if larg is not None and (isinstance(larg, bool) or not isinstance(larg, (int, float)) or not 10 <= larg <= 150):
            erros.append(f"cartas.yaml: emitentes.{chave}.logo_largura_mm: número entre 10 e 150 (mm)")
        if e.get("logo"):
            p = _dentro(raiz, e["logo"])
            if not p:
                erros.append(f"cartas.yaml: emitentes.{chave}.logo: arquivo não encontrado na pasta do cadastro: "
                             f"{e['logo']}")
            e["logo_caminho"] = str(p)
            e.pop("logo")
        emitentes[chave] = e
    familias = {}
    for fam, textos in (g.get("familias") or {}).items():
        if fam not in FAMILIAS_CARTA:
            erros.append(f"cartas.yaml: familias.{fam}: use uma de {FAMILIAS_CARTA}")
            continue
        # texto, ou lista de linhas (a assinatura da familia, como na SES: "Eng° Francisco...", "CREA ...")
        if not isinstance(textos, dict) or any(not (isinstance(v, str) or _textos(v)) for v in textos.values()):
            erros.append(f"cartas.yaml: familias.{fam}: cada campo é um texto ou uma lista de linhas")
            continue
        familias[fam] = textos
    extras = {k: v for k, v in g.items() if k not in ("signatario", "emitentes", "familias")}
    for k, v in extras.items():                  # bloco 7: pleito_reajuste, prazo, conclusao
        if not isinstance(v, dict) or any(not (isinstance(x, str) or _textos(x)) for x in v.values()):
            erros.append(f"cartas.yaml: {k}: cada campo é um texto ou uma lista de linhas")
    return {"signatario": list(g.get("signatario") or []), "emitentes": emitentes, "familias": familias, **extras}


def _espelhos(raiz: Path, contratos: list[dict], ents: set[str], erros: list[str],
              avisos: list[str]) -> list[dict]:
    """espelho/<slug>.yaml + modelos/espelho/<slug>/*.docx (spec §4.2, §8). A regra e' normalizada
    pelo motor; aqui se confere o que so' o cadastro sabe: contrato, emissor e os controles reais
    de cada modelo Word (o modelo tem que ter todo controle que a saida preenche)."""
    pasta = raiz / "espelho"
    if not pasta.is_dir():
        return []
    por_nome = {c["nome_curto"]: c for c in contratos}
    out = []
    for arq in sorted(pasta.glob("*.yaml")):
        onde = f"espelho/{arq.name}"
        try:
            regra = espelho.normalizar(_ler(arq))
        except espelho.RegraInvalida as e:
            erros.extend(f"{onde}: {x}" for x in e.erros)
            continue
        nome = regra["contrato"]
        if nome not in por_nome:
            erros.append(f"{onde}: contrato: {nome!r} não existe em contratos/")
            continue
        if arq.stem != slug(nome):
            erros.append(f"{onde}: arquivo deveria chamar-se {slug(nome)}.yaml")
        modelos = {}
        nomes_gerados: dict[str, str] = {}
        for s in regra["saidas"]:
            if s["emissor"] not in ents:
                erros.append(f"{onde}: saidas/{s['chave']}: emissor não cadastrado: {s['emissor']}")
            n = espelho.nome_arquivo(regra, s, nome, 1, "2026-01", s["emissor"])
            if n in nomes_gerados:
                erros.append(f"{onde}: saidas/{s['chave']} e {nomes_gerados[n]} gerariam o mesmo arquivo "
                             f"({n}); dê um `rotulo` a uma delas")
            nomes_gerados[n] = s["chave"]
            caminho = raiz / "modelos" / "espelho" / slug(nome) / s["modelo"]
            if not caminho.is_file():
                erros.append(f"{onde}: saidas/{s['chave']}: modelo não encontrado: {s['modelo']}")
                continue
            dados = caminho.read_bytes()
            try:
                tags = espelho_docx.controles(dados)
            except espelho_docx.DocxInvalido as e:
                erros.append(f"{onde}: {s['modelo']}: {e}")
                continue
            faltam = espelho.campos_da_saida(s) - tags
            if "mes_ano" in tags:              # o periodo pode vir como 'MAIO/2026' (Regiao Oeste)
                faltam.discard("periodo")
            if faltam:
                erros.append(f"{onde}: {s['modelo']}: sem os controles {sorted(faltam)}")
            for opc in espelho.CAMPOS_OPCIONAIS:
                if s["retencoes"].get(opc) and opc not in tags:
                    avisos.append(f"{onde}: {s['modelo']}: sem o controle {opc} (linha não sairá no espelho)")
            modelos[s["chave"]] = {"caminho": caminho, "sha256": hashlib.sha256(dados).hexdigest()}
        canonico = json.dumps(regra, ensure_ascii=False, sort_keys=True)
        out.append({"contrato": nome, "slug": slug(nome), "situacao": regra["situacao"], "regra": regra,
                    "sha256": hashlib.sha256(canonico.encode("utf-8")).hexdigest(), "modelos": modelos})
    return out
