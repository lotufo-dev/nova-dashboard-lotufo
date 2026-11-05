"""Integridade do codigo em producao (issue #421): avisa quando o clone ou o `frontend\\dist` mudaram fora do deploy.

O `scripts/deploy.ps1` chama `python -m app.cli integridade registrar --raiz <raiz>` e isto grava
`<raiz>/deploy-atual.json`: o commit, a data e o sha256 do manifesto de `frontend/dist` (caminho relativo e sha256 de
cada arquivo, em ordem). O servidor confere, na subida e de hora em hora (`agendar`), tres coisas:

- `git rev-parse HEAD` do clone igual ao commit gravado;
- `git status --porcelain` vazio, respeitando o `.gitignore` (venv, node_modules e dist ja' ficam de fora);
- o manifesto do `dist` igual ao gravado.

O git roda com `-c safe.directory=<clone>`: o servidor e' SYSTEM e o clone pertence aos Administradores. O resultado
fica em `ESTADO` e o bloco Seguranca (`seguranca.itens`) o le; a mensagem diz quantos arquivos, nunca quais nem onde.
Cada diferenca nova grava uma linha `seguranca.arvore_alterada` na auditoria; a mesma diferenca nas horas seguintes
nao grava de novo. Em dev (`DASH_DEV=1`) nada roda. Enquanto o deploy esta' rodando (`watchdog.pause` na raiz) a
conferencia espera: o build esvazia o `dist` e a producao ainda nao tem o registro novo.
"""
import datetime
import hashlib
import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path

from app import auditoria, db, tempo

log = logging.getLogger("app.integridade")

ARQUIVO_REGISTRO = "deploy-atual.json"
ARQUIVO_PAUSA = "watchdog.pause"
INTERVALO_SEG = 3600
PRAZO_GIT_SEG = 60
ESPERA_PAUSA_SEG = 60

OK, DIFERENTE, SEM_REGISTRO, ERRO = "ok", "diferente", "sem_registro", "erro"
TITULO_DIFERENTE = "Código em produção diferente do último deploy"
TITULO_SEM_REGISTRO = "Sem registro do último deploy"
TITULO_ERRO = "Não foi possível conferir o código em produção"

# Ultima conferencia: {estado, detalhe, data (ISO UTC da primeira vez que viu esta diferenca), assinatura}; None = nao
# rodou nesta execucao (dev, testes, ou antes da primeira conferencia).
ESTADO: dict | None = None
_anterior: str | None = None      # assinatura da conferencia anterior desta execucao ("" = estava sem diferenca)
_commit: str | None = None
_commit_lido = False


def clone_padrao() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def raiz_padrao() -> Path | None:
    """A pasta acima de `dados`, onde mora o banco (a mesma conta de `instalacao.caminho_arquivo`)."""
    banco = os.environ.get("DASH_DB_PATH")
    return Path(banco).parent.parent if banco else None


def _git(clone: Path, *args: str) -> str:
    r = subprocess.run(["git", "-c", f"safe.directory={clone.as_posix()}", "--no-optional-locks", "-C", str(clone), *args],
                       capture_output=True, text=True, timeout=PRAZO_GIT_SEG, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"git {args[0]} falhou (codigo {r.returncode})")
    return r.stdout


def commit_do_clone(clone: Path) -> str:
    return _git(clone, "rev-parse", "HEAD").strip()


def commit_atual() -> str | None:
    """Os 7 primeiros caracteres do commit do clone, lidos uma vez (e' o codigo que esta' rodando); `None` se o git
    nao responde. O /api/health mostra isto."""
    global _commit, _commit_lido
    if not _commit_lido:
        try:
            _commit = commit_do_clone(clone_padrao())[:7]
        except (RuntimeError, OSError, subprocess.SubprocessError):
            _commit = None
        _commit_lido = True
    return _commit


def arquivos_alterados(clone: Path) -> list[str]:
    """As linhas do `git status --porcelain` (arquivo novo conta, o ignorado nao). Cada arquivo de pasta nova conta."""
    return [ln for ln in _git(clone, "status", "--porcelain", "--untracked-files=all").splitlines() if ln.strip()]


