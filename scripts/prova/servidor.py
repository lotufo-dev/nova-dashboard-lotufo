"""Servidor de prova (issue #702): sobe o sistema inteiro sobre um banco que nao e' o de trabalho.

  DASH_DB_PATH=<pasta temporaria>/prova.db DASH_CADASTRO_DIR=cadastro-exemplo python3 scripts/prova/servidor.py

Sobre uma copia do banco (um arquivo que ja' tem contratos), a primeira subida pede `--copia`: a prova roda as
migracoes e cria tres usuarios de teste nela, um deles administrador, e isso nao se faz sem alguem dizer que o
arquivo e' copia. O banco de uma instalacao (a producao) e' recusado sempre, com ou sem `--copia`.

O que faz, nesta ordem:
  1. confere as variaveis (`comum.py`): recusa o banco padrao, banco dentro do repositorio, banco de uma
     instalacao, banco com contratos sem `--copia`, variavel faltando e `--porta` ja' ocupada;
  2. monta o frontend numa pasta ao lado do banco (`frontend/dist` nao e' tocado), a menos de `--dist` ou
     `--sem-frontend`;
  3. gera a senha dos usuarios de teste num arquivo ao lado do banco (`prova-senha.txt`, fora do repositorio; a
     senha nunca aparece na tela) e prepara o banco com `semear.py`: migracoes, um usuario por perfil e, em banco
     novo, o cadastro e o historico de medicoes da pasta do cadastro;
  4. sobe o backend em 127.0.0.1, na porta pedida (`--porta`) ou numa livre, com `DASH_DEV=1`, `DASH_SEM_JOBS=1`
     e o e-mail no simulador (`correio-simulado/` ao lado do banco). Nenhuma outra DASH_* do terminal chega ao
     servidor: RM e Microsoft 365 ficam desligados mesmo que estejam configurados na maquina;
  5. grava `prova-servidor.json` ao lado do banco (endereco, usuarios, pasta de saida), que `retrato.py` e
     `capturar.mjs` leem, e fica no ar ate' Ctrl+C.

So' biblioteca padrao. O backend roda com o Python de `backend/.venv` quando existe (senao, o que chamou).
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comum  # noqa: E402

ESPERA_SUBIDA = 90  # segundos; a primeira subida num banco novo roda todas as migracoes


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def porta_ocupada(porta: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", porta))
        except OSError:
            return True
    return False


def exigir_porta_livre(porta: int) -> None:
    """Com a porta ja' ocupada por outra dashboard, o `/api/health` DELA responderia "ok" antes de o backend da
    prova desistir da porta, e a prova seria anunciada no ar em cima do servidor errado."""
    if porta_ocupada(porta):
        raise comum.Recusa(f"A porta {porta} já está em uso por outro processo. Escolha outra com --porta ou rode "
                           "sem --porta, que a prova pega uma livre.")


def montar_frontend(destino: Path) -> None:
    """`vite build` com a saida em `destino`. Sem `tsc`: os tipos sao conferidos por `npm run typecheck`."""
    node = shutil.which("node")
    vite = comum.FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"
    if node is None or not vite.exists():
        raise comum.Recusa("Para montar o frontend faltam o Node ou as dependências (rode `npm ci` em frontend/, "
                           "na pasta principal). Sem tela: use --sem-frontend.")
    print(f"montando o frontend em {destino} ...", flush=True)
    feito = subprocess.run([node, str(vite), "build", "--outDir", str(destino), "--emptyOutDir", "--logLevel", "warn"],
                           cwd=comum.FRONTEND)
    if feito.returncode != 0:
        raise comum.Recusa("O frontend não montou (erro do vite acima).")


def garantir_senha(arquivo: Path) -> bool:
    """Gera a senha de teste se o arquivo ainda nao existe. Devolve True quando gerou agora."""
    if arquivo.exists() and arquivo.read_text(encoding="utf-8").strip():
        return False
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(secrets.token_urlsafe(18) + "\n", encoding="utf-8")
    try:
        arquivo.chmod(0o600)
    except OSError:
        pass  # Windows: a pasta temporaria ja' e' so' de quem roda
    return True


class Servidor:
    """O servidor de prova no ar. `encerrar()` derruba o processo e apaga o `prova-servidor.json`."""

    def __init__(self, base: str, processo: subprocess.Popen, dados: dict, arquivos: dict, log):
        self.base, self.processo, self.dados, self.arquivos, self._log = base, processo, dados, arquivos, log

    def encerrar(self) -> None:
        if self.processo.poll() is None:
            self.processo.terminate()
            try:
                self.processo.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.processo.kill()
                self.processo.wait(timeout=10)
        self._log.close()
        self.arquivos["servidor"].unlink(missing_ok=True)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.encerrar()


def _fim_do_log(arquivo: Path, linhas: int = 30) -> str:
    try:
        return "\n".join(arquivo.read_text(encoding="utf-8", errors="replace").splitlines()[-linhas:])
    except OSError:
        return ""


def _esperar_saude(base: str, processo: subprocess.Popen, log: Path) -> None:
    limite = time.monotonic() + ESPERA_SUBIDA
    while time.monotonic() < limite:
        if processo.poll() is not None:
            raise comum.Recusa(f"O servidor de prova caiu ao subir (código {processo.returncode}). Fim do log:\n"
                               + _fim_do_log(log))
        try:
            with urllib.request.urlopen(f"{base}/api/health", timeout=2) as r:
                if json.load(r).get("status") == "ok":
                    return
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(0.3)
    raise comum.Recusa(f"O servidor de prova não respondeu em {ESPERA_SUBIDA} s. Fim do log:\n" + _fim_do_log(log))


ROTULOS = {"novo": "novo", "vazio": "sem contratos: o cadastro será aplicado", "copia": "cópia",
           "preparado": "a prova já rodou nele"}


def subir(ambiente=os.environ, porta: int | None = None, dist: Path | None = None,
          com_frontend: bool = True, copia: bool = False) -> Servidor:
    """Confere o ambiente, prepara o banco e devolve o servidor ja' respondendo. Levanta `comum.Recusa`.
    Todas as recusas vem antes de a prova gravar qualquer coisa: nem pasta, nem senha, nem migracao, nem conta.
    (O banco com contratos e' aberto so' para leitura, para contar contratos e usuarios de teste.)"""
    banco = comum.banco_de_prova(ambiente)
    cadastro = comum.cadastro_de_prova(ambiente)
    saida = comum.saida_de_prova(ambiente, banco)
    arquivos = comum.arquivos_da_prova(banco)
    o_que_e = comum.conferir_copia(banco, copia)
    if porta:
        exigir_porta_livre(porta)
    banco.parent.mkdir(parents=True, exist_ok=True)

    if not com_frontend:
        dist = None
    elif dist is None:
        dist = arquivos["dist"]
        montar_frontend(dist)
    elif not (dist / "index.html").exists():
        raise comum.Recusa(f"--dist não tem um frontend montado (falta index.html): {dist}")

    python = comum.python_do_backend()
    env = comum.ambiente_do_servidor(ambiente, banco, cadastro, dist)
    env["PYTHONPATH"] = os.pathsep.join([str(comum.BACKEND), *filter(None, [ambiente.get("PYTHONPATH")])])
    print(f"banco da prova: {banco} ({ROTULOS[o_que_e]})", flush=True)
    gerou = garantir_senha(arquivos["senha"])
    semear = [python, str(Path(__file__).resolve().parent / "semear.py"), str(arquivos["senha"])]
    semear += (["--redefinir"] if gerou else []) + (["--copia"] if copia else [])
    if subprocess.run(semear, cwd=comum.BACKEND, env=env).returncode != 0:
        raise comum.Recusa("O banco da prova não ficou pronto (mensagem acima).")

    if porta:
        exigir_porta_livre(porta)   # de novo: montar o frontend e preparar o banco levam tempo
    else:
        porta = porta_livre()
    base = f"http://127.0.0.1:{porta}"
    log = open(arquivos["log"], "w", encoding="utf-8")
    processo = subprocess.Popen(
        [python, "-m", "uvicorn", "--factory", "app.main:create_app", "--host", "127.0.0.1", "--port", str(porta)],
        cwd=comum.BACKEND, env=env, stdout=log, stderr=subprocess.STDOUT)
    dados = {"base": base, "porta": porta, "pid": processo.pid, "banco": str(banco), "cadastro": str(cadastro),
             "saida": str(saida), "senha": str(arquivos["senha"]), "frontend": dist is not None,
             "usuarios": {p: comum.email_de_teste(p) for p in comum.PERFIS}}
    servidor = Servidor(base, processo, dados, arquivos, log)
    try:
        _esperar_saude(base, processo, arquivos["log"])
    except BaseException:
        servidor.encerrar()
        raise
    arquivos["servidor"].write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    return servidor


def main(argv: list | None = None) -> int:
    p = argparse.ArgumentParser(description="Sobe o servidor de prova sobre DASH_DB_PATH e DASH_CADASTRO_DIR.")
    p.add_argument("--porta", type=int, help="porta em 127.0.0.1 (padrão: uma livre)")
    p.add_argument("--dist", help="frontend já montado (padrão: monta agora, ao lado do banco)")
    p.add_argument("--sem-frontend", action="store_true", help="só a API (basta para o retrato)")
    p.add_argument("--copia", action="store_true",
                   help="o banco de DASH_DB_PATH é uma cópia com contratos: a prova roda as migrações e cria os "
                        "usuários de teste nela (sem isto, banco que já tem contrato é recusado)")
    args = p.parse_args(argv)
    try:
        servidor = subir(porta=args.porta, dist=comum.absoluto(args.dist) if args.dist else None,
                         com_frontend=not args.sem_frontend, copia=args.copia)
    except comum.Recusa as e:
        print(f"RECUSADO: {e}", file=sys.stderr)
        return 2
    d = servidor.dados
    print(f"\nservidor de prova no ar: {servidor.base}" + ("" if d["frontend"] else " (só a API)"))
    print("  entrar como: " + ", ".join(d["usuarios"].values()))
    print(f"  senha (a mesma para os três): no arquivo {d['senha']}")
    print(f"  e-mails enviados caem em: {servidor.arquivos['correio']}")
    print(f"  retratos e capturas saem em: {d['saida']}")
    print(f"  log: {servidor.arquivos['log']}")
    print("Ctrl+C derruba (em segundo plano: kill no processo deste roteiro).", flush=True)

    def _parar(*_):
        raise KeyboardInterrupt

    # rodando em segundo plano o Ctrl+C nao chega: o `kill` (SIGTERM) derruba do mesmo jeito, sem deixar o backend
    signal.signal(signal.SIGTERM, _parar)
    try:
        servidor.processo.wait()
        print(f"o servidor de prova parou sozinho (código {servidor.processo.returncode}); fim do log:\n"
              + _fim_do_log(servidor.arquivos["log"]), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        servidor.encerrar()


if __name__ == "__main__":
    sys.exit(main())
