# Dashboard Lotufo: reestruturação (o sistema onde o trabalho é feito)

> **Histórico.** Este documento deixou de ser autoridade em 15/11/2026 (`docs/adr/0001`). As regras vivas estão em
> `.claude/rules/`, `GLOSSARY.md` e `docs/adr/`. Leia-o só para saber de onde veio uma decisão antiga; onde ele e o
> código divergem, vale o código.

**Data:** 2026-09-21
**Autor:** Leonardo Praeiro (com Claude)
**Status:** Decisões aprovadas tópico a tópico entre 2026-09-16 e 2026-09-21; aguardando revisão desta spec e plano de implementação.
**Substitui** como autoridade de produto a spec `2026-08-28-dashboard-contratos-medicoes-design.md` (v3, "sistema que observa"). O que aquela spec define e esta não contradiz continua valendo (dinheiro em centavos, auditoria, histórico, segurança, hospedagem).
**Fontes:** diário `docs/decisoes-reestruturacao-2026-09-16.md` (cada decisão com a justificativa do Leonardo e a verificação feita) e os levantamentos em `docs/`: `inventario-fica-ou-sai`, `espelho-regras-por-obra`, `mapeamento-emails-medicao`, `nomes-arquivo-por-obra`, `reajuste-pleitos`, `prazos-vigencia-execucao`.

## 0. Filosofia

**O sistema é onde o trabalho é feito; o registro é consequência.**

A versão anterior vigiava Outlook, SharePoint e RM e pedia que a pessoa confirmasse palpites numa fila de sugestões. Na prática isso modelou o processo na ordem errada, gerou ruído (24 sugestões para 12 medições; 84 de 102 alertas de reajuste falsos) e não entrou na rotina de ninguém. A equipe continuou gerando espelho e baixando certidões na dashboard antiga e protocolando pelo Outlook.

A reestruturação inverte o papel do sistema:

1. **Ponto de passagem obrigatória.** O sistema faz o trabalho que a pessoa já é obrigada a fazer: gerar o espelho, mandar o e-mail ao faturamento, montar o pacote e mandar o e-mail de protocolo, mandar o pleito de reajuste, a carta de prazo e a comunicação de conclusão. O registro nasce do ato.
2. **Nada adivinha.** Saem a leitura de e-mail, a leitura de planilha e a fila de sugestões. A única fonte automática é o RM, que é fato contábil, e mesmo ele só confirma o que a pessoa já fez.
3. **Quem executa não julga.** Operação: digitar poucos campos, arrastar, conferir, clicar. Regras, cadastro e instrumentos contratuais ficam com o Leonardo, por arquivo versionado, sem tela.
4. **Aviso em que dá para confiar.** Poucos, com obra, dias e valor, que somem por um ato real e continuam enquanto o órgão não responde.
5. **Avisa e deixa seguir.** Nada bloqueia a operação; o que foge da regra pede uma linha de justificativa, auditada. Bloqueio empurra o trabalho para fora do sistema.
6. **Simples que funciona.** Sem serviço pago por uso, sem cálculo de índice de reajuste, sem custo e margem, número do ofício digitado, assinatura por fora.
7. **A regra vem do documento real.** Toda regra desta spec saiu de e-mail, contrato, apostilamento ou nota reais; quando a lembrança e o documento divergiram, valeu o documento.

## 1. Usuários e acessos

| Perfil | Quem | Faz |
|---|---|---|
| Operação | as operadoras (mesmo acesso); estagiária quando houver | Tudo da seção 3: espelho, nota, documentos, protocolo, pleitos e cartas, marcar medição final |
| Diretoria | Direção do grupo | Só leitura: tela da seção 10.5 e página da obra |
| Administrador | Leonardo | Usuários, auditoria, saúde do RM e do backup. Não há tela de cadastro |

- Acesso só pela rede interna (servidor `<servidor>`), como hoje.
- Cada pessoa de operação conecta a **própria conta Microsoft** uma vez; todo e-mail enviado pelo sistema sai da caixa de quem clicou.
- Permissão por obra e perfil financeiro separado: fora do escopo.
- Trocar a própria senha: entra. Sessão de 30 dias na rede interna.

## 2. O processo real e os estados da medição

Processo verificado nos e-mails de maio a setembro de 2026:

1. O órgão informa a medição por canal não mapeável (e-mail, WhatsApp, foto, planilha devolvida). Correções acontecem aqui, antes da nota.
2. A engenharia gera o **espelho** e manda ao faturamento.
3. O faturamento emite a(s) nota(s) **no portal da prefeitura** e devolve os PDFs. O lançamento no RM vem depois, do mesmo dia a dois dias (medido em produção).
4. A engenharia monta o **pacote** (carta, notas, certidões, regularidade, peças técnicas), assina pelo DocuSign e **protocola por e-mail** ao órgão. Essa é a data do ofício, que manda.
5. O órgão paga; a baixa aparece no RM.

