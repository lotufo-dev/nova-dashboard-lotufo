"""Carga do historico de medicoes por CSV (spec 2026-10-20 §2.4, opcao A; issues #258 e #259).

ENSAIO (`ensaiar`): le o CSV de uma obra, confere linha a linha contra o banco e devolve o relatorio, sem gravar.
GRAVAR (`gravar`): com o OK do Leo no ensaio, numa transacao so' por obra, cria as medicoes `nova` e corrige as
que ja' existem sem sobrescrever nada (issue #260): aprovado diferente vira evento novo de atesto com a fonte (o
vigente e' o ultimo), duplicata (coluna `cancelar`) e' cancelada com motivo e competencia errada (coluna
`corrige competência`) e' corrigida com a auditoria. O pedido de medicao existente nunca muda: foi congelado no
protocolo. A chave e' (obra, numero, tipo).

Categorias por linha: `nova` (nao existe medicao com a chave), `igual` (competencia, pedido e aprovado iguais
aos do banco), `valor diferente` (pedido ou aprovado diferem do banco), `incompleta` (o CSV deixa vazio um valor
que o banco tem), `conflito` (o mesmo numero e tipo com outra competencia, no banco ou noutra linha do CSV, ou
medicao cancelada/desistida no banco), `cancelamento` (duplicata a cancelar) e `correção` (competencia errada no
banco, com `corrige competência`). Linha que nao se le vira `erro`, com o numero da linha do arquivo.
"""

import csv
import datetime
import io
import re
import unicodedata
from pathlib import Path

from app import auditoria, contratos, db, dinheiro
from app.cadastro_arquivos import slug

TIPOS = ("execucao", "projeto", "reajuste")
ROTULOS = {"execucao": "execução", "projeto": "projeto", "reajuste": "reajuste"}
CATEGORIAS = ("nova", "igual", "valor diferente", "incompleta", "cancelamento", "correção", "conflito", "erro")
# Estados em que a medicao saiu do ciclo: o CSV nao pode dar como "igual" o que o banco encerrou
ESTADOS_TERMINAIS = ("cancelada", "desistida")

# Cabecalho normalizado (sem acento, minusculas, "nº" vira "no") -> campo
COLUNAS = {
    "no": "numero",
    "no do orgao": "numero_orgao",
    "tipo": "tipo",
    "competencia": "competencia",
    "periodo": "periodo",
    "valor pedido": "valor_pedido",
    "valor aprovado": "valor_aprovado",
    "data da aprovacao": "data_aprovacao",
    "meio": "meio",
    "no do processo no orgao": "processo_orgao",
    "data do protocolo da nota": "data_protocolo_nota",
    "nf": "nf",
    "fonte": "fonte",
    "cancelar": "cancelar",
    "corrige competencia": "corrige_competencia",
}
OBRIGATORIAS = ("numero", "tipo", "competencia", "valor_pedido", "valor_aprovado")
ROTULO_COLUNA = {"numero": "nº", "tipo": "tipo", "competencia": "competência", "valor_pedido": "valor pedido",
                 "valor_aprovado": "valor aprovado"}


# Meio da aprovacao no CSV (normalizado) -> `medicao_atestos.meio` (042). Meio desconhecido e' erro da linha:
# nunca adivinhar. "protocolo fisico" e' o carimbo no oficio entregue no balcao.
MEIOS = {"e-mail": "email", "email": "email", "smo": "smo", "oficio": "oficio", "carimbo": "carimbo",
         "protocolo fisico": "carimbo", "ci": "ci", "outro": "outro"}


class CsvInvalido(ValueError):
    """O arquivo inteiro nao se le (cabecalho, codificacao, obra): nada a relatar por linha."""


class CargaRecusada(ValueError):
    """O ensaio tem linha com erro ou conflito: nada e' gravado ate' o CSV ser corrigido."""


def _normalizar(texto: str) -> str:
    # "n°" (grau, comum no Excel) vale "nº"; o ponto de "nº." cai
    texto = texto.replace("°", "º").replace("º.", "º")
    ascii_ = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_.strip().lower())


