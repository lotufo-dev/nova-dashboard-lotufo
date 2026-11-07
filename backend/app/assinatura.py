"""Conferencia do PDF assinado no DocuSign (spec 2026-09-21 §6), por AVISO. Bloco 5.

Tres regras, sobre o texto de cada pagina (o carimbo do DocuSign sai como texto extraivel):
(1) as N primeiras paginas do assinado batem com as N do pacote montado, ignorando o carimbo;
(2) paginas a mais no fim so' se forem o "Certificado de Conclusao" do DocuSign;
(3) todas as N paginas tem o carimbo "Docusign Envelope ID: <GUID>", o mesmo em todas.
Pega pagina trocada e, sobretudo, PDF que ainda nao foi assinado (o CT-286 da Orla foi protocolado
sem nenhuma pagina carimbada). Comparacao por semelhanca e nao por igualdade: o DocuSign reescreve o
PDF e o extrator devolve espacos e quebras diferentes.
"""
import re
import unicodedata
from difflib import SequenceMatcher

from app import leitura_pdf, pdfs

LIMIAR = 0.90
_ENVELOPE = re.compile(r"DOCUSIGN\s+ENVELOPE\s+ID\s*:?\s*([0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12})",
                       re.IGNORECASE)
_CERTIFICADO = re.compile(r"CERTIFICADO\s+DE\s+CONCLUS|CERTIFICATE\s+OF\s+COMPLETION", re.IGNORECASE)


# O texto que a assinatura do DocuSign poe na pagina: o rotulo, o nome de quem assinou e o codigo (hex e "..."). A
# conferencia do termo (`protocolo._plano_sem_timbre`) o tira antes de juntar as paginas (issue #519). So' sai o que e'
# do widget: o rotulo, o codigo (linha so' de hex) e, colado a eles, uma linha com cara de nome proprio (so' letras,
# ate' 6 palavras, sem numero, "nº" ou palavra do oficio). Linha da carta intercalada fica (gate Sol da PR #549).
_ROTULO = re.compile(r"(?:(?:DOCU)?SIGNED\s+BY|ASSINADO\s+POR)\s*:", re.IGNORECASE)
_CODIGO_RE = r"(?=[0-9A-F]*[0-9])[0-9A-F]{12,}(?:\.{3}|…)?"
_CODIGO = re.compile(rf"(?<![0-9A-Z]){_CODIGO_RE}(?![0-9A-Z])", re.IGNORECASE)
_SO_CODIGO = re.compile(rf"^\s*{_CODIGO_RE}\s*$", re.IGNORECASE)
_NOME = re.compile(r"^[^\W\d_ºª][^\d_ºª/:;()]{1,79}$")
# radicais do oficio e da frase do termo: plural e conjugacao tambem nao contam como nome (gate Sol, rodada 2)
_DO_OFICIO = ("TERMO", "APOSTIL", "REAJUST", "COMPETENC", "MEDICA", "MEDICO", "CONTRAT", "OFICIO", "NOTA")


def _e_nome(linha: str) -> bool:
    t = linha.strip()
    if not _NOME.match(t) or len(t.split()) > 6:
        return False
    return not any(_plano(w).startswith(r) for w in t.split() for r in _DO_OFICIO)


def sem_bloco_de_assinatura(texto: str) -> str:
    linhas = (texto or "").split("\n")
    for i, linha in enumerate(linhas):
        m = _ROTULO.search(linha)
        if not m:
            continue
        resto = _CODIGO.sub(" ", linha[m.end():]).strip()       # tudo na mesma linha: rotulo, nome e codigo
        linhas[i] = linha[:m.start()] + ("" if not resto or _e_nome(resto) else " " + resto)
        nome = bool(resto)
        for passo in (-1, 1):                                     # codigo antes ou depois; nome colado ao bloco
            k = i + passo
            while 0 <= k < len(linhas) and abs(k - i) <= 3:
                if not linhas[k].strip():
                    k += passo
                    continue
                if _SO_CODIGO.match(linhas[k]):
                    linhas[k] = ""
                elif passo == 1 and not nome and _e_nome(linhas[k]) and not _ROTULO.search(linhas[k]):
                    linhas[k], nome = "", True
                else:
                    break
                k += passo
    return "\n".join("" if _SO_CODIGO.match(x) else x for x in linhas)


