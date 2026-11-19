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
  - "backend/app/inicio.py"
  - "backend/app/fechamento.py"
  - "backend/app/a_receber.py"
  - "frontend/src/Medic*.tsx"
  - "frontend/src/Notas*.tsx"
  - "frontend/src/Espelho.tsx"
  - "frontend/src/Protocolo.tsx"
  - "frontend/src/formato.ts"
---

# Dinheiro, medição e histórico

Os termos (pedido, aprovado, faturado, medido, cota, valor cheio, vínculo) estão no `GLOSSARY.md`.

- **Centavos inteiros.** Só `app/dinheiro.py` arredonda, uma vez, no fim.
- **Cheio e cota.** A medição guarda o valor cheio; a cota é derivada na leitura. O contrato é cadastrado na cota.
- **Valor congela, correção é evento.** O pedido congela no envio da planilha/carta e o valor protocolado congela
  no protocolo. Corrigir é registrar um evento novo, nunca sobrescrever. O valor que veio do espelho muda gerando
  o espelho de novo; depois do protocolo, por reapresentação.
- **Nada financeiro se apaga.** A auditoria só acrescenta e grava quem fez; sem usuário, "pelo sistema".
- **Fontes de valor.** O documento assinado manda; a nota fiscal desempata; a planilha é insumo.
- **Vínculo nota ↔ medição** segue a força da prova (`docs/adr/0005`): o documento antes do valor; valor só
  exato, dentro da obra, com medição candidata única; pela saída do espelho, só nota emitida depois do envio do
  espelho e sem outra nota ativa de mesmo valor; nunca por campo preenchido por terceiros no RM, nem em carga de
  histórico ou em fechamento.
- **Recebimento** vem da baixa no RM; à mão, só o administrador, com motivo (`docs/adr/0006`).
- **O servidor valida** a transição de estado e o valor; a tela só reflete.
- Teste de dinheiro leva caso de centavo ímpar e de rateio com resíduo.
