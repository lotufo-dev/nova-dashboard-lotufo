---
paths:
  - "backend/app/inicio.py"
  - "backend/app/diretoria.py"
  - "backend/app/paineis.py"
  - "backend/app/avisos*.py"
  - "backend/app/custo_obra.py"
  - "backend/app/api_inicio.py"
  - "backend/app/api_diretoria.py"
  - "backend/app/api_paineis.py"
  - "frontend/src/Inicio.tsx"
  - "frontend/src/Diretoria.tsx"
  - "frontend/src/AReceberPagina.tsx"
  - "frontend/src/AvisosPagina.tsx"
  - "frontend/src/CustoObra.tsx"
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
- **Custo** é "custo lançado no RM"; margem e lucro ficam fora (`docs/adr/0004`).
- **O backend calcula o que alguma tela mostra.** Número sem tela sai junto com a tela.
- **A apresentação é do sistema:** tela que substitui um controle manual da equipe parte do dado do sistema e da
  pergunta de quem lê, não do arquivo da pessoa.
- **Correção de dado feita pelo dono é silenciosa na tela:** o número sai certo, sem selo nem aviso; o registro
  fica na auditoria.
