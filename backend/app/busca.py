"""Busca unica do topo (issue #819; decisao do dono de 18/11/2026, #805): obra, numero de medicao e numero de processo.

Uma consulta so', com o recorte do perfil aplicado AQUI: o perfil sem `ver_siga` (a mesma regra da tela SIGA, #829)
nao recebe o grupo de processos, nem a contagem dele.

Como a pergunta e' lida (sem acento e sem caixa: "Medição" = "medicao", "15ª" = "15a"):
- Obras: cada palavra da pergunta aparece no apelido, no instrumento, no nome da obra, no contratante, no sub-orgao
  ou no municipio. O hifen e a barra nao atrapalham: "mt388" acha "MT-388". A pergunta que e' so' um numero de
  medicao ("15") acha obra so' pelo nome, nao pelo instrumento.
- Medicoes: a pergunta tem um numero solto ("15", "15ª", "15a"); as outras palavras, se houver, filtram a obra
  ("MT-388 15"). "medicao", "reajuste" e "projeto" escolhem o tipo ou somem da conta.
- Processos: cada palavra aparece no numero do SIGA, no codigo, no nome que o robo leu, no complemento ou no nome
  montado (obra e assunto).
Cada grupo devolve no maximo LIMITE itens e o total que casou. Nada de valor em reais sai daqui.

A medicao que nao anda (prevista, cancelada ou desistida) continua no resultado (a pagina dela abre, e quem procura
uma cancelada quer acha'-la), com o estado em `estado`; a viva vem com `estado` nulo (revisao da #819). A obra sai so'
com o que a linha do resultado desenha (o instrumento ficou de fora: a tela nao o usa).
"""
import re
import sqlite3
import unicodedata

from app import medicoes, siga
from app.permissoes import VER_SIGA, tem

LIMITE = 8
MAX_PERGUNTA = 100
# os estados em que a medicao nao anda: saem escritos na linha do resultado
ESTADOS_MARCADOS = ("prevista", "cancelada", "desistida")

# Quem abre o SIGA: a permissao unica `ver_siga` (issue #829), a mesma da rota da tela, da aba do contratante, do menu
# e do App. Desde a decisao do dono de 19/11/2026 a diretoria tambem a tem (so' para ler).
def ve_siga(perfil: str) -> bool:
    return tem(perfil, VER_SIGA)


def normalizar(texto: str | None) -> str:
    """Sem acento, sem caixa e com os ordinais abertos: "15ª Medição" -> "15a medicao"."""
    s = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _compacto(s: str) -> str:
    return re.sub(r"[^0-9a-z]", "", s)


def _casa(palavra: str, alvo: str, alvo_compacto: str) -> bool:
    if palavra in alvo:
        return True
    c = _compacto(palavra)
    return bool(c) and c in alvo_compacto


def _todas(palavras: list[str], alvo: str) -> bool:
    compacto = _compacto(alvo)
    return all(_casa(p, alvo, compacto) for p in palavras)


_NUMERO = re.compile(r"^(?:n[o.]?)?(\d{1,4})[ao]?\.?$")     # "15", "15a", "15o" (ordinal aberto), "n15", "no15"
_PALAVRAS_DE_MEDICAO = {"medicao", "medicoes", "med", "med.", "da", "de", "do", "e", "execucao"}
_TIPOS = {"reajuste": "reajuste", "projeto": "projeto"}


def _palavras(pergunta: str) -> list[str]:
    return [p.strip(",;:()") for p in normalizar(pergunta).split() if p.strip(",;:()")]


def ler_pergunta(pergunta: str) -> dict:
    """As palavras e, quando ha', o numero da medicao (o ultimo numero solto) e o tipo pedido."""
    palavras = _palavras(pergunta)
    numero, i_numero = None, None
    for i, p in enumerate(palavras):
        m = _NUMERO.match(p)
        if m:
            numero, i_numero = int(m.group(1)), i
    tipo = next((_TIPOS[p] for p in palavras if p in _TIPOS), None)
    da_obra = [p for i, p in enumerate(palavras)
               if i != i_numero and p not in _PALAVRAS_DE_MEDICAO and p not in _TIPOS]
    return {"palavras": palavras, "numero": numero, "tipo": tipo, "da_obra": da_obra}


def _obras(conn: sqlite3.Connection) -> list[dict]:
    saida = []
    for r in conn.execute(
            "SELECT c.id, c.nome_curto, c.numero_instrumento, c.orgao AS orgao_texto, c.municipio, "
            "ob.nome AS obra_nome, o.familia, o.chave, o.nome FROM contratos c "
            "LEFT JOIN orgaos o ON o.id=c.orgao_id LEFT JOIN obras ob ON ob.id=c.obra_id ORDER BY c.id"):
        contratante, sub = medicoes.contratante(r["familia"], r["chave"], r["nome"], r["orgao_texto"])
        nome = r["nome_curto"] or r["numero_instrumento"]
        alvo = normalizar(" ".join(x for x in (r["nome_curto"], r["numero_instrumento"], r["obra_nome"], contratante,
                                               sub, r["municipio"]) if x))
        saida.append({"id": r["id"], "nome": nome, "contratante": contratante, "orgao_sub": sub,
                      "_alvo": alvo, "_nome": normalizar(nome)})
    return saida