Estados da medição e quem os move:

| Estado | Entra quando | Por quem |
|---|---|---|
| `espelho_gerado` | a pessoa gera o espelho (a medição nasce aqui) | operação |
| `espelho_enviado` | o e-mail ao faturamento é aceito pelo Graph | sistema, no ato do envio |
| `nota_emitida` | todas as notas esperadas foram anexadas, ou o RM enxergou as notas da Lotufo (o que vier primeiro) | operação ou RM |
| `protocolada` | o e-mail de protocolo é aceito pelo Graph | sistema, no ato do envio |
| `recebida` | baixa do RM cobre o devido | RM |
| `cancelada` | ato com motivo | operação |

Regras:

- Tipos: `execucao`, `reajuste`, `projeto`. **Reajuste é medição própria**, com número, espelho e nota próprios, criada junto com a de execução quando a pessoa digita o valor do reajuste.
- Uma medição gera uma ou mais notas (seção 4.2). "Nota emitida" só fecha quando o conjunto esperado está completo, ou quando a pessoa declara completo com justificativa.
- Gerar o espelho de novo guarda a versão anterior como substituída, com data e motivo opcional. Nada é sobrescrito.
- Protocolar sem nota: avisa e segue com justificativa (casos reais: Coxipó recebe a medição pronta do órgão; Região Oeste protocola por link).
- **Medição final**: marcação feita pela operação. Põe o contrato em "em encerramento" (seção 7.4).
- O número do protocolo devolvido pelo órgão é campo opcional, com o comprovante anexado. A MTPAR não devolve.
- Carga do legado: `recebida` continua; legado `nf_emitida` e `protocolada` viram `protocolada`; `prevista` sem valor é descartada (o cronograma já guarda o previsto). A regra roda primeiro em ensaio, com relatório, antes de tocar a produção.

## 3. O fluxo da operação

O que a pessoa faz no sistema para protocolar uma medição. Digitação total: quatro campos e o número do ofício.

0. **Fora da medição, quando a tela inicial avisar:** arrastar a certidão renovada; uma vez por mês, anexar o PDF de regularidade da empresa.
1. **Gerar o espelho** (na obra): número, competência, valor da medição ou do projeto, valor do reajuste. Opcional: arrastar o que o órgão mandou, que fica como evidência "informado pelo órgão".
2. **Conferir e enviar ao faturamento:** o sistema mostra uma linha por nota (emissor, município, valor, mão de obra, material, INSS, ISS, IRRF, IBS, CBS, líquido). A pessoa confere e envia; o e-mail sai com os espelhos anexados.
3. **Anexar as notas:** arrastar os PDFs que o faturamento devolveu. O sistema lê a nota da Lotufo e **confere contra o espelho**. Em consórcio, arrastar também as notas das consorciadas e a fatura do consórcio (FRC).
4. **Montar o protocolo:** digitar o(s) número(s) do ofício (CT); arrastar as peças técnicas que o órgão exige e que são feitas fora (caderno ou boletim assinado, planilha editável, relatório fotográfico, diário, ensaios). O sistema gera a carta e junta sozinho notas, certidões vigentes, regularidade do mês e comprovante do CNO, na ordem do órgão.
5. **Assinar por fora:** baixar o pacote, assinar no DocuSign, arrastar o assinado de volta.
6. **Conferir e enviar:** prévia com destinatários, cópias, assunto, anexos com tamanho e o que falta. Enviar marca a medição como protocolada.
7. **Depois:** o RM marca o recebimento. Opcional: número de protocolo do órgão e comprovante.

## 4. Espelho de nota fiscal

### 4.1 Decisão

O gerador é **reconstruído em Python dentro do sistema**. Sai o caminho atual (dashboard antiga → Worker → Power Automate → Office Script lendo a planilha-motor de cada obra no OneDrive → modelo Word). O fluxo do Power Automate continua ligado até cada obra passar nos gabaritos.

### 4.2 Regra por obra

O motor atual não calcula: lê células da planilha de cada obra. A reconstrução reimplementa as fórmulas, tabeladas em `docs/espelho-regras-por-obra-2026-09-16.md`, e vira a **regra fiscal da obra** no cadastro (seção 8):