def _competencia(texto: str) -> str:
    """'2025-04' ou '04/2025' -> '2025-04'."""
    m = re.fullmatch(r"([0-9]{4})-([0-9]{2})", texto) or re.fullmatch(r"([0-9]{2})/([0-9]{4})", texto)
    if not m:
        raise ValueError(f"competência inválida: {texto!r} (use AAAA-MM ou MM/AAAA)")
    ano, mes = (m.group(1), m.group(2)) if "-" in texto else (m.group(2), m.group(1))
    if not 1 <= int(mes) <= 12:
        raise ValueError(f"competência inválida: {texto!r} (mês fora de 01 a 12)")
    return f"{ano}-{mes}"


def _data(texto: str, campo: str) -> str | None:
    if not texto:
        return None
    for formato in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(texto, formato).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"{campo} inválida: {texto!r} (use DD/MM/AAAA)")


def _valor(texto: str, campo: str) -> int | None:
    if not texto:
        return None
    try:
        return dinheiro.parse_brl(texto)
    except ValueError as e:
        raise ValueError(f"{campo}: {texto!r}: {e}") from None


def _ler_texto(caminho: Path) -> str:
    try:
        bruto = caminho.read_bytes()
    except OSError:
        raise CsvInvalido(f"não foi possível ler o arquivo {caminho.name} (sem permissão ou removido)") from None
    if b"\x00" in bruto:
        raise CsvInvalido("o arquivo tem byte nulo: não é um CSV de texto (salve como CSV no Excel)")
    try:
        return bruto.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return bruto.decode("cp1252")  # CSV salvo pelo Excel em pt-BR
    except UnicodeDecodeError:
        raise CsvInvalido("codificação não reconhecida: salve o CSV em UTF-8") from None


def ler_csv(caminho: Path) -> list[tuple[int, dict]]:
    """Linhas do CSV como (numero da linha no arquivo, {campo: texto}). Separador `;` (Excel pt-BR) ou `,`."""
    texto = _ler_texto(caminho)
    primeira = (texto.splitlines() or [""])[0]   # \r sozinho tambem (CSV do Excel do Mac)
    leitor = csv.reader(io.StringIO(texto, newline=""), delimiter=";" if ";" in primeira else ",",
                        strict=True)   # aspas nao fechadas recusam o arquivo, nunca viram linha "igual"
    posicao = {"inicio": 1}
    try:
        return _linhas(leitor, posicao)
    except csv.Error:
        # A mensagem do modulo csv e' em ingles: so' a linha e a causa provavel. Com aspa sem fechar o leitor
        # vai ate' o fim do arquivo, entao `line_num` seria a ultima linha; cita onde o registro comecou
        raise CsvInvalido(f"o arquivo não se lê como CSV (linha {posicao['inicio']}): aspas sem fechar ou "
                          "caractere inválido") from None


def _linhas(leitor, posicao: dict) -> list[tuple[int, dict]]:
    try:
        cabecalho = next(leitor)
    except StopIteration:
        raise CsvInvalido("arquivo vazio") from None
    campos = []
    for coluna in cabecalho:
        nome = _normalizar(coluna)
        if nome not in COLUNAS:
            raise CsvInvalido(f"coluna desconhecida no cabeçalho: {coluna!r}")
        if COLUNAS[nome] in campos:
            raise CsvInvalido(f"coluna repetida no cabeçalho: {coluna!r}")
        campos.append(COLUNAS[nome])
    faltam = [c for c in OBRIGATORIAS if c not in campos]
    if faltam:
        raise CsvInvalido(f"faltam colunas no cabeçalho: {', '.join(ROTULO_COLUNA[c] for c in faltam)}")
    linhas, inicio = [], leitor.line_num + 1
    posicao["inicio"] = inicio
    for celulas in leitor:
        n_linha, inicio = inicio, leitor.line_num + 1      # a linha onde o registro COMECA (celula com quebra)
        posicao["inicio"] = inicio                         # onde o PROXIMO comeca, se ele nao se ler
        if not any(c.strip() for c in celulas):
            continue
        dados = {campo: celulas[i].strip() for i, campo in enumerate(campos) if i < len(celulas)}
        if len(celulas) != len(campos):
            # Valor com virgula sem aspas num CSV separado por virgula desloca as colunas: nunca adivinhar
            dados["_erro"] = f"a linha tem {len(celulas)} colunas e o cabeçalho tem {len(campos)}"
        linhas.append((n_linha, dados))
    return linhas


