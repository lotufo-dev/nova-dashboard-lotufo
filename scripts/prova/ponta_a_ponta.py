"""Teste de ponta a ponta (issue #701): sobe o sistema inteiro com dados de exemplo, entra como cada perfil e abre
as telas principais. Um comando so', o mesmo na maquina e na CI (job `ponta-a-ponta`):

  python3 scripts/prova/ponta_a_ponta.py

O que faz: cria uma pasta temporaria, monta o frontend nela, sobe o servidor de prova (`servidor.py`) num banco
NOVO com o `cadastro-exemplo/` e o e-mail no simulador, e roda `capturar.mjs --conferir`: admin, engenharia e
diretoria entram pela tela de login e abrem cada tela de `telas.mjs`, a 1440 de largura. Reprova (codigo 1) com erro
de console, resposta 4xx/5xx, tela de erro, tela em branco ou tela que nao carrega; as telas reprovadas ficam
fotografadas em `<pasta>/saida/capturas/`, ao lado do `relato.json`.

As variaveis DASH_DB_PATH e DASH_CADASTRO_DIR do terminal nao valem aqui: o teste e' sempre banco novo e cadastro
de exemplo. Opcoes: `--pasta` (onde trabalhar; a CI usa para achar as capturas), `--dist` (frontend ja' montado),
`--larguras` e `--capturas` (repassadas a `capturar.mjs`). Se passar, a pasta temporaria criada aqui e' apagada.

So' biblioteca padrao; o backend roda com o Python de `backend/.venv` e as telas com o Playwright de `frontend/`.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comum  # noqa: E402
import servidor as servidor_de_prova  # noqa: E402


def main(argv: list | None = None) -> int:
    p = argparse.ArgumentParser(description="Sobe o sistema com dados de exemplo e abre as telas como cada perfil.")
    p.add_argument("--pasta", help="pasta de trabalho, fora do repositório (padrão: uma temporária, apagada se passar)")
    p.add_argument("--dist", help="frontend já montado (padrão: monta agora)")
    p.add_argument("--larguras", default="1440", help="larguras de janela, separadas por vírgula (padrão 1440)")
    p.add_argument("--capturas", default="falha", choices=["todas", "falha", "nenhuma"],
                   help="quais telas fotografar (padrão: só as reprovadas)")
    args = p.parse_args(argv)

    node = shutil.which("node")
    if node is None:
        print("RECUSADO: falta o Node no PATH.", file=sys.stderr)
        return 2
    inicio = time.monotonic()
    temporaria = args.pasta is None
    pasta = Path(tempfile.mkdtemp(prefix="dashboard-ponta-a-ponta-")) if temporaria else comum.absoluto(args.pasta)
    banco = pasta / "prova.db"
    if banco.exists():
        print(f"RECUSADO: {banco} já existe. O teste de ponta a ponta sempre parte de um banco novo: use uma pasta "
              "vazia.", file=sys.stderr)
        return 2
    ambiente = {**os.environ, "DASH_DB_PATH": str(banco), "DASH_CADASTRO_DIR": str(comum.CADASTRO_EXEMPLO),
                "DASH_PROVA_SAIDA": str(pasta / "saida")}
    try:
        with servidor_de_prova.subir(ambiente, dist=comum.absoluto(args.dist) if args.dist else None) as servidor:
            print(f"servidor de prova no ar em {servidor.base} ({time.monotonic() - inicio:.0f} s)", flush=True)
            codigo = subprocess.run(
                [node, str(Path(__file__).resolve().parent / "capturar.mjs"), "--conferir",
                 "--larguras", args.larguras, "--capturas", args.capturas],
                cwd=comum.RAIZ, env=ambiente).returncode
    except comum.Recusa as e:
        print(f"RECUSADO: {e}", file=sys.stderr)
        return 2
    segundos = time.monotonic() - inicio
    if codigo == 0:
        print(f"ponta a ponta: PASSOU em {segundos:.0f} s")
        if temporaria:
            shutil.rmtree(pasta, ignore_errors=True)
    else:
        print(f"ponta a ponta: REPROVOU em {segundos:.0f} s. Capturas, relato e log do servidor em {pasta}",
              file=sys.stderr)
    return codigo


if __name__ == "__main__":
    sys.exit(main())