- **Saídas** (uma por nota) e seus eixos independentes: tipo (execução, reajuste, projeto), município (MT-388, Estações BRT, BRT, Atalaia), entidade emissora (Leblon 50/50; Atalaia 80/20; BRT 49/49/2), fonte de recurso (Coxipó 3ª). Saída com valor zero não emite.
- **Rateio** por fator fixo cadastrado, com a última parcela recebendo o resto.
- **Retenções:** padrão é mão de obra 40% truncada, material por diferença, INSS 11% e ISS 5% sobre a mão de obra, IRRF sobre o total (1,2% SINFRA, SES e prefeituras; 1,5% MTPAR; 4,8% projeto). Exceções tabeladas, não inferidas: Alta Floresta 60/40 sem INSS; MT-388 Cáceres com ISS sobre material e líquido sem ISS; Deciolândia com ISS destacado e sem IRRF, digitando o valor cheio do consórcio e emitindo a cota de 33,33%; Maternidade VG com ISS de 2% sobre o total.
- **Arredondamento:** a conta imita a planilha da obra, inclusive o ponto flutuante do Excel (decisão do Leonardo em 2026-09-23, depois de a conferência achar um espelho real que a conta decimal exata não reproduzia: Oriundi 46ª, Rivoli VG, MO 6.764,19). TRUNC/ROUND nas células como o Excel (double levado a 15 dígitos significativos antes do corte) e a leitura do espelho como o motor antigo (folga de 1e-4 centavo no truncamento). Cada tributo de cada obra declara truncar ou arredondar. O resultado final continua em centavos inteiros.
- **IBS e CBS:** linhas novas no espelho (as notas de 2026 já destacam CBS 0,9% e IBS 0,1%, com redução quando aplicável). Alíquotas e redução ficam na regra fiscal, com vigência por data.
- **Valor por extenso:** regras do motor atual (acentos, cem e cento, milhão e milhões, "de reais"), em caixa alta.
- **Modelos Word:** os 61 modelos vão para o repositório; campos por controle de conteúdo (valor, mão de obra, material, INSS, ISS, IRRF, extenso, medição, período), mais os novos de IBS e CBS.

### 4.3 Prova

Uma obra só passa a ser gerada pelo sistema quando reproduz **ao centavo** os gabaritos: as 14 notas conferidas (MT-388, Atalaia, BRT, Estações), a MT-402 23ª, os cinco valores por extenso, e ao menos um espelho real recente da própria obra. Ordem de porte: MT-402, MT-401, Cavalaria; Região Oeste; MTPAR (Cultural, Espaço Show, Orla, Xtreme, Granito); 5 Bairros, Coxipó 2ª e 3ª; Alta Floresta; MT-388; Estações e Terminais BRT; Leblon; Atalaia; BRT; Deciolândia; Maternidade VG.

### 4.4 Nomes dos arquivos gerados

Padrão único para tudo que o sistema gera:

```
{DOCUMENTO} - {obra} - {nº}ª {Natureza} ({MM.AAAA})[ - {consorciada}][ - {município}].{ext}
```

`DOCUMENTO` é `ESPELHO`, `CARTA` ou `OFÍCIO`; o ofício leva o número na frente (`CT-301-LT-2026 - ...`), com a sigla da entidade (LT, CCL, CO). `obra` é o nome curto do cadastro. Número com dois dígitos. `Natureza` é `Medição`, `Reajuste` ou `Projeto`. Consorciada e município só aparecem quando a obra tem mais de um. O que vem de fora (nota, FRC, planilha com revisão, PDF do DocuSign) é só reconhecido, nunca renomeado.

## 5. E-mails enviados pelo sistema

### 5.1 Mecânica

- Microsoft Graph com permissão **delegada, por usuário**: `Mail.Send`, `Mail.ReadWrite` (necessária para anexos acima de 3 MB, por rascunho e sessão de upload) e `offline_access`. Login por código de dispositivo numa tela "conectar minha conta". O token de atualização fica em arquivo por usuário, na pasta de segredos, fora do repositório.
- O sistema **não lê** caixa de e-mail. `Mail.ReadWrite` tecnicamente permite leitura; o código a usa só para criar o rascunho, subir os anexos e enviar, e isso é coberto por teste. As permissões `Mail.Read`, `Mail.Read.Shared`, `Sites.Read.All` e `Files.Read.All` deixam de ser pedidas.
- Todo envio grava, sem alteração posterior: quem enviou, data e hora, destinatários, cópias, assunto, identificador da mensagem, e nome, tamanho e hash de cada anexo. **Falha de envio não muda estado nenhum.**
- A mensagem aparece nos itens enviados da pessoa; a resposta do órgão chega à caixa dela normalmente.
- Um envio pode cobrir mais de uma medição (SINFRA manda execução e reajuste juntos).

### 5.2 Tipos de envio

