"""Medido por grupo da planilha de medicao (issue #490): grava e consulta as leituras.

Cada xlsx lido e' um evento em `medicao_grupos` (migracao 068), ligado a versao da planilha/carta quando veio do
anexo, sem versao quando veio da carga de uma pasta (`python -m app.cli medicoes planilhas`). A soma dos grupos tem
de bater com o valor pedido da medicao (`valor_protocolado_centavos`) com tolerancia de um real; a leitura recusada
no anexo fica registrada com o motivo, para a tela avisar "planilha não lida". Vale a leitura mais nova.
So' a medicao de execucao tem leitura por grupo (reajuste e projeto nao entram). Quem le o xlsx e' a
`leitura_planilha_medicao`; aqui so' se grava e se consulta.
"""
import re
from pathlib import Path

from app import arquivos, auditoria, db
from app import leitura_planilha_medicao as leitura
from app.medicoes import nome_medicao

ACAO = "medicao.grupos"
PREFIXO_AVISO = "Planilha não lida: "
# "01ª", "15ª Medição", "3º": o nº da medicao no nome do arquivo da carga (o "(05_2026)" ao lado nao tem ª nem º)
_NUMERO_NO_NOME = re.compile(r"(?<!\d)(\d{1,3})\s*[ªº°]")
COLUNAS_ITEM = ("item", "codigo", "descricao", "unidade", "quantidade_contratada", "quantidade_medida",
                "quantidade_acumulada", "preco_unitario_centavos", "valor_medido_centavos", "valor_acumulado_centavos")


def cadastro_de_custo(conn, contrato_id: int) -> list[dict] | None:
    """Os grupos do cadastro de custo da obra (`itens_planilha`, issue #489), na ordem do yaml; None sem cadastro.
    A #489 ainda nao entrou: ate' la' toda obra le pelos titulos de grupo da propria planilha. Quando entrar, este e'
    o unico ponto a ligar (a leitura ja' agrupa por prefixo de `itens_planilha`)."""
    return None


def conferir_medicao(m) -> None:
    """Recusa (ValueError) a medicao que nao tem leitura por grupo: reajuste, projeto ou sem valor pedido."""
    if m["tipo"] != "execucao":
        raise ValueError(f"{nome_medicao(m['numero'], m['tipo'])}: só a medição de execução tem leitura por grupo")
    if m["valor_protocolado_centavos"] is None:
        raise ValueError(f"{nome_medicao(m['numero'], m['tipo'])} não tem valor pedido para conferir a planilha")


def _ja_lida(conn, medicao_id: int, sha: str, planilha_id: int | None):
    return conn.execute(
        "SELECT id, total_centavos FROM medicao_grupos WHERE medicao_id=? AND sha256=? AND "
        "COALESCE(planilha_id, 0)=? AND situacao='lida'", (medicao_id, sha, planilha_id or 0)).fetchone()


def _gravar(conn, usuario_id, m, sha: str, origem: str, planilha_id, arquivo, situacao: str, motivo,
            lido: dict | None, total, pedido) -> int:
    cur = conn.execute(
        "INSERT INTO medicao_grupos (medicao_id, planilha_id, sha256, arquivo, origem, situacao, motivo, grupo_por, "
        "total_centavos, pedido_centavos, usuario_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (m["id"], planilha_id, sha, arquivo, origem, situacao, motivo, lido["grupo_por"] if lido else None,
         total, pedido, usuario_id))
    lid = cur.lastrowid
    if lido:
        ordem = 0
        for g in lido["grupos"]:          # na ordem dos grupos: a consulta remonta a mesma ordem
            for it in g["itens"]:
                ordem += 1
                conn.execute(
                    f"INSERT INTO medicao_grupo_itens (leitura_id, ordem, grupo, {', '.join(COLUNAS_ITEM)}) "
                    f"VALUES (?,?,?,{','.join('?' * len(COLUNAS_ITEM))})",
                    (lid, ordem, g["nome"], *(it[k] for k in COLUNAS_ITEM)))
    auditoria.registrar(conn, usuario_id, ACAO, "medicao", m["id"], None, {
        "leitura_id": lid, "situacao": situacao, "origem": origem, "planilha_id": planilha_id, "sha256": sha,
        "total_centavos": total, "pedido_centavos": pedido, "motivo": motivo})
    return lid


