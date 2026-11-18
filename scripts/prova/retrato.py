"""Retrato das respostas da API, antes e depois de uma mudanca (issue #702).

Com o servidor de prova no ar (`servidor.py`, mesmas DASH_DB_PATH e DASH_CADASTRO_DIR):

  python3 scripts/prova/retrato.py tirar antes          # guarda a resposta de cada rota de leitura
  ... aplica a mudanca (codigo, cadastro, comando) e sobe o servidor de novo ...
  python3 scripts/prova/retrato.py tirar depois
  python3 scripts/prova/retrato.py comparar antes depois   # diz o que mudou, rota por rota

`tirar` entra como o usuario de teste do perfil (`--perfil`, padrao admin), pede cada rota de `ROTAS` (as com
`{contrato}`, `{medicao}`... uma vez por registro; `--contrato N` restringe a uma obra) e grava um JSON por rota em
`<saida>/retrato/<rotulo>/`, com o status e o corpo. Rota que responde 404 ou 422 tambem entra: o retrato registra
o que a API diz, nao julga.

`comparar` recebe dois rotulos (ou duas pastas) e lista rota que apareceu ou sumiu, status que mudou e cada campo
diferente, com o caminho dentro do JSON. Lista de registros com `id` e' casada pelo id. `--ignorar campo` tira da
conta um campo que muda sozinho (ex.: `hoje`). Sai com 0 se nada mudou e 1 se mudou.

A saida de uma copia do banco tem dado real: ela mora fora do repositorio (ver `comum.py`). So' biblioteca padrao.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import http.cookiejar
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comum  # noqa: E402

# Rotas de leitura que entram no retrato. Um marcador por rota, no maximo; os ids saem de `FONTES`.
# Rota GET nova no backend entra aqui ou em `FORA`, com o motivo: `backend/tests/test_prova.py` cobra as duas listas
# contra as rotas de verdade.
ROTAS = (
    "/api/inicio",
    "/api/inicio/painel",
    "/api/medicoes/andamento",
    "/api/medicoes/resumo",
    "/api/medicoes/fila",
    "/api/contratos",
    "/api/contratos/{contrato}",
    "/api/contratos/{contrato}/cabecalho",
    "/api/contratos/{contrato}/ficha",
    "/api/contratos/{contrato}/cadastro",
    "/api/contratos/{contrato}/aditivos",
    "/api/contratos/{contrato}/cronograma",
    "/api/contratos/{contrato}/cronograma/versoes",
    "/api/contratos/{contrato}/curva",
    "/api/contratos/{contrato}/custo",
    "/api/contratos/{contrato}/custo-grupos",
    "/api/contratos/{contrato}/custo-rm",
    "/api/contratos/{contrato}/espelho",
    "/api/contratos/{contrato}/medicoes",
    "/api/contratos/{contrato}/notas",
    "/api/contratos/{contrato}/planilhas/sugestao",
    "/api/contratos/{contrato}/prazos",
    "/api/contratos/{contrato}/protocolos",
    "/api/contratos/{contrato}/reajuste",
    "/api/contratos/{contrato}/checklist-protocolo",
    "/api/medicoes/{medicao}",
    "/api/medicoes/{medicao}/grupos",
    "/api/medicoes/{medicao}/notas",
    "/api/medicoes/{medicao}/par",
    "/api/medicoes/{medicao}/frc",
    "/api/medicoes/{medicao}/planilhas/comparacao",
    "/api/medicoes/{medicao}/respostas-orgao",
    "/api/protocolos/{protocolo}",
    "/api/notas/envio/{protocolo}",
    "/api/pleitos/{pleito}",
    "/api/espelhos/{espelho}",
    "/api/espelhos/{espelho}/envio",
    "/api/diretoria",
    "/api/fechamento",
    "/api/resumo-medicoes",
    "/api/documentos",
    "/api/entidades",
    "/api/certidoes/tipos",
    "/api/notas/a-enviar",
    "/api/notas/aguardando-pagamento",
    "/api/paineis/alertas",
    "/api/rm/status",
    "/api/rm/reconciliacao",
    "/api/siga",
    "/api/admin/pendencias-cadastro",
    "/api/admin/usuarios",
)

# De onde saem os ids de cada marcador: (rota que lista, caminho ate' a lista dentro da resposta). Mais de uma
# fonte por marcador soma. As que dependem de `{contrato}` rodam uma vez por contrato.
FONTES = {
    "contrato": (("/api/contratos", ()),),
    "medicao": (("/api/contratos/{contrato}/medicoes", ()),),
    "protocolo": (("/api/contratos/{contrato}/protocolos", ("protocolos",)),),
    "pleito": (("/api/contratos/{contrato}/reajuste", ("pleitos",)), ("/api/contratos/{contrato}/prazos", ("pleitos",))),
    "espelho": (("/api/contratos/{contrato}/espelho", ("espelhos",)),),
}

# Rotas GET que ficam de fora, com o motivo. A chave e' o caminho como o backend declara.
_ARQUIVO = "devolve arquivo (PDF, planilha, zip), não JSON"
_SESSAO = "muda a cada sessão ou a cada minuto (acesso, auditoria, saúde): só faria ruído na comparação"
_CORREIO = "estado da caixa de e-mail de quem está logado; no servidor de prova é o simulador"
_PARAMETRO = "só responde com os parâmetros que a tela manda (número, competência, período)"
FORA = {
    "/api/health": _SESSAO,
    "/api/auth/eu": _SESSAO,
    "/api/auth/acessos": _SESSAO,
    "/api/admin/auditoria": _SESSAO,
    "/api/admin/saude": _SESSAO,
    "/api/admin/backup": _SESSAO,
    "/api/admin/usuarios/{alvo_id}/acessos": _SESSAO,
    "/api/admin/contas-microsoft": _CORREIO,
    "/api/correio/status": _CORREIO,
    "/api/correio/remetente": _CORREIO,
    "/api/correio/contatos": _CORREIO,
    "/api/correio/assinatura": _CORREIO,
    "/api/correio/respostas/nao-vistas": _CORREIO,
    "/api/contratos/{contrato_id}/reajuste/sugestao": _PARAMETRO,
    "/api/contratos/{contrato_id}/planilhas/avisos": _PARAMETRO,
    "/api/contratos/{contrato_id}/medicoes.csv": _ARQUIVO,
    "/api/resumo-medicoes.csv": _ARQUIVO,
    "/api/certidoes/{certidao_id}/arquivo": _ARQUIVO,
    "/api/diretoria/qdop.xlsx": _ARQUIVO,
    "/api/documentos/zip": _ARQUIVO,
    "/api/documentos/regularidades/{rid}/arquivo": _ARQUIVO,
    "/api/espelhos/{espelho_id}/arquivos/{documento_id}": _ARQUIVO,
    "/api/medicoes/{medicao_id}/boletins/{atesto_id}": _ARQUIVO,
    "/api/medicoes/{medicao_id}/documentos/{documento_id}": _ARQUIVO,
    "/api/medicoes/{medicao_id}/frc/{formato}": _ARQUIVO,
    "/api/medicoes/{medicao_id}/planilhas/{planilha_id}/{peca}": _ARQUIVO,
    "/api/medicoes/{mid}/assinados/{assinatura_id}": _ARQUIVO,
    "/api/pleitos/{pid}/documento": _ARQUIVO,
    "/api/protocolos/{pid}/pacote": _ARQUIVO,
    "/api/protocolos/{pid}/assinado": _ARQUIVO,
    "/api/protocolos/{pid}/comprovante": _ARQUIVO,
}

_MARCADOR = re.compile(r"\{([^}]+)\}")


def forma(rota: str) -> str:
    """A rota sem o nome dos marcadores: `/api/contratos/{}/medicoes`. E' como as listas daqui se comparam com as
    rotas do backend, que chamam o mesmo id de `contrato_id`, `mid` ou `pid`."""
    return _MARCADOR.sub("{}", rota)


def marcador(rota: str) -> str | None:
    achados = _MARCADOR.findall(rota)
    if len(achados) > 1:
        raise ValueError(f"rota com mais de um marcador não entra no retrato: {rota}")
    return achados[0] if achados else None


# --- comparador (puro) ------------------------------------------------------------------------------------------

AUSENTE = object()


def _mostra(valor, largura: int = 90) -> str:
    if valor is AUSENTE:
        return "(não tem)"
    texto = json.dumps(valor, ensure_ascii=False, sort_keys=True)
    return texto if len(texto) <= largura else texto[:largura - 1] + "…"


def _por_id(lista: list) -> dict | None:
    """A lista como `{id: item}` quando todo item e' um registro com `id` e nenhum id se repete."""
    if not lista or not all(isinstance(i, dict) and "id" in i for i in lista):
        return None
    try:
        mapa = {i["id"]: i for i in lista}
    except TypeError:      # id que nao serve de chave
        return None
    return mapa if len(mapa) == len(lista) else None