def _plano(texto: str) -> str:
    t = _ENVELOPE.sub(" ", texto or "")
    t = "".join(unicodedata.normalize("NFKD", c)[:1] for c in t)
    return re.sub(r"[^0-9A-Z]", "", t.upper())


def _lista(paginas: list[int]) -> str:
    return ", ".join(str(p) for p in paginas[:12]) + (" …" if len(paginas) > 12 else "")


def conferir(montado: list[str], assinado: list[str]) -> dict:
    n, a = len(montado), len(assinado)
    avisos = []
    comum = min(n, a)
    if a < n:
        avisos.append({"codigo": "paginas_a_menos",
                       "mensagem": f"O assinado tem {a} páginas; o pacote montado tem {n}."})
    diferentes = []
    for i in range(comum):
        m, s = _plano(montado[i]), _plano(assinado[i])
        if not m and not s:
            continue
        if not m or not s or SequenceMatcher(None, m, s, autojunk=False).ratio() < LIMIAR:
            diferentes.append(i + 1)
    if diferentes:
        avisos.append({"codigo": "pagina_diferente",
                       "mensagem": f"Página(s) {_lista(diferentes)} do assinado não batem com o pacote montado."})
    # O certificado pode ter varias paginas (CT-073: 4) e so' a primeira traz o titulo: dali em diante,
    # tudo e' certificado. Pagina a mais ANTES do titulo e' que e' suspeita.
    inicio = next((n + j for j, t in enumerate(assinado[n:]) if _CERTIFICADO.search((t or "")[:400])), a)
    extras = list(range(n + 1, inicio + 1))
    if extras:
        avisos.append({"codigo": "paginas_extras",
                       "mensagem": f"Página(s) {_lista(extras)} a mais no fim, que não são o certificado do DocuSign."})
    ids = []
    for i in range(comum):
        m = _ENVELOPE.search(assinado[i] or "")
        ids.append(m.group(1).upper() if m else None)
    sem = [i + 1 for i, g in enumerate(ids) if not g]
    if comum and len(sem) == comum:
        avisos.append({"codigo": "nao_assinado",
                       "mensagem": "Nenhuma página tem o carimbo do DocuSign: o PDF parece não assinado."})
    elif sem:
        avisos.append({"codigo": "sem_carimbo", "mensagem": f"Página(s) {_lista(sem)} sem o carimbo do DocuSign."})
    distintos = {g for g in ids if g}
    if len(distintos) > 1:
        avisos.append({"codigo": "envelopes_diferentes",
                       "mensagem": f"O carimbo traz {len(distintos)} envelopes diferentes."})
    return {"ok": not avisos, "avisos": avisos, "envelope": next(iter(distintos)) if len(distintos) == 1 else None,
            "paginas_montado": n, "paginas_assinado": a, "certificado": a - n - len(extras) if a > n else 0}


def textos(pdf: bytes) -> list[str]:
    """O texto de cada pagina de um pacote (montado ou assinado), com o teto de paginas do pacote."""
    return leitura_pdf.textos_por_pagina_com_limite(pdf, pdfs.TETO_PAGINAS_PACOTE)


def paginas_com(paginas: list[str], frase: str) -> list[str]:
    """As paginas cujo texto traz `frase`, sem contar acento, caixa, espaco e pontuacao (o DocuSign quebra linhas)."""
    alvo = _plano(frase)
    return [t for t in paginas if alvo in _plano(t)]


def conferir_pdfs(montado_pdf: bytes, assinado_pdf: bytes) -> dict:
    return conferir(textos(montado_pdf), textos(assinado_pdf))