def _interpretar(bruto: dict, janela: tuple[str, str] | None) -> dict:
    """Valida e converte uma linha. ValueError com a mensagem do primeiro problema."""
    if bruto.get("_erro"):
        raise ValueError(bruto["_erro"])
    numero = bruto.get("numero", "")
    # ate' 9 digitos: numero maior nao e' medicao e estouraria o inteiro do SQLite
    if not re.fullmatch(r"[0-9]{1,9}", numero) or int(numero) < 1:
        raise ValueError(f"nº inválido: {numero!r}")
    tipo = _normalizar(bruto.get("tipo", ""))
    if tipo not in TIPOS:
        raise ValueError(f"tipo desconhecido: {bruto.get('tipo', '')!r} (use {', '.join(ROTULOS.values())})")
    competencia = _competencia(bruto.get("competencia", ""))
    if janela and not janela[0] <= competencia <= janela[1]:
        raise ValueError(f"competência {competencia} fora do contrato ({janela[0]} a {janela[1]})")
    numero_orgao = bruto.get("numero_orgao", "")
    if numero_orgao and (not re.fullmatch(r"[0-9]{1,9}", numero_orgao) or int(numero_orgao) < 1):
        raise ValueError(f"nº do órgão inválido: {numero_orgao!r}")
    cancelar = bruto.get("cancelar", "")
    if cancelar and (not re.fullmatch(r"[0-9]{1,9}", cancelar) or int(cancelar) < 1):
        raise ValueError(f"cancelar: {cancelar!r} não é o nº da medição que substitui esta")
    if cancelar and int(cancelar) == int(numero):
        raise ValueError("cancelar: a medição não substitui a si mesma")
    corrige = _normalizar(bruto.get("corrige_competencia", ""))
    if corrige not in ("", "sim", "nao"):
        raise ValueError(f"corrige competência: {bruto.get('corrige_competencia')!r} (use sim ou deixe vazio)")
    meio = bruto.get("meio", "")
    if meio and _normalizar(meio) not in MEIOS:
        raise ValueError(f"meio desconhecido: {meio!r} (use e-mail, SMO, ofício, carimbo, CI ou outro)")
    return {"numero": int(numero), "tipo": tipo, "competencia": competencia,
            "numero_orgao": int(numero_orgao) if numero_orgao else None,
            "periodo": _periodo(bruto.get("periodo", "")),
            "valor_pedido": _valor(bruto.get("valor_pedido", ""), "valor pedido"),
            "valor_aprovado": _valor(bruto.get("valor_aprovado", ""), "valor aprovado"),
            "data_aprovacao": _data(bruto.get("data_aprovacao", ""), "data da aprovação"),
            "meio": MEIOS[_normalizar(meio)] if meio else None,
            "processo_orgao": bruto.get("processo_orgao") or None,
            "data_protocolo_nota": _data(bruto.get("data_protocolo_nota", ""), "data do protocolo da nota"),
            "nfs": _nfs(bruto.get("nf", "")),
            "fonte": bruto.get("fonte") or None,
            "cancelar": int(cancelar) if cancelar else None,
            "corrige_competencia": corrige == "sim"}


def _nfs(texto: str) -> list[str]:
    """'101' ou '101/102' (medicao faturada em mais de uma nota, padrao MT-388) -> ['101', '102']."""
    nfs = [n.strip() for n in re.split(r"[/,+]", texto) if n.strip()]
    for n in nfs:
        if not re.fullmatch(r"[0-9A-Za-z.-]{1,20}", n):
            raise ValueError(f"NF inválida: {n!r} (use o número da nota; várias separadas por /)")
    return nfs


def _periodo(texto: str) -> tuple[str, str] | None:
    """'10/03/2025 a 30/04/2025' -> ('2025-03-10', '2025-04-30'). Vazio: sem periodo."""
    if not texto:
        return None
    partes = re.split(r"\s+a\s+", texto.strip())
    if len(partes) != 2:
        raise ValueError(f"período inválido: {texto!r} (use DD/MM/AAAA a DD/MM/AAAA)")
    ini, fim = _data(partes[0], "data de início do período"), _data(partes[1], "data de fim do período")
    if ini > fim:
        raise ValueError(f"período invertido: {texto!r}")
    return ini, fim


