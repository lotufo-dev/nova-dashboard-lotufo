"""Cobranca ao orgao: quais notas do RM cobram o orgao por uma medicao (docs/adr/0015).

O RM classifica cada nota por um tipo de movimento (`notas_fiscais.codtmv`). So' a nota de cobranca ao orgao entra no
faturado do RM e no a receber, vira vinculo automatico com a medicao e deixa a medicao fechar pela baixa. A regra tem
duas partes:

- a lista geral (`CODTMV_COBRANCA`, issue #563), que vale em toda obra; tipo novo so' entra nela por decisao;
- os tipos extras do contrato (`tipos_cobranca_extras_rm` no cadastro versionado da obra; vazio por padrao), que
  valem SO' para a nota atribuida `aquele contrato: pela medicao a que esta' ligada (`nf_alocacoes`) ou, sem vinculo,
  pelo centro de custo do contrato. O mesmo tipo em nota de outra obra, ou em nota sem obra, nao e' cobranca.

`e_cobranca` e' a UNICA resposta a "esta nota, atribuida a este contrato, e' cobranca?". Quem le notas do banco pode
estreitar a consulta com `tipos_buscados` (todo tipo que e' cobranca em alguma obra), mas a decisao, nota a nota e com
o contrato na mao, e' sempre de `e_cobranca`. Este modulo nao importa nenhum outro do sistema.

Uso tipico (uma leitura dos extras por conta):

    extras = cobranca_orgao.extras_por_contrato(conn)
    if cobranca_orgao.e_cobranca(nota["codtmv"], medicao["contrato_id"], extras): ...
"""
import json
import re

# Issue #563: tipos de movimento do RM (codtmv) que sao cobranca ao orgao em toda obra. 2.2.15 (nota do fornecedor,
# saida contra fornecedor) e 2.2.10 (pessoas fisicas) ficam fora. 2.2.07 e' o do consorcio do Leblon com tomador SINFRA.
CODTMV_COBRANCA = ("2.2.01", "2.2.02", "2.2.07", "2.2.16")
# O formato de um tipo de movimento de nota de saida no RM. A sincronizacao so' traz `2.2.%` (consultas DASH10 e
# DASH11 do docs/runbook.md): tipo de outra familia no cadastro nunca casaria com nota nenhuma.
FORMATO_CODTMV = re.compile(r"2\.2\.\d{2}")


def extras_por_contrato(conn) -> dict[int, frozenset[str]]:
    """contrato -> os tipos de movimento que, so' nele, tambem sao cobranca ao orgao (`tipos_cobranca_extras_rm` do
    cadastro). O contrato sem a chave nao aparece."""
    return {r[0]: frozenset(json.loads(r[1])) for r in conn.execute(
        "SELECT id, tipos_cobranca_extras_rm FROM contratos WHERE tipos_cobranca_extras_rm IS NOT NULL")}


def e_cobranca(codtmv: str | None, contrato_id: int | None, extras: dict[int, frozenset[str]]) -> bool:
    """Esta nota (pelo tipo de movimento `codtmv`), atribuida a este contrato, e' cobranca ao orgao? Vale a lista
    geral e, alem dela, os tipos extras DESTE contrato (`extras`, de `extras_por_contrato`). Nota sem contrato
    (`contrato_id` None) so' e' cobranca pela lista geral; nota sem tipo (so' lida do PDF, ainda nao veio do RM) nao
    e' cobranca por esta regra, e quem a aceita mesmo assim decide isso do lado de fora."""
    if codtmv in CODTMV_COBRANCA:
        return True
    return codtmv is not None and contrato_id is not None and codtmv in extras.get(contrato_id, ())


def tipos_buscados(extras: dict[int, frozenset[str]]) -> tuple[str, ...]:
    """Todo tipo de movimento que e' cobranca em ALGUMA obra (a lista geral e os extras de todos os contratos), para
    estreitar uma consulta de notas. Nao decide nada: a nota de tipo extra ainda passa por `e_cobranca` com o contrato."""
    de_obras = set().union(*extras.values()) if extras else set()
    return (*CODTMV_COBRANCA, *sorted(de_obras - set(CODTMV_COBRANCA)))
