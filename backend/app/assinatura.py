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