def _ordem_da_obra(o: dict, palavras: list[str]) -> tuple:
    """O apelido que comeca com a pergunta vem antes; depois o que a contem; depois o resto, por nome."""
    junta = " ".join(palavras)
    return (not o["_nome"].startswith(junta), junta not in o["_nome"], o["_nome"])


def _publica(o: dict) -> dict:
    return {k: v for k, v in o.items() if not k.startswith("_")}


def buscar(conn: sqlite3.Connection, pergunta: str, perfil: str) -> dict:
    q = ler_pergunta(pergunta[:MAX_PERGUNTA])
    grupos: dict = {"obras": {"itens": [], "total": 0}, "medicoes": {"itens": [], "total": 0}}
    com_siga = ve_siga(perfil)
    if com_siga:
        grupos["processos"] = {"itens": [], "total": 0}
    if not q["palavras"]:
        return grupos

    obras = _obras(conn)
    # so' o numero da medicao ("15", "15ª"): a obra casa pelo nome, nao pelo instrumento ("155/2022" nao e' a 15ª)
    so_numero = q["numero"] is not None and not q["da_obra"]
    casadas = sorted((o for o in obras if _todas(q["palavras"], o["_nome"] if so_numero else o["_alvo"])),
                     key=lambda o: _ordem_da_obra(o, q["palavras"]))
    grupos["obras"] = {"itens": [_publica(o) for o in casadas[:LIMITE]], "total": len(casadas)}

    if q["numero"] is not None:
        da_obra = {o["id"]: o for o in obras if _todas(q["da_obra"], o["_alvo"])}
        if da_obra:
            sql = "SELECT id, contrato_id, numero, tipo, competencia, estado FROM medicoes WHERE numero=?"
            args: list = [q["numero"]]
            if q["tipo"]:
                sql += " AND tipo=?"
                args.append(q["tipo"])
            linhas = [r for r in conn.execute(sql + " ORDER BY competencia DESC, contrato_id, tipo='reajuste', id", args)
                      if r["contrato_id"] in da_obra]
            grupos["medicoes"] = {"total": len(linhas), "itens": [
                {"id": r["id"], "contrato_id": r["contrato_id"], "titulo": medicoes.titulo(dict(r)),
                 "competencia": r["competencia"], "obra": da_obra[r["contrato_id"]]["nome"],
                 "contratante": da_obra[r["contrato_id"]]["contratante"],
                 "estado": r["estado"] if r["estado"] in ESTADOS_MARCADOS else None}
                for r in linhas[:LIMITE]]}

    if com_siga:
        grupos["processos"] = _processos(conn, q["palavras"], {o["id"]: o for o in obras})
    return grupos


def _processos(conn: sqlite3.Connection, palavras: list[str], obras: dict[int, dict]) -> dict:
    casados = []
    for p in conn.execute(
            "SELECT sp.id, sp.codigo, sp.numero, sp.nome, sp.contrato_id, sp.medicao_id, sp.protocolo_id, "
            "sp.categoria, sp.complemento, m.numero AS m_numero, m.tipo AS m_tipo "
            "FROM siga_processos sp LEFT JOIN medicoes m ON m.id=sp.medicao_id ORDER BY sp.id DESC"):
        # o mesmo nome que a tela SIGA mostra (siga.painel e nomeDoProcesso em siga.ts): "<obra> · <o que e'>"
        categoria = siga._categoria(p)
        if categoria == "outros":
            categoria = siga.categoria_sugerida(p["nome"]) or categoria
        titulo_medicao = medicoes.titulo({"numero": p["m_numero"], "tipo": p["m_tipo"]}) if p["medicao_id"] \
            else siga._titulo_das_medicoes(conn, None, p["protocolo_id"])
        obra = obras.get(p["contrato_id"]) if p["contrato_id"] else None
        assunto = f"{obra['nome']} · {siga.o_que_e(categoria, p['complemento'], titulo_medicao)}" if obra \
            else p["complemento"] or p["nome"] or p["numero"] or p["codigo"] or "Processo sem nome"
        alvo = normalizar(" ".join(x for x in (p["numero"], p["codigo"], p["nome"], p["complemento"], assunto) if x))
        if _todas(palavras, alvo):
            casados.append({"id": p["id"], "numero": p["numero"], "assunto": assunto})
    return {"itens": casados[:LIMITE], "total": len(casados)}
