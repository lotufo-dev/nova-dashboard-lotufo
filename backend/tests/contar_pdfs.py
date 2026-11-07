"""Plugin de pytest que conta os PDFs gerados por modulo de teste (chamadas a `FPDF.output`, inclusive nas fixtures).

Nao e' carregado sozinho: so' entra com `-p contar_pdfs`, e a suite normal nao muda. Roda em serie (sem xdist):

    cd backend && PYTHONPATH=tests .venv/bin/python -m pytest -q -p contar_pdfs tests

No fim imprime `PDFs gerados por modulo`. E' a medicao que decide quem leva o marcador `pdf` (README)."""
import collections

import fpdf
import pytest

_contagem = collections.Counter()
_atual = [None]
_original = fpdf.FPDF.output


def _output_contado(self, *args, **kwargs):
    _contagem[_atual[0]] += 1
    return _original(self, *args, **kwargs)


fpdf.FPDF.output = _output_contado


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    _atual[0] = item.nodeid.split("::")[0]
    yield


def pytest_terminal_summary(terminalreporter):
    terminalreporter.section("PDFs gerados por modulo")
    for modulo, n in sorted(_contagem.items(), key=lambda par: (-par[1], str(par[0]))):
        terminalreporter.write_line(f"{n:6d}  {modulo}")