def contrato_da_obra(conn, obra: str):
    """O contrato cujo slug do nome curto e' `obra` (o mesmo nome do arquivo `contratos/<obra>.yaml`)."""
    achados = [c for c in conn.execute(
        "SELECT id, nome_curto, vigencia_inicio, vigencia_fim FROM contratos WHERE nome_curto IS NOT NULL")
        if slug(c["nome_curto"]) == obra]
    if len(achados) != 1:
        raise CsvInvalido(f"obra {obra!r} não encontrada no banco" if not achados
                          else f"obra {obra!r} corresponde a mais de um contrato")
    return achados[0]


def _janela(conn, contrato) -> tuple[str, str] | None:
    """Competencias aceitas: do mes do inicio ao mes do fim da vigencia, com os aditivos de prazo assinados.
    Sem as duas datas, nao confere."""
    ini, fim = contrato["vigencia_inicio"], contratos.vigente(conn, contrato["id"])["vigencia_fim_vigente"]
    return (ini[:7], fim[:7]) if ini and fim else None


def ensaiar(conn, caminho: Path, obra: str | None = None) -> dict:
    """Relatorio do ensaio. `obra` padrao: o nome do arquivo sem extensao. So' le o banco."""
    obra = obra or caminho.stem
    contrato = contrato_da_obra(conn, obra)
    janela = _janela(conn, contrato)
    existentes = {(m["numero"], m["tipo"]): m for m in conn.execute(
        "SELECT id, numero, tipo, competencia, estado, valor_protocolado_centavos, valor_atestado_centavos "
        "FROM medicoes WHERE contrato_id=?", (contrato["id"],))}
    lidas = []
    for n_linha, bruto in ler_csv(caminho):
        tipo_csv = bruto.get("tipo", "")
        item = {"linha": n_linha, "numero": bruto.get("numero", ""),
                "tipo": ROTULOS.get(_normalizar(tipo_csv), tipo_csv)}
        try:
            lidas.append((item, _interpretar(bruto, janela)))
        except ValueError as e:
            lidas.append(({**item, "categoria": "erro", "detalhe": str(e)}, None))
    # O mesmo (nº, tipo) com mais de uma competencia no CSV: TODAS as linhas do grupo sao conflito
    grupos = {}
    for item, d in lidas:
        if d is not None:
            grupos.setdefault((d["numero"], d["tipo"]), []).append((item["linha"], d["competencia"]))
    linhas, vistas = [], {}
    for item, d in lidas:
        if d is None:
            linhas.append(item)
            continue
        rotulo_tipo = ROTULOS[d["tipo"]]
        item = {**item, "numero": d["numero"], "tipo": rotulo_tipo, "competencia": d["competencia"]}
        chave = (d["numero"], d["tipo"])
        grupo = grupos[chave]
        if len({comp for _, comp in grupo}) > 1:
            outras = ", ".join(f"linha {n} {comp}" for n, comp in grupo if comp != d["competencia"])
            linhas.append({**item, "categoria": "conflito",
                           "detalhe": f"o mesmo nº tem outra competência no CSV ({outras})"})
            continue
        if chave in vistas:
            linhas.append({**item, "categoria": "erro",
                           "detalhe": f"nº {d['numero']} {rotulo_tipo} repetido (já na linha {vistas[chave]})"})
            continue
        vistas[chave] = item["linha"]
        m = existentes.get(chave)
        if d["cancelar"] is not None:
            linhas.append(_classificar_cancelamento(item, d, m, existentes, grupos))
            continue
        if m is None and d["valor_pedido"] is None:
            # Medicao historica nasce protocolada e congelada: sem o pedido ela ficaria congelada sem valor, e o
            # primeiro preenchimento depois nao passaria pelo documento (gate Sol da #259)
            linhas.append({**item, "categoria": "erro", "detalhe": "medição nova sem valor pedido"})
        elif m is None:
            linhas.append({**item, "categoria": "nova", "detalhe": "", "dados": d})
        elif m["estado"] in ESTADOS_TERMINAIS:
            linhas.append({**item, "categoria": "conflito", "detalhe": f"no banco a medição está {m['estado']}"})
        elif m["competencia"] != d["competencia"] and not d["corrige_competencia"]:
            linhas.append({**item, "categoria": "conflito",
                           "detalhe": f"banco tem competência {m['competencia']} (se o banco está errado, marque "
                                      "\"corrige competência\" com sim)"})
        else:
            difs, vazios = [], []
            for rotulo, campo, col in (("pedido", "valor_pedido", "valor_protocolado_centavos"),
                                       ("aprovado", "valor_aprovado", "valor_atestado_centavos")):
                if d[campo] is None and m[col] is not None:
                    # Celula vazia = o CSV nao informa (nao e' zero), e por isso nunca da a linha como igual
                    vazios.append(f"{rotulo} vazio no CSV, banco {_fmt(m[col])}")
                elif d[campo] != m[col]:
                    difs.append(f"{rotulo}: banco {_fmt(m[col])}, CSV {_fmt(d[campo])}")
            # Um valor diferente e o outro vazio: "valor diferente", com a celula vazia no detalhe
            categoria = "valor diferente" if difs else "incompleta" if vazios else "igual"
            if m["competencia"] != d["competencia"]:
                categoria, difs = "correção", [f"competência: banco {m['competencia']}, CSV {d['competencia']}", *difs]
            linhas.append({**item, "categoria": categoria, "detalhe": "; ".join(difs + vazios),
                           "dados": d, "medicao_id": m["id"]})
    totais = {c: sum(1 for li in linhas if li["categoria"] == c) for c in CATEGORIAS}
    return {"obra": obra, "contrato": contrato["nome_curto"], "contrato_id": contrato["id"], "linhas": linhas,
            "totais": totais}


