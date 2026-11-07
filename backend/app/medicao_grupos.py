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
    """O evento da leitura, com o contexto em que foi feita (pedido conferido e cadastro usado, tambem na recusa e
    na falha) e, na lida, a quantidade de itens: o gatilho da 068 recusa item alem dela (a leitura fica selada)."""
    itens = [(g["nome"], it) for g in lido["grupos"] for it in g["itens"]] if lido and situacao == "lida" else []
    cur = conn.execute(
        "INSERT INTO medicao_grupos (medicao_id, planilha_id, sha256, arquivo, origem, situacao, motivo, grupo_por, "
        "cadastro_sha256, total_centavos, pedido_centavos, itens, usuario_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (medicao_id, planilha_id, sha, arquivo, origem, situacao, motivo, lido["grupo_por"] if lido else None,
         cad_sha, total, pedido, len(itens), usuario_id))
    lid = cur.lastrowid
    # na ordem dos grupos: a consulta remonta a mesma ordem
    for ordem, (grupo, it) in enumerate(itens, 1):
        conn.execute(
            f"INSERT INTO medicao_grupo_itens (leitura_id, ordem, grupo, {', '.join(COLUNAS_ITEM)}) "
            f"VALUES (?,?,?,{','.join('?' * len(COLUNAS_ITEM))})",
            (lid, ordem, grupo, *(it[k] for k in COLUNAS_ITEM)))
    auditoria.registrar(conn, usuario_id, ACAO, "medicao", medicao_id, None, {
        "leitura_id": lid, "situacao": situacao, "origem": origem, "planilha_id": planilha_id, "sha256": sha,
        "total_centavos": total, "pedido_centavos": pedido, "grupo_por": lido["grupo_por"] if lido else None,
        "cadastro_sha256": cad_sha, "itens": len(itens), "motivo": motivo})
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


def _contexto(conn, medicao_id: int, planilha_id: int | None) -> tuple[int, list[dict] | None, str | None]:
    """(pedido de referencia, cadastro, impressao do cadastro) de agora; ValueError na medicao sem leitura por grupo."""
    m = conn.execute("SELECT * FROM medicoes WHERE id=?", (medicao_id,)).fetchone()
    ref = referencia(conn, m, planilha_id)
    conferir_medicao(m, ref)
    cad = cadastro_de_custo(conn, m["contrato_id"])
    return ref, cad, _assinatura(cad)


