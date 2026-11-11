---
paths:
  - "backend/app/correio.py"
  - "backend/app/api_correio.py"
  - "backend/app/graph.py"
  - "backend/app/envio_reserva.py"
  - "backend/app/api_envios.py"
  - "backend/app/notas_envio.py"
  - "backend/app/api_notas_envio.py"
  - "backend/app/protocolo.py"
  - "backend/app/oficios.py"
  - "backend/app/carta.py"
  - "backend/app/cobranca_certidoes.py"
  - "frontend/src/ComporEmail.tsx"
  - "frontend/src/EnviarNota.tsx"
  - "frontend/src/LiberarEnvio.tsx"
  - "frontend/src/NotasAEnviar.tsx"
  - "frontend/src/FluxoOficio.tsx"
---

# Envio de e-mail (faturamento, órgão, cobrança)

- O e-mail sai da conta Microsoft **de quem clicou** (Graph, login delegado), com a assinatura gravada da
  pessoa. Não existe conta de serviço; não propor.
- **Envio único e registrado**: reserva atômica antes de chamar o Graph (migração 035, `envio_reserva.py`).
  Reserva presa só sai por `POST /api/envios/liberar` (≥15 min, justificativa, auditado). Falha depois do
  `/send` vira "O e-mail SAIU" (`EnvioNaoRegistrado`); falha no `/send` vira "envio incerto" (`EnvioIncerto`)
  e o rascunho não é apagado. Reenviar espelho já enviado exige `reenviar: true`.
- Última versão enviada é a vigente: destinatários, cópias, assunto, texto e títulos seguem o último envio
  registrado; o histórico fica, o vigente é marcado.
- Conteúdo que vai ao órgão: o corpo é montado pela lista real de anexos; certidão vencida bloqueia; a menos de
  15 dias avisa; link de arquivo grande só de `lotufoengmt-my.sharepoint.com` / `lotufoengmt.sharepoint.com`.
- Cco é respeitado e chega ao e-mail. Envio registrado por fora (`.eml`) exige From com endereço, Date válida
  e To ou Subject.
- Cobrança de certidão por e-mail (issue #665): no máximo um e-mail por dia útil (segunda a sexta, fora feriado de
  `feriados.py`), na primeira rodada a partir das 08h de Cuiabá, só com a lista "Renovar agora"
  (`documentos.renovar_agora`: vencida, nunca anexada ou que vence até o próximo protocolo previsto), assunto
  "Certidões a renovar (N)"; lista vazia não gera e-mail. Destinatários e conta que envia vêm do cadastro
  (`cobranca_certidoes` do `geral.yaml`). O dia é reservado em `cobranca_certidoes_envios` antes de o e-mail sair
  (motivo `renovar AAAA-MM-DD`): reinício ou rodadas simultâneas não repetem; a reserva só é desfeita quando o
  e-mail com certeza não saiu (envio incerto fica sem repetir no dia). A tela Início continua lendo
  `cobranca_certidoes.listas` (vencidas e vencendo em 15 dias), que não decide mais o e-mail.
- **Leitura: só a conversa que o sistema enviou** (decisão de 10/11/2026, issue #644). A resposta do órgão à
  planilha/carta é lida pela conversa gravada no envio (`envios.conversa_id`), com a conta Microsoft de quem enviou
  e só com essa pessoa logada (a tela chama ao entrar e a cada 5 minutos; sem job, nada é lido para quem só
  consulta). A única consulta que lista mensagem é `correio.consulta_da_conversa`; nunca listar a caixa de entrada
  nem buscar por texto. Grava remetente, data, assunto, trecho (até 500 caracteres) e nomes dos anexos; corpo
  inteiro e anexo não se gravam. O simulador serve a leitura por `<pasta>/respostas/<conversa>/*.json`.
- Dev nunca manda e-mail de verdade: usar o simulador (`DASH_GRAPH_SIMULADOR=dados/correio-simulado`).
- Teste obrigatório para qualquer mudança aqui: dois POST simultâneos resultam em 1×200 e 1×409.