def _classificar_cancelamento(item: dict, d: dict, m, existentes: dict, grupos: dict) -> dict:
    """Linha com `cancelar`: a medicao do banco e' duplicata da que tem o nº em `cancelar` (mesmo tipo)."""
    rotulo = ROTULOS[d["tipo"]]
    substituta = (d["cancelar"], d["tipo"])
    if m is None:
        return {**item, "categoria": "erro", "detalhe": f"cancelar: não há {d['numero']}ª {rotulo} no banco"}
    if m["estado"] == "cancelada":
        return {**item, "categoria": "igual", "detalhe": "já cancelada"}
    if m["estado"] in ("recebida", "desistida"):
        # recebida nao se cancela (TRANSICOES): recebeu-se por ela, e isso pede decisao, nao carga
        return {**item, "categoria": "conflito", "detalhe": f"no banco a medição está {m['estado']}: não se cancela "
                                                            "pela carga"}
    if substituta not in existentes and substituta not in grupos:
        return {**item, "categoria": "erro", "detalhe": f"cancelar: a {d['cancelar']}ª {rotulo} que a substitui não "
                                                        "está no banco nem no CSV"}
    alvo = existentes.get(substituta)
    if alvo is not None and alvo["estado"] in ESTADOS_TERMINAIS:
        return {**item, "categoria": "erro", "detalhe": f"cancelar: a {d['cancelar']}ª {rotulo} que a substitui está "
                                                        f"{alvo['estado']}"}
    return {**item, "categoria": "cancelamento", "detalhe": f"duplicata da {d['cancelar']}ª {rotulo}",
            "dados": d, "medicao_id": m["id"]}


def _fmt(centavos: int | None) -> str:
    return "vazio" if centavos is None else dinheiro.format_brl(centavos)


