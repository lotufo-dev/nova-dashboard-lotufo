# Pacote 1 — envio único e registrado (fase 4, 10/10/2026)

Branch `fix/envio-unico` (a partir de `master` 958627a). Sem merge, sem push, produção não tocada.
Corrige A-01, A-02 e A-03 de `06-verificacao-api.md` e o N-02 do consolidado (simulador).

## O que mudou, arquivo por arquivo

| Arquivo | O que mudou (em linguagem simples) |
|---|---|
| `backend/migrations/035_envio_reserva.sql` | Duas colunas novas em protocolos, espelhos e pleitos: quando e por quem o envio foi "reservado". |
| `backend/app/envio_reserva.py` (novo) | Antes de mandar o e-mail, o sistema "pega a vez" daquele documento numa operação que só uma pessoa consegue fazer por vez. Quem chega depois recebe 409: "Este envio está em andamento ou foi interrompido (iniciado às HH:MM por <nome>). Confira a caixa de Enviados do Outlook: se o e-mail NÃO saiu, libere o envio e repita." A reserva **não expira** (revisão abaixo): só sai por `liberar_manual`, com justificativa de ao menos 10 caracteres e linha `envio.liberar` na auditoria. |
| `backend/app/protocolo.py`, `espelhos.py`, `pleitos.py` | O `enviar` de cada um: valida como antes → reserva → manda o e-mail → marca "enviado" e libera a reserva no mesmo gravar. Se der erro ANTES de o e-mail sair, libera a reserva e mostra o erro de sempre. Se o e-mail saiu e a marcação final pegou o banco travado, responde a verdade (ver abaixo) e a reserva fica, segurando a repetição até alguém liberar. No protocolo (que pode mandar vários num e-mail só), ou reserva todos, ou nenhum. |
| `backend/app/correio.py` | (1) Depois que o e-mail sai, gravar o registro tenta até 3 vezes (1 s entre elas) se o banco estiver travado; se ainda falhar, avisa "e-mail enviado e não registrado" (`EnvioNaoRegistrado`) em vez de "tente novamente". (2) `depois_do_envio`: o mesmo aviso para a marcação feita depois do e-mail nos três módulos. (3) Simulador (só dev/teste) grava cada envio num arquivo de nome único (data-hora com microssegundos + 4 letras aleatórias). |
| `backend/app/db.py` | A regra "isto é banco travado?" mudou de lugar (veio de `main.py`), porque agora o correio também usa. |
| `backend/app/main.py` | Resposta nova para "o e-mail saiu e o registro falhou": erro 500 com "O e-mail SAIU, mas o registro no sistema falhou. NÃO envie de novo: confira a caixa de Enviados do Outlook e avise o administrador. Assunto: …". O "Banco de dados ocupado — tente novamente" continua para os outros casos. |
| `backend/app/api_protocolos.py`, `api_notas_envio.py`, `api_espelhos.py`, `api_pleitos.py` | "Envio em andamento" responde 409 (conflito) com a mensagem, e não 422. |
| `backend/app/api_envios.py` (novo) + registro em `main.py` | `POST /api/envios/liberar` `{tabela, id, justificativa}`: libera a reserva presa (perfil com `editar_cadastros`; diretoria recebe 403; erro de regra → 422). |
| `frontend/src/LiberarEnvio.tsx` (novo) | Quando o erro é o 409 "Este envio está em andamento…", aparece logo abaixo da mensagem o campo "Por que liberar (confira antes a caixa de Enviados)" e o botão "Liberar envio". Deu certo: o erro some e aparece "Envio liberado; pode repetir." |
| `frontend/src/EnviarNota.tsx`, `Espelho.tsx`, `FluxoOficio.tsx` | Usam o `LiberarEnvio` no lugar onde já mostravam o erro de envio; o resto do layout não mudou. A mensagem do servidor (409 e 500) já aparecia antes: `api.ts` entrega o `detail` para qualquer código de erro. |
| Testes existentes (`test_correio.py`, `test_api_correio.py`, `test_espelhos.py`, `test_notas_envio.py`) | Liam o arquivo `1.json` do simulador; passam a ler o primeiro arquivo da pasta (o nome mudou). |

