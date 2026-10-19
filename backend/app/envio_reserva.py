"""Reserva do envio ANTES do e-mail (testes de quebra de 10/10/2026, A-01/A-02; migracao 035).

O e-mail nao se desfaz e leva segundos; a marca `enviado` so' entra depois dele. Sem reserva, dois cliques
simultaneos passavam pela mesma checagem "ja' enviado?" e mandavam dois e-mails. A reserva e' um UPDATE
condicional dentro de `db.mutacao` (BEGIN IMMEDIATE): so' um escritor por vez, entao so' um ganha.

Reserva presa NAO se toma sozinha (revisao do pacote 1, 10/10/2026). Ela fica presa em dois casos que o
banco nao distingue: o processo morreu antes do e-mail (queda, reinicio do servico) ou o e-mail SAIU e o
registro falhou (A-03, com `envio_id` NULL). Tomar a reserva depois de X minutos mandaria, no segundo caso, o
segundo e-mail ao orgao -- o defeito que este modulo corrige. Quem decide e' uma pessoa, depois de olhar a
caixa de Enviados: `liberar_manual`, com justificativa e auditoria.
"""
import datetime
import logging
import sys
import time

from app import auditoria, db, tempo

log = logging.getLogger("app.envio_reserva")

# Lista fixa: o nome da tabela entra no SQL, entao nunca vem do cliente. Valor = entidade na auditoria.
TABELAS = {"protocolos": "protocolo", "espelhos": "espelho", "pleitos": "pleito"}
# Liberar antes disto pode soltar um envio que AINDA esta' saindo (gate Sol S1, 10/10/2026): quem recebe o 409
# confere os Enviados enquanto o e-mail do outro ainda esta' no Graph, nao ve nada e libera. 15 minutos passa
# de qualquer envio legitimo, inclusive a sessao de upload de 25 MB em blocos (timeout de 60 s por requisicao).
IDADE_MINIMA_LIBERACAO = 15
# Condicao extra da reserva, conferida no MESMO UPDATE (#210): ler a situacao antes de reservar deixava outra
# pessoa gerar a versao nova no meio, e o e-mail saia com os arquivos velhos. Espelho so' se reserva vigente e
# sem medicao que ja' tenha espelho vigente mais novo (o "superado" do #208). SQL fixo, nunca do cliente.
_CONDICAO = {
    "espelhos": "situacao='vigente' AND NOT EXISTS (SELECT 1 FROM espelho_medicoes em "
                "JOIN espelho_medicoes em2 ON em2.medicao_id=em.medicao_id JOIN espelhos e2 ON e2.id=em2.espelho_id "
                "WHERE em.espelho_id=espelhos.id AND e2.situacao='vigente' AND e2.versao > espelhos.versao)",
}


class EnvioEmAndamento(ValueError):
    """Outra pessoa (ou outro clique) esta' enviando, ou acabou de enviar, o mesmo documento. A rota responde 409
    com `detalhe()`: a tela decide pelo `codigo`, nao pelo texto (gate Sol S6)."""

    def __init__(self, mensagem: str, codigo: str, reservado_em: str | None = None,
                 reservado_por_nome: str | None = None, liberavel_a_partir_de: str | None = None):
        super().__init__(mensagem)
        self.codigo, self.reservado_em = codigo, reservado_em
        self.reservado_por_nome, self.liberavel_a_partir_de = reservado_por_nome, liberavel_a_partir_de

    def detalhe(self) -> dict:
        return {"mensagem": str(self), "codigo": self.codigo, "reservado_em": self.reservado_em,
                "reservado_por_nome": self.reservado_por_nome, "liberavel_a_partir_de": self.liberavel_a_partir_de}


def _local(texto_utc: str) -> datetime.datetime:
    return tempo.para_local(datetime.datetime.fromisoformat(texto_utc))


def _hora(texto_utc: str) -> str:
    return _local(texto_utc).strftime("%H:%M")


def _liberavel(texto_utc: str) -> datetime.datetime:
    return _local(texto_utc) + datetime.timedelta(minutes=IDADE_MINIMA_LIBERACAO)


def _nome(conn, usuario_id) -> str:
    r = conn.execute("SELECT nome FROM usuarios WHERE id=?", (usuario_id,)).fetchone()
    return r[0] if r else "outro usuário"


def _tabela(tabela: str) -> str:
    if tabela not in TABELAS:
        raise ValueError(f"tabela sem reserva de envio: {tabela}")
    return tabela


def reservado(conn, reservado_em: str, reservado_por: int | None) -> EnvioEmAndamento:
    """A recusa de envio reservado (409 com `ENVIO_RESERVADO`): a tela oferece a liberacao a partir dela."""
    nome = _nome(conn, reservado_por)
    return EnvioEmAndamento(
        f"Este envio está em andamento ou foi interrompido (iniciado às {_hora(reservado_em)} por {nome}). Confira a "
        "caixa de Enviados do Outlook: se o e-mail NÃO saiu, libere o envio e repita.",
        "ENVIO_RESERVADO", _local(reservado_em).isoformat(), nome, _liberavel(reservado_em).isoformat())


