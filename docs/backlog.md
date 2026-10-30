# Backlog

Uma linha por item: data, o que é, onde. Fechou: apagar a linha.

Limpeza de 30/10/2026 (#350): saiu o registro do trabalho já entregue, o que perdeu o objeto com o corte de
25/09/2026 (sem leitura de e-mail e SharePoint) e o que repete issue aberta. O histórico fica no git.

## Código

- 2026-10-13 Backup (#55): ficam fora do backup os arquivos de `dados\certidoes`, `regularidades`, `protocolos`, `pleitos`, `frc` e `assinaturas` (todos pelo sha256, como os quatro já cobertos). Acrescentá-los a `PASTAS_ARQUIVOS` em `backup.py`.
- 2026-10-13 Backup (#55, gate Sol S1): a cópia externa diária do BANCO (`_copiou_hoje` e `copiar_externo`, `backup.py` › `rodada`) continua na thread do snapshot, como antes da #55; compartilhamento pendurado nela ainda para os snapshots. Levá-la para o worker dos arquivos (depois da passada externa, o que também deixa o banco lá fora citando só arquivos já copiados).
- 2026-10-13 Formulários (resto da issue #11): ainda ficam desabilitados até o campo valer, em vez de validar no clique e mostrar o erro no campo, o `FormMotivo` (`MedicaoAtos.tsx`), o "Adicionar link" (`EnviarNota.tsx`), o "Registrar" do envio por fora (`RegistrarFora.tsx`), o "Gravar regularidade" (`DocumentosEmpresa.tsx`) e o nº do órgão (`MedicaoPagina.tsx`; em `Protocolo.tsx` deixa clicar vazio, mas sem erro no campo). Padrão: `ErroCampo` e `aria-describedby`, como em `MedicaoAtos.tsx` › `FormProtocoloManual`.
- 2026-09-28 A natureza `projeto` dos documentos exigidos só aparece no checklist da medição, não no quadro de exigidos da obra (`ObraAbas.tsx`).
- 2026-09-25 Catálogo de contatos corta em 200 linhas, sem virtualização (`correio.py`). [G5-04]
- 2026-09-25 Decisão D6 do loop de UI ("Emitir" só nas certidões que pedem ação): na obra já é assim; em Documentos o botão aparece em toda certidão exigida, com destaque só na urgente (`DocumentosEmpresa.tsx`).
- 2026-09-21 Teto de 25 MiB por e-mail (`correio.MAX_TOTAL`): o envio SINFRA não se divide; acima do teto vira pendência "troque o maior anexo por um link" (spec §5.1: 25 MB por documento).
- 2026-09-02 Health expõe os campos de backup a qualquer cliente da rede interna (sem login). Restringir a admin se a rede deixar de ser confiável.
- 2026-10-10 Pacote 3, do gate Sol, fica: canal de tempo no login (conta existente grava contador, inexistente não; = V-13, baixa) e lockout de 15 min usável para trancar uma conta de propósito, inclusive o admin (= V-04/A-05; mitigado por Desbloquear na tela e `cli desbloquear`; desde a #3 (limite de login por origem), no máximo 20 tentativas erradas por IP em 15 min, o que ainda deixa um IP trancar uma conta com 5). Admin que tenta rebaixar o próprio perfil responde 409 (regra de 28/09), não 422.
- 2026-10-13 #4, gate Sol S2: a escrita equivalente do login recusado (`auth._escrita_dummy`) sobe e desce o contador da conta de menor id. Se `usuarios` ganhar gatilho de UPDATE, coluna de versão/`updated_at` ou restrição no contador, mover essa escrita para uma tabela própria de uma linha (migração nova).
- 2026-09-21 Dívida (gate Sol): o retrato `valor_anterior/valor_novo` de aditivo vindo do cadastro é o vigente no momento da aplicação, como no fluxo manual (`aditivos.py`); instrumento retroativo acrescentado depois não recalcula os retratos já gravados (seria sobrescrever histórico). O vigente em si não é afetado: soma deltas.
- 2026-09-24 `LIMIAR` da conferência (0,90) calibrado com três PDFs reais (Cavalaria, CT-073, CT-286); rever se aparecer falso "página diferente" com planilha longa.
- 2026-09-02 Consultas trazem 24 meses de NFs `2.2.%` de todas as coligadas; NF de coligada sem entidade mapeada só aparece na reconciliação se alguma entidade tiver a coligada (filtro por `coligada_rm`). Sem paginação nem parâmetro de data na API: rever se a resposta passar de alguns MB.
- 2026-09-22 Consorciada A (NF emitida em outro município): sem leitor da nota da consorciada; a nota fica só como documento.
- 2026-09-09 Casador do RM (revisto em 15/10/2026, #71): restam as NFs órfãs. Decidido pelo Leo: Hospital AFL — o valor da medição é o da planilha assinada, a NF de reajuste casa à parte (sem fator no casador: a obra está concluída e não gera medição nova); desalocar manual auditado entrou (admin, #71); nível da NF não vale; a auditoria de divergência campo-livre × centro não será feita.

## Cadastro (Leo)

- 2026-09-24 Reajuste já aplicado sem apostilamento no cadastro: Xtreme (mai/2026), Espaço Show (fev/2026) e MT-388 (jan/2026), conforme o levantamento de 17/09. Cadastrar os apostilamentos (ou o pleito) desses ciclos.
- 2026-09-24 Endossos do seguro-garantia sem histórico: 7 instrumentos de prazo dos últimos 60 dias apareciam com endosso atrasado (Granito, Espaço Show, Estações BRT, Cavalaria, Complexo Cultural, Leblon, MT-402); em 30/10/2026 nenhum `endosso_garantia` está no cadastro. Cadastrar os que já foram entregues.
- 2026-09-24 Paralisações da MT-402 (01/02 a 05/05/2026) e da Coxipó 2ª (desde 01/10/2025) seguem com `# CONFERIR: Leonardo` no cadastro.
- 2026-09-21 Em aberto no cadastro: **Deciolândia** (o TA 155/2022/01/02 acrescenta R$ 10.043.137,01 mas legado e QDOP trazem R$ 1.225.592,35; o instrumento de prazo que leva a 30/11/2026 não está no SharePoint); data de assinatura do TA 176/2025/01/01 das Estações BRT (PDF imagem; usada a data de arquivamento, 03/08/2026) e do 4º TA da Região Oeste (usada a publicação, 20/04/2026); vigência da Cavalaria (SMO 01/11/2027 × banco 05/10/2027); QDOP com vigência errada nos Terminais BRT (16/02/2027; o contrato dá 20/03/2027).
- 2026-09-22 Os apostilamentos de prazo de Leblon (24/08) e MT-402 (26/08) entraram com datas de fonte secundária (SMO, endosso do seguro, planilha da medição, QDOP) porque a cláusula primeira dos PDFs não tem texto: conferir no Diário Oficial quando possível.
- 2026-09-23 SES e prefeituras: incluir `regularidade` na lista do órgão se algum protocolo delas levar o PDF do DP (nenhum dos conferidos levou).

## Decisões do Leo em aberto

- 2026-10-28 #296 (curva S da carteira), gate Sol S1: a curva da carteira no Resumo acumula só dentro da janela de 12 meses (parte de zero no primeiro mês), como já fazia; o Leo decide se ela passa a acumular desde o início dos contratos. O desvio em p.p. do QDOP já conta o histórico inteiro.
- 2026-09-22 **IBS/CBS**: motor e tela prontos (linhas informativas, não deduzem do líquido), mas NENHUMA regra os declara. As notas reais de 2026 trazem CBS 0,9% e IBS 0,1% com redução de 60% (efetivas 0,36% e 0,04%), base = bruto − ISS − PIS − COFINS. Falta decidir se entram no espelho; depois acrescentar os controles `ibs`/`cbs` nos modelos Word e descomentar nos YAMLs.
- 2026-10-15 Recebimento à mão sem NF ligada (revisor da PR #206, fora do recorte da #203): quando a NF chega depois, `sincronizacao_rm.alocar` recusa ligar a medição já recebida, a NF fica solta e `diretoria._notas_em_aberto` a soma no a receber pelo centro de custo. A Saúde não avisa, porque `_recebidas_sem_baixa` só vê as notas ligadas. Decidir se a NF pode ligar a medição recebida à mão (sem mudar o estado dela) ou se vira aviso próprio.
- 2026-10-15 Recebimento automático com parte do faturamento cancelada no RM (gate Sol na PR #202; já existia em master, `_recebimentos` só olha as alocações vigentes): uma medição faturada em duas NFs, com uma delas cancelada no RM, vira `recebida` quando a outra é quitada. A PR #202 fechou o caso do vínculo desfeito à mão. O caso da NF cancelada continua aberto: falta decidir se a medição espera a nota nova.
- 2026-09-02 Itens de medição e medição de ajuste negativa (spec §15.4; hoje o leitor recusa valor negativo com mensagem): conferir se as issues do boletim (#281 a #290) cobrem; se cobrirem, apagar esta linha.

## Externo (Leo)

- 2026-09-25 Diretório Microsoft nas sugestões de destinatário: o código já pede `People.Read` e `User.ReadBasic.All`; falta acrescentá-las (delegadas) no aplicativo do Entra ID e cada pessoa "Conectar de novo".
- 2026-09-04 RM: a API só responde HTTP, então a credencial da conta de serviço viaja em claro na rede interna; trocar a senha do RM que passou pelo chat e criar uma conta de serviço só-leitura.
- 2026-09-02 Segundo administrador da dashboard.

## Decisões vigentes (registro)

- 2026-09-02 Decisão (gate Sol): "execução após a data-base" usa a COMPETÊNCIA, não a data do ofício; aniversário no meio do mês não separa a competência. Revisar se um órgão cobrar pró-rata.
- 2026-09-24 O fluxo "Certidão Alerta" do Power Automate continua ligado (decisão de 2026-09-24); os avisos da tela inicial não dependem dele.