def gravar(conn, usuario_id: int, caminho: Path, obra: str | None = None) -> dict:
    """Cria as medicoes `nova` do CSV, numa transacao so' (por obra), e devolve o relatorio com o que foi feito.

    Linha com erro ou conflito recusa o arquivo inteiro (CargaRecusada, nada gravado): o CSV se corrige e se
    roda de novo. `igual` passa (rodar duas vezes nao duplica). `valor diferente` e `incompleta` nao mexem na
    medicao existente: correcao e' evento novo (issue #260).

    Medicao nova: estado `protocolada` e congelada (e' historico: o pedido ja' saiu), valor pedido como
    protocolado, aprovado como evento de atesto (data, meio, processo e fonte), protocolo da nota quando o CSV
    traz a data. A NF do CSV, achada no RM da empresa do contrato, e' vinculada; se o RM ja' tem a baixa que
    cobre os titulos, a regra de sempre (`sincronizacao_rm._recebimentos`) passa a medicao a `recebida`, com a
    data da baixa."""
    from app import sincronizacao_rm   # import local: sincronizacao_rm importa medicoes e notas
    with db.mutacao(conn):
        rel = ensaiar(conn, caminho, obra)
        ruins = rel["totais"]["erro"] + rel["totais"]["conflito"]
        if ruins:
            raise CargaRecusada(f"{ruins} linha(s) com erro ou conflito; corrija o CSV (rode com --ensaio para "
                                "ver quais)")
        cid = rel["contrato_id"]
        coligada = conn.execute("SELECT e.coligada_rm FROM contratos c JOIN entidades e "
                                "ON e.id=COALESCE(c.entidade_id, 1) WHERE c.id=?", (cid,)).fetchone()[0]
        criadas = {}
        for li in rel["linhas"]:
            if li["categoria"] == "nova":
                criadas[_criar(conn, usuario_id, cid, li)] = li
                li["acao"] = "criada"
            elif li["categoria"] == "cancelamento":
                li["acao"] = _cancelar(conn, usuario_id, li)
            elif li["categoria"] in ("valor diferente", "correção"):
                li["acao"] = _corrigir(conn, usuario_id, li)
            elif li["categoria"] == "incompleta":
                li["acao"] = "não alterada (o CSV não traz o valor que o banco tem)"
            else:
                li["acao"] = "já existe"
        corrigidas = [li for li in rel["linhas"] if li["categoria"] in ("cancelamento", "valor diferente", "correção")]
        from app import diretoria    # import local: diretoria importa sincronizacao_rm
        mapa = diretoria._mapa_contratos(conn)          # uma vez por carga, nao por medicao
        vinculadas = []
        for mid, li in criadas.items():
            texto, ok = _vincular_nfs(conn, usuario_id, mid, li["dados"], cid, coligada, mapa)
            li["acao"] += texto
            if ok:
                vinculadas.append(mid)
        sincronizacao_rm._recebimentos(conn, vinculadas)
        for mid, li in criadas.items():
            if conn.execute("SELECT estado FROM medicoes WHERE id=?", (mid,)).fetchone()[0] == "recebida":
                li["acao"] += "; recebida (baixa no RM)"
        if criadas or corrigidas:     # rodar de novo sem nada novo nao deixa rastro
            auditoria.registrar(conn, usuario_id, "medicao.carga_historico", "contrato", cid, None,
                                {"arquivo": caminho.name, "criadas": len(criadas), "corrigidas": len(corrigidas),
                                 "linhas": [li["linha"] for li in criadas.values()],
                                 "linhas_corrigidas": [li["linha"] for li in corrigidas]})
    rel["criadas"], rel["corrigidas"] = len(criadas), len(corrigidas)
    return rel


def _criar(conn, usuario_id: int, contrato_id: int, li: dict) -> int:
    d = li["dados"]
    ini, fim = d["periodo"] or (None, None)
    cur = conn.execute(
        "INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, congelada, valor_protocolado_centavos, "
        "valor_protocolado_origem, numero_orgao, periodo_inicio, periodo_fim) "
        "VALUES (?,?,?,?,'protocolada',1,?,?,?,?,?)",
        (contrato_id, d["numero"], d["tipo"], d["competencia"], d["valor_pedido"], "manual", d["numero_orgao"],
         ini, fim))
    mid = cur.lastrowid
    auditoria.registrar(conn, usuario_id, "medicao.criar", "medicao", mid, None,
                        {"numero": d["numero"], "tipo": d["tipo"], "competencia": d["competencia"],
                         "estado": "protocolada", "valor_protocolado_centavos": d["valor_pedido"],
                         "numero_orgao": d["numero_orgao"], "periodo_inicio": ini, "periodo_fim": fim,
                         "origem": "carga do histórico", "linha": li["linha"], "fonte": d["fonte"]})
    if d["data_protocolo_nota"]:
        conn.execute("INSERT INTO medicao_protocolos (medicao_id, data, numero_processo, origem) "
                     "VALUES (?,?,?,'manual')", (mid, d["data_protocolo_nota"], d["processo_orgao"]))
        auditoria.registrar(conn, usuario_id, "medicao.protocolo", "medicao", mid, None,
                            {"data": d["data_protocolo_nota"], "numero_processo": d["processo_orgao"],
                             "origem": "manual"})
    if d["valor_aprovado"] is not None:
        _registrar_atesto(conn, usuario_id, mid, d, None)
    return mid


