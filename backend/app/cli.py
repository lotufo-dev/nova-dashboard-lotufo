import argparse
import getpass
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from app import (auth, cadastro_aplicar, cadastro_arquivos, carga_medicoes, conciliacao, correcao_medicoes, db,
                 documentos, instalacao, legado)

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
        for aviso in li.get("avisos", []):
            print(f"    AVISO: {aviso}")
    print("Total: " + ", ".join(f"{c} {n}" for c, n in rel["totais"].items()))
    a = rel["avisos_nf"]
    if a["janela"] or a["nao_encontrada"]:
        print(f"Avisos de NF: {a['janela']} linhas sem NF por janela, {a['nao_encontrada']} com NF não encontrada")


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


def _corrigir_medicoes(args) -> int:
    """`cadastro corrigir-medicoes <arquivo.yaml> [--ensaio] --usuario <e-mail>`: corrige medições existentes
    (cancelar, reabrir, trocar tipo, ligar/desligar NF, protocolar, estado), numa transação só. O ensaio executa
    tudo e desfaz no fim."""
    if not args.arquivo:
        print("`cadastro corrigir-medicoes` exige o arquivo .yaml com as operações")
        return 1
    caminho = Path(args.arquivo)
    if not caminho.is_file():
        print(f"Arquivo não encontrado: {caminho}")
        return 1
    if not args.usuario:
        print("`cadastro corrigir-medicoes` exige --usuario (e-mail de quem aplica)")
        return 1
    try:
        operacoes = correcao_medicoes.ler(caminho)
    except correcao_medicoes.ArquivoInvalido as e:
        print(f"Arquivo recusado, nada foi lido: {e}")
        return 1
    conn = db.get_conn()
    try:
        if not args.ensaio:
            db.migrate(conn)
        u = conn.execute("SELECT id FROM usuarios WHERE email=? AND ativo=1", (args.usuario,)).fetchone()
        if u is None:
            print(f"Usuário não encontrado ou inativo: {args.usuario}")
            return 1
        try:
            rel = correcao_medicoes.executar(conn, u["id"], operacoes, ensaio=args.ensaio)
        except correcao_medicoes.CorrecaoRecusada as e:
            print(f"Recusado, nada foi gravado: {e}")
            _relatorio_correcao(e.relatorio)
            return 1
        except sqlite3.OperationalError as e:
            print("Recusado, nada foi gravado: o banco está ocupado por outra gravação; rode de novo em instantes"
                  if "locked" in str(e) or "busy" in str(e) else f"Banco ilegível, nada foi gravado: {db.db_path()}")
            return 1
        except sqlite3.DatabaseError:
            print(f"Banco ilegível, nada foi gravado: {db.db_path()}")
            return 1
    finally:
        conn.close()
    print(f"ENSAIO (nada foi gravado): {caminho.name}" if rel["ensaio"] else f"GRAVADO: {caminho.name}")
    _relatorio_correcao(rel)
    return 1 if rel["erros"] else 0


def _relatorio_correcao(rel: dict) -> None:
    for i in rel["itens"]:
        rotulo = f"  {i['n']}. {i['operacao'] or '?'}" + (f" {i['alvo']}" if i["alvo"] else "")
        if i["situacao"] == "erro":
            print(f"{rotulo}: ERRO: {i['erro']}")
            continue
        estado = f" [{i['antes']} → {i['depois']}]" if i["antes"] and i["antes"] != i["depois"] else ""
        print(f"{rotulo}: {i['situacao']}{estado}")
        for d in i["detalhes"]:
            print(f"     {d}")
    print(f"Total: feito {rel['feitos']}, já feito {rel['ja_feitos']}, erro {rel['erros']}")


def _cadastro(args) -> int:
    if args.acao == "carregar-medicoes":
        return _carregar_medicoes(args)
    if args.acao == "corrigir-medicoes":
        return _corrigir_medicoes(args)
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
        if not instalacao.ligada():        # issue #417: a copia nao fala com o RM
            print(instalacao.MSG_RM)
            return 1
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


