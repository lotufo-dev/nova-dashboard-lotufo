---
paths:
  - "backend/app/dinheiro.py"
  - "backend/app/medicoes.py"
  - "backend/app/api_medicoes.py"
  - "backend/app/notas*.py"
  - "backend/app/api_notas*.py"
  - "backend/app/espelho*.py"
  - "backend/app/protocolo.py"
  - "backend/app/api_protocolos.py"
  - "backend/app/reajuste.py"
  - "backend/app/aditivos.py"
  - "backend/app/frc.py"
  - "backend/app/qdop.py"
  - "backend/app/conciliacao.py"
  - "backend/app/sincronizacao_rm.py"
  - "frontend/src/Medic*.tsx"
  - "frontend/src/Notas*.tsx"
  - "frontend/src/Espelho.tsx"
  - "frontend/src/Protocolo.tsx"
  - "frontend/src/formato.ts"
---

# Dinheiro, medição e histórico

- Valor é inteiro em centavos; só `app/dinheiro.py` arredonda, uma vez, no fim. `parse_brl` tem teto
  (R$ 99.999.999.999,99) e aceita só `[0-9]`.
- A medição guarda o valor **cheio**; a cota do consórcio é derivada na leitura. O cadastro guarda o contrato
  na cota. Base cheia × cota: provado no Leblon (dobro exato) e na Rota do Oeste (×0,18).
- Valor protocolado é congelado no protocolo. Correção é evento novo (auditoria), nunca sobrescrita.
  Valor de origem `espelho` não se edita à mão: gera o espelho de novo; depois de protocolada, reapresentação.
- Nenhum registro financeiro é apagado fisicamente. Auditoria é append-only e grava quem fez; sem usuário,
  "pelo sistema".
- Hierarquia das fontes de valor: documento assinado manda; nota fiscal desempata; planilha é insumo.
- Estados da medição: prevista → planilha/carta gerada → planilha/carta enviada → boletim recebido → espelho
  gerado → espelho enviado → nota emitida → protocolada → recebida (tabela em `medicoes.TRANSICOES`). O reajuste
  não tem planilha/carta: vai da prevista ao espelho. O pedido congela no envio da planilha/carta; o aprovado vem
  do boletim (corrigir é boletim novo). Cancelada/desistida são saídas por exceção. Transição fora dessa ordem é 422 com a mensagem por extenso ("Transição inválida: estado → estado"); o
  servidor valida, não só a tela. O 409 com `codigo` é o da reserva de envio (envio duplicado).
- Competência anterior ao início do contrato → 422; anterior à última medição do mesmo tipo → aviso.
- Reajuste e execução tramitam separados na MTPAR e SES; juntos na SINFRA e Pref. VG (pendência `irma_fora`).
- Teste de dinheiro sempre com caso de centavo ímpar e de rateio com resíduo.