def _registrar_atesto(conn, usuario_id: int, mid: int, d: dict, antes: dict | None) -> None:
    """Atesto e' evento (039/042): o vigente na medicao e o evento novo entram juntos; o anterior fica na linha do
    tempo. Sem data no CSV, o dia que ja' valia fica (como em `medicoes.definir_valor`)."""
    cur = conn.execute("UPDATE medicoes SET valor_atestado_centavos=?, valor_atestado_origem='manual', "
                       "atestado_em=COALESCE(?, atestado_em) WHERE id=? AND estado NOT IN ('cancelada','desistida')",
                       (d["valor_aprovado"], d["data_aprovacao"], mid))
    db.exigir_uma_linha(cur, "Medição encerrada concorrentemente: o aprovado não pôde ser gravado")
    dia = conn.execute("SELECT atestado_em FROM medicoes WHERE id=?", (mid,)).fetchone()[0]
    conn.execute("INSERT INTO medicao_atestos (medicao_id, valor_centavos, origem, atestado_em, usuario_id, "
                 "meio, numero_orgao, observacao) VALUES (?,?,'manual',?,?,?,?,?)",
                 (mid, d["valor_aprovado"], dia, usuario_id, d["meio"], d["processo_orgao"], d["fonte"]))
    auditoria.registrar(conn, usuario_id, "medicao.valor_atestado", "medicao", mid, antes,
                        {"valor_atestado_centavos": d["valor_aprovado"], "valor_atestado_origem": "manual",
                         "atestado_em": dia, "meio": d["meio"], "fonte": d["fonte"], "origem": "carga do histórico"})


def _corrigir(conn, usuario_id: int, li: dict) -> str:
    """Medicao existente que o documento contradiz. Nada se sobrescreve: o aprovado diferente vira evento novo
    (o vigente e' o ultimo), a competencia errada se corrige com antes/depois na auditoria, e o pedido fica (foi
    congelado no protocolo; so' o primeiro preenchimento, de quem foi protocolada sem valor, passa)."""
    from app import medicoes   # import local: medicoes importa sincronizacao_rm, que importa notas
    d, mid = li["dados"], li["medicao_id"]
    m = conn.execute("SELECT * FROM medicoes WHERE id=?", (mid,)).fetchone()
    feito = []
    if m["competencia"] != d["competencia"]:
        cur = conn.execute("UPDATE medicoes SET competencia=? WHERE id=? AND competencia=?",
                           (d["competencia"], mid, m["competencia"]))
        db.exigir_uma_linha(cur, "Medição alterada concorrentemente: a competência não pôde ser corrigida")
        auditoria.registrar(conn, usuario_id, "medicao.competencia", "medicao", mid,
                            {"competencia": m["competencia"]},
                            {"competencia": d["competencia"], "origem": "carga do histórico", "linha": li["linha"],
                             "fonte": d["fonte"]})
        feito.append(f"competência corrigida de {m['competencia']} para {d['competencia']}")
    if d["valor_aprovado"] is not None and d["valor_aprovado"] != m["valor_atestado_centavos"]:
        _registrar_atesto(conn, usuario_id, mid, d, {"valor_atestado_centavos": m["valor_atestado_centavos"],
                                                     "atestado_em": m["atestado_em"]})
        feito.append("aprovado registrado como evento novo" if m["valor_atestado_centavos"] is not None
                     else "aprovado registrado")
    if d["valor_pedido"] is not None and d["valor_pedido"] != m["valor_protocolado_centavos"]:
        if m["valor_protocolado_centavos"] is None:
            medicoes.definir_valor(conn, usuario_id, mid, "protocolado", d["valor_pedido"], "manual")
            feito.append("pedido preenchido")
        else:
            feito.append("pedido diferente não alterado (congelado no protocolo)")
    return "; ".join(feito) or "já existe"


def _cancelar(conn, usuario_id: int, li: dict) -> str:
    """Duplicata: cancelada com o motivo, nunca apagada; sai da soma do painel e do saldo pelo estado."""
    from app import medicoes
    d = li["dados"]
    motivo = f"Duplicata da medição {d['cancelar']} de {ROTULOS[d['tipo']]} (carga do histórico" + (
        f": {d['fonte']})" if d["fonte"] else ")")
    medicoes.mudar_estado(conn, usuario_id, li["medicao_id"], "cancelada", motivo, origem="carga do histórico")
    return f"cancelada ({motivo})"