def ler_e_registrar(conn, usuario_id: int | None, medicao_id: int, dados: bytes, *, origem: str,
                    planilha_id: int | None = None, arquivo: str | None = None, gravar_recusa: bool = False,
                    guardar_arquivo: bool = False, ensaio: bool = False) -> dict:
    """Le o xlsx e grava a leitura da medicao. Devolve {"situacao": "lida" | "repetida" | "recusada", "anterior"
    (na repetida, a situacao da leitura reaproveitada), "motivo", "total_centavos", "pedido_centavos",
    "diferenca_centavos", "leitura_id"}. A mesma planilha na mesma versao, contra o mesmo pedido e o mesmo cadastro,
    nao se le duas vezes ("repetida"). A recusa so' se grava com `gravar_recusa` (o anexo: a tela avisa); na carga,
    so' se imprime. `guardar_arquivo` (a carga) grava o xlsx na pasta das planilhas so' quando a leitura vale.
    Toda decisao (reaproveitar, conferir o total, gravar) e' tomada sob o lock da gravacao, com o pedido e o
    cadastro relidos ali; o que se olha antes so' evita abrir o xlsx a toa. A medicao que nao tem leitura por grupo
    levanta ValueError (nada se grava)."""
    sha = arquivos.sha_de(dados)

    def resposta(situacao_, motivo_, lido_, ref_, anterior=None, leitura_id=None, total=None):
        total = lido_["total_centavos"] if lido_ else total
        return {"situacao": situacao_, "anterior": anterior, "motivo": motivo_, "total_centavos": total,
                "pedido_centavos": ref_, "diferenca_centavos": None if total is None else total - ref_,
                "leitura_id": leitura_id}

    def repetida(ant, ref_):
        return resposta("repetida", ant["motivo"], None, ref_, ant["situacao"], ant["id"], ant["total_centavos"])

    ref, cad, cad_sha = _contexto(conn, medicao_id, planilha_id)
    lido = motivo = lido_com = None          # `lido_com`: a impressao do cadastro com que o xlsx foi lido
    ant = _anterior(conn, medicao_id, sha, planilha_id, ref, cad_sha)
    if ensaio:
        if ant is not None:
            return repetida(ant, ref)
        lido, motivo = _ler(dados, cad)
        return resposta(*_conferir(lido, motivo, ref), lido, ref)
    if ant is None:                         # so' uma dica: a decisao e' sob o lock, abaixo
        lido, motivo = _ler(dados, cad)
        lido_com = cad_sha
        if guardar_arquivo and _conferir(lido, motivo, ref)[0] == "lida":
            arquivo, _ = arquivos.gravar_bytes("planilhas", dados, "xlsx")     # pelo hash: repetir nao duplica
    with db.mutacao(conn):
        ref, cad, cad_sha = _contexto(conn, medicao_id, planilha_id)     # sob o lock: pedido e cadastro de agora
        ant = _anterior(conn, medicao_id, sha, planilha_id, ref, cad_sha)
        if ant is not None:
            return repetida(ant, ref)
        if lido_com != cad_sha or (lido is None and motivo is None):
            lido, motivo = _ler(dados, cad)
        situacao_, motivo_ = _conferir(lido, motivo, ref)
        if situacao_ == "recusada" and not gravar_recusa:
            return resposta(situacao_, motivo_, lido, ref)
        if guardar_arquivo and situacao_ == "lida" and arquivo is None:
            arquivo, _ = arquivos.gravar_bytes("planilhas", dados, "xlsx")
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
    """Erro inesperado na leitura do anexo (nao e' recusa da planilha): fica gravado com o contexto tentado (pedido e
    cadastro), para a tela avisar e para a carga (`medicoes planilhas`) ler o anexo de novo. Nao apaga uma leitura
    valida do mesmo contexto (`situacao` a prefere). Levanta se nem isso grava (quem chama devolve o erro)."""
    v = conn.execute("SELECT id, arquivo_planilha FROM medicao_planilhas WHERE medicao_id=? AND versao=?",
                     (medicao_id, versao)).fetchone()
    with db.mutacao(conn):
        ref, _, cad_sha = _contexto(conn, medicao_id, v["id"])
        _gravar(conn, usuario_id, medicao_id, arquivos.sha_de(dados), "anexo", v["id"], v["arquivo_planilha"],
                "falhou", FALHA, None, cad_sha, None, ref)
    return {"situacao": "falhou", "aviso": PREFIXO_AVISO + FALHA}


def _filtro_vigente(conn, medicao_id: int) -> tuple[str, tuple] | None:
    """As leituras que valem agora, ou None (medicao sem leitura por grupo: reajuste, projeto, sem pedido).
    Na medicao com planilha/carta, so' as da versao vigente (a revisao em PDF fica sem leitura: a da versao anterior
    nao representa mais o pedido); na medicao sem planilha/carta (historico), as da carga. Nas duas, so' as feitas
    contra o pedido de referencia e o cadastro de custo de agora: pedido ou cadastro que mudaram depois deixam a
    leitura antiga de lado ate' a carga ler de novo."""
    vigente = conn.execute("SELECT id FROM medicao_planilhas WHERE medicao_id=? ORDER BY versao DESC LIMIT 1",
                           (medicao_id,)).fetchone()
    pid = vigente["id"] if vigente else None
    try:
        ref, _, cad_sha = _contexto(conn, medicao_id, pid)
    except ValueError:
        return None
    versao = "g.planilha_id IS NULL" if pid is None else "g.planilha_id=?"
    return (f"g.medicao_id=? AND {versao} AND g.pedido_centavos=? AND COALESCE(g.cadastro_sha256, '')=?",
            (medicao_id, *(() if pid is None else (pid,)), ref, cad_sha or ""))


def situacao(conn, medicao_id: int) -> dict:
    """A leitura mais nova que vale: {"situacao": "sem_leitura" | "lida" | "recusada" | "falhou", "aviso"}. A falha
    inesperada so' aparece quando nao ha' leitura (lida ou recusada) no mesmo contexto: ela nao desfaz a que existe."""
    with db.leitura(conn):
        return _situacao(conn, _filtro_vigente(conn, medicao_id))