| Envio | Destinatários | Texto | Anexos |
|---|---|---|---|
| Espelho ao faturamento | fixos do cadastro geral, mais consorciadas na obra de consórcio | fixo | um espelho por nota |
| Protocolo de medição | família do órgão (5.3) | fixo por família | pacote (seção 6) |
| Pleito de reajuste | protocolo do órgão e fiscal | fixo | ofício gerado mais planilha de cálculo e cronograma anexados pela pessoa |
| Carta de prorrogação de prazo | idem | fixo | carta gerada mais cronograma anexado |
| Comunicação de conclusão | idem | fixo | carta gerada |

O corpo do e-mail fica editável na prévia para o caso que fuja do padrão (exemplo: colar um link do SharePoint).

### 5.3 Famílias de protocolo (cadastro do órgão)

- **MTPAR:** o e-mail de protocolo mais o fiscal nominal da obra; cópias fixas; pede devolutiva do número de protocolo; **um PDF único**; medição e reajuste **sempre separados**, dois ofícios.
- **SINFRA**, por superintendência (SAGPM/SUOESP, SUEF I, SUEF II, SUPU, SACID, protocolo geral): endereço da superintendência mais fiscal e supervisora; não pede devolutiva; PDF assinado mais planilha editável; medição e reajuste juntos; **25 MB por documento**, medição e reajuste em arquivos separados, **na ordem do check-list**. Há dois envios: o da medição assinada e o da nota com certidões e regularidade.
- **SES:** o e-mail de protocolo mais fiscal; carta com lista numerada dos anexos; PDF único; medição e reajuste em dois ofícios e dois e-mails.
- **Prefeitura de Cuiabá e de Várzea Grande:** envio reativo; aceita pacote por link.

O fiscal nominal muda com o tempo: o cadastro guarda o histórico.

### 5.4 Número do ofício (CT)

**Digitado à mão.** O contador é da empresa inteira e vive fora do sistema. O sistema avisa se o número já foi usado, sem travar. Famílias que separam medição e reajuste pedem dois números.

## 6. Pacote de protocolo e assinatura

- O sistema **monta o pacote**: carta gerada pelo modelo da família ou da obra, notas anexadas, certidões vigentes exigidas, regularidade do mês, comprovante do CNO da obra, e as peças técnicas que a pessoa arrastou, na ordem definida no cadastro do órgão. Saída conforme a família: PDF único, ou PDF mais ZIP de certidões, mais planilha.
- Acima de 25 MB por documento (SINFRA): separa medição e reajuste; persistindo, avisa.
- **A carta** traz número do ofício, data, destinatário e fiscal, referência do contrato, assunto, corpo padrão, e na SES a lista numerada dos anexos com a nota discriminada. Número da medição, competência e valores vêm dos dados, o que elimina os erros de cópia achados nas cartas reais (41ª no lugar de 42ª, ano errado).
- **Assinatura manual, do pacote inteiro:** a pessoa baixa, assina no DocuSign e arrasta o assinado de volta. Não há integração.
- **Conferência do assinado**, por aviso: (1) as primeiras páginas batem, por texto, com as páginas do pacote montado, ignorando o carimbo; (2) páginas a mais no fim só são aceitas se reconhecidas como certificado do DocuSign; (3) todas as páginas do pacote têm o carimbo do envelope, com o mesmo identificador. Pega página trocada e, sobretudo, PDF que ainda não foi assinado.

## 7. Nota fiscal, reajuste, prazos e encerramento

### 7.1 Nota: o PDF avança, o RM confirma

- A nota nasce no portal da prefeitura; o RM é lançado depois. **Quem chegar primeiro avança a medição; o segundo confirma.**
- Leitor determinístico do PDF da NFS-e da Lotufo, nos dois leiautes em uso (Prefeitura de Cuiabá e DANFSe nacional): número, data, competência, tomador, valor, ISS, INSS, IRRF, IBS, CBS, líquido. PDF sem texto: a pessoa digita número, data e valor.
- **Conferência contra o espelho** antes do protocolo: qualquer diferença aparece na prévia.
- Notas de consorciadas e FRC são anexadas sem leitura obrigatória. A FRC continua sendo emitida e numerada pela controladoria; o sistema só guarda.
- O RM (notas e baixas de hora em hora, casamento por centro de custo e valor, como hoje) confirma pelo número da nota, em silêncio. Avisos: valor divergente; nota protocolada que não aparece no RM depois de 5 dias. Dúvida de casamento vira botão "vincular nota" dentro da medição. **Recebimento só pelo RM.**

### 7.2 Reajuste

