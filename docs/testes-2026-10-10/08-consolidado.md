# 08 — Consolidado dos testes de quebra (fases 1–3, 10/10/2026)

Fontes: 01 inventário, 02 vermelho estático, 03 fuzz de API, 04 tours no navegador, 05 roteiro, 06 verificação
pela API (verificador A, instância isolada na 8081), 07 verificação pela tela (verificador B, Playwright).
Os verificadores receberam só os passos (05) e não leram 02–04.

**Resultado da verificação: 34 de 34 alegações CONFIRMADAS em duas rodadas. Nenhuma derrubada.**

Severidade final = a menor entre a alegada e a proposta pelo verificador (regra da fase 3: só mantém ou baixa).
Onde baixou, a coluna "antes" mostra a original.

## Lista final

| Roteiro | Origem | O que é | Final | Antes |
|---|---|---|---|---|
| A-01 | F-01 / V-01 | 3 envios simultâneos do mesmo espelho = 3 e-mails e 3 registros | **alta** | |
| A-02 | F-01 / S1 | 3 envios simultâneos do mesmo protocolo de NOTA = 3 e-mails ao órgão (provado agora; no fuzz faltavam os arquivos) | **alta** | |
| A-03 | F-02 / V-02 | banco travado: e-mail sai, envio não fica registrado, resposta manda repetir | média | alta |
| A-16 | T-04 | valor da medição do espelho editável depois da nota, sem aviso; notas seguem "confere" | média | alta |
| A-17 | T-08 / S5 | Cco do envio da nota é descartado sem aviso | média | alta |
| A-19 | T-13 / S9 | página em branco com validade 2099 vira a certidão vigente | média | alta |
| A-06 | F-08 / V-05 | 10 senhas erradas simultâneas contam como 1; a certa entra | média | |
| A-09 | F-07 / S4 | medição `prevista` protocolada direto pela API, sem nota nem envio | média | |
| A-18 | T-09 | SINFRA: medição sai sem o reajuste irmão, sem aviso | média | |
| B-01 | T-02 | "medido no mês": Início (por lançamento, setembro irreal) × Carteira (por competência) | média | |
| B-09 | T-15 / S16 | diretoria vê botões de envio e recebe "Permissão necessária: editar_cadastros" | média | |
| B-10 | T-16 / V-14 | admin não troca senha nem perfil pela tela | média | |
| A-04 | F-03 / V-03 | corpo enorme sem login é lido inteiro antes do 401 (100 MB = 1,4 s) | baixa | alta |
| A-05 | F-04 / V-04 | 5 senhas erradas trancam 15 min; sem desbloqueio (expira sozinho) | baixa | alta |
| A-07 | F-05 / S2 | ID gigante → erro 500 | baixa | média |
| A-08 | F-06 / S3 | nota manual com valor gigante → erro 500 | baixa | média |
| A-10 | F-09 / V-09 | texto do campo e-mail de login falho fica inteiro na auditoria | baixa | |
| A-11 | F-10 / V-11 | "envio por fora" aceita PNG como .eml e protocola | baixa | |
| A-12 | F-11 / V-12 | destinatário e Cco livres no envio (por desenho) | baixa | |
| A-13 | F-12 / S10 | link "do OneDrive" aceita qualquer site e entra no e-mail ao órgão | baixa | |
| A-14 | F-13 / S14 | valor com algarismo arábico-índico aceito | baixa | |
| A-15 | F-14 / S17 | nº do órgão vazio apaga o gravado (só pela API) | baixa | |
| A-20 | T-18 | espelho aceita competência 3 anos antes do contrato | baixa | média |
| A-21 | T-01 | três totais de "obras ativas" (19, 21, 22) | baixa | média |
| B-02 | T-05 | linha do tempo não mostra edição de valor | baixa | |
| B-03 | T-06 | "Valor monetario invalido" sem acento e sem ensinar o formato | baixa | |
| B-04 | T-07 | coluna "Nota" cortada 32 px a 1024 px | baixa | |
| B-06 | T-11 | aviso velho fica depois do envio (a página mostra "enviada" em outros pontos) | baixa | |
| B-07 | T-12 | registrar nº do protocolo sem texto "gravado" (o selo some) | baixa | |
| B-08 | T-14 | recusa de PDF corrompido mostra "ValueError" | baixa | |
| B-11 | T-17 | auditoria com códigos internos e janela de 500 eventos | baixa | |
| B-12 | T-19 | mensagens com "(execucao)" e inglês do validador | baixa | |
| B-13 | T-20 | celular: valor quebra no meio, nome da obra vira "Es…" | baixa | |
| B-05 | T-10 | clique duplo em "Enviar a nota": a tela PROTEGE (1 pedido, 1 e-mail) | ok | |

Nota sobre A-13: o verificador propôs média; a alegação original era baixa. Pela regra fica **baixa**, mas o
risco (link de outro site no e-mail oficial ao órgão) merece ser olhado junto com A-17.

