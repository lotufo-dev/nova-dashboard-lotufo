# Cadastro de exemplo

Cadastro 100% fictício, só para os testes, a CI e o primeiro contato com o sistema. Nenhum nome, valor,
e-mail, CNPJ ou texto aqui vem do cadastro real: o órgão, as empresas e as obras não existem, os e-mails são
`@exemplo.gov.br` e `@exemplo.com.br`, e os CNPJs são inventados (só o dígito verificador é válido).

O cadastro real mora fora do repositório (repositório privado `lotufo-cadastro`, clonado em
`C:\DashboardLotufo\cadastro` na produção). O sistema lê a pasta indicada por `DASH_CADASTRO_DIR`; sem a
variável, lê esta.

```
cd backend
.venv\Scripts\python -m app.cli cadastro validar
$env:DASH_DB_PATH = "<banco de teste>"; .venv\Scripts\python -m app.cli cadastro aplicar --usuario <e-mail> --ensaio
```

Estrutura (a mesma do cadastro real): `geral.yaml`, `orgaos.yaml`, `entidades.yaml`, `cartas.yaml`,
`frc.yaml`, `contratos/<slug>.yaml`, `espelho/<slug>.yaml` e `modelos/` (modelos Word do espelho, planilha do
QDOP e logo da FRC). Os modelos `.docx` e `.xlsx` são neutros, sem logotipo; o logo da FRC é um retângulo cinza.

- Obra Própria: contrato da empresa sozinha (100%), com espelho de medição e reajuste.
- Obra Consórcio: contrato do Consórcio Exemplo (empresa própria 50% e Engenharia Beta 50%), em dois
  municípios, com espelho de medição que rateia entre as duas empresas e os dois municípios.

`medicoes/obra-propria.csv` é o histórico de medições de exemplo da Obra Própria, no formato de
`cadastro carregar-medicoes <obra>.csv --ensaio` (o nome do arquivo é o slug da obra, como em `contratos/`).
Separador `;`, valores em reais com vírgula, competência AAAA-MM, datas DD/MM/AAAA, período
`DD/MM/AAAA a DD/MM/AAAA`, meio `e-mail`, `SMO`, `ofício`, `carimbo` (ou `protocolo físico`), `CI` ou `outro`.
Sem `--ensaio` e com `--usuario`, o comando cria as medições que faltam (protocoladas, com o aprovado como
evento de atesto e a NF vinculada quando está no RM; recebida se o RM já tem a baixa). Linha com erro ou
conflito recusa o arquivo inteiro; medição que já existe não é alterada.
