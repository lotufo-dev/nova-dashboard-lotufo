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
  - "backend/app/respostas_orgao.py"
  - "frontend/src/ComporEmail.tsx"
  - "frontend/src/EnviarNota.tsx"
  - "frontend/src/LiberarEnvio.tsx"
  - "frontend/src/NotasAEnviar.tsx"
  - "frontend/src/FluxoOficio.tsx"
---

# Envio e leitura de e-mail

- **Quem envia.** O e-mail que é ato de uma pessoa (ao faturamento, ao órgão) sai da conta Microsoft de quem
  clicou, com a assinatura gravada dela. O e-mail automático (cobrança de certidões, cópia do dono, alerta de
  segurança) sai da conta configurada para ele. Conta de serviço não existe.
- **Envio único, registrado antes de sair.** A reserva atômica vem antes da chamada ao Graph. Reserva presa só
  sai por liberação com justificativa, auditada. Falha depois do envio diz que o e-mail saiu; falha no envio
  fica como "envio incerto" e não se repete sozinha. Reenviar exige intenção explícita.
- **A última versão enviada é a vigente**: destinatários, cópias, assunto e texto seguem o último envio
  registrado; o histórico fica.
- **O que vai ao órgão.** O corpo é montado pela lista real de anexos. Certidão vencida trava o pacote
  (`docs/adr/0002`). Link de arquivo grande só dos hosts de `DASH_SHAREPOINT_HOSTS`.
- **Leitura: só a conversa que o sistema enviou** (`docs/adr/0003`), com a conta de quem enviou e com essa
  pessoa logada. Uma consulta só lista mensagem, a da conversa gravada no envio; a caixa de entrada nunca é
  listada nem pesquisada. Grava remetente, data, assunto, trecho e nomes dos anexos; o corpo inteiro e os anexos
  ficam fora.
- **Dev.** Ligue o simulador (`DASH_GRAPH_SIMULADOR=dados/correio-simulado`). Com `DASH_DEV=1` e sem simulador,
  todo envio é recusado (`instalacao.exigir_envio`, issue #707): no envio feito por pessoa, antes da reserva; nos
  jobs de alerta de segurança e de cobrança de certidões, a marca própria do job é gravada, a recusa vem em
  `correio.enviar_e_registrar` antes de qualquer chamada ao Graph e a marca é solta: nada sai e nada fica preso.
  O e-mail real em dev só sai com `DASH_EMAIL_REAL_EM_DEV=1`, para o teste deliberado. Sem `DASH_DEV` (produção)
  a trava não existe.
- Toda mudança aqui sai com o teste de concorrência: dois POST simultâneos resultam em 1×200 e 1×409.
