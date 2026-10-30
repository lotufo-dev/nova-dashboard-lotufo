import argparse
import getpass
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from app import auth, cadastro_aplicar, cadastro_arquivos, carga_medicoes, conciliacao, db, documentos, legado

REPOSITORIO = Path(__file__).resolve().parent.parent.parent
EXEMPLO = REPOSITORIO / "cadastro-exemplo"


def raiz_padrao() -> Path:
    """Raiz do cadastro: `DASH_CADASTRO_DIR` (o cadastro real mora fora do repositório) ou, sem ela, o
    `cadastro-exemplo/` fictício do próprio repositório. Lida a cada chamada, não ao importar o módulo."""
    return Path(os.environ.get("DASH_CADASTRO_DIR") or EXEMPLO)


# Consultas do RM com as notas e baixas de jun/2021 a set/2024 (cadastradas em 2026-09-25, RM Fluxus)
CONSULTA_NF_ANTIGA, CONSULTA_BAIXA_ANTIGA = "DASH12", "DASH13"


def _legado(args) -> int:
    """`legado remapear [--ensaio]`: estados do legado para a maquina do espelho (bloco 3). Roda `db.migrate`
    ANTES, para o remapeamento valer com o banco ja' na migracao 021 e com o servico ainda parado."""
    conn = db.get_conn()
    try:
        db.migrate(conn)
        u = conn.execute("SELECT id FROM usuarios WHERE email=? AND ativo=1", (args.usuario,)).fetchone()
        if u is None:
            print(f"Usuário não encontrado ou inativo: {args.usuario}")
            return 1
        rel = legado.remapear(conn, u["id"], ensaio=args.ensaio)
    finally:
        conn.close()
    print("ENSAIO (nada foi gravado)" if rel["ensaio"] else "APLICADO")
    for chave in ("nf_emitida_para_protocolada", "prevista_sem_valor_cancelada", "recebida_mantida"):
        print(f"  {chave}: {rel[chave]}")
    return 0


def _documentos(args) -> int:
    """`documentos importar <pasta> [--ensaio]`: carga das certidoes vigentes de uma pasta LOCAL (bloco 4).
    O sistema nao le SharePoint: quem roda baixa a biblioteca `Certidoes` para uma pasta antes."""
    pasta = Path(args.pasta)
    if not pasta.is_dir():
        print(f"Pasta não encontrada: {pasta}")
        return 1
    conn = db.get_conn()
    try:
        db.migrate(conn)
        u = conn.execute("SELECT id FROM usuarios WHERE email=? AND ativo=1", (args.usuario,)).fetchone()
        if u is None:
            print(f"Usuário não encontrado ou inativo: {args.usuario}")
            return 1
        rel = documentos.importar_pasta(conn, u["id"], pasta, ensaio=args.ensaio)
    finally:
        conn.close()
    print("ENSAIO (nada foi gravado)" if rel["ensaio"] else "APLICADO")
    for chave in ("gravadas", "repetidas", "vencidas", "positivas", "sem_leitura"):
        print(f"  {chave}: {len(rel[chave])}")
        for item in rel[chave]:
            print(f"    - {item}")
    return 0


def _conta(args) -> int:
    """`desbloquear <email>` e `redefinir-senha <email>` (A-05, 10/10/2026): a saida para quando o unico
    administrador se tranca e nao ha ninguem para usar a tela. Auditoria sem autor (usuario_id nulo)."""
    nova = getpass.getpass("Senha nova: ") if args.cmd == "redefinir-senha" else None
    conn = db.get_conn()
    try:
        db.migrate(conn)
        u = conn.execute("SELECT id FROM usuarios WHERE email=?", (args.email.lower(),)).fetchone()
        if u is None:
            print(f"Usuário não encontrado: {args.email}")
            return 1
        try:
            if nova is None:
                auth.desbloquear(conn, None, u["id"])
            else:
                auth.redefinir_senha(conn, None, u["id"], nova)
        except ValueError as e:
            print(f"Nada foi gravado: {e}")
            return 1
    finally:
        conn.close()
    print("Usuário desbloqueado." if nova is None else "Senha redefinida; as sessões abertas desse usuário caíram.")
    return 0


def _commit(raiz: Path) -> str | None:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=raiz, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() or None if r.returncode == 0 else None


def _relatorio(rel: dict) -> None:
    print("ENSAIO (nada foi gravado)" if rel["ensaio"] else "APLICADO")
    for nome in ("orgaos", "entidades", "contratos", "instrumentos", "pleitos", "cronograma", "geral", "espelho",
                 "frc"):
        r = rel[nome]
        print(f"  {nome}: {len(r['criados'])} criados, {len(r['alterados'])} alterados, {r['iguais']} iguais")
        for rotulo in r["criados"]:
            print(f"    + {rotulo}")
        for rotulo in r["alterados"]:
            print(f"    ~ {rotulo}")
    for aviso in rel["avisos"]:
        print(f"  AVISO: {aviso}")


