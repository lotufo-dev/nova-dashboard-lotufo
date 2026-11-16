# Documentos de domínio

Como as skills de engenharia leem a documentação de domínio deste repositório ao explorar o código.

## Antes de explorar, ler

- **`GLOSSARY.md`** na raiz do repositório.
- **`docs/adr/`**: as decisões registradas que tocam a área em que se vai trabalhar.
- **`.claude/rules/`**: as regras de dinheiro, envio, banco, dado de teste e texto na tela, que valem como
  decisões já tomadas.

As specs em `docs/superpowers/specs/` são histórico: lê-se uma só para entender de onde veio uma decisão, não como
autoridade. A skill `mattpocock-skills:domain-modeling` (chamada também pela `mattpocock-skills:grilling` e pela
`mattpocock-skills:codebase-design`) atualiza o glossário e os ADRs quando um termo ou uma decisão é de fato
resolvido.

## Estrutura

Contexto único:

```
/
├── GLOSSARY.md
├── docs/adr/
└── backend/ e frontend/
```

## Usar o vocabulário do glossário

Quando a saída nomear um conceito do domínio (título de issue, proposta de refatoração, hipótese, nome de teste),
usar o termo como está no `GLOSSARY.md`, sem sinônimo que o glossário evita. Se o conceito não está lá, ou a
linguagem é inventada (repensar), ou há uma lacuna real (anotar para a `mattpocock-skills:domain-modeling`).

## Apontar conflito com decisão registrada

Se a saída contradiz uma decisão de `docs/adr/` ou de `.claude/rules/`, dizer isso às claras, em vez de passar por
cima em silêncio.
