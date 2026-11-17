"""Checklist "pronto para protocolar" (spec 2026-09-21 §9; nasceu na fase 3 T7).

A pergunta da mesa de protocolo e' uma so': "posso levar ESTE contrato ao orgao hoje?". Desde o
bloco 4 o QUE e' exigido vem do cadastro (`documentos.exigidos`): a lista do orgao para a natureza
da medicao (medicao/projeto ou reajuste), a excecao do contrato e, em obra de consorcio, as
certidoes do consorcio E de cada consorciada, mais a regularidade mensal do DP onde o orgao a pede.

Modulo PURO DE LEITURA: nao escreve nada. A regra de vigencia mora em `certidoes.py` e a situacao
em `documentos.situacao`; aqui so' se decide o VEREDITO.

Tres decisoes que o formato carrega:

1. 'vencendo' NAO impede o protocolo. Certidao valida hoje e' certidao valida hoje -- o orgao
   aceita. Ela aparece com situacao propria (e `dias`) para quem monta a pasta ver que renovar
   virou urgente.
2. 'nao_se_aplica' ENTRA na lista, com situacao propria, e nao pesa no veredito: a decisao fica
   visivel e auditavel.
3. Contrato SEM orgao no cadastro (tela antiga, testes) cobra os tipos `aplicavel_por_padrao`,
   como antes do cadastro versionado.
"""
import sqlite3

from app import contratos, documentos, entidades, tempo

# 'ok': vigente com folga | 'vencendo': vigente, perto de vencer (limiar de documentos.limiar)
# 'pendente': sem documento valendo hoje | 'nao_se_aplica': declarado nao exigivel
SITUACOES = ("ok", "vencendo", "pendente", "nao_se_aplica")
# Situacoes que NAO travam o protocolo -- so' 'pendente' trava.
LIBERAM = frozenset({"ok", "vencendo", "nao_se_aplica"})


def pronto_para_protocolar(conn: sqlite3.Connection, contrato_id: int, natureza: str = "execucao") -> dict:
    """Veredito + linha a linha (empresa x documento exigido), HOJE (Cuiaba).

    `natureza` e' o tipo da medicao: 'execucao', 'projeto' ou 'reajuste'.
    """
    c = conn.execute("SELECT * FROM contratos WHERE id=?", (contrato_id,)).fetchone()
    if c is None:
        raise ValueError(f"Contrato {contrato_id} não encontrado")
    hoje = tempo.hoje_local()
    ex = documentos.exigidos(conn, contrato_id, natureza)
    ids = ex["entidades"] + ([ex["regularidade"]] if ex["regularidade"] else [])
    ents = {e: entidades.detalhe(conn, e) or {} for e in ids}

    def nome(eid):
        return ents[eid].get("nome_curto") or ents[eid].get("nome")

    itens = []
    for eid in ex["entidades"]:
        for t in ex["tipos"]:
            s = documentos.situacao(conn, eid, t, hoje)
            sit = s["situacao"] if s["situacao"] in ("ok", "vencendo", "nao_se_aplica") else "pendente"
            vale = sit in ("ok", "vencendo")
            itens.append({"entidade_id": eid, "entidade": nome(eid), "tipo_id": t["id"], "tipo": t["nome"],
                          "chave": t.get("chave"), "jurisdicao": t["jurisdicao"], "situacao": sit,
                          "validade": s["certidao"]["validade"] if vale else None, "dias": s["dias"],
                          "certidao_id": s["certidao"]["id"] if vale else None,
                          # o `pendente` cobre dois casos que a tela mostra diferente: a certidao vencida (trava o
                          # envio, docs/adr/0002) e a que nunca foi cadastrada (falta, nao trava)
                          "nunca_cadastrada": s["situacao"] == "faltando",
                          "link_emissao": t.get("link_emissao")})
    if ex["regularidade"]:
        r = documentos.situacao_regularidade(conn, ex["regularidade"], hoje)
        itens.append({"entidade_id": ex["regularidade"], "entidade": nome(ex["regularidade"]), "tipo_id": None,
                      "tipo": "Regularidade mensal", "chave": "regularidade", "jurisdicao": None,
                      "situacao": "ok" if r["situacao"] == "ok" else "pendente", "validade": None, "dias": None,
                      "certidao_id": None, "nunca_cadastrada": r["situacao"] == "faltando", "link_emissao": None,
                      "competencia": r["competencia"], "esperada": r["esperada"]})
    ent = contratos.entidade_de(c)
    e = entidades.detalhe(conn, ent)
    return {"contrato_id": contrato_id,
            "entidade_id": ent,
            # Entidade apagada do cadastro nao existe (desativar e' SOFT), mas a guarda evita 500.
            "entidade": e["nome"] if e else None,
            "natureza": natureza,
            "itens": itens,
            # `all` de lista vazia e' True de proposito: sem exigencia nao ha o que cobrar.
            "pronto": all(i["situacao"] in LIBERAM for i in itens)}
