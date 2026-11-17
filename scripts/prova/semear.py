"""Prepara o banco da prova (issue #702). Quem chama e' o `servidor.py`, com o Python do backend:

  - roda as migracoes;
  - cria um usuario de teste por perfil (`prova-<perfil>@exemplo.com.br`), com a senha lida de um arquivo;
  - em banco NOVO (sem contrato nenhum), aplica o cadastro de `DASH_CADASTRO_DIR` e carrega o historico de
    `medicoes/<obra>.csv`, pelos mesmos comandos que o dono usa (`app.cli cadastro aplicar|carregar-medicoes`).

Numa copia do banco so' entram os usuarios de teste: o cadastro e as medicoes sao os que a copia ja' tem.
Nada de SQL solto aqui: o banco da prova nasce pelas mesmas portas da producao, entao acompanha as migracoes.

Uso (o servidor monta): python semear.py <arquivo-da-senha> [--redefinir]
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comum  # noqa: E402

from app import auth, cli, db  # noqa: E402

NOMES = {"admin": "Administração de prova", "engenharia": "Engenharia de prova", "diretoria": "Diretoria de prova"}


def main(argv: list) -> int:
    senha = Path(argv[0]).read_text(encoding="utf-8").strip()
    redefinir = "--redefinir" in argv[1:]
    # as mesmas recusas do servidor, para este arquivo nao servir de atalho para o banco padrao
    comum.banco_de_prova()
    cadastro = comum.cadastro_de_prova()

    conn = db.get_conn()
    try:
        db.migrate(conn)
        novo = conn.execute("SELECT COUNT(*) FROM contratos").fetchone()[0] == 0
        for perfil in comum.PERFIS:
            email = comum.email_de_teste(perfil)
            achado = conn.execute("SELECT id FROM usuarios WHERE email=?", (email,)).fetchone()
            if achado is None:
                auth.criar_usuario(conn, NOMES[perfil], email, senha, perfil)
                print(f"usuário de teste criado: {email} ({perfil})")
            elif redefinir:
                auth.redefinir_senha(conn, None, achado["id"], senha)
                print(f"usuário de teste já existia, senha redefinida: {email}")
    finally:
        conn.close()

    if not novo:
        print("banco com contratos: é uma cópia, o cadastro não foi aplicado")
        return 0
    admin = comum.email_de_teste("admin")
    print(f"banco novo: aplicando o cadastro de {cadastro.name}/")
    if cli.main(["cadastro", "aplicar", "--raiz", str(cadastro), "--usuario", admin]) != 0:
        return 1
    for csv in sorted((cadastro / "medicoes").glob("*.csv")):
        if cli.main(["cadastro", "carregar-medicoes", str(csv), "--usuario", admin]) != 0:
            return 1
    return 0


if __name__ == "__main__":
    if os.environ.get("DASH_DEV") != "1":
        sys.exit("semear.py só roda pelo servidor de prova (scripts/prova/servidor.py).")
    sys.exit(main(sys.argv[1:]))