def _instalacao(args) -> int:
    """`instalacao gerar-chave --saida <pasta>` e `instalacao assinar --chave <privada> --maquina <nome> --saida
    <arquivo>` (issue #417): rodam no Mac do dono. A chave privada nunca vai ao servidor nem ao repositório; o servidor
    recebe só o arquivo assinado (runbook, "Instalação assinada"). `instalacao verificar [--arquivo <arquivo>]` roda no
    servidor (o deploy chama)."""
    if args.acao == "verificar":
        # Issue #417: o deploy roda isto com o codigo NOVO, depois do build e antes de parar a producao; sem
        # "autorizada" ele para ali, antes de migrar o banco. Sem o atalho do dev e sem caminho nem maquina na saida.
        r = instalacao.conferir_caminho(Path(args.arquivo) if args.arquivo else instalacao.caminho_arquivo())
        if r["instalacao"] == instalacao.AUTORIZADA:
            print("Instalação autorizada para esta máquina.")
            return 0
        print(f"Instalação NÃO autorizada (motivo: {r['motivo']}).")
        return 1
    if not args.saida:
        print(f"`instalacao {args.acao}` exige --saida")
        return 1
    if args.acao == "gerar-chave":
        try:
            privada, publica = instalacao.gerar_chave(Path(args.saida))
        except FileExistsError as e:
            print(f"Recusado, nada foi gravado: já existe {e.args[0]}")
            return 1
        print(f"Chave privada: {privada} (só sua: guarde uma cópia cifrada fora desta máquina; nunca no servidor "
              "nem no repositório)")
        print(f"Chave pública: {publica}")
        print(publica.read_text(encoding="ascii"), end="")
        return 0
    if not args.chave or not args.maquina:
        print("`instalacao assinar` exige --chave <chave privada> e --maquina <nome da máquina>")
        return 1
    caminho = Path(args.chave)
    if not caminho.is_file():
        print(f"Chave não encontrada: {caminho}")
        return 1
    try:
        try:
            chave = instalacao.ler_chave_privada(caminho)
        except TypeError:           # chave cifrada: pede a senha sem eco
            chave = instalacao.ler_chave_privada(caminho, getpass.getpass("Senha da chave: ").encode("utf-8"))
    except (ValueError, TypeError):
        print(f"Recusado, nada foi gravado: {caminho} não é uma chave privada Ed25519 (ou a senha não confere)")
        return 1
    if not instalacao.e_a_chave_embutida(chave):
        print("Recusado, nada foi gravado: esta chave não é a que o código confere (app/instalacao.py); o servidor "
              "recusaria o arquivo (motivo assinatura).")
        return 1
    saida = Path(args.saida)
    if saida.exists():          # nunca por cima de outro arquivo (a propria chave, por engano)
        print(f"Recusado, nada foi gravado: já existe {saida}")
        return 1
    try:
        conteudo = instalacao.assinar(chave, args.maquina)
    except ValueError as e:
        print(f"Recusado, nada foi gravado: {e}")
        return 1
    saida.parent.mkdir(parents=True, exist_ok=True)
    with open(saida, "xb") as f:
        f.write(conteudo)
    print(f"Arquivo assinado para a máquina {args.maquina.strip()}: {saida}")
    return 0


def _dono(args) -> int:
    """`dono gerar-chave --saida <pasta>`: roda no Mac do dono (a privada nunca vai ao servidor)."""
    from pyrage import x25519
    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)
    privada, publica = saida / "chave-privada-dono.txt", saida / "chave-publica-dono.txt"
    if privada.exists() or publica.exists():
        print("Já existe um par de chaves nessa pasta; escolha outra pasta.", file=sys.stderr)
        return 1
    identidade = x25519.Identity.generate()
    privada.write_text(f"{identidade}\n", encoding="utf-8")
    os.chmod(privada, 0o600)
    publica.write_text(f"{identidade.to_public()}\n", encoding="utf-8")
    print(f"Chave pública (leve só esta ao servidor): {publica}\nChave privada (guarde no cofre, nunca no servidor): {privada}")
    return 0


