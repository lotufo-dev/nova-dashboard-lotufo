# A ronda diária fica fora do produto e é temporária

Em 18/11/2026, dia do deploy do redesenho, a equipe ainda fazia boa parte do ciclo da medição por e-mail: pedia
espelho, recebia nota e protocolava sem passar pela dashboard. O levantamento do que tinha sido feito por fora
levou uma madrugada e ainda deixou documento sem ler. O dono concluiu que o hábito de usar a dashboard vai demorar
e que, até lá, ela não pode ficar dias atrás do que aconteceu.

Havia dois caminhos. Pôr a leitura de caixa de e-mail e de SharePoint dentro do produto reabriria o
`docs/adr/0003`, que tirou exatamente isso da primeira versão por gerar ruído. Decidimos pelo outro: a **ronda**,
uma rotina diária da sessão do agente, fora do produto, que lê as fontes do dono, compara com a dashboard e lança
o que tem documento que prova. O produto continua lendo só o que lhe foi entregue, o que ele mesmo enviou e o RM.

O roteiro é a skill `ronda` (`.claude/skills/ronda/SKILL.md`). As decisões do dono que ela segue:

- Roda em dia útil, às 11h30, numa máquina do escritório que fica ligada e alcança a produção sem VPN.
- Lê a caixa de e-mail do dono, o SharePoint e o RM. O que o conector não entrega (PDF só imagem, arquivo
  compactado, anexo grande) é baixado pelo navegador com a conta do dono logada.
- Lança só o que tem documento que prova. O que é conta do agente fica numa lista, com o motivo.
- Lança pela tela, com o PDF anexado e com um usuário próprio de perfil engenharia. O arquivo de correção fica para
  o que a tela não faz. Nunca aciona envio de e-mail.
- Espera um dia útil antes de lançar, para a pessoa ter a chance de lançar sozinha.
- Não altera o que uma pessoa lançou: a diferença vai para o relato.
- Confere os totais depois de gravar. Se não fecham ao centavo, para e relata.
- O relato vai só para o dono.
- Acaba depois de duas semanas seguidas sem nenhum ato feito por fora.

## Consequências

- **A dashboard fica, no máximo, um dia útil atrás** do que a equipe fez por e-mail, desde que o documento tenha
  chegado à caixa do dono.
- **O que o órgão responde só a quem enviou não é visto** (número de protocolo, aviso de pagamento). A ronda anota
  o que escapou; depois de duas semanas o dono decide, com essa medida, se pede acesso a outra caixa.
- **Há gravação diária na produção sem o dono olhando antes.** Quem a segura é a prova exigida por ato, a espera de
  um dia, a conferência ao centavo e o rito do `docs/runbook.md` para o que for por arquivo de correção ou cadastro
  (`docs/adr/0014`). Um documento lido errado entra na produção antes de o dono ver o relato.
- **A ronda pode atrasar o hábito que ela espera.** Com a dashboard em dia sem a equipe, some um motivo para usá-la.
  Por isso a ronda conta os atos feitos por fora, por pessoa e por dia, e essa contagem é o critério de fim. O que
  fazer com a contagem é do dono.
- **As três primeiras rodadas são à mão**, em sessão com o dono. A tarefa agendada só é montada depois.
- **Não é parte do produto**: não tem código em `backend/` nem em `frontend/`, não tem teste na CI e não entra no
  deploy. Se a ronda mostrar um ato que a tela não consegue registrar, isso vira linha no `docs/backlog.md`.
- O usuário próprio da ronda é conta de acesso: quem cria é o dono.