def diferencas(antes, depois, ignorar=frozenset(), caminho: str = "") -> list:
    """Cada ponto em que `depois` difere de `antes`: lista de (caminho no JSON, valor antes, valor depois)."""
    if isinstance(antes, dict) and isinstance(depois, dict):
        achadas = []
        for chave in sorted({*antes, *depois}, key=str):
            if chave in ignorar:
                continue
            onde = f"{caminho}.{chave}" if caminho else str(chave)
            if chave not in antes:
                achadas.append((onde, AUSENTE, depois[chave]))
            elif chave not in depois:
                achadas.append((onde, antes[chave], AUSENTE))
            else:
                achadas += diferencas(antes[chave], depois[chave], ignorar, onde)
        return achadas
    if isinstance(antes, list) and isinstance(depois, list):
        a, d = _por_id(antes), _por_id(depois)
        if (a is not None or not antes) and (d is not None or not depois) and (antes or depois):
            a, d, achadas = a or {}, d or {}, []
            for i in sorted({*a, *d}, key=lambda x: (str(type(x)), x)):
                onde = f"{caminho}[id={i}]"
                if i not in a:
                    achadas.append((onde, AUSENTE, d[i]))
                elif i not in d:
                    achadas.append((onde, a[i], AUSENTE))
                else:
                    achadas += diferencas(a[i], d[i], ignorar, onde)
            # mesmos registros em outra ordem tambem e' mudanca (a tela mostra na ordem da resposta)
            comuns_antes = [i["id"] for i in antes if i["id"] in d]
            comuns_depois = [i["id"] for i in depois if i["id"] in a]
            if comuns_antes != comuns_depois:
                achadas.append((f"{caminho}[ordem]", comuns_antes, comuns_depois))
            return achadas
        achadas = []
        for n in range(max(len(antes), len(depois))):
            onde = f"{caminho}[{n}]"
            if n >= len(antes):
                achadas.append((onde, AUSENTE, depois[n]))
            elif n >= len(depois):
                achadas.append((onde, antes[n], AUSENTE))
            else:
                achadas += diferencas(antes[n], depois[n], ignorar, onde)
        return achadas
    # 1 e 1.0 sao o mesmo numero no JSON, mas True nao e' 1
    if type(antes) is not type(depois) and not ({type(antes), type(depois)} <= {int, float}):
        return [(caminho, antes, depois)]
    return [] if antes == depois else [(caminho, antes, depois)]