def _sentinela(args) -> int:
    """`sentinela antes-da-456 --banco <db>` (issue #478): com o serviço parado e antes de voltar o código para um
    commit anterior à #456, passa o ponto de leitura da sentinela para a auditoria e tira a tabela, os gatilhos e a
    linha da 063 (docs/runbook.md, "Rollback para um commit anterior à issue #456"). Não roda as migrações."""
    from app import sentinela
    banco = Path(args.banco)
    if not banco.is_file():
        print(f"Banco não encontrado: {banco}")
        return 1
    anterior = os.environ.get("DASH_DB_PATH")
    os.environ["DASH_DB_PATH"] = str(banco)
    try:
        conn = db.get_conn()
        try:
            r = sentinela.antes_da_456(conn)
        finally:
            conn.close()
    finally:
        if anterior is None:
            os.environ.pop("DASH_DB_PATH", None)
        else:
            os.environ["DASH_DB_PATH"] = anterior
    if r["gravado"]:
        print(f"Ponto da sentinela gravado na auditoria: registro {r['ponto']}.")
    elif r["ponto"] is not None:
        print(f"Ponto da sentinela já estava na auditoria: registro {r['ponto']}.")
    print(f"sentinela_ponto: {r['tabela']} migracao 063: {r['migracao']}")
    return 0 if r["tabela"] == 0 and r["migracao"] == 0 else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    ca = sub.add_parser("criar-admin")
    ca.add_argument("--nome", required=True)
    ca.add_argument("--email", required=True)
    cad = sub.add_parser("cadastro")
    cad.add_argument("acao", choices=["validar", "aplicar", "carregar-medicoes", "corrigir-medicoes"])
    cad.add_argument("arquivo", nargs="?", help="CSV da obra (<obra>.csv) em `carregar-medicoes`; YAML das "
                                                "operações em `corrigir-medicoes`")
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
    ins = sub.add_parser("instalacao", help="chave do dono e arquivo assinado da instalação (no Mac do dono)")
    ins.add_argument("acao", choices=["gerar-chave", "assinar", "verificar"])
    ins.add_argument("--saida", help="pasta das chaves (gerar-chave) ou arquivo assinado (assinar)")
    ins.add_argument("--arquivo", help="arquivo a conferir (só em `verificar`; padrão: o da subida do servidor)")
    ins.add_argument("--chave", help="chave privada (só em `assinar`)")
    ins.add_argument("--maquina", help="nome da máquina, o COMPUTERNAME do servidor (só em `assinar`)")
    itg = sub.add_parser("integridade", help="registro do último deploy (o deploy.ps1 chama)")
    itg.add_argument("acao", choices=["registrar"])
    itg.add_argument("--raiz", required=True, help="raiz dos dados, onde fica o deploy-atual.json")
    sen = sub.add_parser("sentinela", help="rollback para antes da issue #456 (o deploy.ps1 chama; ver o runbook)")
    sen.add_argument("acao", choices=["antes-da-456"])
    sen.add_argument("--banco", required=True, help="banco da produção, com o serviço parado")
    dn = sub.add_parser("dono", help="cópia cifrada para a chave do dono")
    dn.add_argument("acao", choices=["gerar-chave"])
    dn.add_argument("--saida", required=True, help="pasta onde gravar o par de chaves")
    for nome, ajuda in (("desbloquear", "destrava a conta bloqueada por senhas erradas"),
                        ("redefinir-senha", "grava senha nova (pedida sem eco) e derruba as sessões")):
        sub.add_parser(nome, help=ajuda).add_argument("email")
    args = p.parse_args(argv)
    if args.cmd in ("desbloquear", "redefinir-senha"):
        return _conta(args)
    if args.cmd == "dono":
        return _dono(args)
    if args.cmd == "sentinela":
        return _sentinela(args)
    if args.cmd == "documentos":
        return _documentos(args)
    if args.cmd == "instalacao":
        return _instalacao(args)
    if args.cmd == "integridade":
        from app import integridade
        try:
            r = integridade.registrar_deploy(Path(args.raiz))
        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            print(f"Registro do deploy NÃO gravado: {e}")
            return 1
        print(f"Registro do deploy gravado: commit {r['commit'][:7]}, {len(r['dist'])} arquivos no dist.")
        return 0
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