- Unidade: o par **(contrato, data-base)**; até dois por contrato (hoje só 5 Bairros, janeiro e março). Cada par guarda o mês de aniversário e o nome do índice como texto (INCC, setorial FGV/DNIT, percentual por apostilamento). **O sistema não calcula índice nem valor de reajuste.**
- O reajuste vale a partir do **mês do aniversário** (OT 028/2015 da CGE, item 3.2.1; cláusula 11.45 do contrato SINFRA). Não existe prazo em dias para o pleito; o "60 dias antes" da dashboard antiga não tem origem em norma.
- Ciclo de cada par, a cada ano: aviso a partir de 30 dias antes do aniversário ("pleito ainda não enviado") → **pleito enviado pelo sistema** (ofício gerado; planilha de cálculo e cronograma anexados pela pessoa; CT manual) → aviso vira "apostilamento pendente há N dias" → **apostilamento carregado no cadastro** (número, data, percentual e eficácia quando houver, PDF) → aviso some.
- O que fecha o ciclo é o **apostilamento**, não o ofício, que é reenviado a cada aditivo. Reemissão é novo pleito no mesmo ciclo.
- Marcação "sem reajuste" no contrato, padrão falso (nenhum caso real encontrado).
- Sai o alerta "execução sem reajuste par".

### 7.3 Prazos

- O relógio que importa é o da **execução**. Na SINFRA a vigência se prorroga sozinha por cláusula; o aviso de vigência só existe onde isso não vale.
- O cadastro do órgão guarda a **folga** entre execução e vigência (SINFRA 90 dias; SES 99; MTPAR a do contrato; Prefeitura de Cuiabá prazo único). Instrumento carregado que quebre a folga gera aviso.
- Ciclo: aviso aos 60 dias do fim da execução, crítico aos 30 → **carta enviada pelo sistema** (a seção "histórico do contrato" sai pronta dos instrumentos já cadastrados; a pessoa digita justificativa, número de dias e CT) → "pedido enviado, instrumento pendente há N dias" → instrumento carregado no cadastro → aviso some e nasce **"endosso do seguro-garantia em 5 dias"**. Execução vencida sem instrumento mantém aviso crítico com os dias e a data do pedido.
- O instrumento de prazo pode ser **termo aditivo** (contratos sob a Lei 8.666) ou **termo de apostilamento** (contratos sob a Lei 14.133). O sistema aceita os dois.
- **Instrumento retroativo é aceito e sinalizado, nunca recusado** (aconteceu em 3 de 8 casos medidos).
- **Paralisação** é registro próprio: ordem de paralisação e ordem de reinício, carregadas no cadastro; o período não conta para o aviso de execução.
- A carta não sugere "chuva" como justificativa isolada (o contrato SINFRA veda); só ligada a ordem de paralisação do órgão.

### 7.4 Encerramento

Contrato ganha o estado **`em_encerramento`**, entre ativo e encerrado, disparado pela medição final. Nele os avisos de prazo param e entram quatro marcos: conclusão comunicada (carta enviada pelo sistema), recebimento provisório, recebimento definitivo, baixa da garantia. Os três últimos entram pelo cadastro. Aviso: "medição final há N dias, conclusão não comunicada".

## 8. Cadastro versionado

**Não existe tela de cadastro.** Tudo abaixo é editado pelo Leonardo com o Claude, em arquivos YAML no repositório, e carregado no banco por comando.

```
cadastro/
  geral.yaml                 faturamento, cópias internas padrão
  orgaos.yaml                órgãos e superintendências: família de protocolo, endereços, cópias,
                             texto, juntos ou separados, planilha editável, limite por documento,
                             ordem do check-list, folga de vigência, vigência automática,
                             documentos exigidos (na medição e no reajuste)
  entidades.yaml             Lotufo, consórcios, consorciadas: CNPJ, papel, coligada RM, sigla do ofício
  contratos/<nome-curto>.yaml  um por obra
  espelho/<nome-curto>.yaml    regra fiscal da obra (seção 4.2)
  modelos/                   modelos Word de espelho, carta e ofício
```

Arquivo do contrato: instrumento, órgão, entidade, objeto, município, CNO, ART, nome curto, lei (8.666, 14.133, 13.303), valor original, percentual da Lotufo e consorciadas com cota, centro de custo do RM, início, execução e vigência originais, status, fiscal com histórico, destinatários extras (supervisora), exceções às regras do órgão, datas-base, marcação sem reajuste, cronograma físico-financeiro vigente, e a lista de **instrumentos** (aditivos de valor e de prazo, apostilamentos de prazo e de reajuste, paralisações, marcos de encerramento), cada um com número, data, efeito e PDF.