def reservar(conn, tabela: str, id_: int, usuario_id: int, envio_id_visto: int | None = None) -> None:
    """Reserva a linha para enviar, ou levanta EnvioEmAndamento.

    `envio_id_visto` e' o `envio_id` que o chamador leu ao validar: se mudou ate' aqui, outro envio terminou
    nesse meio-tempo (a reserva dele ja' foi liberada) e este seria o e-mail repetido.
    """
    t = _tabela(tabela)
    condicao = f" AND {_CONDICAO[t]}" if t in _CONDICAO else ""
    with db.mutacao(conn):
        cur = conn.execute(
            f"UPDATE {t} SET envio_reservado_em=datetime('now'), envio_reservado_por=? "
            f"WHERE id=? AND envio_id IS ? AND envio_reservado_em IS NULL{condicao}",
            (usuario_id, id_, envio_id_visto))
        if cur.rowcount:
            return
        r = conn.execute(f"SELECT envio_id, envio_reservado_em, envio_reservado_por FROM {t} WHERE id=?",
                         (id_,)).fetchone()
        if r is None:
            raise ValueError("registro não encontrado")
        if r["envio_reservado_em"] is not None:
            raise reservado(conn, r["envio_reservado_em"], r["envio_reservado_por"])
        if condicao and conn.execute(f"SELECT 1 FROM {t} WHERE id=?{condicao}", (id_,)).fetchone() is None:
            raise ValueError(_recusa_condicao(conn, t, id_))
        e = conn.execute("SELECT usuario_id, enviado_em FROM envios WHERE id=?", (r["envio_id"],)).fetchone()
        if e is None:       # envio_id sem envio (nao deveria existir): recusa sem quebrar
            raise EnvioEmAndamento("Este envio acabou de ser feito por outra pessoa. Confira a caixa de Enviados "
                                   "antes de repetir.", "ENVIO_CONCLUIDO_NO_MEIO")
        raise EnvioEmAndamento(
            f"Este envio acabou de ser feito (às {_hora(e['enviado_em'])} por {_nome(conn, e['usuario_id'])}). "
            "Confira a caixa de Enviados antes de repetir.", "ENVIO_CONCLUIDO_NO_MEIO")


def _recusa_condicao(conn, tabela: str, id_: int) -> str:
    """Mensagem de quem perdeu a corrida para a versao nova (so' espelhos tem condicao hoje)."""
    situacao = conn.execute(f"SELECT situacao FROM {tabela} WHERE id=?", (id_,)).fetchone()[0]
    if situacao != "vigente":
        return "esta versão do espelho foi substituída; envie a versão vigente"
    return "uma medição deste espelho tem espelho mais novo: envie aquela versão"


def liberar(conn, tabela: str, id_: int) -> None:
    """Zera a reserva. Dentro do envelope do chamador entra no mesmo commit (db.mutacao e' reentrante)."""
    t = _tabela(tabela)
    with db.mutacao(conn):
        conn.execute(f"UPDATE {t} SET envio_reservado_em=NULL, envio_reservado_por=NULL WHERE id=?", (id_,))


def liberar_com_retentativa(conn, tabela: str, id_: int) -> None:
    """Solta a reserva depois de uma falha ANTES do e-mail; chamada de dentro do `except` dessa falha.

    Banco travado ganha mais duas chances (gate Sol S4, 10/10/2026). Se ainda falhar, a pessoa precisa saber que
    nada saiu E que a trava ficou: ValueError com o erro original encadeado (e no log), nao o lock cru.
    """
    erro_original = sys.exception()
    for tentativa in range(3):
        if tentativa:
            time.sleep(1)
        try:
            return liberar(conn, tabela, id_)
        except Exception as e:
            erro = e
            if not db.eh_lock(e):
                break
    log.error("envio NAO feito e trava nao removida (%s %s): %r", tabela, id_, erro, exc_info=erro_original)
    raise ValueError("O envio NÃO foi feito, mas a trava não pôde ser removida (banco ocupado). Aguarde 15 minutos "
                     "e libere o envio.") from erro_original


def liberar_manual(conn, usuario_id: int, tabela: str, id_: int, justificativa: str, conferi_enviados: bool) -> None:
    """Uma pessoa conferiu a caixa de Enviados e destrava o envio (o e-mail NAO saiu). Fica na auditoria, com a
    declaracao explicita (gate Sol S5). Reserva recente recusa: pode ser envio ainda saindo (S1)."""
    from app import protocolo   # import local: protocolo importa este modulo
    t = _tabela(tabela)
    justificativa = (justificativa or "").strip()
    if len(justificativa) < protocolo.MIN_JUSTIFICATIVA:
        raise ValueError(f"Informe por que liberar (ao menos {protocolo.MIN_JUSTIFICATIVA} caracteres)")
    if conferi_enviados is not True:
        raise ValueError("Confirme que conferiu a caixa de Enviados")
    with db.mutacao(conn):
        r = conn.execute(
            f"SELECT envio_reservado_em, envio_reservado_por, envio_reservado_em > datetime('now', ?) AS recente, "
            f"CAST(ROUND((julianday('now') - julianday(envio_reservado_em)) * 1440) AS INTEGER) AS idade "
            f"FROM {t} WHERE id=?", (f"-{IDADE_MINIMA_LIBERACAO} minutes", id_)).fetchone()
        if r is None or r["envio_reservado_em"] is None:
            raise ValueError("Este envio não está reservado")
        if r["recente"]:
            raise ValueError(f"Envio iniciado há {r['idade']} min por {_nome(conn, r['envio_reservado_por'])}: "
                             f"aguarde até {_liberavel(r['envio_reservado_em']).strftime('%H:%M')} antes de liberar "
                             "(pode ainda estar saindo)")
        liberar(conn, t, id_)
        auditoria.registrar(conn, usuario_id, "envio.liberar", TABELAS[t], id_,
                            {"reservado_em": r["envio_reservado_em"], "reservado_por": r["envio_reservado_por"]},
                            {"justificativa": justificativa, "conferi_enviados": True})