## Testes novos

- `tests/test_envio_reserva.py` (unidade): reserva exclusiva e liberação; reserva de 1 hora atrás continua dando `EnvioEmAndamento` (sem tomada automática); `liberar_manual` exige justificativa, só age com reserva, zera as colunas e audita `envio.liberar`; `envio_id` sem envio não quebra; envio concluído entre a leitura e a reserva não se repete; tabela fora da lista é recusada; registro com banco travado tenta de novo; registro que nunca grava levanta `EnvioNaoRegistrado` (e o e-mail saiu de fato); simulador não sobrescreve envios simultâneos.
- `tests/test_api_protocolos.py`: corrida determinística (segundo envio de dentro do primeiro, por outra conexão); 3 threads com `Barrier` e correio falso de 0,3 s → um 200 e dois 409; falha antes do e-mail destrava e a segunda tentativa vai; registro que falha depois do e-mail → 500 "O e-mail SAIU" e o POST seguinte → 409; marcação final travada → 500 "O e-mail SAIU"; `/api/notas/envio/{pid}/enviar` com envio em andamento → 409; reserva presa só sai pela rota de liberação (diretoria 403, engenharia 200, justificativa curta 422, tabela fora da lista 422) e depois o envio vai.
- `frontend/src/LiberarEnvio.test.tsx` (vitest): só o 409 de envio reservado oferece a liberação; liberar manda `{tabela, id, justificativa}` e mostra "Envio liberado; pode repetir.".
- `tests/test_api_espelhos.py`: corrida determinística; 3 threads → um 200 e dois 409 (e reenviar depois, de propósito, continua valendo); falha antes do e-mail destrava; marcação final travada → 500 e depois 409.
- `tests/test_api_pleitos.py`: corrida determinística; marcação final travada → 500 e depois 409.

### ANTES (código de `master`, commit 3145791 só com os testes)

```
test_envio_reserva.py   7 failed
  ImportError: cannot import name 'envio_reserva' from 'app'            (x4)
  AttributeError: module 'app.correio' has no attribute 'time'          (x2)
  AssertionError: assert '<simulado-1@dashboard>' != '<simulado-1@dashboard>'

test_api_protocolos.py  6 failed, 3 passed
  test_segundo_envio_durante_o_primeiro_e_recusado      AssertionError: assert [] == ['EnvioEmAndamento']
  test_tres_envios_simultaneos_saem_uma_vez             AssertionError: ['{"envio_id":1}', '{"envio_id":2}', '{"envio_id":3}']
  test_falha_antes_do_email_destrava_...                sqlite3.OperationalError: no such column: envio_reservado_em
  test_registro_que_falha_depois_do_email_...           AssertionError: {"detail":"Banco de dados ocupado — tente novamente em instantes."}
  test_marcacao_final_travada_tambem_diz_que_saiu       assert (503 == 500)
  test_envio_de_nota_em_andamento_responde_409          sqlite3.OperationalError: no such column: envio_reservado_em

test_api_espelhos.py    4 failed, 6 passed
  test_segundo_envio_do_espelho_durante_o_primeiro_...  AssertionError: assert [] == ['EnvioEmAndamento']
  test_tres_envios_simultaneos_do_espelho_saem_uma_vez  AssertionError: ['{"envio_id":1}', '{"envio_id":2}', '{"envio_id":3}']
  test_falha_antes_do_email_destrava_o_espelho          sqlite3.OperationalError: no such column: envio_reservado_em
  test_espelho_registrado_pela_metade_...               AssertionError: {"detail":"Banco de dados ocupado — tente novamente em instantes."}

test_api_pleitos.py     2 failed, 2 passed
  test_segundo_envio_do_pleito_durante_o_primeiro_...   AssertionError: assert [] == ['EnvioEmAndamento']
  test_pleito_registrado_pela_metade_...                AssertionError: {"detail":"Banco de dados ocupado — tente novamente em instantes."}
```

As falhas reproduzem os defeitos: três envios simultâneos → três `200` com `envio_id` 1, 2, 3 (A-01/A-02);
e-mail que saiu e não foi registrado → 503 "tente novamente" (A-03); simulador com o mesmo nome (N-02).