Comando: `cadastro validar` (esquema, referências, somas, datas coerentes, folga) e `cadastro aplicar [--ensaio]` (mostra a diferença; aplica numa transação; idempotente; grava auditoria com o hash do commit). O deploy de produção roda `aplicar`.

Regra de história: instrumento assinado já aplicado **não é editado**; correção é entrada nova que referencia a corrigida. O carregador recusa alteração silenciosa de instrumento aplicado.

Carga inicial: as **22 obras do QDOP de 27/08/2026**, com os status dele (em andamento → ativo; paralisada → suspenso; concluída → em encerramento), pré-preenchida com o que os levantamentos já acharam e conferida obra a obra pelo Leonardo.

Na dashboard, contrato, aditivos, entidades e tipos de documento viram **só leitura**.

## 9. Documentos de protocolo

Duas gavetas:

- **Certidões** (têm validade, são da empresa): federal, FGTS, trabalhista, estadual, municipal da sede, falência. Entidades: as sete com uso comprovado (Lotufo, Guaxe, Encomind, Rivoli, consórcios Integra BRT, Complexo Leblon e Oriundi). O órgão de consórcio recebe as do consórcio e das consorciadas.
- **Regularidade mensal** (por competência, por empresa, vinda do DP): folha, SEFIP/eSocial, INSS. Um PDF por mês, anexado uma vez, usado em todos os protocolos daquele mês. O comprovante do CNO é da obra e vem do cadastro; o sistema junta os dois.

Regras:

- Subir documento é **operação**: arrastar o PDF; o sistema lê tipo, empresa (pelo CNPJ) e validade; a pessoa confere e grava. Os seis leitores da dashboard antiga são portados e provados contra as certidões reais que ela usa de teste. A validade da certidão de falência é calculada (30 dias úteis, com feriados nacionais). PDF sem texto passa pelo **OCR local** (Tesseract no servidor, português; emenda de 2026-09-24, decisão do Leonardo): primeiras 2 páginas, um por vez, com prazo; a leitura vai para conferência e a certidão gravada fica marcada "lida por OCR". Sem OCR instalado, ou se ele falha: três campos digitados.
- O leitor registra a natureza: negativa, ou positiva com efeito de negativa. Positiva pura é recusada.
- Vale sempre a de maior validade por empresa e tipo. Histórico não se apaga.
- **O que é exigido** vem do cadastro do órgão, com exceção por contrato. No reajuste da SINFRA vão as mesmas cinco da medição, como a operação envia (decisão de 2026-09-23; a IN 001/2024 exigiria só a estadual). Certidão de falência não vai em protocolo de medição nem de reajuste (conferido em 24 protocolos reais em 2026-09-23).
- O ponto de cobrança é a **prévia do protocolo**: exigido, vigente hoje, faltando, com o link de emissão ao lado. Faltou: avisa e segue com justificativa.
- ZIP por empresa com data de referência ("vigentes em DD/MM"), para licitação.

## 10. Telas

### 10.1 Tela inicial da operação

- **Avisos** (seção 11), uma linha cada, com obra, dias e valor quando houver.
- **Medições protocoladas no mês: X de N** obras ativas, pela data do ofício.
- **Valor protocolado no mês** e **total protocolado no mês anterior**.
- Nada de sugestões, pendências ou "parada no órgão".

### 10.2 Medições

Lista de medições em andamento, com filtro por obra e estado, para a pessoa retomar de onde parou. É navegação, não aviso.

### 10.3 Página da obra

Cabeçalho com órgão, instrumento, valor vigente, percentual da Lotufo, execução e vigência com dias restantes, status. Abas: Medições (gerar espelho; cada medição com a linha do tempo em painel lateral), Notas, Documentos, Reajuste, Prazos, Contrato (leitura).

### 10.4 Documentos de protocolo

Por empresa: vigentes, vencendo, faltando; área de arrastar; regularidade do mês; ZIP.

### 10.5 Tela da diretoria

Tudo na **cota da Lotufo**. Vocabulário fixo: **medido, faturado (nota emitida), protocolado, recebido**.

1. **Onde está o dinheiro:** medido esperando nota → nota emitida esperando protocolo → protocolado esperando pagamento (até 30, 31 a 60, mais de 60 dias; por órgão) → recebido no mês. À parte: reajustes esperando apostilamento (quantos, há quantos dias, e o valor já medido quando existir).
2. **O mês e o ano:** medido no mês contra o previsto no cronograma e contra o mesmo mês do ano anterior; acumulado do ano; um gráfico de 12 meses.
3. **Os próximos meses:** faturamento previsto para 6 meses (cronogramas); recebimento previsto = protocolado mais o prazo de pagamento medido de cada órgão (referência em 09/2026: SINFRA 5 dias, MTPAR 10, Prefeitura de Cuiabá 57).
4. **A carteira:** saldo a executar; meses de produção no ritmo dos últimos 6 meses; participação de cada órgão; contratos cuja execução acaba em 6 meses.
5. **As obras:** tabela no estilo do QDOP com farol e o motivo escrito; clique abre a obra; **exporta o QDOP no leiaute oficial** (GL.SGI.FRP.DE.250).