def _vincular_nfs(conn, usuario_id: int, medicao_id: int, d: dict, contrato_id: int,
                  coligada: int | None, mapa: tuple) -> tuple[str, bool]:
    """Vincula as NFs do CSV, TODAS ou nenhuma. Devolve (complemento do relatorio, vinculou).

    Cada NF precisa estar no RM da empresa do contrato, ser desta obra pelo centro de custo (o atual ou um dos
    anteriores, a mesma chave da diretoria) e estar livre; e as notas juntas precisam cobrir o valor da medicao.
    Faltando qualquer uma, nenhuma entra: uma nota vinculada que cobre so' parte (medicao em duas notas, padrao
    MT-388, com uma fora do CSV) seria dada como recebida pela sincronizacao seguinte com o RM, que so' segura
    cobertura parcial depois de vinculo desfeito a mao (revisor da #259). A medicao fica protocolada sem nota,
    e a nota segue no a receber pelo centro de custo, como hoje."""
    from app import sincronizacao_rm   # import local: importa medicoes e notas
    if not d["nfs"]:
        return "", False
    rotulo = "/".join(d["nfs"])
    if coligada is None:
        return f"; NF {rotulo} não vinculada (empresa do contrato sem coligada no RM)", False
    _, por_centro, por_coligada = mapa
    centros = {cc for (col, cc), donos in por_centro.items() if col == coligada and contrato_id in donos}
    # Contrato sem centro so' se identifica pela coligada quando ela isola a obra (consorcio: uma coligada, um
    # contrato), como na diretoria; na Lotufo (muitas obras, uma coligada) nao ha' como saber de que obra e' a NF
    if not centros and por_coligada.get(coligada) != [contrato_id]:
        return f"; NF {rotulo} não vinculada (o contrato não tem centro de custo do RM no cadastro)", False
    achadas, problemas = [], []
    for nf in d["nfs"]:
        numero = int(nf) if nf.isdigit() and len(nf) <= 18 else None
        notas = conn.execute("SELECT id, valor_centavos, centro_custo FROM notas_fiscais WHERE coligada=? AND "
                             "situacao='ativa' AND (numero=? OR numero_int=?)", (coligada, nf, numero)).fetchall()
        if len(notas) != 1:
            problemas.append(f"NF {nf} não encontrada no RM" if not notas
                             else f"NF {nf} com mais de uma nota com esse número no RM")
            continue
        cc = (notas[0]["centro_custo"] or "").strip()
        donos = por_centro.get((coligada, cc), []) if cc else []
        if any(n["id"] == notas[0]["id"] for n in achadas):
            problemas.append(f"NF {nf} repetida na linha")
        elif centros and donos != [contrato_id]:
            # o centro tem de ser DESTA obra e so' dela: centro de outra obra, ou dividido entre duas, nao serve
            problemas.append(f"NF {nf} é de outra obra no RM, pelo centro de custo" if contrato_id not in donos
                             else f"NF {nf} tem centro de custo de mais de uma obra no cadastro")
        elif not centros and donos:
            problemas.append(f"NF {nf} é de outra obra no RM, pelo centro de custo")
        elif conn.execute("SELECT 1 FROM nf_alocacoes WHERE nota_id=? AND desfeita_em IS NULL",
                          (notas[0]["id"],)).fetchone():
            problemas.append(f"NF {nf} já está em outra medição")
        else:
            achadas.append(notas[0])
    if problemas:
        return f"; NF {rotulo} não vinculada ({'; '.join(problemas)})", False
    valor = conn.execute("SELECT COALESCE(valor_atestado_centavos, valor_protocolado_centavos) FROM medicoes "
                         "WHERE id=?", (medicao_id,)).fetchone()[0]
    soma = sum(n["valor_centavos"] for n in achadas)
    # Sem tolerancia: a de R$ 1,00 (issue #35) e' do pagamento do titulo, nao da nota que fatura a medicao
    if soma < valor:
        return (f"; NF {rotulo} não vinculada (as notas somam {dinheiro.format_brl(soma)} e a medição vale "
                f"{dinheiro.format_brl(valor)}: falta nota no CSV)"), False
    for n in achadas:
        sincronizacao_rm.alocar(conn, usuario_id, n["id"], medicao_id, "manual", None, "carga_historico")
    return f"; NF {rotulo} vinculada", True
