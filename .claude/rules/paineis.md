---
paths:
  - "backend/app/inicio.py"
  - "backend/app/diretoria.py"
  - "backend/app/fechamento.py"
  - "backend/app/resumo_medicoes.py"
  - "backend/app/paineis.py"
  - "backend/app/avisos*.py"
  - "backend/app/custo_obra.py"
  - "backend/app/api_inicio.py"
  - "backend/app/api_diretoria.py"
  - "backend/app/api_paineis.py"
  - "backend/app/api_contratos.py"
  - "backend/app/fila_medicoes.py"
  - "frontend/src/Inicio.tsx"
  - "frontend/src/ObrasCarteira.tsx"
  - "frontend/src/Contratos.tsx"
  - "frontend/src/ContratantePagina.tsx"
  - "frontend/src/ObrasContratantes.tsx"
  - "frontend/src/ObrasAndamento.tsx"
  - "frontend/src/ObrasPecas.tsx"
  - "frontend/src/listaObras.ts"
  - "frontend/src/Fechamento.tsx"
  - "frontend/src/ResumoDasMedicoes.tsx"
  - "frontend/src/AvisosPagina.tsx"
  - "frontend/src/avisos.ts"
---

# Painéis, avisos e números para a diretoria

Os nomes das etapas e dos valores são os do `GLOSSARY.md`.

- **Só aparece o que tem lastro.** Número antigo ou sem prova (data do evento, documento) fica fora do painel. A
  idade de uma etapa conta da data do evento (envio, protocolo, emissão), nunca da competência.
- **Tudo na cota** nas telas da diretoria; o valor cheio aparece ao abrir a obra.
- **Aviso com data vai para a agenda; pendência sem data aparece onde se resolve** e na lista do administrador
  (`docs/adr/0008`).
- **Prazo do órgão:** uma conta só, a de `docs/adr/0007`.
- **Tempo parado tem uma leitura só.** "Com quem está" e "parada há" de uma medição saem de `fila_medicoes` (o passo
  da vez diz com quem está; os dias úteis contam do evento que abriu o passo; no Pagamento, crítico só depois do
  prazo do órgão). Tela nova que mostre tempo parado usa essa leitura, para a mesma medição não ter dois tons.
- **Contagem que resume uma tabela nasce no servidor, junto com a leitura que pinta a linha.** A tela não repete
  limite (dias, percentual): recebe a situação pronta e os limites para escrever o rótulo.
- **Custo** é "custo lançado no RM"; margem e lucro ficam fora (`docs/adr/0004`).
- **O backend calcula o que alguma tela mostra.** Número sem tela sai junto com a tela.
- **A apresentação é do sistema:** tela que substitui um controle manual da equipe parte do dado do sistema e da
  pergunta de quem lê, não do arquivo da pessoa.
- **Correção de dado feita pelo dono é silenciosa na tela:** o número sai certo, sem selo nem aviso; o registro
  fica na auditoria.