### DEPOIS (`fix/envio-unico`)

```
PASSED tests/test_envio_reserva.py::test_reserva_e_exclusiva_e_liberar_destrava
PASSED tests/test_envio_reserva.py::test_reserva_velha_pode_ser_tomada
PASSED tests/test_envio_reserva.py::test_envio_concluido_entre_a_leitura_e_a_reserva_nao_se_repete
PASSED tests/test_envio_reserva.py::test_tabela_fora_da_lista_recusa
PASSED tests/test_envio_reserva.py::test_registro_com_banco_travado_tenta_de_novo
PASSED tests/test_envio_reserva.py::test_registro_que_nunca_grava_diz_que_o_email_saiu
PASSED tests/test_envio_reserva.py::test_simulador_nao_sobrescreve_envios_simultaneos
PASSED tests/test_api_protocolos.py::test_fluxo_completo_pela_api
PASSED tests/test_api_protocolos.py::test_erros_de_entrada
PASSED tests/test_api_protocolos.py::test_diretoria_nao_cria_protocolo
PASSED tests/test_api_protocolos.py::test_segundo_envio_durante_o_primeiro_e_recusado
PASSED tests/test_api_protocolos.py::test_tres_envios_simultaneos_saem_uma_vez
PASSED tests/test_api_protocolos.py::test_falha_antes_do_email_destrava_e_a_segunda_tentativa_vai
PASSED tests/test_api_protocolos.py::test_registro_que_falha_depois_do_email_diz_que_saiu_e_trava_a_repeticao
PASSED tests/test_api_protocolos.py::test_marcacao_final_travada_tambem_diz_que_saiu
PASSED tests/test_api_protocolos.py::test_envio_de_nota_em_andamento_responde_409
PASSED tests/test_api_espelhos.py::test_fluxo_previa_gerar_baixar_enviar
PASSED tests/test_api_espelhos.py::test_valor_invalido_e_obra_inexistente
PASSED tests/test_api_espelhos.py::test_arquivo_de_outro_espelho_da_404
PASSED tests/test_api_espelhos.py::test_diretoria_le_mas_nao_gera
PASSED tests/test_api_espelhos.py::test_evidencia_do_orgao_anexada_e_baixada
PASSED tests/test_api_espelhos.py::test_evidencia_que_nao_e_pdf_da_415
PASSED tests/test_api_espelhos.py::test_segundo_envio_do_espelho_durante_o_primeiro_e_recusado
PASSED tests/test_api_espelhos.py::test_tres_envios_simultaneos_do_espelho_saem_uma_vez
PASSED tests/test_api_espelhos.py::test_falha_antes_do_email_destrava_o_espelho
PASSED tests/test_api_espelhos.py::test_espelho_registrado_pela_metade_diz_que_saiu_e_trava_a_repeticao
PASSED tests/test_api_pleitos.py::test_pleito_de_reajuste_pela_api
PASSED tests/test_api_pleitos.py::test_medicao_final_pela_api_poe_o_contrato_em_encerramento
PASSED tests/test_api_pleitos.py::test_segundo_envio_do_pleito_durante_o_primeiro_e_recusado
PASSED tests/test_api_pleitos.py::test_pleito_registrado_pela_metade_diz_que_saiu_e_trava_a_repeticao
30 passed in 36.17s
```

Os dois testes com threads rodaram 5 vezes seguidas sem oscilar (2 passed em todas, ~4 s).

### Suíte inteira

```
1ª rodada (sem a revisão): backend 835 passed, 1 skipped in 420.50s
Depois da revisão (73f0e79):
  backend : 838 passed, 1 skipped in 467.94s (0:07:47)
  frontend: Test Files 26 passed (26) · Tests 82 passed (82)   (o rastro "dado inesperado" na saída é o erro
            proposital do ErrorBoundary.test.tsx, já existente)
  npm run typecheck: sem erro
Depois do gate Sol (516d205):
  backend : 849 passed, 1 skipped in 652.50s (0:10:52)
  frontend: Test Files 27 passed (27) · Tests 84 passed (84)
  npm run typecheck: sem erro
Depois do S8 (7adfcc1):
  backend : 851 passed, 1 skipped in 416.67s (0:06:56)
  frontend: Test Files 27 passed (27) · Tests 85 passed (85)
  npm run typecheck: sem erro
```