def comparar(antes: dict, depois: dict, ignorar=frozenset(), limite: int = 40) -> list:
    """Compara dois retratos (`{rota: {"status": n, "corpo": ...}}`) e devolve as linhas do relatorio; lista vazia
    quer dizer que nada mudou. `limite` corta as diferencas mostradas por rota (a contagem continua inteira)."""
    linhas = []
    for rota in sorted({*antes, *depois}):
        if rota not in antes:
            linhas.append(f"{rota}: só no depois (status {depois[rota]['status']})")
            continue
        if rota not in depois:
            linhas.append(f"{rota}: só no antes (status {antes[rota]['status']})")
            continue
        a, d = antes[rota], depois[rota]
        achadas = diferencas(a.get("corpo"), d.get("corpo"), frozenset(ignorar))
        if a["status"] == d["status"] and not achadas:
            continue
        linhas.append(f"{rota}: " + (f"status {a['status']} → {d['status']}" if a["status"] != d["status"]
                                     else f"{len(achadas)} diferença(s)"))
        for onde, x, y in achadas[:limite]:
            linhas.append(f"  {onde or '(resposta inteira)'}: {_mostra(x)} → {_mostra(y)}")
        if len(achadas) > limite:
            linhas.append(f"  … e mais {len(achadas) - limite} (use --limite para ver)")
    return linhas


