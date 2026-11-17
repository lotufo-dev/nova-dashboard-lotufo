# Spike RM — conduto API + Consulta SQL provado fim a fim

**Task 3 da Fase 0** · Executado em 2026-08-31, inline com o dono (cadastro das consultas feito por computer-use no RM.exe local; execução da API pelo dono com a credencial dele via `scripts/spike_rm.ps1`).

## 1. Auth e URL que funcionaram

- **Endpoint:** `GET http://<servidor-rm>:<porta-da-api>/api/framework/v1/consultaSQLServer/RealizaConsulta/{codigo}/{coligada}/{sistema}`
- **Auth:** HTTP Basic. Usuário = **código do usuário no RM** — para o dono é `<código do usuário no RM>` (pode ter espaço, como mostrado em "Código do Usuário" no painel Sistema do RM). O formato Windows (`nome.sobrenome`, `DOMINIO\...`) retorna **401**.
- **Sistema:** a instalação da Lotufo **não licencia a aplicação "Global" (G)** — o dropdown do cadastro só oferece Chronus, Fluxus, Bis, Agilis, Solum e Nucleus. As consultas do spike foram cadastradas em **RM Fluxus → sistema `F`** na URL. (O plano previa `G`; ajuste registrado.)
- **Coligada na URL:** `0`, com a consulta marcada "**Visível a todas Coligadas**" no cadastro.
- Consultas cadastradas (módulo Serviços Globais > Gestão > Visões de Dados, todas com `(NOLOCK)`): `DASH01` coligadas, `DASH02` NFs recentes TMOV, `DASH03` baixas FLAN, `DASH04` NFs por coligada, `DASH05` agregado STATUSLAN/parciais, `DASH06` campos livres preenchidos.
- **Formato da resposta (importante para o parser da fase 5):** array JSON; **chaves com valor NULL são OMITIDAS** do objeto (ex.: `DATABAIXA` só aparece quando baixado); datas com fuso (`2026-08-25T00:00:00-04:00`); decimais com 4 casas.
- **Segurança:** a senha viaja em Basic **sobre HTTP puro** na porta `<porta-da-api>` (LAN). Para a fase 5: conta de serviço dedicada de permissão mínima e avaliar HTTPS/túnel no host RM.
- Consulta SQL do RM é SELECT-only (o cadastro valida) — o conduto é somente-leitura por construção.

## 2. O financeiro dá baixa no RM? Parciais e estornos?

**Sim, dá baixa em massa** (DASH05, FLAN inteira com `PAGREC = 1`):

| STATUSLAN | Significado (RM) | Qtde | c/ `VALORBAIXADO` < `VALORORIGINAL` |
|---|---|---|---|
| 0 | Em aberto | 9.530 | — |
| 1 | Baixado | 18.422 | 822 |
| 2 | Cancelado | 14 | — |
| 3 | Baixado por acordo | 28 | — |
| 4 | Baixado parcialmente | 175 | 61 |

- **Baixa parcial existe** (status 4 + os 822/61 com valor baixado menor). Exemplo real: original 1.600,36, baixado 904,26.
- **Baixa com valor MAIOR que o original também** (juros/multa/correção): original 958,01, baixado 1.143,33.
- **Estorno/cancelamento:** status 2 e 3 existem, em volume pequeno.
- `DATABAIXA` preenchida quando baixado — com **typo real** observado (`2036-06-16`): a sincronização da fase 5 deve validar datas (faixa plausível) antes de confiar.
- Conclusão para o modelo: o estado "NF paga" é derivável da FLAN (STATUSLAN + VALORBAIXADO + DATABAIXA), tratando parciais como estado próprio e datas como não-confiáveis.

## 3. Que campo da NF pode carregar o nº da medição?

**Hoje, nenhum de forma sistemática.** DASH06 sobre as 8.630 NFs (`CODTMV LIKE '2.%'`):

| Campo | Preenchidos | % |
|---|---|---|
| CAMPOLIVRE1 | 403 | 4,7% |
| CAMPOLIVRE2 | 269 | 3,1% |
| CAMPOLIVRE3 | 171 | 2,0% |