## Revisão do coordenador (10/10/2026) — reserva sem expiração

A tomada automática depois de 10 minutos reabria o A-03: no caso "o e-mail SAIU e o registro falhou" a linha
fica com `envio_id` NULL e reserva presa; passados 10 minutos, um novo POST reservava de novo e mandava o
SEGUNDO e-mail ao órgão. O banco não distingue isso de "o processo morreu antes do e-mail", então a decisão é
humana: a pessoa confere a caixa de Enviados e libera com justificativa (auditada). Também: no ramo "acabou de
ser feito", `envio_id` sem envio correspondente agora recusa com mensagem em vez de quebrar com `TypeError`.

Commits da revisão: b1da42f (testes, vermelhos), 1189295 (backend), 73f0e79 (frontend).

ANTES (b1da42f, código da rodada anterior):

```
E   AssertionError: Regex pattern did not match.
E   Failed: DID NOT RAISE EnvioEmAndamento
E   AttributeError: module 'app.envio_reserva' has no attribute 'liberar_manual'
E   TypeError: 'NoneType' object is not subscriptable
FAILED tests/test_envio_reserva.py::test_reserva_e_exclusiva_e_liberar_destrava
FAILED tests/test_envio_reserva.py::test_reserva_antiga_continua_travada - Fa...
FAILED tests/test_envio_reserva.py::test_liberar_manual_exige_justificativa_e_audita
FAILED tests/test_envio_reserva.py::test_envio_inconsistente_nao_quebra - Typ...
4 failed, 5 passed in 10.59s
E   assert (200 == 409)
FAILED tests/test_api_protocolos.py::test_reserva_presa_so_sai_pela_liberacao_manual
1 failed, 9 passed in 18.40s
LiberarEnvio.test.tsx: Test Files 1 failed (o componente ainda não existia)
```

O `assert (200 == 409)` é o defeito apontado: a reserva de 1 hora atrás foi tomada e o e-mail saiu de novo.

DEPOIS: `test_envio_reserva.py` 9 passed; `test_api_protocolos.py` 10 passed; `test_api_espelhos.py` 10 passed;
`test_api_pleitos.py` 4 passed; `LiberarEnvio.test.tsx` 2 passed; `npm run typecheck` sem erro.

## Gate Sol: 7 achados, 7 corrigidos (+ S8 da reverificação)

Commits: b802fc6 (testes, vermelhos) · 2c279ec (S2) · 4dda8e6 (S3) · f6b9e5b (S1, S4, S5, S6 no backend) ·
516d205 (S5, S6, S7 no frontend).