def ler_e_registrar(conn, usuario_id: int | None, medicao_id: int, dados: bytes, *, origem: str,
                    planilha_id: int | None = None, arquivo: str | None = None, gravar_recusa: bool = False,
                    guardar_arquivo: bool = False, ensaio: bool = False) -> dict:
    """Le o xlsx e grava a leitura da medicao. Devolve {"situacao": "lida" | "repetida" | "recusada", "motivo",
    "total_centavos", "pedido_centavos", "diferenca_centavos", "leitura_id"}. A mesma planilha (sha256) na mesma
    versao nao se le duas vezes ("repetida"). A recusa so' se grava com `gravar_recusa` (o anexo: a tela avisa);
    na carga, so' se imprime. `guardar_arquivo` (a carga) grava o xlsx na pasta das planilhas so' quando a leitura
    vale (o anexo ja' foi gravado pela planilha/carta). A medicao que nao tem leitura por grupo levanta ValueError (nada se grava)."""
    m = conn.execute("SELECT * FROM medicoes WHERE id=?", (medicao_id,)).fetchone()
    conferir_medicao(m)
    sha, pedido = arquivos.sha_de(dados), m["valor_protocolado_centavos"]
    saida = {"situacao": "lida", "motivo": None, "total_centavos": None, "pedido_centavos": pedido,
             "diferenca_centavos": None, "leitura_id": None}
    ja = _ja_lida(conn, medicao_id, sha, planilha_id)
    if ja is not None:
        return {**saida, "situacao": "repetida", "leitura_id": ja["id"], "total_centavos": ja["total_centavos"],
                "diferenca_centavos": ja["total_centavos"] - pedido}
    lido = None
    try:
        lido = leitura.ler(dados, cadastro_de_custo(conn, m["contrato_id"]))
        saida.update(total_centavos=lido["total_centavos"], diferenca_centavos=lido["total_centavos"] - pedido)
        leitura.conferir_total(lido["total_centavos"], pedido)
    except leitura.PlanilhaRecusada as e:
        saida.update(situacao="recusada", motivo=str(e))
        lido = None
    if ensaio or (saida["situacao"] == "recusada" and not gravar_recusa):
        return saida
    if guardar_arquivo and saida["situacao"] == "lida":
        arquivo, _ = arquivos.gravar_bytes("planilhas", dados, "xlsx")     # pelo hash: repetir nao duplica
    with db.mutacao(conn):
        m = conn.execute("SELECT * FROM medicoes WHERE id=?", (medicao_id,)).fetchone()
        if saida["situacao"] == "lida":
            ja = _ja_lida(conn, medicao_id, sha, planilha_id)       # de novo, sob o lock
            if ja is not None:
                return {**saida, "situacao": "repetida", "leitura_id": ja["id"]}
        saida["leitura_id"] = _gravar(conn, usuario_id, m, sha, origem, planilha_id, arquivo, saida["situacao"],
                                      saida["motivo"], lido, saida["total_centavos"], pedido)
    return saida


def ler_anexo(conn, usuario_id: int, medicao_id: int, versao: int, dados: bytes) -> dict | None:
    """O xlsx anexado a versao da planilha/carta (registro ou revisao), lido depois de a versao estar gravada: a
    recusa nao impede o registro, fica gravada e volta como aviso. None na medicao sem leitura por grupo."""
    v = conn.execute("SELECT id, arquivo_planilha FROM medicao_planilhas WHERE medicao_id=? AND versao=?",
                     (medicao_id, versao)).fetchone()
    m = conn.execute("SELECT * FROM medicoes WHERE id=?", (medicao_id,)).fetchone()
    try:
        conferir_medicao(m)
    except ValueError:
        return None
    r = ler_e_registrar(conn, usuario_id, medicao_id, dados, origem="anexo", planilha_id=v["id"],
                        arquivo=v["arquivo_planilha"], gravar_recusa=True)
    return {"situacao": r["situacao"], "aviso": PREFIXO_AVISO + r["motivo"] if r["motivo"] else None}


def _filtro_vigente(conn, medicao_id: int) -> tuple[str, tuple]:
    """As leituras que valem: na medicao com planilha/carta, so' as da versao vigente (a revisao em PDF, ou ainda
    sem leitura, fica sem leitura: a da versao anterior nao representa mais o pedido); na medicao sem
    planilha/carta (historico), as da carga."""
    vigente = conn.execute("SELECT id FROM medicao_planilhas WHERE medicao_id=? ORDER BY versao DESC LIMIT 1",
                           (medicao_id,)).fetchone()
    if vigente is None:
        return "g.medicao_id=? AND g.planilha_id IS NULL", (medicao_id,)
    return "g.medicao_id=? AND g.planilha_id=?", (medicao_id, vigente["id"])


def situacao(conn, medicao_id: int) -> dict:
    """A leitura mais nova que vale: {"situacao": "sem_leitura" | "lida" | "recusada", "aviso"}."""
    onde, args = _filtro_vigente(conn, medicao_id)
    r = conn.execute(f"SELECT g.situacao, g.motivo FROM medicao_grupos g WHERE {onde} ORDER BY g.id DESC LIMIT 1",
                     args).fetchone()
    if r is None:
        return {"situacao": "sem_leitura", "aviso": None}
    return {"situacao": r["situacao"], "aviso": PREFIXO_AVISO + r["motivo"] if r["situacao"] == "recusada" else None}