def _situacao(conn, filtro: tuple[str, tuple] | None) -> dict:
    """A situacao sobre um filtro ja' calculado: quem tambem le os grupos usa o mesmo (issue #501)."""
    if filtro is None:
        return {"situacao": "sem_leitura", "aviso": None}
    onde, args = filtro
    r = conn.execute(f"SELECT g.situacao, g.motivo FROM medicao_grupos g WHERE {onde} "
                     "ORDER BY g.situacao = 'falhou', g.id DESC LIMIT 1", args).fetchone()
    if r is None:
        return {"situacao": "sem_leitura", "aviso": None}
    return {"situacao": r["situacao"], "aviso": PREFIXO_AVISO + r["motivo"] if r["situacao"] != "lida" else None}


def grupos(conn, medicao_id: int) -> dict:
    """O medido por grupo da leitura lida mais nova que vale, com os itens, e a situacao (uma recusa depois da
    ultima lida volta como aviso, com os grupos da lida). Tudo sai de um retrato so' (issue #501): o filtro e' calculado
    uma vez e a situacao, a leitura e os itens sao lidos dele na mesma transacao de leitura, para uma revisao gravada
    no meio nao misturar a situacao de uma versao com os grupos de outra."""
    with db.leitura(conn):
        return _grupos(conn, _filtro_vigente(conn, medicao_id))


def _grupos(conn, filtro: tuple[str, tuple] | None) -> dict:
    saida = {**_situacao(conn, filtro), "leitura": None, "grupos": []}
    if filtro is None:
        return saida
    onde, args = filtro
    lida = conn.execute(
        "SELECT g.id, g.origem, g.planilha_id, p.versao, g.sha256, g.grupo_por, g.total_centavos, g.pedido_centavos, "
        "g.criado_em FROM medicao_grupos g LEFT JOIN medicao_planilhas p ON p.id=g.planilha_id "
        f"WHERE {onde} AND g.situacao='lida' ORDER BY g.id DESC LIMIT 1", args).fetchone()
    if lida is None:
        return saida
    saida["leitura"] = dict(lida)
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


def _ler_arquivo(caminho: Path) -> tuple[bytes | None, str | None]:
    """(bytes, motivo para pular): abre uma vez e le no maximo o teto mais um byte do mesmo descritor (o arquivo
    trocado entre conferir o tamanho e ler nao passa do teto, nem entra na memoria inteiro)."""
    with open(caminho, "rb") as f:
        dados = f.read(leitura.MAX_BYTES_ARQUIVO + 1)
    if len(dados) > leitura.MAX_BYTES_ARQUIVO:
        return None, f"arquivo grande demais (acima de {leitura.MAX_BYTES_ARQUIVO // 1_000_000} MB)"
    return dados, None


def _anexos(conn, usuario_id, contrato_id: int, ensaio: bool) -> list[dict]:
    """As medicoes de execucao com planilha/carta anexada em .xlsx: a versao vigente e' lida do proprio anexo (as
    anexadas antes desta leitura existir entram aqui; as ja' lidas voltam como "repetida")."""
    saida = []
    for r in conn.execute(
            "SELECT m.id, m.numero, m.tipo, p.id AS planilha_id, p.versao, p.arquivo_planilha, p.sha256_planilha "
            "FROM medicoes m "
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
        # sem o hash registrado nao ha' como conferir o arquivo: nao se liga qualquer bytes a versao (#503)
        if not r["sha256_planilha"]:
            linha["motivo"] = "a versão não tem o sha256 da planilha registrado"
            continue
        dados, linha["motivo"] = _ler_arquivo(caminho)
        if linha["motivo"]:
            continue
        # o arquivo gravado tem de ser o que a versao registrou: trocado ou corrompido, nao se liga a ela
        if arquivos.sha_de(dados) != r["sha256_planilha"]:
            linha["motivo"] = "o arquivo do anexo não confere com o registrado na versão"
            continue
        try:
            res = ler_e_registrar(conn, usuario_id, r["id"], dados, origem="anexo", planilha_id=r["planilha_id"],
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
        dados, linha["motivo"] = _ler_arquivo(caminho)
        if linha["motivo"]:
            continue
        try:
            r = ler_e_registrar(conn, usuario_id, m["id"], dados, origem="carga",
                                guardar_arquivo=True, ensaio=ensaio)
        except ValueError as e:
            linha["motivo"] = str(e)
            continue
        linha.update({k: r[k] for k in CAMPOS_SAIDA})
    return saida + _anexos(conn, usuario_id, contrato_id, ensaio)