Implicações para a fase 5: (a) o vínculo NF↔medição **não pode depender de campo do RM** — será por heurística (coligada + valor + data de emissão + contexto do espelho detectado no Outlook) com aceite/ajuste humano; (b) recomendação de processo: passar a preencher `CAMPOLIVRE1` com `IC/contrato + nº medição` daqui em diante, o que tornaria o vínculo determinístico para NFs novas.

## 4. As coligadas-consórcio emitem NF?

**Sim** (DASH04 — total bate com DASH06: 8.630):

| Coligada | Nome | NFs `2.%` | Última emissão |
|---|---|---|---|
| 1 | Lotufo Engenharia | 3.056 | 2026-08-25 |
| 2 | ELF Locação | 3.373 | 2026-08-24 |
| 7 | ME Locações | 1.508 | 2026-08-28 |
| 12 | **Consórcio Oriundi** | 132 | 2026-08-03 |
| 18 | **Consórcio Integra BRT** | 100 | 2026-07-16 |
| 17 | **Consórcio Complexo Leblon** | 31 | 2026-08-11 |
| 6 | Arica Engenharia | 216 | 2026-08-14 |
| 3, 10, 11, 13, 14 | consórcios encerrados | 67/49/51/27/20 | 2021–2024 |

Os três consórcios ativos do processo de medição (Oriundi, Leblon, Integra BRT) emitem NF pelas próprias coligadas, com atividade recente — a sincronização da fase 5 enxerga os dois níveis (NF "cheia" do consórcio contra o órgão + NF da Lotufo contra o consórcio) varrendo `CODCOLIGADA` sem filtro. GCOLIGADA tem 21 coligadas (0–20).

## 5. Esquema real confirmado (nomes exatos, sem erro em nenhuma consulta)

- `GCOLIGADA`: `CODCOLIGADA`, `NOMEFANTASIA`
- `TMOV`: `IDMOV`, `CODCOLIGADA`, `NUMEROMOV`, `SERIE`, `DATAEMISSAO`, `VALORBRUTO`, `CODTMV`, `STATUS`, `CAMPOLIVRE1..3`
- `FLAN`: `IDLAN`, `CODCOLIGADA`, `NUMERODOCUMENTO`, `VALORORIGINAL`, `STATUSLAN`, `DATABAIXA`, `VALORBAIXADO`, `PAGREC`, `DATAVENCIMENTO`

Todos os nomes previstos no plano existem na versão 12.1.2510 — nenhum ajuste foi necessário.

## 6. Tipos de movimento (CODTMV) que representam NF na Lotufo

Observado na DASH02 (50 movimentos mais recentes):

- **`2.2.xx` com série `1` = notas fiscais de fato** (vistos: 2.2.01, 2.2.03, 2.2.04, 2.2.05, 2.2.10, 2.2.15). `STATUS`: `A` (aberto), `F` (faturado), `Q` (quitado — a confirmar semântica exata com o faturamento).
- **`2.1.xx` com séries `OMRS`/`OVP`/`OVS` = ordens/movimentos preparatórios** (medição de locação, ordem de venda), não NF — ex.: 2.1.02 série OMRS da ME Locações, 2.1.03 OVP, 2.1.04 OVS.
- Para a fase 5: filtrar NF como `CODTMV LIKE '2.2.%'` (e confirmar com a equipe a lista fechada de subtipos por coligada); manter `2.1.%` fora do fluxo fiscal, mas potencialmente útil como sinal de medição de locação.

## Anexos e reprodução

- Script: [`scripts/spike_rm.ps1`](../../../scripts/spike_rm.ps1) (UTF-8 BOM; credencial via `Get-Credential`, nunca gravada; aceita `-Consultas A,B` mesmo via `powershell -File`).
- Saídas brutas (fora do git, dados de negócio): `%TEMP%\rm-spike-saida\DASH0*.json`.
- Fase 5 será desenhada sobre: API+Basic (usuário-código RM), sistema `F`, SELECT-only, respostas com NULL omitido, FLAN como fonte de "pago", heurística p/ vínculo NF↔medição, varredura multi-coligada.