def arquivos_do_dist(dist: Path) -> dict[str, str]:
    """Caminho relativo (com `/`) -> sha256 do conteudo, de cada arquivo do `dist`."""
    out = {}
    if dist.is_dir():
        for p in sorted(dist.rglob("*")):
            if p.is_file():
                out[p.relative_to(dist).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def manifesto(arquivos: dict[str, str]) -> str:
    """sha256 da lista ordenada `caminho<TAB>sha256` de cada arquivo."""
    texto = "".join(f"{caminho}\t{sha}\n" for caminho, sha in sorted(arquivos.items()))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def registrar_deploy(raiz: Path, clone: Path | None = None, agora: datetime.datetime | None = None) -> dict:
    """Grava `<raiz>/deploy-atual.json` para o commit e o `dist` que estao no clone agora (o deploy e o rollback chamam)."""
    clone = clone or clone_padrao()
    arquivos = arquivos_do_dist(clone / "frontend" / "dist")
    registro = {"commit": commit_do_clone(clone), "data": (agora or tempo.agora_utc()).isoformat(),
                "manifesto": manifesto(arquivos), "dist": arquivos}
    destino = raiz / ARQUIVO_REGISTRO
    raiz.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_name(destino.name + ".tmp")
    temporario.write_text(json.dumps(registro, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(temporario, destino)
    return registro


def _ler_registro(raiz: Path) -> dict | None:
    try:
        r = json.loads((raiz / ARQUIVO_REGISTRO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(r, dict) or not isinstance(r.get("commit"), str) or not isinstance(r.get("manifesto"), str):
        return None
    return r


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def conferir(raiz: Path, clone: Path | None = None) -> dict:
    """Confere o clone e o `dist` contra o registro do ultimo deploy. Devolve `{estado, detalhe, assinatura}`;
    `detalhe` e' o que a tela diz (contagens, sem nome de arquivo nem caminho)."""
    clone = clone or clone_padrao()
    registro = _ler_registro(raiz)
    if registro is None:
        return {"estado": SEM_REGISTRO, "detalhe": "", "assinatura": ""}
    try:
        commit = commit_do_clone(clone)
        alterados = arquivos_alterados(clone)
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        log.warning("conferencia de integridade: %s", e)
        return {"estado": ERRO, "detalhe": "", "assinatura": ""}
    dist = arquivos_do_dist(clone / "frontend" / "dist")
    gravado = registro.get("dist") if isinstance(registro.get("dist"), dict) else {}
    manifesto_dist = manifesto(dist)
    dist_alterado = manifesto_dist != registro["manifesto"]
    n_dist = len({c for c in dist.keys() | gravado.keys() if dist.get(c) != gravado.get(c)})
    partes = []
    if commit != registro["commit"]:
        partes.append("commit diferente do registrado")
    if alterados:
        partes.append(_plural(len(alterados), "arquivo alterado", "arquivos alterados"))
    if dist_alterado:
        partes.append(_plural(n_dist, "arquivo do dist alterado", "arquivos do dist alterados") if n_dist
                      else "dist alterado")
    if not partes:
        return {"estado": OK, "detalhe": "", "assinatura": ""}
    assinatura = hashlib.sha256(json.dumps([commit, sorted(alterados), dist_alterado, manifesto_dist]).encode()
                                ).hexdigest()
    return {"estado": DIFERENTE, "detalhe": "; ".join(partes), "assinatura": assinatura,
            "alterados": len(alterados), "dist": n_dist, "commit_diferente": commit != registro["commit"]}


def _ultima_assinatura_auditada(conn) -> str | None:
    r = conn.execute("SELECT json_extract(depois, '$.assinatura') FROM audit_log "
                     "WHERE acao='seguranca.arvore_alterada' ORDER BY id DESC LIMIT 1").fetchone()
    return r[0] if r else None


def rodar(conn, raiz: Path | None = None, clone: Path | None = None) -> dict | None:
    """Uma conferencia: atualiza `ESTADO` e, a cada diferenca nova, grava `seguranca.arvore_alterada` na auditoria.
    Nao faz nada em dev, sem raiz, ou enquanto o deploy esta' rodando."""
    global ESTADO, _anterior
    raiz = raiz or raiz_padrao()
    if os.environ.get("DASH_DEV") == "1" or raiz is None or (raiz / ARQUIVO_PAUSA).exists():
        return ESTADO
    r = conferir(raiz, clone)
    if (raiz / ARQUIVO_PAUSA).exists():     # o deploy comecou no meio da conferencia: o que ela leu nao vale
        return ESTADO
    agora =tempo.iso_utc(tempo.agora_utc().strftime("%Y-%m-%d %H:%M:%S"))
    if r["estado"] == DIFERENTE:
        # a data do item e' a da primeira vez que se viu esta mesma diferenca
        mesma = ESTADO is not None and ESTADO.get("assinatura") == r["assinatura"]
        r["data"] = ESTADO["data"] if mesma else agora
        conhecida = _anterior if _anterior is not None else _ultima_assinatura_auditada(conn)
        if r["assinatura"] != conhecida:
            with db.mutacao(conn):
                auditoria.registrar(conn, None, "seguranca.arvore_alterada", "integridade", None, None,
                                    {"assinatura": r["assinatura"], "commit_diferente": r["commit_diferente"],
                                     "arquivos_alterados": r["alterados"], "arquivos_do_dist": r["dist"]})
        _anterior = r["assinatura"]
    else:
        r["data"] = agora
        _anterior = ""
    ESTADO = r
    return r


def itens() -> list[dict]:
    """O que a ultima conferencia pede no bloco Seguranca: `[{nivel, mensagem, data}]`."""
    if ESTADO is None:
        return []
    est = ESTADO["estado"]
    if est == DIFERENTE:
        return [{"nivel": "critico", "data": ESTADO["data"], "mensagem": f"{TITULO_DIFERENTE}: {ESTADO['detalhe']}"}]
    if est == SEM_REGISTRO:
        return [{"nivel": "atencao", "data": ESTADO["data"],
                 "mensagem": TITULO_SEM_REGISTRO}]
    if est == ERRO:
        return [{"nivel": "atencao", "data": ESTADO["data"],
                 "mensagem": TITULO_ERRO}]
    return []


def proxima_espera(raiz: Path | None, intervalo_seg: int) -> int:
    """O deploy reinicia o servidor com a pausa ainda de pe': a conferencia da subida nao rodou, entao a proxima vem
    logo (`ESPERA_PAUSA_SEG`) e nao so' daqui a uma hora."""
    return min(intervalo_seg, ESPERA_PAUSA_SEG) if raiz is not None and (raiz / ARQUIVO_PAUSA).exists() else intervalo_seg


def agendar(intervalo_seg: int = INTERVALO_SEG) -> threading.Thread:
    """Confere na subida e depois de hora em hora. Nunca derruba o servidor."""
    def loop():
        while True:
            try:
                conn = db.get_conn()
                try:
                    rodar(conn)
                finally:
                    conn.close()
            except Exception:
                log.exception("conferencia de integridade falhou")
            time.sleep(proxima_espera(raiz_padrao(), intervalo_seg))

    t =threading.Thread(target=loop, name="integridade", daemon=True)
    t.start()
    return t
