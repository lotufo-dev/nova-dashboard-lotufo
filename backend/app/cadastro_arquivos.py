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

from app import dinheiro, entidades, espelho, espelho_docx, tempo

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
TIPOS_PLEITO = ("reajuste", "prazo", "conclusao")
# Pecas que o orgao pode pedir no pleito de reajuste (mesma lista de `pleitos.PECAS_ORGAO`).
PECAS_PLEITO = ("falencia", "contrato_social", "documento_representante", "balanco")
_CICLO = re.compile(r"^([0-9]{4})(-[0-9]{2})?$")
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
                       "nova_execucao_fim", "nova_vigencia_fim", "pdf", "ordinal"}


class CadastroInvalido(Exception):
    def __init__(self, erros: list[str]):
        self.erros = erros
        super().__init__("\n".join(erros))


def _textos(v) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) and x.strip() for x in v)


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
        for campo in ("exigida", "solto"):
            if campo in p and not isinstance(p[campo], bool):
                erros.append(f"{onde}: pecas[{i}].{campo}: use true ou false")
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
    if bruto.get("delta_valor") not in (None, ""):
        texto = str(bruto["delta_valor"]).strip()
        sinal = -1 if texto.startswith("-") else 1
        try:
            inst["delta_valor_centavos"] = sinal * dinheiro.parse_brl(texto.lstrip("-").strip())
        except ValueError as e:
            falha("delta_valor", str(e))
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


def _dados_instrumentos(c: dict, falha, avisos: list[str]) -> None:
    """Bloco 7: campos de `dados` que reajuste e prazos leem, validados e normalizados."""
    meses = {d["mes"] for d in c["datas_base"]}
    de_prazo = {i["chave"] for i in c["instrumentos"]
                if i["tipo"] in ("aditivo_prazo", "apostilamento_prazo", "aditivo_misto")}
    for inst in c["instrumentos"]:
        d, onde = inst["dados"], f"instrumentos[{inst['chave']}]"
        if inst["tipo"] == "apostilamento_reajuste":
            if d.get("data_base") is not None and str(d["data_base"]) not in meses:
                falha(f"{onde}.data_base", "use AAAA-MM de uma das datas_base do contrato")
            # "2026-06" (Granito) vale: o reajuste le so' o ano. Nao normaliza: instrumento aplicado nao muda.
            if d.get("ciclo") is not None and not _CICLO.match(str(d["ciclo"])):
                falha(f"{onde}.ciclo", "use o ano do ciclo (ex.: 2026)")
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
                "ciclo": None, "dias": None}
        if p["tipo"] == "reajuste":
            if str(p.get("data_base") or "") not in meses:
                falha(f"{onde}.data_base", "use uma das datas_base do contrato (AAAA-MM)")
            if _inteiro(p.get("ciclo"), 2000) is None:
                falha(f"{onde}.ciclo", "obrigatório no reajuste (ano, ex.: 2026)")
            item["data_base"], item["ciclo"] = str(p.get("data_base") or ""), p.get("ciclo")
        elif p["tipo"] == "prazo" and p.get("dias") is not None:
            if _inteiro(p["dias"], 1) is None:
                falha(f"{onde}.dias", "use um inteiro > 0")
            item["dias"] = p["dias"]
        out.append(item)
    return out


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
        c["datas_base"].append({"mes": mes, "indice": str(db_.get("indice") or "")})
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
    return c


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
    contratos = []
    for arquivo in sorted((raiz / "contratos").glob("*.yaml")):
        c = _contrato(_ler(arquivo), arquivo, raiz, chaves_orgao, chaves_ent, erros, avisos)
        if c is not None:
            contratos.append(c)
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
    cob = g.get("cobranca_certidoes")
    if cob is not None:
        listas = {c: [str(x).strip().lower() for x in ((cob.get(c) if isinstance(cob, dict) else None) or [])]
                  for c in ("para", "enviada_por")}
        for campo, emails in listas.items():
            if not emails or not all(_EMAIL.match(e) for e in emails):
                erros.append(f"geral.yaml: cobranca_certidoes.{campo}: use uma lista de e-mails")
        out["cobranca_certidoes"] = listas
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