## Achados novos da fase 3
- **N-01 (baixa):** a aba "Aguardando pagamento" mostra um número (obras) e a tabela outro (notas), sem dizer
  que contam coisas diferentes.
- **N-02 (ferramenta de teste, só dev):** o simulador de e-mail dá nome ao arquivo pela contagem da pasta;
  envios simultâneos sobrescrevem o mesmo arquivo. A tabela `envios` é a prova confiável. B-05 continua
  válido porque contou os pedidos de rede (1), não só os arquivos.

## Proposta de pacotes para a fase 4 (correção)

1. **Envio único e registrado** — A-01, A-02, A-03 (e N-02 no simulador). Uma trava por protocolo/espelho
   antes de mandar o e-mail; se o registro falhar depois do envio, não dizer "tente novamente".
2. **O que vai ao órgão** — A-16, A-17, A-18, A-19, A-13, A-11. Valor do espelho travado depois da nota (ou
   aviso crítico), Cco que chega, reajuste irmão junto na SINFRA/VG, teto de validade da certidão manual,
   link só do OneDrive/SharePoint da empresa, .eml conferido.
3. **Login e contas** — A-06, A-05, A-10, A-04, B-10. Contador de falhas atômico, desbloqueio e troca de
   senha pelo admin, mascarar o e-mail inválido na auditoria, teto de tamanho de corpo.
4. **Regras de estado e entrada** — A-09, A-20, A-07, A-08, A-14, A-15.
5. **Tela e textos** — B-01, A-21, N-01, B-09, B-02, B-03, B-04, B-06, B-07, B-08, B-11, B-12, B-13.

## Estado dos ambientes
- Banco principal de dev (8080): alterado pelo verificador B (631, 632, 638 protocoladas). Restaurar
  `dashboard-pre-fase1.db` antes da fase 4.
- Instância do verificador A: parada; `backend/dados/verif/dashboard.db` devolvido ao limpo.
- Simulador: fase 2 arquivada em `fuzz/saidas/correio-simulado-fase2/`; verificador B deixou 3 arquivos em
  `backend/dados/correio-simulado/enviados/`; verificador A, 12 em `backend/dados/verif/correio-simulado/`.
  Nenhum e-mail saiu da máquina.

## Fechamento da fase 4 (10/10/2026, 19h47 a ~23h50)

Cinco pacotes, cinco branches, cinco gates Sol, cinco deploys com OK do dono. Cada pacote: testes que falhavam
antes da correção, revisão do coordenador (Fable), reprodução dos scripts da fase 3 contra a branch, gate Sol
(GPT-5.6 via codex), merge em master, backup consistente da produção e `deploy.ps1` com rollback automático.

| Pacote | Branch | Merge | Achados fechados | Gate Sol | Suíte final |
|---|---|---|---|---|---|
| 1 Envio único e registrado | `fix/envio-unico` | c7b0638 | A-01, A-02, A-03 (+ B-05 confirmado como proteção) | 7 achados, 7 corrigidos, + S8 da revisão | 851 / 85 |
| 2 O que vai ao órgão | `fix/conteudo-envio` | 81cc580 | A-16, A-17, A-18, A-19, A-13, A-11 | 7 achados, 6 corrigidos, 1 refutado | 874 / 92 |
| 3 Login e contas | `fix/login-contas` | e16a108 | A-06, A-05, B-10, A-10, A-04 | 6 achados, 4 corrigidos, 2 para o backlog | 898 / 95 |
| 4 Regras de estado e entrada | `fix/regras-entrada` | 7e7f67a | A-09, A-20, A-07, A-08, A-14, A-15 | 6 achados, 5 corrigidos, 1 registrado | 920 / 97 |
| 5 Tela e textos | `fix/tela-textos` | ae8c66a | B-01, A-21, N-01, B-09, B-02, B-03, B-12, B-04, B-06, B-07, B-08, B-11, B-13 | 6 achados, 6 corrigidos, + S7 da revisão | 932 / 111 |

Por desenho, sem mudança: A-12 (destinatário e Cco livres; sem vínculo usuário↔obra — a auditoria registra).
Migrações novas: 035 (reserva de envio) e 036 (índice da auditoria). Backups da produção antes de cada deploy em
`C:\DashboardLotufo\dados\dashboard-PRE-*.db` (ENVIO-UNICO, CONTEUDO-ENVIO, LOGIN-CONTAS, REGRAS-ENTRADA,
TELA-TEXTOS).

Pendências que ficaram (em `docs/backlog.md`): limite por origem no login e canal de tempo entre conta existente
e inexistente (V-13/V-04); upload do comprovante do protocolo pela tela; limite de 500 eventos na auditoria;
a pendência `irma_fora` segue aparecendo no detalhe de protocolo já enviado enquanto a irmã estiver com nota
emitida (só informativo).

Resultado: dos 34 achados confirmados na fase 3, 33 corrigidos e em produção e 1 mantido por desenho (A-12).