# --- tirar ------------------------------------------------------------------------------------------------------

class Cliente:
    """Sessao no servidor de prova: entra pela mesma rota da tela e guarda o cookie."""

    def __init__(self, base: str, email: str, senha: str):
        self.base = base
        self._abrir = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())).open
        pedido = urllib.request.Request(f"{base}/api/auth/login", method="POST",
                                        data=json.dumps({"email": email, "senha": senha}).encode(),
                                        headers={"Content-Type": "application/json"})
        try:
            self._abrir(pedido, timeout=30).read()
        except urllib.error.HTTPError as e:
            raise comum.Recusa(f"Não entrou como {email} (status {e.code}). O servidor de prova é o deste banco?")
        except (urllib.error.URLError, OSError) as e:
            raise comum.Recusa(f"O servidor de prova não respondeu em {base} ({e}). Suba com servidor.py.")

    def ler(self, rota: str) -> dict:
        try:
            with self._abrir(f"{self.base}{rota}", timeout=60) as r:
                status, tipo, bruto = r.status, r.headers.get("content-type", ""), r.read()
        except urllib.error.HTTPError as e:
            status, tipo, bruto = e.code, e.headers.get("content-type", ""), e.read()
        if "json" in tipo:
            try:
                return {"status": status, "corpo": json.loads(bruto)}
            except ValueError:
                pass
        return {"status": status, "corpo": {"tipo": tipo, "bytes": len(bruto),
                                            "sha256": hashlib.sha256(bruto).hexdigest()}}


def _lista(corpo, caminho: tuple) -> list:
    for chave in caminho:
        corpo = corpo.get(chave) if isinstance(corpo, dict) else None
    return corpo if isinstance(corpo, list) else []


def ids_dos_marcadores(ler, contratos: list | None = None) -> dict:
    """Os ids de cada marcador de `FONTES`, lidos da propria API. `ler(rota)` devolve `{"status", "corpo"}`."""
    def ids(rota, caminho):
        return [i["id"] for i in _lista(ler(rota).get("corpo"), caminho) if isinstance(i, dict) and "id" in i]

    achados = {"contrato": [i for rota, caminho in FONTES["contrato"] for i in ids(rota, caminho)]}
    if contratos:
        achados["contrato"] = [i for i in achados["contrato"] if i in contratos]
    for nome, fontes in FONTES.items():
        if nome == "contrato":
            continue
        vistos = []
        for rota, caminho in fontes:
            for c in achados["contrato"] if "{contrato}" in rota else [None]:
                vistos += ids(rota.replace("{contrato}", str(c)), caminho)
        achados[nome] = sorted(set(vistos))
    return achados


def rotas_do_retrato(ids: dict) -> list:
    """`ROTAS` com cada marcador trocado pelos ids: a lista de caminhos que o retrato pede."""
    caminhos = []
    for rota in ROTAS:
        m = marcador(rota)
        caminhos += [rota] if m is None else [rota.replace("{" + m + "}", str(i)) for i in ids[m]]
    return caminhos


def arquivo_da_rota(rota: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "__", rota.strip("/")) + ".json"


def pasta_do_retrato(saida: Path, rotulo: str, raiz: Path = comum.RAIZ, base: Path | None = None) -> Path:
    """Rotulo simples vira `<saida>/retrato/<rotulo>`; com barra, e' um caminho de pasta. O caminho passa pela
    mesma recusa da saida (`comum.saida_de_prova`): o retrato de uma copia do banco tem dado real, e dentro do
    repositorio so' pode morar em `.prova/`."""
    if re.fullmatch(r"[A-Za-z0-9._-]+", rotulo):
        return saida / "retrato" / rotulo
    return comum.saida_permitida(comum.absoluto(rotulo, base), f"O retrato '{rotulo}'", raiz)


