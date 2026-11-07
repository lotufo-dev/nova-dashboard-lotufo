"""Medido por grupo da planilha de medicao (issue #490): grava e consulta as leituras.

Cada xlsx lido e' um evento em `medicao_grupos` (migracao 068), ligado a versao da planilha/carta quando veio do
anexo, sem versao quando veio da carga de uma pasta (`python -m app.cli medicoes planilhas`), para as medicoes
anteriores ao fluxo da planilha/carta. A soma dos grupos tem de bater, com tolerancia de um real, com o valor de
referencia: o pedido da versao da planilha/carta lida (o da revisao depois do envio tambem, embora o pedido da medicao
fique o congelado no envio) ou, na carga, o pedido da medicao. A leitura recusada no anexo fica registrada com o
motivo, para a tela avisar "planilha não lida". Vale a leitura mais nova da versao vigente.
So' a medicao de execucao tem leitura por grupo (reajuste e projeto nao entram). Os grupos vem do cadastro de custo
da obra (issue #489) quando houver, senao dos titulos da planilha. Quem le o xlsx e' a `leitura_planilha_medicao`;
aqui so' se grava e se consulta.
"""
import hashlib
import json
import re
from pathlib import Path

from app import arquivos, auditoria, contratos, db
from app import leitura_planilha_medicao as leitura
from app.medicoes import nome_medicao

ACAO = "medicao.grupos"
PREFIXO_AVISO = "Planilha não lida: "
FALHA = "falha inesperada na leitura"
# "01ª", "15ª Medição", "3º": o nº da medicao no nome do arquivo da carga (o "(05_2026)" ao lado nao tem ª nem º)
_NUMERO_NO_NOME = re.compile(r"(?<!\d)(\d{1,3})\s*[ªº°]")
COLUNAS_ITEM = ("item", "codigo", "descricao", "unidade", "quantidade_contratada", "quantidade_medida",
                "quantidade_acumulada", "preco_unitario_centavos", "valor_medido_centavos", "valor_acumulado_centavos")
CAMPOS_SAIDA = ("situacao", "motivo", "total_centavos", "pedido_centavos", "diferenca_centavos")


def cadastro_de_custo(conn, contrato_id: int) -> list[dict] | None:
    """Os grupos do cadastro de custo da obra (`itens_planilha`, issue #489), na ordem do yaml; None sem cadastro."""
    grupos_ = [{"nome": g["nome"], "itens_planilha": g["itens_planilha"]}
               for g in contratos.custo_grupos(conn, contrato_id)]
    return grupos_ or None