| Item | Problema | Conserto | Teste |
|---|---|---|---|
| S1 (alta) | `liberar_manual` soltava a reserva de um envio ainda no Graph: B recebe 409, confere os Enviados cedo demais, libera e repete. | `liberar_manual` recusa reserva com menos de 15 min (`IDADE_MINIMA_LIBERACAO`): "Envio iniciado há N min por <nome>: aguarde até HH:MM antes de liberar (pode ainda estar saindo)". | reserva de 1 min → ValueError / 422 pela rota; de 16 min → libera. |
| S2 (alta) | Timeout ou 5xx no próprio `/send` apagava o rascunho e soltava a reserva, mas o e-mail podia ter saído. | `ErroGraph.status` (None sem resposta). Só o `POST /me/messages/{mid}/send` é ponto sem volta: 4xx nele apaga o rascunho e sobe `ErroGraph` (reserva solta); sem resposta, 5xx ou resposta ilegível → `EnvioIncerto` (subclasse de `EnvioNaoRegistrado`), não apaga nada, reserva fica, 500 "Não deu para confirmar se o e-mail saiu…". O token é renovado antes do `/send`. | `/send` 413 → ErroGraph e DELETE; sem resposta / 503 / ilegível → EnvioIncerto e sem DELETE; falha no anexo → ErroGraph e DELETE; `_http` carrega o status; pela API: 500, reserva fica, 2º POST 409. |
| S3 (alta) | Só lock na marcação final virava "O e-mail SAIU"; outro erro saía como 500 genérico. | `depois_do_envio` captura `Exception`, com `log.critical` e causa encadeada. | `auditoria.registrar` quebrando no `protocolo.enviar` → 500 "O e-mail SAIU", reserva fica, 1 linha em `envios`. |
| S4 (média) | `liberar` falhando no caminho "nada saiu" mascarava o erro e prendia a reserva. | `liberar_com_retentativa` (3 tentativas no lock); se não der, ValueError "O envio NÃO foi feito, mas a trava não pôde ser removida (banco ocupado). Aguarde 15 minutos e libere o envio." encadeado ao erro original, que vai ao log. | unidade: 2 locks e depois libera; lock sempre → ValueError com `__cause__` = erro original. |
| S5 (média) | Liberação sem declaração explícita. | `conferi_enviados: bool` obrigatório na rota; `liberar_manual` recusa se não for true; auditoria grava `conferi_enviados: true`; no componente, caixa "Conferi a caixa de Enviados do Outlook e este e-mail NÃO consta" habilita o botão e o bloco mostra quem iniciou e quando. | unidade e rota (sem o campo → 422; false → 422); vitest: botão desabilitado até marcar. |
| S6 (baixa) | A tela decidia pelo prefixo do texto. | `EnvioEmAndamento` com `codigo` (`ENVIO_RESERVADO` / `ENVIO_CONCLUIDO_NO_MEIO`), `reservado_em`, `reservado_por_nome`, `liberavel_a_partir_de` (hora local, ISO); as 4 rotas de envio respondem 409 com esse `detail`; `api.ts` aceita `detail.mensagem` e guarda o detail cru em `ApiErro.corpo`; `envioReservado` decide por `corpo.codigo`. Único outro leitor de `detail` no front é o próprio `api.ts`. | unidade (atributos e `detalhe()`), rota (`codigo`, nome), vitest (`api.test.ts` e `envioReservado`). |
| S8 (reverificação do A-01) | Com o envio instantâneo, três POST simultâneos no espelho deram DOIS 200: o segundo leu o espelho depois de o primeiro concluir, viu o `envio_id` novo e reservou — reenvio da versão vigente sem ninguém confirmar. | `EnvioIn.reenviar` (padrão false). Versão com `envio_id` e sem `reenviar` → 409 `ESPELHO_JA_ENVIADO` ("Esta versão do espelho já foi enviada ao faturamento (às HH:MM por <nome>). Para mandar de novo, confirme o reenvio."), checagem só de leitura antes da reserva; `envio_id_visto` mantido. Tela: caixa "Confirmo o reenvio desta versão (substitui o envio anterior)" quando o espelho já tem envio ou chega esse 409; `reenviar: true` só marcada; sem o bloco "Liberar envio" (não há reserva). | corrida com 3 threads em duas rodadas (Graph lento e instantâneo) → exatamente um 200; 2º POST sem `reenviar` → 409 e nenhum e-mail, com `reenviar` → 200 e +1; vitest da caixa. Commits dfa999b (testes), 9c46c65 (backend), 7adfcc1 (frontend). |
| S7 (baixa) | "Pode repetir" sem recarregar a tela. | Depois de liberar: EnviarNota `carregar()`, Espelho `carregar()`, FluxoOficio `aoMudar()`; texto "Trava removida. Confira os dados e envie de novo." | vitest. |

ANTES (b802fc6):