def tirar(args) -> int:
    banco = comum.banco_de_prova()
    comum.cadastro_de_prova()
    arquivo = comum.arquivos_da_prova(banco)["servidor"]
    if not arquivo.exists():
        raise comum.Recusa(f"O servidor de prova deste banco não está no ar (falta {arquivo.name} ao lado do banco). "
                           "Suba com: python3 scripts/prova/servidor.py")
    servidor = json.loads(arquivo.read_text(encoding="utf-8"))
    saida = comum.saida_de_prova(banco=banco)
    pasta = pasta_do_retrato(saida, args.rotulo)
    if pasta.exists() and any(pasta.iterdir()):
        if not args.sobrescrever:
            raise comum.Recusa(f"Já existe um retrato em {pasta}. Use outro rótulo ou --sobrescrever.")
        for velho in pasta.glob("*.json"):
            velho.unlink()
    pasta.mkdir(parents=True, exist_ok=True)

    senha = Path(servidor["senha"]).read_text(encoding="utf-8").strip()
    cliente = Cliente(servidor["base"], servidor["usuarios"][args.perfil], senha)
    ids = ids_dos_marcadores(cliente.ler, args.contrato)
    if args.contrato and sorted(ids["contrato"]) != sorted(set(args.contrato)):
        raise comum.Recusa(f"--contrato pede {sorted(set(args.contrato))} e o banco só tem {ids['contrato']} deles.")
    indice = []
    for rota in rotas_do_retrato(ids):
        resposta = cliente.ler(rota)
        nome = arquivo_da_rota(rota)
        (pasta / nome).write_text(json.dumps({"rota": rota, **resposta}, ensure_ascii=False, indent=1, sort_keys=True),
                                  encoding="utf-8")
        indice.append({"rota": rota, "status": resposta["status"], "arquivo": nome})
    (pasta / "indice.json").write_text(json.dumps({
        "rotulo": args.rotulo, "perfil": args.perfil, "tirado_em": datetime.datetime.now().isoformat(timespec="seconds"),
        "contratos": ids["contrato"], "rotas": indice}, ensure_ascii=False, indent=1), encoding="utf-8")
    por_status: dict = {}
    for i in indice:
        por_status[i["status"]] = por_status.get(i["status"], 0) + 1
    print(f"retrato '{args.rotulo}' ({args.perfil}): {len(indice)} rota(s) em {pasta}")
    print("  status: " + ", ".join(f"{s}: {n}" for s, n in sorted(por_status.items())))
    return 0


def ler_retrato(pasta: Path) -> dict:
    indice = pasta / "indice.json"
    if not indice.exists():
        raise comum.Recusa(f"Não há retrato em {pasta} (falta indice.json).")
    retrato = {}
    for item in json.loads(indice.read_text(encoding="utf-8"))["rotas"]:
        dados = json.loads((pasta / item["arquivo"]).read_text(encoding="utf-8"))
        retrato[dados["rota"]] = {"status": dados["status"], "corpo": dados.get("corpo")}
    return retrato


def comparar_pastas(args) -> int:
    so_caminhos = all(not re.fullmatch(r"[A-Za-z0-9._-]+", r) for r in (args.antes, args.depois))
    saida = Path() if so_caminhos else comum.saida_de_prova()
    antes, depois = (ler_retrato(pasta_do_retrato(saida, r)) for r in (args.antes, args.depois))
    linhas = comparar(antes, depois, frozenset(args.ignorar or ()), args.limite)
    if not linhas:
        print(f"nada mudou: {len(antes)} rota(s) iguais em '{args.antes}' e '{args.depois}'")
        return 0
    print(f"mudou de '{args.antes}' para '{args.depois}':")
    print("\n".join(linhas))
    return 1


def main(argv: list | None = None) -> int:
    p = argparse.ArgumentParser(description="Retrato das respostas da API do servidor de prova, e a comparação.")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tirar", help="guarda a resposta de cada rota de leitura")
    t.add_argument("rotulo", help="nome do retrato (ex.: antes, depois)")
    t.add_argument("--perfil", choices=comum.PERFIS, default="admin")
    t.add_argument("--contrato", type=int, action="append", help="só este contrato (id); pode repetir")
    t.add_argument("--sobrescrever", action="store_true")
    c = sub.add_parser("comparar", help="diz o que mudou entre dois retratos")
    c.add_argument("antes")
    c.add_argument("depois")
    c.add_argument("--ignorar", action="append", help="campo que não entra na comparação; pode repetir")
    c.add_argument("--limite", type=int, default=40, help="diferenças mostradas por rota (padrão 40)")
    args = p.parse_args(argv)
    try:
        return tirar(args) if args.cmd == "tirar" else comparar_pastas(args)
    except comum.Recusa as e:
        print(f"RECUSADO: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