Avisos da diretoria: execução vencida sem instrumento; pagamento atrasado além do prazo normal daquele órgão; obra paralisada; reajuste pendente há mais de 90 dias. Certidão não aparece aqui.

"Prazo normal do órgão" = terceiro quartil dos dias entre o protocolo e a baixa nos últimos 12 meses daquele órgão, com no mínimo 10 notas; abaixo disso, 30 dias.

O total a receber só vai para a tela depois de conciliado com a controladoria: a medição bruta de 09/2026 mistura consórcios no valor cheio e notas cuja baixa não casou.

**Custo e margem: fora**, por decisão reafirmada em 2026-09-21.

### 10.6 Administração

Usuários, auditoria, saúde do RM (rodadas, reconciliação) e do backup. Sai a tela Microsoft 365 de detecção; entra a lista de contas Microsoft conectadas.

## 11. Catálogo de avisos

| Aviso | Aparece quando | Some quando | Quem vê |
|---|---|---|---|
| Execução vencendo | 60 dias do fim (crítico aos 30), sem pedido enviado | carta enviada | operação |
| Instrumento de prazo pendente | carta enviada, instrumento não carregado; ou execução vencida | instrumento carregado | operação, diretoria se vencida |
| Vigência vencendo | só em órgão sem prorrogação automática | instrumento carregado | operação |
| Folga quebrada | instrumento deixou execução e vigência fora da folga | novo instrumento | operação |
| Endosso do seguro-garantia | instrumento de prazo carregado | marcado como entregue no cadastro | operação |
| Reajuste: pleito não enviado | 30 dias antes do aniversário | pleito enviado | operação |
| Reajuste: apostilamento pendente | pleito enviado | apostilamento carregado | operação, diretoria após 90 dias |
| Documentos da empresa | certidão exigida vencida, ou vencendo (7 dias para as de 30 dias de validade; 15 para as demais); uma linha por empresa | documento novo gravado | operação |
| Regularidade do mês | dia 10 sem o PDF do mês | PDF anexado | operação |
| Nota divergente do espelho | leitura da nota difere do espelho | nova nota ou justificativa | operação |
| Nota ausente do RM | 5 dias após o protocolo | RM enxerga a nota | operação |
| Pagamento atrasado | protocolada além do prazo normal do órgão | baixa no RM | diretoria |
| Obra paralisada | paralisação aberta | ordem de reinício carregada | diretoria |
| Conclusão não comunicada | medição final sem a carta | carta enviada | operação |

O e-mail diário de avisos fica fora desta spec.

## 12. Modelo de dados

Mudanças sobre o banco atual (migrações 001 a 017), sempre por migração nova, sem reescrever histórico:

- `medicoes`: novos estados e transições (seção 2); marcação `final`; número do protocolo do órgão.
- **`envios`** (novo): tipo, usuário, data e hora, para, cópia, assunto, identificador da mensagem; `envio_anexos` (nome, tamanho, hash); `envio_medicoes` (N para N). Substitui `medicao_protocolos` para o que é novo; o legado fica.
- **`espelhos`** (novo): versões por medição, com entradas, saídas calculadas, arquivos e situação (vigente, substituído).
- `medicao_documentos`: passa a aceitar arquivo local (evidência do órgão, nota em PDF, peça técnica, pacote montado, pacote assinado), com hash.
- `notas_fiscais`: origem (`pdf`, `rm`), valores lidos do PDF, situação da confirmação.
- `contratos`: nome curto, lei, município, CNO, ART, estado `em_encerramento`; `contrato_datas_base` (novo); `contrato_fiscais` (histórico).
- `orgaos` (novo) com as regras da família; `entidades` ganha sigla do ofício e o papel consorciada.
- `instrumentos`: generaliza `aditivos` (aditivo de valor, de prazo, apostilamento de prazo, de reajuste, paralisação, marco de encerramento); os aditivos existentes migram.
- `pleitos` (novo): reajuste, prazo e conclusão, ligados ao envio e ao instrumento que os atendeu.
- `certidoes`: seis tipos, natureza; `regularidade_mensal` (novo).
- `graph_tokens` não entra no banco: arquivo por usuário na pasta de segredos.
- Saem, com os dados arquivados: `sugestoes`, `deteccao_padroes`, `deteccao_config`, `mensagens_observadas`, `planilhas_config`, `planilhas_observadas`, `graph_sincronizacoes`.