def grupos(conn, medicao_id: int) -> dict:
    """O medido por grupo da leitura lida mais nova, com os itens, e a situacao da leitura mais nova (uma recusa
    depois da ultima lida volta como aviso, com os grupos da lida)."""
    onde, args = _filtro_vigente(conn, medicao_id)
    lida = conn.execute(
        "SELECT g.id, g.origem, g.planilha_id, p.versao, g.sha256, g.grupo_por, g.total_centavos, g.pedido_centavos, "
        "g.criado_em FROM medicao_grupos g LEFT JOIN medicao_planilhas p ON p.id=g.planilha_id "
        f"WHERE {onde} AND g.situacao='lida' ORDER BY g.id DESC LIMIT 1", args).fetchone()
    saida = {**situacao(conn, medicao_id), "leitura": dict(lida) if lida else None, "grupos": []}
    if lida is None:
        return saida
    itens = [(r["grupo"], {k: r[k] for k in COLUNAS_ITEM}) for r in conn.execute(
        f"SELECT grupo, {', '.join(COLUNAS_ITEM)} FROM medicao_grupo_itens WHERE leitura_id=? ORDER BY ordem",
        (lida["id"],))]
    saida["grupos"] = leitura.agrupar(itens, [])
    return saida


# --- carga de uma pasta (CLI) ------------------------------------------------------------------------------------

def numero_no_nome(nome: str) -> int | None:
    m = _NUMERO_NO_NOME.search(nome)
    return int(m.group(1)) if m else None


def carregar_pasta(conn, usuario_id: int | None, contrato_id: int, pasta: Path, ensaio: bool = False) -> list[dict]:
    """Um xlsx por medicao, o nº da medicao no nome do arquivo. Cada arquivo devolve {"arquivo", "medicao",
    "situacao" ("lida", "repetida", "recusada", "pulado"), "motivo", "total_centavos", "pedido_centavos",
    "diferenca_centavos"}. Arquivo que nao casa com medicao nenhuma e' listado e pulado, e tambem os varios arquivos
    com o mesmo nº (qual vale e' escolha de quem monta a pasta) e a medicao que ja' tem planilha/carta anexada (a
    leitura dela vem do anexo)."""
    saida = []
    caminhos = sorted(p for p in pasta.iterdir() if p.is_file() and not p.name.startswith("~$"))
    por_numero: dict[int, int] = {}
    for p in caminhos:
        n = numero_no_nome(p.name) if p.suffix.lower() == ".xlsx" else None
        if n is not None:
            por_numero[n] = por_numero.get(n, 0) + 1
    for caminho in caminhos:
        linha = {"arquivo": caminho.name, "medicao": None, "situacao": "pulado", "motivo": None,
                 "total_centavos": None, "pedido_centavos": None, "diferenca_centavos": None}
        saida.append(linha)
        if caminho.suffix.lower() != ".xlsx":
            linha["motivo"] = "não é .xlsx"
            continue
        numero = numero_no_nome(caminho.name)
        if numero is None:
            linha["motivo"] = "sem o nº da medição no nome (ex.: 15ª)"
            continue
        if por_numero[numero] > 1:
            linha["motivo"] = f"mais de um arquivo da medição nº {numero} na pasta: deixe só o que vale"
            continue
        m = conn.execute("SELECT * FROM medicoes WHERE contrato_id=? AND numero=? AND tipo='execucao'",
                         (contrato_id, numero)).fetchone()
        if m is None:
            linha["motivo"] = f"nenhuma medição de execução nº {numero} neste contrato"
            continue
        if conn.execute("SELECT 1 FROM medicao_planilhas WHERE medicao_id=?", (m["id"],)).fetchone() is not None:
            linha.update(medicao=nome_medicao(m["numero"], m["tipo"]),
                         motivo="a medição tem planilha/carta anexada: a leitura vem do anexo")
            continue
        linha["medicao"] = nome_medicao(m["numero"], m["tipo"])
        dados = caminho.read_bytes()
        try:
            conferir_medicao(m)
        except ValueError as e:
            linha["motivo"] = str(e)
            continue
        r = ler_e_registrar(conn, usuario_id, m["id"], dados, origem="carga", guardar_arquivo=True, ensaio=ensaio)
        linha.update({k: r[k] for k in ("situacao", "motivo", "total_centavos", "pedido_centavos",
                                        "diferenca_centavos")})
    return saida