def _assinatura(cadastro: list[dict] | None) -> str | None:
    if not cadastro:
        return None
    return hashlib.sha256(json.dumps(cadastro, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def referencia(conn, m, planilha_id: int | None) -> int | None:
    """O valor que a soma dos grupos tem de bater: o pedido da versao da planilha/carta lida ou, sem versao (carga),
    o pedido da medicao."""
    if planilha_id is not None:
        return conn.execute("SELECT valor_pedido_centavos FROM medicao_planilhas WHERE id=?",
                            (planilha_id,)).fetchone()[0]
    return m["valor_protocolado_centavos"]


def conferir_medicao(m, ref: int | None) -> None:
    """Recusa (ValueError) a medicao que nao tem leitura por grupo: reajuste, projeto ou sem valor pedido."""
    if m["tipo"] != "execucao":
        raise ValueError(f"{nome_medicao(m['numero'], m['tipo'])}: só a medição de execução tem leitura por grupo")
    if ref is None:
        raise ValueError(f"{nome_medicao(m['numero'], m['tipo'])} não tem valor pedido para conferir a planilha")


def _anterior(conn, medicao_id: int, sha: str, planilha_id: int | None, ref: int, cad_sha: str | None):
    """A leitura ja' feita da mesma planilha, na mesma versao, contra o mesmo pedido e o mesmo cadastro (lida, ou
    recusada no anexo). A falha inesperada nao conta: a proxima tentativa le de novo."""
    return conn.execute(
        "SELECT id, situacao, motivo, total_centavos FROM medicao_grupos WHERE medicao_id=? AND sha256=? AND "
        "COALESCE(planilha_id, 0)=? AND pedido_centavos=? AND COALESCE(cadastro_sha256, '')=? "
        "AND situacao IN ('lida','recusada') ORDER BY id DESC LIMIT 1",
        (medicao_id, sha, planilha_id or 0, ref, cad_sha or "")).fetchone()


def _gravar(conn, usuario_id, medicao_id: int, sha: str, origem: str, planilha_id, arquivo, situacao: str, motivo,
            lido: dict | None, cad_sha, total, pedido) -> int:
    cur = conn.execute(
        "INSERT INTO medicao_grupos (medicao_id, planilha_id, sha256, arquivo, origem, situacao, motivo, grupo_por, "
        "cadastro_sha256, total_centavos, pedido_centavos, usuario_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (medicao_id, planilha_id, sha, arquivo, origem, situacao, motivo, lido["grupo_por"] if lido else None,
         cad_sha if lido else None, total, pedido, usuario_id))
    lid = cur.lastrowid
    if lido and situacao == "lida":
        ordem = 0
        for g in lido["grupos"]:          # na ordem dos grupos: a consulta remonta a mesma ordem
            for it in g["itens"]:
                ordem += 1
                conn.execute(
                    f"INSERT INTO medicao_grupo_itens (leitura_id, ordem, grupo, {', '.join(COLUNAS_ITEM)}) "
                    f"VALUES (?,?,?,{','.join('?' * len(COLUNAS_ITEM))})",
                    (lid, ordem, g["nome"], *(it[k] for k in COLUNAS_ITEM)))
    auditoria.registrar(conn, usuario_id, ACAO, "medicao", medicao_id, None, {
        "leitura_id": lid, "situacao": situacao, "origem": origem, "planilha_id": planilha_id, "sha256": sha,
        "total_centavos": total, "pedido_centavos": pedido, "grupo_por": lido["grupo_por"] if lido else None,
        "motivo": motivo})
    return lid


def _ler(dados: bytes, cadastro):
    """(leitura, motivo da recusa): so' a recusa deterministica da planilha vira motivo; o resto sobe."""
    try:
        return leitura.ler(dados, cadastro), None
    except leitura.PlanilhaRecusada as e:
        return None, str(e)


def _conferir(lido, motivo, ref: int) -> tuple[str, str | None]:
    if lido is None:
        return "recusada", motivo
    try:
        leitura.conferir_total(lido["total_centavos"], ref)
    except leitura.PlanilhaRecusada as e:
        return "recusada", str(e)
    return "lida", None


def ler_e_registrar(conn, usuario_id: int | None, medicao_id: int, dados: bytes, *, origem: str,
                    planilha_id: int | None = None, arquivo: str | None = None, gravar_recusa: bool = False,
                    guardar_arquivo: bool = False, ensaio: bool = False) -> dict:
    """Le o xlsx e grava a leitura da medicao. Devolve {"situacao": "lida" | "repetida" | "recusada", "anterior"
    (na repetida, a situacao da leitura reaproveitada), "motivo", "total_centavos", "pedido_centavos",
    "diferenca_centavos", "leitura_id"}. A mesma planilha na mesma versao, contra o mesmo pedido e o mesmo cadastro,
    nao se le duas vezes ("repetida"). A recusa so' se grava com `gravar_recusa` (o anexo: a tela avisa); na carga,
    so' se imprime. `guardar_arquivo` (a carga) grava o xlsx na pasta das planilhas so' quando a leitura vale.
    O pedido, o cadastro e a repeticao sao conferidos de novo sob o lock da gravacao. A medicao que nao tem leitura
    por grupo levanta ValueError (nada se grava)."""
    sha = arquivos.sha_de(dados)

    def estado():
        m_ = conn.execute("SELECT * FROM medicoes WHERE id=?", (medicao_id,)).fetchone()
        ref_ = referencia(conn, m_, planilha_id)
        conferir_medicao(m_, ref_)
        cad_ = cadastro_de_custo(conn, m_["contrato_id"])
        return ref_, cad_, _assinatura(cad_)

    def resposta(situacao, motivo, lido, ref_, anterior=None, leitura_id=None, total=None):
        total = lido["total_centavos"] if lido else total
        return {"situacao": situacao, "anterior": anterior, "motivo": motivo, "total_centavos": total,
                "pedido_centavos": ref_, "diferenca_centavos": None if total is None else total - ref_,
                "leitura_id": leitura_id}

    def repetida(ant, ref_):
        return resposta("repetida", ant["motivo"], None, ref_, ant["situacao"], ant["id"], ant["total_centavos"])

    ref, cad, cad_sha = estado()
    ant = _anterior(conn, medicao_id, sha, planilha_id, ref, cad_sha)
    if ant is not None:
        return repetida(ant, ref)
    lido, motivo = _ler(dados, cad)
    situacao_, motivo_ = _conferir(lido, motivo, ref)
    if ensaio or (situacao_ == "recusada" and not gravar_recusa):
        return resposta(situacao_, motivo_, lido, ref)
    if guardar_arquivo and situacao_ == "lida":
        arquivo, _ = arquivos.gravar_bytes("planilhas", dados, "xlsx")     # pelo hash: repetir nao duplica
    with db.mutacao(conn):
        ref2, cad2, cad_sha2 = estado()                  # de novo, sob o lock: o pedido ou o cadastro podem ter mudado
        if cad_sha2 != cad_sha:
            lido, motivo = _ler(dados, cad2)
        ref, cad_sha = ref2, cad_sha2
        ant = _anterior(conn, medicao_id, sha, planilha_id, ref, cad_sha)
        if ant is not None:
            return repetida(ant, ref)
        situacao_, motivo_ = _conferir(lido, motivo, ref)
        if situacao_ == "recusada" and not gravar_recusa:
            return resposta(situacao_, motivo_, lido, ref)
        lid = _gravar(conn, usuario_id, medicao_id, sha, origem, planilha_id, arquivo, situacao_, motivo_, lido,
                      cad_sha, lido["total_centavos"] if lido else None, ref)
    return resposta(situacao_, motivo_, lido, ref, leitura_id=lid)


def _resumo_anexo(r: dict) -> dict:
    situacao_ = r["anterior"] if r["situacao"] == "repetida" else r["situacao"]
    return {"situacao": situacao_, "aviso": PREFIXO_AVISO + r["motivo"] if r["motivo"] else None}


def ler_anexo(conn, usuario_id: int | None, medicao_id: int, versao: int, dados: bytes) -> dict | None:
    """O xlsx anexado a versao da planilha/carta (registro ou revisao), lido depois de a versao estar gravada: a
    recusa nao impede o registro, fica gravada e volta como aviso. None na medicao sem leitura por grupo."""
    v = conn.execute("SELECT id, arquivo_planilha FROM medicao_planilhas WHERE medicao_id=? AND versao=?",
                     (medicao_id, versao)).fetchone()
    m = conn.execute("SELECT * FROM medicoes WHERE id=?", (medicao_id,)).fetchone()
    try:
        conferir_medicao(m, referencia(conn, m, v["id"]))
    except ValueError:
        return None
    return _resumo_anexo(ler_e_registrar(conn, usuario_id, medicao_id, dados, origem="anexo", planilha_id=v["id"],
                                         arquivo=v["arquivo_planilha"], gravar_recusa=True))


def registrar_falha(conn, usuario_id: int | None, medicao_id: int, versao: int, dados: bytes) -> dict:
    """Erro inesperado na leitura do anexo (nao e' recusa da planilha): fica gravado, para a tela avisar e para a
    carga (`medicoes planilhas`) ler o anexo de novo. Levanta se nem isso grava (quem chama devolve o erro)."""
    v = conn.execute("SELECT id, arquivo_planilha FROM medicao_planilhas WHERE medicao_id=? AND versao=?",
                     (medicao_id, versao)).fetchone()
    with db.mutacao(conn):
        _gravar(conn, usuario_id, medicao_id, arquivos.sha_de(dados), "anexo", v["id"], v["arquivo_planilha"],
                "falhou", FALHA, None, None, None, None)
    return {"situacao": "falhou", "aviso": PREFIXO_AVISO + FALHA}


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
    """A leitura mais nova que vale: {"situacao": "sem_leitura" | "lida" | "recusada" | "falhou", "aviso"}."""
    onde, args = _filtro_vigente(conn, medicao_id)
    r = conn.execute(f"SELECT g.situacao, g.motivo FROM medicao_grupos g WHERE {onde} ORDER BY g.id DESC LIMIT 1",
                     args).fetchone()
    if r is None:
        return {"situacao": "sem_leitura", "aviso": None}
    return {"situacao": r["situacao"], "aviso": PREFIXO_AVISO + r["motivo"] if r["situacao"] != "lida" else None}


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


def _linha(arquivo: str, medicao=None, motivo=None) -> dict:
    return {"arquivo": arquivo, "medicao": medicao, "situacao": "pulado", "motivo": motivo, "total_centavos": None,
            "pedido_centavos": None, "diferenca_centavos": None}


def _grande_demais(tamanho: int) -> str | None:
    if tamanho > leitura.MAX_BYTES_ARQUIVO:
        return f"arquivo grande demais (acima de {leitura.MAX_BYTES_ARQUIVO // 1_000_000} MB)"
    return None


def _anexos(conn, usuario_id, contrato_id: int, ensaio: bool) -> list[dict]:
    """As medicoes de execucao com planilha/carta anexada em .xlsx: a versao vigente e' lida do proprio anexo (as
    anexadas antes desta leitura existir entram aqui; as ja' lidas voltam como "repetida")."""
    saida = []
    for r in conn.execute(
            "SELECT m.id, m.numero, m.tipo, p.versao, p.arquivo_planilha FROM medicoes m "
            "JOIN medicao_planilhas p ON p.medicao_id=m.id AND p.versao=(SELECT MAX(versao) FROM medicao_planilhas "
            "WHERE medicao_id=m.id) WHERE m.contrato_id=? AND m.tipo='execucao' ORDER BY m.numero",
            (contrato_id,)).fetchall():
        rel = r["arquivo_planilha"] or ""
        if not rel.lower().endswith(".xlsx"):
            continue
        linha = _linha(f"anexo da versão {r['versao']}", nome_medicao(r["numero"], r["tipo"]))
        saida.append(linha)
        try:
            caminho = arquivos.caminho_seguro(rel)
        except ValueError:
            caminho = None
        if caminho is None or not caminho.is_file():
            linha["motivo"] = "o arquivo do anexo não foi encontrado"
            continue
        linha["motivo"] = _grande_demais(caminho.stat().st_size)
        if linha["motivo"]:
            continue
        try:
            res = ler_e_registrar(conn, usuario_id, r["id"], caminho.read_bytes(), origem="anexo",
                                  planilha_id=conn.execute("SELECT id FROM medicao_planilhas WHERE medicao_id=? AND "
                                                           "versao=?", (r["id"], r["versao"])).fetchone()[0],
                                  arquivo=rel, gravar_recusa=True, ensaio=ensaio)
        except ValueError as e:
            linha["motivo"] = str(e)
            continue
        linha.update({k: res[k] for k in CAMPOS_SAIDA})
    return saida


def carregar_pasta(conn, usuario_id: int | None, contrato_id: int, pasta: Path, ensaio: bool = False) -> list[dict]:
    """Um xlsx por medicao, o nº da medicao no nome do arquivo, e depois os anexos .xlsx das medicoes com
    planilha/carta (`_anexos`). Cada linha devolve {"arquivo", "medicao", "situacao" ("lida", "repetida",
    "recusada", "pulado"), "motivo", "total_centavos", "pedido_centavos", "diferenca_centavos"}. Arquivo que nao casa
    com medicao nenhuma e' listado e pulado, e tambem os varios arquivos com o mesmo nº (qual vale e' escolha de
    quem monta a pasta) e o da medicao que tem planilha/carta anexada (a leitura dela vem do anexo)."""
    saida = []
    caminhos = sorted(p for p in pasta.iterdir() if p.is_file() and not p.name.startswith("~$"))
    por_numero: dict[int, int] = {}
    for p in caminhos:
        n = numero_no_nome(p.name) if p.suffix.lower() == ".xlsx" else None
        if n is not None:
            por_numero[n] = por_numero.get(n, 0) + 1
    for caminho in caminhos:
        linha = _linha(caminho.name)
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
        linha["medicao"] = nome_medicao(m["numero"], m["tipo"])
        if conn.execute("SELECT 1 FROM medicao_planilhas WHERE medicao_id=?", (m["id"],)).fetchone() is not None:
            linha["motivo"] = "a medição tem planilha/carta anexada: a leitura vem do anexo"
            continue
        linha["motivo"] = _grande_demais(caminho.stat().st_size)     # antes de ler o arquivo para a memoria
        if linha["motivo"]:
            continue
        try:
            r = ler_e_registrar(conn, usuario_id, m["id"], caminho.read_bytes(), origem="carga",
                                guardar_arquivo=True, ensaio=ensaio)
        except ValueError as e:
            linha["motivo"] = str(e)
            continue
        linha.update({k: r[k] for k in CAMPOS_SAIDA})
    return saida + _anexos(conn, usuario_id, contrato_id, ensaio)