```
E   TypeError: ErroGraph() takes no keyword arguments
E   AttributeError: module 'app.correio' has no attribute 'EnvioIncerto'
E   AttributeError: module 'app.correio' has no attribute 'EnvioIncerto'
E   AttributeError: module 'app.correio' has no attribute 'EnvioIncerto'
E   TypeError: ErroGraph() takes no keyword arguments
E   AttributeError: 'ErroGraph' object has no attribute 'status'
FAILED tests/test_correio.py::test_send_recusado_com_4xx_apaga_o_rascunho_e_nao_registra
FAILED tests/test_correio.py::test_send_sem_resposta_clara_e_envio_incerto_e_nao_apaga_nada[sem-resposta]
FAILED tests/test_correio.py::test_send_sem_resposta_clara_e_envio_incerto_e_nao_apaga_nada[5xx]
FAILED tests/test_correio.py::test_send_sem_resposta_clara_e_envio_incerto_e_nao_apaga_nada[resposta-ilegivel]
FAILED tests/test_correio.py::test_falha_antes_do_send_continua_erro_do_graph_e_apaga_o_rascunho
FAILED tests/test_correio.py::test_erro_do_graph_carrega_o_status_http - Attr...
6 failed, 10 passed in 8.31s
E   TypeError: liberar_manual() got an unexpected keyword argument 'conferi_enviados'
E   TypeError: liberar_manual() takes 5 positional arguments but 6 were given
E   AttributeError: 'EnvioEmAndamento' object has no attribute 'codigo'
E   RuntimeError: Graph fora do ar
E   AttributeError: module 'app.envio_reserva' has no attribute 'liberar_com_retentativa'
FAILED tests/test_envio_reserva.py::test_liberar_manual_exige_justificativa_declaracao_e_audita
FAILED tests/test_envio_reserva.py::test_liberar_manual_recusa_envio_que_pode_estar_saindo
FAILED tests/test_envio_reserva.py::test_erro_de_reserva_vem_estruturado - At...
FAILED tests/test_envio_reserva.py::test_liberar_depois_de_falha_insiste_e_nao_esconde_o_erro
4 failed, 8 passed in 34.66s
E   TypeError: string indices must be integers, not 'str'
E   TypeError: string indices must be integers, not 'str'
E   TypeError: string indices must be integers, not 'str'
E   TypeError: string indices must be integers, not 'str'
E   assert (200 == 422)
E   AttributeError: module 'app.correio' has no attribute 'EnvioIncerto'
E   RuntimeError: cadeia de auditoria quebrada
FAILED tests/test_api_protocolos.py::test_tres_envios_simultaneos_saem_uma_vez
FAILED tests/test_api_protocolos.py::test_registro_que_falha_depois_do_email_diz_que_saiu_e_trava_a_repeticao
FAILED tests/test_api_protocolos.py::test_envio_de_nota_em_andamento_responde_409
FAILED tests/test_api_protocolos.py::test_reserva_presa_so_sai_pela_liberacao_manual
FAILED tests/test_api_protocolos.py::test_liberar_envio_recente_pela_rota_e_recusado
FAILED tests/test_api_protocolos.py::test_envio_incerto_no_graph_segura_a_reserva
FAILED tests/test_api_protocolos.py::test_qualquer_falha_na_marcacao_final_diz_que_o_email_saiu
7 failed, 6 passed in 63.45s (0:01:03)
     × detail estruturado (409 de envio reservado): mensagem na tela e corpo cru para a decisao 37ms
     × decide pelo codigo do erro, nao pelo texto 23ms
     × mostra quem iniciou, exige a declaracao e libera 95ms
⎯⎯⎯⎯⎯⎯⎯ Failed Tests 3 ⎯⎯⎯⎯⎯⎯⎯
 FAIL  src/api.test.ts > api: detail do servidor > detail estruturado (409 de envio reservado): mensagem na tela e corpo cru para a decisao
 FAIL  src/LiberarEnvio.test.tsx > LiberarEnvio > decide pelo codigo do erro, nao pelo texto
 FAIL  src/LiberarEnvio.test.tsx > LiberarEnvio > mostra quem iniciou, exige a declaracao e libera
 Test Files  2 failed (2)
      Tests  3 failed | 1 passed (4)
```

ANTES do S8 (dfa999b):