## 13. O que sai do código

`deteccao.py`, `sincronizacao_graph.py`, a parte de leitura de `graph.py`, `sugestoes.py` e suas rotas e telas (Sugestões, Painel da Engenharia atual, Microsoft 365), formulários de contrato, aditivo, entidade e tipo de certidão, alerta de reajuste sem par, painel geral atual. Ficam: autenticação, permissões, auditoria encadeada, dinheiro, cronograma, leitura de PDF, RM (cliente e sincronização), backup, watchdog, deploy pinado.

## 14. Migração e corte

1. Cadastro das 22 obras conferido e aplicado; medições de julho de 2026 em diante carregadas; estados do legado remapeados em ensaio e depois em produção, com backup antes.
2. Espelho obra a obra, conforme os gabaritos; até lá o fluxo antigo gera o espelho daquela obra.
3. Certidões: no dia do corte, reler os PDFs vigentes da pasta de certidões do SharePoint pelo leitor novo, carregar, conferir.
4. Os fluxos do Power Automate e a dashboard antiga **continuam ligados** (decisão do Leonardo em 2026-09-24, que substitui os antigos itens 4 e 5 desta seção). A aba de licitações não é portada.
5. O corte do bloco 9 fica no sistema novo: sai o código de detecção e a leitura do Graph.

## 15. Segurança, erros e testes

- Valem as regras do projeto: centavos inteiros, arredondamento único, sem exclusão física de registro financeiro, auditoria sem alteração, correção como evento novo.
- Envio de e-mail, montagem de pacote e carga do cadastro são auditados com usuário e hash dos arquivos.
- Arquivos arrastados: PDF validado por assinatura de arquivo, teto de tamanho, nome em disco pelo hash, leitura em subprocesso com tempo máximo, como já é feito nas certidões.
- Testes no padrão do repositório (`backend/tests/test_<modulo>.py`): gabaritos do espelho; leitores de certidão e de nota contra textos reais; conferência do PDF assinado; cadastro (validação, idempotência, recusa de alteração de instrumento aplicado); máquina de estados; envio contra um simulador do Graph.
- Revisão adversarial (gate Sol) nas branches que tocam dinheiro (espelho, nota, diretoria), autenticação (Graph por usuário) e arquivo externo (pacote, leitores).

## 16. Fora de escopo

Custo e margem; cálculo de índice e de valor de reajuste; integração com DocuSign; leitura de caixa de e-mail e de planilha; licitações; acesso de fora da rede; permissão por obra; e-mail diário de avisos; emissão e numeração da FRC; emissão de certidão em portal.

## 17. Ordem de entrega

1. **Fundação:** cadastro versionado, carga das 22 obras, órgãos e entidades, nova máquina de estados, contas Microsoft por usuário com envio.
2. **Espelho:** gerador, conferência em tela e envio ao faturamento; obras por ondas.
3. **Nota:** leitor do PDF, conferência contra o espelho, confirmação pelo RM.
4. **Documentos de protocolo:** seis leitores, duas gavetas, migração das certidões.
5. **Protocolo:** carta, pacote, assinatura manual com conferência, envio.
6. **Tela inicial e avisos.**
7. **Reajuste e prazos:** pleitos e cartas, instrumentos, paralisação, encerramento.
8. **Diretoria** e exportação do QDOP.
9. **Corte:** remoção do código de detecção e da leitura do Graph (Power Automate e dashboard antiga continuam ligados, decisão de 2026-09-24).

Esta spec é o guarda-chuva. **Cada bloco ganha o seu próprio plano de implementação**, escrito quando o bloco anterior estiver entregue, e é uma branch, com merge em `master` só com OK do Leonardo.

## 18. Pendências externas

- No aplicativo do Entra ID: incluir `Mail.Send` e `Mail.ReadWrite` delegadas; as operadoras com usuário no sistema e conta conectada.
- Modelos de carta por família e o check-list de cada órgão (SINFRA: anexo da IN 001/2024).
- Conferir no QDOP: Estações e Terminais BRT com vigência anterior ao fim da execução; Maternidade com as duas datas iguais; situação de prazo de Deciolândia, Xtreme, Atalaia e MT-401.
- Quem protocola Deciolândia e Rota do Oeste (não aparecem na caixa do Leonardo).
- Conciliação do total a receber com a controladoria antes de exibi-lo.
- Alta Floresta: obra concluída, contrato aberto, vigência vencida em 26/06/2026; adiado pelo Leonardo.
- Um PDF assinado que tenha vindo com o certificado do DocuSign, para servir de gabarito.
