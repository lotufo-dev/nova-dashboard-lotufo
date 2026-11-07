import datetime
import sqlite3
from fastapi import APIRouter, Depends, HTTPException, Query
from app import (auditoria, backup, copia_dono, copia_dono_envio, correio, envio_reserva, graph, instalacao, seguranca,
                 sentinela, siga, tempo)
from app.api_auth import conexao
from app.permissoes import exigir

router = APIRouter(prefix="/api/admin")
MAX_INT64 = 9223372036854775807

@router.get("/auditoria")
def listar_auditoria(limite: int = Query(default=100, ge=1, le=500),
                     antes_de: int | None = Query(default=None, ge=1, le=MAX_INT64),
                     usuario: dict = Depends(exigir("administrar", com_csrf=False)),
                     conn: sqlite3.Connection = Depends(conexao)):
    """Do mais recente ao mais antigo. `antes_de` e' o cursor: o id do ultimo evento da pagina anterior.
    A cadeia e' verificada so' na primeira pagina (sem cursor); nas seguintes `cadeia_integra` vem nulo."""
    # um a mais que o pedido so' para saber se ainda ha' anteriores
    linhas = conn.execute(
        # `contrato_id`: a obra do objeto, para a tela levar da medicao ou do protocolo ate' ela (o evento so' guarda o id
        # da medicao/protocolo); nulo quando o objeto nao e' dessas entidades ou ja' nao existe.
        "SELECT a.*, CASE a.entidade "
        "  WHEN 'medicao' THEN (SELECT contrato_id FROM medicoes WHERE id = CAST(a.entidade_id AS INTEGER)) "
        "  WHEN 'protocolo' THEN (SELECT contrato_id FROM protocolos WHERE id = CAST(a.entidade_id AS INTEGER)) "
        "END AS contrato_id FROM audit_log a WHERE a.id < ? ORDER BY a.id DESC LIMIT ?",
        (MAX_INT64 if antes_de is None else antes_de, limite + 1)).fetchall()
    return {"cadeia_integra": auditoria.verificar_cadeia(conn) if antes_de is None else None,
            "ha_mais": len(linhas) > limite,
            "eventos": [dict(l) for l in linhas[:limite]]}


@router.get("/backup")
def saude_do_backup(usuario: dict = Depends(exigir("administrar", com_csrf=False)),
                    conn: sqlite3.Connection = Depends(conexao)):
    """Administracao > Saude (issue #31): ultimo backup, quantos estao guardados, ultimo erro
    e se esta atrasado (mais de 2 h sem snapshot). So' admin: traz caminhos e erros do servidor. Na instalacao nao
    autorizada a copia externa nao roda (issue #417, main.py): a tela mostra o estado efetivo, nao o configurado.
    Issue #420: sem erro do envio na memoria (o servidor reiniciou), a copia mais recente que nao saiu inteira por
    e-mail aparece como erro do envio, lida do banco."""
    externa = backup.pasta_externa() is not None and instalacao.ligada()
    s = backup.situacao(backup.pasta_local(), externa, tempo.agora_utc())
    if not s["ultimo_envio_copia_dono_erro"]:
        s["ultimo_envio_copia_dono_erro"] = copia_dono_envio.pendente(conn, backup.pasta_local())
    return s


@router.post("/copia-dono")
def gerar_copia_dono(usuario: dict = Depends(exigir("administrar")), conn: sqlite3.Connection = Depends(conexao)):
    """Botao "Gerar cópia do dono agora" (Administracao > Saude, issue #419). So' admin.
    Sem chave publica configurada nada e' gerado. A copia gerada sai por e-mail (issue #420); falha no envio nao
    desfaz a copia: fica no log e na Saude. `emails` = quantos sairam, de `partes` (nulo quando nada foi tentado);
    `completo` so' com todas as partes enviadas."""
    try:
        destino = copia_dono.gerar_e_registrar(backup.pasta_local().parent.parent, backup.pasta_local())
    except copia_dono.NaoConfigurada:
        raise HTTPException(409, copia_dono.NAO_CONFIGURADA)
    except Exception as e:
        raise HTTPException(500, f"Não foi possível gerar a cópia do dono: {copia_dono._motivo(e)}")
    return {"arquivo": destino.name, **copia_dono_envio.enviar_nova(conn, destino)}


@router.post("/copia-dono/reenviar")
def reenviar_copia_dono(usuario: dict = Depends(exigir("administrar")),
                        conn: sqlite3.Connection = Depends(conexao)):
    """Botao "Reenviar cópia do dono" (issue #420): a copia mais recente sai de novo por e-mail. So' admin; o e-mail
    sai da conta de `copia_dono.enviada_por` do cadastro, e quem clicou fica na auditoria."""
    try:
        return copia_dono_envio.reenviar(conn, backup.pasta_local(), {"id": usuario["id"], "email": usuario["email"]})
    except envio_reserva.EnvioEmAndamento as e:
        conn.rollback()
        detalhe = e.detalhe()
        if getattr(e, "reserva_id", None):         # reserva presa: o que a liberacao precisa (e qual parte, #482)
            detalhe |= {"tabela": copia_dono_envio.TABELA, "id": e.reserva_id, "parte": e.parte, "partes": e.partes,
                        "assunto": e.assunto}
        raise HTTPException(409, detail=detalhe) from None
    except copia_dono_envio.EnvioNaoConfigurado as e:
        raise HTTPException(409, str(e)) from None
    except (ValueError, graph.ErroGraph) as e:
        conn.rollback()
        raise HTTPException(422, str(e)) from None


@router.get("/saude")
def saude(usuario: dict = Depends(exigir("administrar", com_csrf=False)),
          conn: sqlite3.Connection = Depends(conexao)):
    """Administracao > Saude: a situacao do monitor do SIGA (issue #330), ao lado da do RM e do backup, e o bloco
    Seguranca (issue #418): `[{nivel, mensagem, data}]`, montado por `app/seguranca.py`, com no maximo
    `seguranca.ITENS_NA_TELA` itens; `seguranca_fora` diz quantos ficaram de fora."""
    itens, fora = seguranca.bloco(conn)
    return {"siga": siga.saude(conn), "seguranca": itens, "seguranca_fora": fora, "sentinela": sentinela.situacao()}


@router.get("/contas-microsoft")
def contas_microsoft(usuario: dict = Depends(exigir("administrar", com_csrf=False)),
                     conn: sqlite3.Connection = Depends(conexao)):
    """Quem tem a conta Microsoft conectada (bloco 9). Cada pessoa conecta a propria em Minha conta;
    aqui so' se ve. `token_em` = quando o arquivo do token foi gravado pela ultima vez."""
    contas = []
    for u in conn.execute("SELECT id, nome, email, perfil FROM usuarios WHERE ativo=1 ORDER BY nome"):
        token_em = None
        if correio.conectado(u["id"]):
            mtime = correio.arquivo_token(u["id"]).stat().st_mtime
            token_em = datetime.datetime.fromtimestamp(mtime, datetime.timezone.utc).isoformat(timespec="seconds")
        contas.append({"usuario_id": u["id"], "nome": u["nome"], "email": u["email"], "perfil": u["perfil"],
                       "conectada": token_em is not None, "token_em": token_em})
    return contas