```
× versão já enviada: reenvio só com a confirmação marcada (S8) 1026ms
⎯⎯⎯⎯⎯⎯⎯ Failed Tests 1 ⎯⎯⎯⎯⎯⎯⎯
TestingLibraryElementError: Unable to find a label with the text of: Confirmo o reenvio desta versão (substitui o envio anterior)
 Test Files  1 failed (1)
      Tests  1 failed | 5 passed (6)
E   AssertionError: ['{"envio_id":1}', '{"envio_id":2}', '{"detail":{"mensagem":"Este envio acabou de ser feito (�s 18:16 por Admin). Conf...tir.","codigo":"ENVIO_CONCLUIDO_NO_MEIO","reservado_em":nul
E   AssertionError: {"envio_id":2}
FAILED tests/test_api_espelhos.py::test_tres_envios_simultaneos_do_espelho_saem_uma_vez[instantaneo]
FAILED tests/test_api_espelhos.py::test_reenvio_da_mesma_versao_exige_confirmacao
2 failed, 10 passed in 10.14s
```

DEPOIS: ver "Suíte inteira".

## Decisões tomadas

1. **A reserva também confere o `envio_id` lido na validação** (afastamento do desenho, ver "dúvidas"). O
   `reservar` recebe `envio_id_visto`; se o `envio_id` da linha mudou entre a validação e a reserva, recusa com
   "Este envio acabou de ser feito (às HH:MM por <nome>). Confira a caixa de Enviados antes de repetir." (também
   409, mesma classe `EnvioEmAndamento`).
2. **Qualquer falha ao registrar depois do e-mail vira `EnvioNaoRegistrado`**, não só lock: o e-mail saiu de
   qualquer jeito. Só o lock ganha as duas tentativas extras; erro de outro tipo (bug) vai direto para o aviso.
3. **`correio.depois_do_envio`** (gerenciador de contexto) concentra a conversão "lock na marcação final →
   `EnvioNaoRegistrado`" para não repetir o mesmo `try/except` em três módulos.
4. **Hora na mensagem em horário de Cuiabá** (`tempo.para_local`); o banco grava UTC.
5. `envio_reservado_por` com `REFERENCES usuarios(id)`, como `aditivos.assinado_por` já faz.
6. Commits separados: testes (vermelhos) → registro honesto (A-03) → simulador (N-02) → reserva (A-01/A-02).

## Dúvidas, riscos e afastamentos do desenho

- **Afastamento (decisão 1) — buraco no desenho original.** Com a reserva checando só "está reservado?", sobrava
  uma janela: o pedido B lê o documento (ainda "não enviado"), o pedido A termina o envio e LIBERA a reserva, e só
  então B reserva — e consegue, mandando o segundo e-mail. A janela é o tempo da validação de B (lê PDFs; na
  `<servidor>` com a CPU freada pode passar de 0,3 s). Conferir o `envio_id` visto fecha a janela sem mudar mais
  nada (é a mesma checagem otimista para os três). Sem isso o teste com threads também ficaria instável.
- **Falha dupla rara** (Graph falha antes do e-mail e o banco fica travado): corrigido no gate Sol S4 — três
  tentativas e, se não der, a mensagem diz que nada saiu e que a trava ficou.
- **`liberar_com_retentativa` pega o erro original por `sys.exception()`** (Python 3.11+), para manter a assinatura
  `(conn, tabela, id_)` pedida; só funciona chamada de dentro do `except`, que é o único uso (está no docstring).
- **Reserva presa depois de uma queda do servidor** (processo morto antes do e-mail) agora exige alguém liberar à
  mão. É o preço de nunca mandar o segundo e-mail sozinho; a mensagem do 409 diz o que fazer.
- **O `LiberarEnvio` não foi conferido no navegador** (precisaria forçar uma reserva presa no banco de dev); está
  coberto pelo teste vitest e pelo typecheck.
- **Cobrança de certidões** (`cobranca_certidoes._enviar`) captura `RuntimeError`, então também captura
  `EnvioNaoRegistrado` e escreve "não enviada" no log (inexato; o `log.critical` do correio diz a verdade). O efeito
  é o mesmo de antes (sem registro, pode repetir na próxima rodada, só para o e-mail do dono). Não mexi.
- **Roteiro de verificação da fase 3:** a ordenação de `verificacao/api/lib.py` (que quebrava com o nome novo do
  simulador) já foi ajustada pelo coordenador.
- A migração 035 entra no próximo deploy (só `ADD COLUMN`; o migrador já pula coluna existente).