def _de_outro_cadastro(conn, cad: dict) -> list[str]:
    """O que o banco já tem e o cadastro dado não conhece: contratos, órgãos e entidades (a empresa própria
    semeada pela migração 006 ainda não tem chave e não conta)."""
    achados = []
    for rotulo, sql, conhecidos in (
            ("contratos", "SELECT numero_instrumento FROM contratos", {c["numero_instrumento"] for c in cad["contratos"]}),
            ("órgãos", "SELECT chave FROM orgaos", {o["chave"] for o in cad["orgaos"]}),
            ("entidades", "SELECT chave FROM entidades WHERE chave IS NOT NULL", {e["chave"] for e in cad["entidades"]})):
        n = sum(1 for r in conn.execute(sql) if r[0] not in conhecidos)
        if n:
            achados.append(f"{n} {rotulo}")
    return achados


def _carregar_medicoes(args) -> int:
    """`cadastro carregar-medicoes <obra>.csv --ensaio` (issue #258): confere o histórico de medições de uma
    obra contra o banco e imprime o relatório, sem gravar. Sem `--ensaio` (issue #259), com o OK do Leo no
    relatório: cria as medições que faltam."""
    if not args.arquivo:
        print("`cadastro carregar-medicoes` exige o arquivo <obra>.csv")
        return 1
    caminho = Path(args.arquivo)
    if not caminho.is_file():
        print(f"Arquivo não encontrado: {caminho}")
        return 1
    if not args.ensaio:
        return _gravar_medicoes(args, caminho)
    banco = db.db_path().resolve()
    if not banco.is_file():
        print(f"Banco não encontrado: {banco}")
        return 1
    try:
        # Somente leitura: o ensaio não pode gravar nem o modo do diário do banco
        conn = sqlite3.connect(f"{banco.as_uri()}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        print(f"Banco não encontrado: {banco}")
        return 1
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN")       # uma foto só do banco para o relatório inteiro
        rel = carga_medicoes.ensaiar(conn, caminho)
    except carga_medicoes.CsvInvalido as e:
        print(f"CSV recusado, nada foi lido: {e}")
        return 1
    except sqlite3.DatabaseError:
        print(f"Banco ilegível ou sem as tabelas do sistema: {banco}")
        return 1
    finally:
        if conn.in_transaction:
            conn.rollback()
        conn.close()
    print(f"ENSAIO (nada foi gravado): {rel['contrato']} ({caminho.name})")
    _relatorio_carga(rel)
    return 0


def _relatorio_carga(rel: dict) -> None:
    for li in rel["linhas"]:
        rotulo = f"linha {li['linha']}: nº {li['numero']} {li['tipo']}"
        if li.get("competencia"):
            rotulo += f" {li['competencia']}"
        print(f"  {rotulo}: {li['categoria']}" + (f" ({li['detalhe']})" if li["detalhe"] else "")
              + (f" -> {li['acao']}" if li.get("acao") else ""))
    print("Total: " + ", ".join(f"{c} {n}" for c, n in rel["totais"].items()))


def _gravar_medicoes(args, caminho: Path) -> int:
    if not args.usuario:
        print("Gravar exige --usuario (e-mail de quem aplica). Para só ver o relatório, use --ensaio.")
        return 1
    conn = db.get_conn()
    try:
        db.migrate(conn)
        u = conn.execute("SELECT id FROM usuarios WHERE email=? AND ativo=1", (args.usuario,)).fetchone()
        if u is None:
            print(f"Usuário não encontrado ou inativo: {args.usuario}")
            return 1
        try:
            rel = carga_medicoes.gravar(conn, u["id"], caminho)
        except carga_medicoes.CsvInvalido as e:
            print(f"CSV recusado, nada foi gravado: {e}")
            return 1
        except carga_medicoes.CargaRecusada as e:
            print(f"Recusado, nada foi gravado: {e}")
            return 1
        except sqlite3.OperationalError as e:
            # outro escritor (a sincronizacao do RM, a tela) segurando o banco: a transacao foi desfeita
            print("Recusado, nada foi gravado: o banco está ocupado por outra gravação; rode de novo em instantes"
                  if "locked" in str(e) or "busy" in str(e) else f"Banco ilegível, nada foi gravado: {db.db_path()}")
            return 1
        except sqlite3.DatabaseError:
            print(f"Banco ilegível, nada foi gravado: {db.db_path()}")
            return 1
        except ValueError as e:
            # recusa de regra no meio da carga (ex.: NF vinculada por outra pessoa ao mesmo tempo)
            print(f"Recusado, nada foi gravado: {e}")
            return 1
    finally:
        conn.close()
    print(f"GRAVADO: {rel['contrato']} ({caminho.name}), {rel['criadas']} medição(ões) criada(s)")
    _relatorio_carga(rel)
    return 0


def _cadastro(args) -> int:
    if args.acao == "carregar-medicoes":
        return _carregar_medicoes(args)
    if args.arquivo:
        print(f"`cadastro {args.acao}` não recebe arquivo (use `cadastro carregar-medicoes {args.arquivo} --ensaio`)")
        return 1
    raiz = Path(args.raiz) if args.raiz else raiz_padrao()
    print(f"Cadastro lido de: {raiz}" + (" (exemplo fictício)" if raiz.resolve() == EXEMPLO.resolve() else ""))
    try:
        cad = cadastro_arquivos.preparar(raiz)
    except cadastro_arquivos.CadastroInvalido as e:
        print(f"Cadastro inválido ({len(e.erros)} erro(s)):")
        for erro in e.erros:
            print(f"  - {erro}")
        return 1
    n = len(cad["contratos"])
    if args.acao == "validar":
        ativas = sum(1 for e in cad["espelho"] if e["situacao"] == "ativa")
        print(f"Cadastro válido: {len(cad['orgaos'])} órgão(s), {len(cad['entidades'])} entidade(s), "
              f"{n} contrato{'s' if n != 1 else ''}, espelho: {len(cad['espelho'])} regra(s) "
              f"({ativas} ativa{'s' if ativas != 1 else ''}){', geral.yaml' if cad['geral'] else ''}.")
        for aviso in cad["avisos"]:
            print(f"  AVISO: {aviso}")
        return 0
    conn = db.get_conn()
    try:
        db.migrate(conn)
        u = conn.execute("SELECT id FROM usuarios WHERE email=? AND ativo=1", (args.usuario,)).fetchone()
        if u is None:
            print(f"Usuário não encontrado ou inativo: {args.usuario}")
            return 1
        if raiz.resolve() == EXEMPLO.resolve():
            # Sem DASH_CADASTRO_DIR a raiz cai no exemplo: esquecer a variável na produção aplicaria obras
            # inventadas (e o CNPJ da empresa própria) por cima do cadastro real.
            de_fora = _de_outro_cadastro(conn, cad)
            if de_fora:
                print(f"Recusado, nada foi gravado: este banco já tem {', '.join(de_fora)} que não são do cadastro de "
                      "exemplo (fictício). Defina DASH_CADASTRO_DIR (ou use --raiz) com o cadastro real.")
                return 1
        try:
            rel = cadastro_aplicar.aplicar(conn, u["id"], cad, ensaio=args.ensaio, commit_hash=_commit(raiz))
        except ValueError as e:
            print(f"Cadastro recusado, nada foi gravado: {e}")
            return 1
        except sqlite3.IntegrityError as e:
            campo = str(e).partition("UNIQUE constraint failed: ")[2] or str(e)
            print(f"Cadastro recusado, nada foi gravado: o banco já tem outro registro com o mesmo valor em {campo} "
                  "(este banco recebeu outro cadastro antes? confira a pasta lida acima).")
            return 1
    finally:
        conn.close()
    _relatorio(rel)
    return 0


def _conciliacao(args) -> int:
    """`conciliacao historica|antiga [--ensaio]`: liga as notas do RM as medicoes antigas sem nota (2026-09-25).
    `antiga` le as notas e baixas de jun/2021 a set/2024 direto do RM (consultas DASH12/DASH13)."""
    if args.acao == "corte":
        if not args.data:
            print("`conciliacao corte` exige --data AAAA-MM-DD")
            return 1
        conn = db.get_conn()
        try:
            db.migrate(conn)
            u = conn.execute("SELECT id FROM usuarios WHERE email=? AND ativo=1", (args.usuario,)).fetchone()
            if u is None:
                print(f"Usuário não encontrado ou inativo: {args.usuario}")
                return 1
            rel = conciliacao.cortar(conn, u["id"], args.data, ensaio=args.ensaio)
        finally:
            conn.close()
        print("ENSAIO (nada foi gravado)" if rel["ensaio"] else "APLICADO")
        print(f"  corte em {rel['data']}: {rel['fechadas']} medições fechadas como recebidas "
              f"({rel['com_nota']} com nota ligada), R$ {rel['valor_centavos'] / 100:,.2f} cheio")
        for obra, n in rel["por_obra"].items():
            print(f"    {obra}: {n}")
        return 0
    antigas = None
    if args.acao == "antiga":
        from app import rm
        cliente = rm.de_ambiente()
        if cliente is None:
            print("RM nao configurado: defina DASH_RM_URL, DASH_RM_USUARIO e DASH_RM_SENHA_ARQUIVO")
            return 1
        antigas = (cliente.consultar(CONSULTA_NF_ANTIGA), cliente.consultar(CONSULTA_BAIXA_ANTIGA))
        print(f"RM: {len(antigas[0])} notas e {len(antigas[1])} baixas antigas")
    conn = db.get_conn()
    try:
        db.migrate(conn)
        u = conn.execute("SELECT id FROM usuarios WHERE email=? AND ativo=1", (args.usuario,)).fetchone()
        if u is None:
            print(f"Usuário não encontrado ou inativo: {args.usuario}")
            return 1
        rel = conciliacao.conciliar(conn, u["id"], ensaio=args.ensaio, antigas=antigas)
    finally:
        conn.close()
    print("ENSAIO (nada foi gravado)" if rel["ensaio"] else "APLICADO")
    for chave in ("legado_sem_nota", "ligadas", "recebidas", "ligadas_em_aberto", "ambiguas", "sem_nota",
                  "antes_do_rm", "obra_sem_centro", "sem_protocolo_ou_valor"):
        print(f"  {chave}: {rel[chave]}")
    for obra, cont in rel["por_obra"].items():
        print(f"    {obra}: " + ", ".join(f"{k} {v}" for k, v in sorted(cont.items())))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    ca = sub.add_parser("criar-admin")
    ca.add_argument("--nome", required=True)
    ca.add_argument("--email", required=True)
    cad = sub.add_parser("cadastro")
    cad.add_argument("acao", choices=["validar", "aplicar", "carregar-medicoes"])
    cad.add_argument("arquivo", nargs="?", help="CSV da obra (<obra>.csv), só em `carregar-medicoes`")
    cad.add_argument("--raiz", help="pasta do cadastro (padrão: DASH_CADASTRO_DIR, ou cadastro-exemplo/)")
    cad.add_argument("--usuario", help="e-mail de quem aplica (obrigatório em `aplicar`)")
    cad.add_argument("--ensaio", action="store_true", help="mostra o que mudaria e não grava")
    leg = sub.add_parser("legado", help="remapeia os estados do legado (bloco 3)")
    leg.add_argument("acao", choices=["remapear"])
    leg.add_argument("--usuario", required=True, help="e-mail de quem aplica")
    leg.add_argument("--ensaio", action="store_true", help="mostra o relatório e desfaz")
    doc = sub.add_parser("documentos", help="carga das certidões vigentes de uma pasta local (bloco 4)")
    doc.add_argument("acao", choices=["importar"])
    doc.add_argument("pasta", help="pasta local com os PDFs (lida recursivamente)")
    doc.add_argument("--usuario", required=True, help="e-mail de quem aplica")
    doc.add_argument("--ensaio", action="store_true", help="mostra o relatório e desfaz")
    con = sub.add_parser("conciliacao", help="liga notas do RM as medicoes antigas sem nota")
    con.add_argument("acao", choices=["historica", "antiga", "corte"])
    con.add_argument("--data", help="data do corte (AAAA-MM-DD), só em `corte`")
    con.add_argument("--usuario", required=True, help="e-mail de quem aplica")
    con.add_argument("--ensaio", action="store_true", help="mostra o relatório e desfaz")
    for nome, ajuda in (("desbloquear", "destrava a conta bloqueada por senhas erradas"),
                        ("redefinir-senha", "grava senha nova (pedida sem eco) e derruba as sessões")):
        sub.add_parser(nome, help=ajuda).add_argument("email")
    args = p.parse_args(argv)
    if args.cmd in ("desbloquear", "redefinir-senha"):
        return _conta(args)
    if args.cmd == "documentos":
        return _documentos(args)
    if args.cmd == "cadastro":
        if args.acao == "aplicar" and not args.usuario:
            p.error("`cadastro aplicar` exige --usuario <e-mail>")
        return _cadastro(args)
    if args.cmd == "legado":
        return _legado(args)
    if args.cmd == "conciliacao":
        return _conciliacao(args)
    senha = getpass.getpass("Senha do administrador: ")
    conn = db.get_conn()
    try:
        db.migrate(conn)
        uid = auth.criar_usuario(conn, args.nome, args.email, senha, "admin")
    finally:
        conn.close()
    print(f"Administrador criado (id={uid}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
