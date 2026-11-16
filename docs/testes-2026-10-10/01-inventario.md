# Inventário do alvo — oráculo dos testes de quebra (10/10/2026)

Levantado só por leitura de código e docs (master `958627a`). Nada foi executado. Caminhos relativos à raiz do repositório.
Convenções: **SEM** = sem validação no servidor; "ver_paineis" etc. = `exigir("...")` de `backend/app/permissoes.py`;
"+CSRF" = exige o cabeçalho `X-CSRF-Token` (padrão de `exigir()` em POST/PUT/DELETE).

## 0. Perfis e permissões (base de tudo)

| Perfil | Permissões (`permissoes.py:8-12`) | Menu (trilho, `navegacao.ts:493-497`) |
|---|---|---|
| diretoria | `ver_paineis` | Início, Carteira, Avisos, Documentos, Obras, A receber |
| engenharia | `ver_paineis`, `editar_cadastros` | Início, Medições, Avisos, Documentos, Obras, A receber |
| admin | as anteriores + `editar_config_fiscal`, `administrar` | todos, mais Administração |

- Sessão: cookie `sessao` (httponly, `samesite=strict`, `secure` desligado com `DASH_SEM_TLS=1`, 12 h) — `api_auth.py:69-71`, `auth.py:13`.
- CSRF: token por sessão, devolvido no login e em `/api/auth/eu`; vive só na memória do front (`api.ts:1`, `App.tsx:32-38`).
- `editar_config_fiscal` não é exigida por nenhuma rota (nenhum `exigir("editar_config_fiscal")` no backend).
- Não existe vínculo usuário↔obra: qualquer engenharia age sobre qualquer obra/medição. Toda checagem de "pertence" é entre objetos (medição↔contrato, documento↔medição), nunca entre usuário e objeto.
- Lado cliente: só `/admin` é barrado para quem não é admin (`App.tsx:47`). Toda outra rota abre para qualquer perfil logado; o que muda é o menu e alguns botões (`podeEditar` = engenharia|admin).

---

## 1. Telas

14 telas (13 rotas + Login), com 18 abas. Roteador próprio em `frontend/src/rota.tsx` (`parseRota`); caminho desconhecido ou id inválido (`/obras/abc`, `/obras/0`, id com mais de 15 dígitos) vira `raiz` → Início (`rota.tsx:237-275`). Caminhos antigos redirecionam: `/certidoes`→`/documentos`, `/painel` e `/diretoria`→`/carteira`, `/contratos[/id]`→`/obras[/id]`, `/obras/{id}/protocolo|notas`→aba medicoes, `/obras/{id}/cronograma|aditivos`→aba contrato, `/notas`→`/medicoes/enviar-nota`, `/notas/aguardando`→`/medicoes/aguardando-pagamento`.

| URL | Componente | O que mostra | Endpoints chamados | Perfis |
|---|---|---|---|---|
| (sem sessão) | `Login.tsx` | e-mail e senha, fundo 3D | POST `/api/auth/login`, GET `/api/auth/eu` | todos |
| `/inicio` | `Inicio.tsx` | cartões, números do mês, medido por contratante, prazos | GET `/api/inicio/painel` | todos (entrada de todos) |
| `/medicoes` (aba resumo) | `MedicoesPagina.tsx` | contagem por situação, quadro por contratante, botão "Iniciar medição" (modal `IniciarMedicao.tsx`, só navega) | GET `/api/medicoes/resumo` | menu: engenharia, admin; diretoria abre pela URL (botão Iniciar escondido, `MedicoesPagina.tsx:188`) |
| `/medicoes/sem-medicao`, `/faturamento`, `/aguardando-nota` | `MedicoesPagina.tsx` (Quadro) | linhas da situação | GET `/api/medicoes/resumo` | idem |
| `/medicoes/enviar-nota` | `NotasAEnviar.tsx` | envios pendentes por órgão, itens (nota, FRC, certidões, regularidade) com estado ok/aviso/falta/vencida; "Começar o envio" (pede o nº do ofício por `window.prompt`); "Registrar envio feito por fora" (modal) | GET `/api/notas/a-enviar`; POST `/api/notas/envio/iniciar`; multipart POST `/api/documentos/regularidades`, `/api/medicoes/{id}/notas` (FRC, `tipo_doc=fatura`), `/api/notas/envio-externo` | idem; **sem gate de perfil no cliente** (diretoria vê os botões e leva 403) |
| `/medicoes/aguardando-pagamento` | `AguardandoPagamento.tsx` | notas enviadas, campo "Nº do protocolo" (SIGA/MTPAR) | GET `/api/notas/aguardando-pagamento`; POST `/api/notas/{medicao_id}/numero-orgao` | idem, sem gate no cliente |
| `/notas/envio/{pid}` | `EnviarNota.tsx` | envio de UM protocolo de nota: checklist de itens, ofício (montar → assinar → enviar), documentos complementares (PDF/ZIP e links do OneDrive), janela de e-mail (`ComporEmail.tsx`), justificativa | GET `/api/notas/envio/{pid}`; POST `/api/notas/envio/{pid}/enviar`; POST `/api/protocolos/{pid}/links`, `/links/{id}/remover`, `/pecas` (tipo=anexo), `/pecas/{id}/remover`, `/montar`, `/assinado`; GET `/api/protocolos/{pid}/pacote`; GET `/api/notas/a-enviar` (juntar/separar); ComporEmail: GET `/api/correio/remetente`, `/api/correio/contatos`, `/api/correio/assinatura` | sem gate no cliente |
| `/avisos` | `AvisosPagina.tsx` | fila de avisos filtrável (família, obra) | GET `/api/inicio` (servidor recorta: diretoria × operação) | todos |
| `/documentos` | `Documentos.tsx` | matriz de certidões por empresa, regularidade mensal, upload/leitura de certidão, ZIP das vigentes numa data | GET `/api/documentos`; POST `/api/documentos/certidoes/ler`, `/api/documentos/certidoes`, `/api/documentos/regularidades`; GET `/api/certidoes/{id}/arquivo`, `/api/documentos/regularidades/{rid}/arquivo`, `/api/documentos/zip?entidade_id&data` | todos; upload escondido para diretoria (`Documentos.tsx:122`) |
| `/obras` | `Contratos.tsx` | lista de obras com situação, término, filtros | GET `/api/contratos`, `/api/entidades`, `/api/inicio` | todos |
| `/a-receber` | `AReceberPagina.tsx` | quanto os órgãos devem e há quanto tempo (cota Lotufo) | GET `/api/diretoria` | todos |
| `/obras/{id}` (aba medicoes) | `ContratoPagina.tsx` + `Espelho.tsx`, `Medicoes.tsx`, `NovaMedicaoManual`, `Protocolo.tsx` (`NovoProtocolo`) | cabeçalho (valor, faturado, a receber, saldo), avisos da obra, cartão do espelho, tabela de medições, CSV, novo protocolo | GET `/api/contratos/{id}/cabecalho`, `/curva`, `/api/inicio`, `/api/contratos/{id}/espelho`, `/medicoes`, `/api/medicoes/andamento?contrato_id`, `/api/rm/status`, `/api/contratos/{id}/medicoes.csv`, `/api/contratos/{id}/protocolos`; POST espelho (prévia/gerar/enviar/evidência), POST `/api/contratos/{id}/medicoes` (só obra sem regra ativa), POST protocolos | todos; edição para engenharia/admin |
| `/obras/{id}/prazos` | `Prazos.tsx` + `FluxoOficio.tsx` | situação de execução/vigência, histórico, pleitos de prazo/conclusão | GET `/api/contratos/{id}/prazos`, `/cadastro`, `/api/contratos`; pleitos (ver §3) | todos; edição engenharia/admin |
| `/obras/{id}/reajuste` | `Reajuste.tsx` + `FluxoOficio.tsx` | ciclos de reajuste por data-base, pleitos de reajuste | GET `/api/contratos/{id}/reajuste`, `/cadastro`; pleitos | idem |
| `/obras/{id}/documentos` | `ObraAbas.tsx` (`DocumentosObra`) | checklist "pronto para protocolar" por natureza | GET `/api/contratos/{id}/checklist-protocolo[?natureza=reajuste]` | todos |
| `/obras/{id}/contrato` | `ObraAbas.tsx` (`ContratoObra`), `Instrumentos.tsx`, `Cronograma.tsx` | cadastro, aditivos/instrumentos, cronograma (só leitura: `podeEditar={false}`, `ObraAbas.tsx:291`) | GET `/api/contratos/{id}`, `/cadastro`, `/aditivos`, `/prazos`, `/cronograma`, `/curva` | todos |
| `/obras/{o}/medicoes/{m}` | `MedicaoPagina.tsx` | 5 etapas (Espelho, Faturamento, Nota, Envio, Pagamento), resumo (competência, estado, próximo passo, valor/atestado), linha do tempo, irmãs da competência; mostra "Esta medição não é desta obra" se m ∉ o | GET `/api/contratos/{o}/medicoes`, `/api/medicoes/andamento?contrato_id`, `/api/contratos/{o}/espelho`, `/cabecalho`, `/protocolos`; formulários de `MedicaoAtos.tsx`; `Notas.tsx`, `Frc.tsx`, `Etapas.tsx` (`EnvioDaMedicao` → `EnviarNota` embutido), `Protocolo.tsx` (`ProtocolosDaMedicao`) | todos; edição engenharia/admin |
| `/obras/{o}/medicoes/nova` | `NovaMedicao.tsx` + `Espelho.tsx` | etapa 1: gerar espelho (cria a medição) | GET `/api/contratos/{o}/cabecalho`, `/espelho`; POST `/espelho/previa`, `/espelho` | idem |
| `/carteira`, `/carteira/qdop`, `/carteira/producao` | `Diretoria.tsx` | KPIs, farol das obras, QDOP, produção 12 meses, download do QDOP | GET `/api/diretoria`, `/api/inicio`, `/api/contratos`, `/api/diretoria/qdop.xlsx` | menu: diretoria, admin; engenharia abre pela URL e o servidor deixa (ver_paineis) |
| `/admin` (saude), `/admin/reconciliacao`, `/admin/usuarios`, `/admin/auditoria` | `Admin.tsx` | saúde/backup/RM + "Sincronizar agora"; reconciliação RM×dashboard; usuários (criar, ativar/desativar) e contas Microsoft; auditoria (100 últimos, filtros na URL) | GET `/api/rm/status`, POST `/api/rm/sincronizar`, GET `/api/health`, `/api/rm/reconciliacao`, `/api/contratos`, GET/POST `/api/admin/usuarios`, PUT `/api/admin/usuarios/{id}`, GET `/api/admin/contas-microsoft`, `/api/admin/auditoria?limite=` | só admin (cliente redireciona, servidor exige `administrar`) |
| `/conta` | `MinhaConta.tsx` | conectar conta Microsoft (código de dispositivo), e-mail de teste, assinatura (PNG/JPG) | GET `/api/correio/status`; POST `/api/correio/conectar`, `/api/correio/teste`, `/api/correio/assinatura`; DELETE `/api/correio/assinatura`; GET `/api/correio/assinatura?v=` | todos pelo menu da conta; **diretoria leva 403** (conhecido, `backlog.md:8`) |

Endpoints SEM uso pela interface (só alcançáveis por API): GET `/api/medicoes/{id}`, GET `/api/contratos/{id}/notas`, GET `/api/paineis/alertas`, GET `/api/certidoes/tipos`, GET `/api/aditivos/{id}/conferencia`, **POST `/api/contratos/{id}/cronograma`** (escrita sem tela), GET `/api/protocolos/{pid}`, GET `/api/pleitos/{pid}`, GET `/api/espelhos/{id}`.

---

## 2. Formulários e ações de escrita

Formatos aceitos pelo servidor (valem para todos os formulários):

- **Dinheiro** (`dinheiro.py:16-29`, `parse_brl`): só pt-BR. Aceita `1.234,56`, `1234,56`, `1234,5`, `0,01`, `R$ 1.000,00`, `1.234` (= R$ 1.234,00). Recusa (422) `1234.56`, `12.34`, `-1,00`, `1,234`, três casas decimais. O `\d` da regex casa dígito Unicode (árabe-índico, largura cheia) e `int()` os converte: `١٢٣,٤٥` passa como R$ 123,45. Campo vazio no espelho = zero.
- **Data**: ISO `AAAA-MM-DD` (pydantic `datetime.date`). `dd/mm/aaaa` → 422. Pydantic em modo lax também aceita número (timestamp Unix) e `AAAA-MM-DDT00:00:00`. A interface usa `<input type="date">`, que já manda ISO.
- **Competência**: `AAAA-MM` com regex `[0-9]` (`api_medicoes.py:26`, `api_cronograma.py:20`). Exceções com `\d` (aceitam dígito Unicode no pydantic): regularidade (`api_documentos.py:110`) e `data_base_mes` dos pleitos (`api_pleitos.py:23`). A interface usa `<input type="month">`.
- **Ids na URL**: `int` sem teto. Rotas que NÃO limitam a 2^63-1 levam o número cru ao SQLite → `OverflowError` → provável 500 (ver §6). Limitam: espelhos, protocolos, pleitos, certidões, regularidades, notas/justificar, notas_envio, aditivos/conferencia, documentos de medição.
- **E-mails de destinatário** (`api_espelhos.py:50-59`, `_emails`, usado por todo envio): `strip().lower()`, descarta vazio, exige só conter `@` e ≤200 caracteres, deduplica. A interface exige `^[^\s@;,]+@[^\s@;,]+\.[^\s@;,]{2,}$` (`ComporEmail.tsx:19`).
- **Uploads** (`arquivos.py`): ver tabela 2.13.

### 2.1 Login (`Login.tsx`) → POST `/api/auth/login`

| Campo | Tipo | Obrig. | Cliente | Servidor |
|---|---|---|---|---|
| email | texto | sim | `type=email required` | `max_length=254`; minúsculas; não existe → mesma resposta e mesmo tempo (hash dummy, `auth.py:19-29`) |
| senha | texto | sim | `required` | **SEM teto de tamanho** (`api_auth.py:43`); argon2 sobre o que vier |

Resposta de erro única: 401 "E-mail ou senha inválidos, ou usuário bloqueado". Lockout em §5.

### 2.2 Usuários (`Admin.tsx` › Usuários)

POST `/api/admin/usuarios` (administrar+CSRF) — `UsuarioIn`:

| Campo | Tipo | Obrig. | Cliente | Servidor |
|---|---|---|---|---|
| nome | texto | sim | `required` | **SEM** (aceita `""`, espaços, 10 MB) |
| email | texto | sim | `type=email required` | **SEM formato** (aceita `x`, `a b`); minúsculas; UNIQUE → 409 |
| senha | texto | sim | `minLength=10` | `len >= 10` → 422; **SEM teto** |
| perfil | select | sim | engenharia/diretoria/admin | lista fechada → 422 |

PUT `/api/admin/usuarios/{id}` — `UsuarioPatch{ativo?: bool, perfil?: str}`: perfil validado; admin não se desativa nem tira o próprio admin (409, `api_usuarios.py:66-70`); id inexistente 404. Desativar não apaga sessões, mas `usuario_atual` exige `ativo=1` a cada pedido (`api_auth.py:22`). A interface só alterna `ativo`.

### 2.3 Medição manual (`Medicoes.tsx` › `NovaMedicaoManual`, só obra sem regra de espelho ativa) → POST `/api/contratos/{id}/medicoes`

| Campo | Tipo | Obrig. | Cliente | Servidor |
|---|---|---|---|---|
| numero | inteiro | sim | `pattern=[0-9]{1,3}` (aceita `0`, `000`) | `1..999` |
| tipo | select | sim | execucao/projeto/reajuste | Literal |
| competencia | mês | sim | `type=month required` | regex AAAA-MM |

Duplicado (contrato, número, tipo) → 422. **O servidor não confere se a obra tem regra de espelho ativa** (conhecido, `backlog.md:17`). Nasce em `prevista`.

### 2.4 Atos da medição (`MedicaoAtos.tsx`, abertos em `MedicaoPagina.tsx`)

**Valor** — PUT `/api/medicoes/{id}/valor` — `ValorIn`:

| Campo | Tipo | Obrig. | Cliente | Servidor |
|---|---|---|---|---|
| campo | protocolado\|atestado | sim | botão abre um ou outro | Literal |
| valor | BRL | sim | `required`, sem formato | `max_length=40`, `parse_brl`, ≤ int64 |
| data | data | não | só no atestado | só com `campo=atestado` (422 senão); **SEM faixa** (futura, 1900) |

Regras: cancelada/desistida → 422; protocolado congelado com valor → 422. **Cliente esconde "Editar o valor" protocolado em `espelho_gerado`/`espelho_enviado` (`MedicaoAtos.tsx:27`); o servidor aceita** → o valor da medição diverge do espelho vigente (só no cliente).

**Protocolo feito fora** — POST `/api/medicoes/{id}/protocolo` — `ProtocoloIn`:

| Campo | Tipo | Obrig. | Cliente | Servidor |
|---|---|---|---|---|
| data | data | sim | `type=date required` | **SEM faixa** (futura, antes da competência, 1900) |
| numero_oficio | texto | não | `maxLength=100` | `max_length=100` |
| numero_processo | texto | não | `maxLength=100` | `max_length=100` |
| apesar_das_pendencias | bool | não | checkbox, só aparece com pendência | trava checklist se `false` e houver certidão pendente (422) |
| justificativa | texto | se apesar | `required maxLength=500` | `max_length=500`; vazia com pendência → 422 |

A interface só mostra o botão depois da etapa 4 feita (`MedicaoPagina.tsx:318-336`). **O servidor aceita a partir de `prevista`, `espelho_gerado`, `espelho_enviado` e `nota_emitida`** (`medicoes.py:184-187`): pula Faturamento, Nota e Envio.

**Recebimento / cancelar / desistir** — POST `/api/medicoes/{id}/estado` — `EstadoIn`:

| Campo | Tipo | Obrig. | Cliente | Servidor |
|---|---|---|---|---|
| estado | recebida\|cancelada\|desistida | sim | botões conforme `PROXIMOS` (`medicao.ts:30`) | Literal + `TRANSICOES` (`medicoes.py:20-36`) → 422 "Transição inválida" |
| motivo | texto | não | `maxLength=1000` | `max_length=1000`; `None` preserva o anterior |
| data | data | não | só em recebida | só para estado com coluna de data (422 senão); confere só "baixa ≥ emissão da nota/NF"; **futura aceita** |

**Medição final** — POST `/api/medicoes/{id}/final` (`FinalIn{data?}`, **SEM faixa**, padrão hoje) e POST `/final/desmarcar` (`motivo` 1..500, obrigatório). Final em cancelada/desistida → 422. Marcar de novo é aceito (regrava `final_em`).

### 2.5 Espelho (`Espelho.tsx`, em `/obras/{id}` e `/obras/{o}/medicoes/nova`)

POST `/api/contratos/{id}/espelho/previa` (não grava) e POST `/api/contratos/{id}/espelho` (grava) — `EspelhoIn`:

| Campo | Tipo | Obrig. | Cliente | Servidor |
|---|---|---|---|---|
| numero | inteiro | sim | `pattern=[0-9]{1,3} required` | `1..999` |
| competencia | mês | sim | `type=month required` | regex AAAA-MM |
| entradas | {chave: BRL} | — | um campo por entrada da regra, sem validação | ≤10 chaves; chave e valor ≤40; chave desconhecida → 422; `parse_brl`; ≤ `TETO_CENTAVOS` (10^13−1, `espelho.py:41`); todos zero → 422 |
| motivo | texto | não | `maxLength=500` | `max_length=500` (vai para a versão substituída) |
| periodo_inicio / periodo_fim | data | não | `type=date` | ambos ou nenhum; `\d{4}-\d{2}-\d{2}`; início ≤ fim; ≤ 366 dias; tem de tocar o mês da competência (`espelhos.py:36-59`) |

Regra: obra sem regra `ativa` → 422; medição do mesmo número já protocolada → 422; gerar de novo = versão nova, a anterior vira `substituido`. Não confere sequência de números nem situação do contrato (encerrado aceita).

Envio ao faturamento — GET `/api/espelhos/{id}/envio` (prévia) e POST `/api/espelhos/{id}/enviar` — `EnvioIn{para[≤30], copia[≤30], cco[≤30], assunto 1..300, corpo ≤20000}`. Versão substituída → 422; para vazio → 422; medição cancelada/desistida → 422; anexos >25 MB → 422. Corpo vira HTML com `html.escape` por linha (`espelhos.py:245`). Reenviar o mesmo espelho é aceito (aviso "este envio substitui").

Evidência do órgão — POST `/api/medicoes/{id}/documentos` (multipart `arquivo`, `tipo_doc` só `evidencia_orgao`): PDF validado completo (tabela 2.13). Aceito em qualquer estado da medição, inclusive cancelada.

### 2.6 Notas (`Notas.tsx`, `Frc.tsx`, `NotasAEnviar.tsx`)

| Ação | Rota | Campos e validação |
|---|---|---|
| Anexar nota/FRC | POST `/api/medicoes/{id}/notas` | multipart `arquivo` (PDF, 10 MB, `%PDF-`), `tipo_doc` `nfs`\|`fatura` (422 outro). PDF lido em subprocesso (até 20 páginas, 60 mil caracteres). Medição cancelada/desistida → 422, **mas o PDF já foi gravado em `dados/notas/`** (`notas.py:257`, órfão inofensivo por sha). Cliente: `accept=application/pdf multiple`, checkbox "é a FRC". |
| Informar número/data/valor | POST `/api/medicoes/{id}/notas/manual` — `ManualIn` | `documento_id` 1..int64 (tem de ser `nfs` desta medição); `numero` 1..999.999.999; `emissao` data **SEM faixa**; `valor` 1..40 caracteres, `parse_brl`, >0, **SEM teto int64** (valor de 20+ dígitos → `OverflowError` no INSERT). Cliente: `pattern=[0-9]{1,9}`, `type=date required`, valor `required`. |
| Declarar completas | POST `/api/medicoes/{id}/notas/completa` — `justificativa` 1..1000 | só em `espelho_gerado`/`espelho_enviado` e com ≥1 nota alocada (422). Cliente `required maxLength=1000`. |
| Justificar divergência | POST `/api/notas/{nota_id}/justificar` — `justificativa` 1..1000 | qualquer nota existente (não confere medição nem perfil de quem lançou). |
| Gerar FRC | POST `/api/medicoes/{id}/frc` — `numero` 1..99.999 | só obra de consórcio; nº já usado por outra medição do consórcio → 422; soma não fecha → 422. Cliente: só dígitos, até 5. |
| Baixar FRC | GET `/api/medicoes/{id}/frc/{pdf\|xlsx}` | outro formato → 404. |

### 2.7 Envio da nota (`NotasAEnviar.tsx`, `EnviarNota.tsx`, `Etapas.tsx`)

POST `/api/notas/envio/iniciar` — `IniciarIn`:

| Campo | Tipo | Obrig. | Cliente | Servidor |
|---|---|---|---|---|
| contrato_id | int | sim | — | 1..int64, existe |
| medicao_ids | int[] | sim | do envio da lista | 1..10 itens; todas do contrato e em `nota_emitida` (422); >1 só onde o órgão junta (SINFRA, VG) |
| numero_oficio | texto | fora SINFRA | `window.prompt`, `trim()`; Cancelar aborta | ≤40; `oficios.canonico` exige um número (422) → `CT-361-LT-2026`; repetido é só aviso |

Mesma composição devolve o protocolo existente; outra composição **descarta** os protocolos ativos e cria outro (`notas_envio.py:208-217`).

POST `/api/notas/envio/{pid}/enviar` — `EnviarIn{para[≤30], copia[≤30], assunto 1..300, corpo ≤20000, justificativa ≤2000}`. **Não tem `cco`**: a janela `ComporEmail` tem o campo Cco, mas `EnviarNota.tsx:208` não o manda e o modelo não o aceita → **Cco digitado some sem aviso**. Certidão vencida → 409 (`protocolo.Bloqueio`); pendência sem justificativa de ≥10 caracteres → 422; ver regras de envio em §4.

POST `/api/notas/envio-externo` (multipart) — "Registrar envio feito por fora":

| Campo | Tipo | Obrig. | Cliente | Servidor |
|---|---|---|---|---|
| medicao_ids | int[] (repetido) | sim | do envio | cada uma existe e está em `nota_emitida`; **SEM teto de quantidade e SEM conferir que são do mesmo contrato** |
| enviado_em | data ISO (texto ≤10) | sim | `type=date required max=hoje` | `fromisoformat`; futura → 422; **SEM limite inferior** |
| observacao | texto | sim | `maxLength=2000` (sem `required`) | ≤2000; vazia → 422 |
| eml | arquivo | não | `accept=.eml,message/rfc822` | ≤25 MB; **conteúdo SEM validação** (qualquer binário vira `evidencias/<sha>.eml`) |

Efeito: `registrar_protocolo(..., apesar_das_pendencias=True)` → **passa por cima da trava de certidão vencida (D8)** que o envio pelo sistema aplica; descarta os protocolos ativos.

POST `/api/notas/{medicao_id}/numero-orgao` — `numero` ≤100. Texto vazio **apaga** o número já gravado.

### 2.8 Protocolo pelo sistema (`Protocolo.tsx`, `EnviarNota.tsx`)

| Ação | Rota | Campos e validação |
|---|---|---|
| Novo protocolo | POST `/api/contratos/{id}/protocolos` — `CriarIn` | `etapa` unico\|medicao\|nota (e tem de existir na família, 422); `medicao_ids` 1..10, do contrato, não encerradas; execução+reajuste juntos só onde o órgão permite; `numero_oficio` ≤40 (obrigatório se a etapa tem carta). Cliente: rádio, checkboxes, ofício `required maxLength=40`. |
| Peça | POST `/api/protocolos/{pid}/pecas` (multipart) | `tipo` ∈ boletim, planilha, diario, fotos, cronograma, art, ensaios, memorial, diagrama, pluviometria, croqui, outro, anexo; extensão do NOME decide: `.xlsx` (25 MB, `PK\x03\x04`), `.zip` (40 MB, só tipo anexo), resto PDF (40 MB, só `%PDF-`, **não abre o PDF no upload**). Protocolo enviado/descartado → 422. Peça não-anexo volta o protocolo a rascunho. |
| Link OneDrive | POST `/api/protocolos/{pid}/links` — `LinkIn{nome ≤200, url ≤2100}` | nome não vazio; url `https://\S{8,2000}` — **qualquer domínio https** (o cliente sugere sharepoint, não exige). Vai no corpo do e-mail como `<a href>` clicável. |
| Remover peça/link | POST `.../pecas/{id}/remover`, `.../links/{id}/remover` | id de outro protocolo → 422. Sem confirmação no cliente. |
| Montar | POST `/api/protocolos/{pid}/montar` — `corpo ≤20000` | só etapa com carta; corpo vazio = gravado ou padrão; PDF montado >40 MB → 422; peça PDF corrompida estoura aqui (422). |
| Assinado | POST `/api/protocolos/{pid}/assinado` (PDF ≤40 MB) | exige montado; conferência é **aviso**, não trava. |
| Prévia | POST `/api/protocolos/envio/previa` — `protocolo_ids` 1..10 | mesmo contrato e etapa (422). |
| Enviar | POST `/api/protocolos/envio` — `EnvioIn` (ids, para, copia, cco, assunto, corpo, justificativa ≤2000) | ver §4. |
| Nº do órgão | POST `/api/protocolos/{pid}/numero-orgao` (form `numero` ≤100, `comprovante` PDF opcional, só `%PDF-`) | só protocolo enviado; vazio apaga o número. |
| Descartar | POST `/api/protocolos/{pid}/descartar` — `motivo` 1..500 | enviado não se descarta. |

### 2.9 Pleitos — reajuste, prazo, conclusão (`FluxoOficio.tsx`)

POST `/api/contratos/{id}/pleitos` — `CriarIn`:

| Campo | Tipo | Obrig. | Cliente | Servidor |
|---|---|---|---|---|
| tipo | reajuste\|prazo\|conclusao | sim | pela aba | Literal |
| numero_oficio | texto | sim | `required maxLength=40` | 1..40; precisa conter número |
| data_base_mes | AAAA-MM | reajuste | vem da tela | regex `\d`; tem de ser data-base do contrato (422) |
| dias | int | prazo | `type=number min=1 required` | 1..3650 |
| justificativa | texto | prazo | `required`, **sem maxLength** | ≤20000; vazia no prazo → 422 |

Conclusão só com contrato em encerramento. **Sem trava de rascunho duplicado do mesmo ciclo** (conhecido, `backlog.md:12`). Anexos (`tipo` planilha_calculo\|cronograma\|outro; `.xlsx` 25 MB ou PDF 40 MB), montar, assinado, prévia (POST sem corpo), enviar (`EnvioIn` com cco), descartar (motivo 1..500): mesmas regras do protocolo. Pleito não confere certidões.

### 2.10 Documentos de protocolo (`Documentos.tsx`)

| Ação | Rota | Campos e validação |
|---|---|---|
| Ler certidão | POST `/api/documentos/certidoes/ler` | só PDF (10 MB); não grava; sem texto → OCR local (1 por vez, 40 s). |
| Gravar certidão | POST `/api/documentos/certidoes` (multipart) | PDF relido no servidor (o que a tela mostrou não vale). Campos digitados só valem se o leitor recusar com motivo "digitável": `entidade_id` 1..int64 (existe e ativa), `tipo` federal\|fgts\|trabalhista\|estadual\|municipal\|falencia, `emissao` data, `validade` data (falência: vazia = 30 dias úteis), `natureza` negativa\|positiva_efeito_negativa, `numero` ≤100. Validade ≤ emissão → 422; CNPJ da empresa não aparece no texto → 422; repetida → 409. **SEM faixa de datas** (emissão futura e validade em 2099 passam; uma certidão assim fica "válida" e destrava protocolos). Cliente: selects e datas `required`. |
| Regularidade | POST `/api/documentos/regularidades` (multipart `arquivo`, `entidade_id` obrigatório, `competencia` opcional) | competência lida do PDF manda; informada e diferente → 422; sem nenhuma → 422. Lê os primeiros 10 MB e abre um subprocesso **antes** de conferir tipo e `%PDF-`. Cliente: `type=month required`. |
| ZIP das vigentes | GET `/api/documentos/zip?entidade_id=&data=` | `entidade_id` int **sem teto**; `data` ISO opcional (qualquer data). |

### 2.11 Conta (`MinhaConta.tsx`, `ComporEmail.tsx`)

- POST `/api/correio/conectar`: sem corpo; servidor sem Graph → 422; já aguardando → devolve o mesmo código. Estado em memória do processo.
- POST `/api/correio/teste`: manda um e-mail real para a própria conta (sem limite de frequência).
- POST `/api/correio/assinatura`: arquivo lido até 1 MB+1; só PNG/JPG pelos bytes mágicos; >1 MB → 422. Cliente `accept=image/png,image/jpeg`. DELETE remove sem confirmação.
- GET `/api/correio/contatos?q=` (≤100): `q` vai entre aspas para `$search` do Graph sem escapar aspas.

### 2.12 Admin

- POST `/api/rm/sincronizar` (administrar): sem corpo; RM não configurado → 422; rodada em andamento → 409.
- GET `/api/admin/auditoria?limite=` 1..500.

### 2.13 Uploads — resumo

| Onde | Tipo aceito | Teto | Conferência | PDF inválido / tipo errado |
|---|---|---|---|---|
| certidão (ler/gravar), evidência, regularidade | PDF (`content-type` exatamente `application/pdf` + `%PDF-`) | 10 MB | abre num leitor em subprocesso (≤20 páginas, 60 mil caracteres, anti-bomba 50:1) | tipo/assinatura errados ou vazio → 415; >10 MB → 413; corrompido → 415 (gravar) / 422 (ler); fila cheia → 422/415 "tente de novo" |
| nota/FRC | PDF | 10 MB | `%PDF-`; leitura em subprocesso só quando `tipo_doc=nfs` | 415/413; corrompido → 422 (ValueError); texto inadequado → 415 |
| peça de protocolo, assinado, anexo de pleito | PDF | 40 MB (`pdfs.py:11`) | só `%PDF-` no upload; abre no montar/assinado (teto 400 páginas) | 415/413; corrompido aparece no montar (422) ou nunca (peças soltas da nota SINFRA vão ao órgão sem abrir) |
| planilha | `.xlsx` pelo NOME + content-type xlsx ou `octet-stream` + `PK\x03\x04` | 25 MB | só assinatura zip (um .docx renomeado passa) | 415/413 |
| zip complementar | `.zip` pelo nome + content-type zip/octet-stream + `PK\x03\x04` | 40 MB | só assinatura | 415/413; tipo ≠ anexo → 422 |
| comprovante do órgão | PDF | 10 MB | só `%PDF-` | 415/413 |
| .eml (envio por fora) | qualquer | 25 MB | **nenhuma** | >25 MB → 422 |
| assinatura | PNG/JPG pelos bytes | 1 MB | bytes mágicos | 422 |

Nome em disco é sempre o sha256 (sem travessia). O nome do cliente vai para o banco (últimos 200 caracteres) e para o `Content-Disposition` do download.

### 2.14 Campos SEM validação no servidor (contagem)

1. `UsuarioIn.nome` — vazio ou gigante.
2. `UsuarioIn.email` — sem formato.
3. `UsuarioIn.senha` — sem teto.
4. `LoginIn.senha` — sem teto (não autenticado).
5. `ProtocoloIn.data` — qualquer data.
6. `ValorIn.data` (atesto) — qualquer data.
7. `ValorIn.valor` protocolado em `espelho_gerado`/`espelho_enviado` — bloqueio só no cliente.
8. `EstadoIn.data` (recebida) — futura aceita.
9. `FinalIn.data` — qualquer data.
10. `ManualIn.valor` — sem teto int64.
11. `ManualIn.emissao` — qualquer data.
12. `para`/`copia`/`cco` de todo envio — só "contém @".
13. `LinkIn.url` — qualquer domínio https.
14. Certidão manual `emissao`/`validade` — sem faixa.
15. `envio-externo.medicao_ids` — sem teto e sem mesmo contrato.
16. `envio-externo.eml` — conteúdo livre.
17. `envio-externo.enviado_em` — sem limite inferior.
18. `numero` do órgão (protocolo e nota) — vazio apaga sem confirmação.
19. `competencia` da regularidade e `data_base_mes` do pleito — regex `\d` (dígito Unicode).

**Total: 19.**

---

## 3. Endpoints (107)

Legenda de permissão: **—** = sem autenticação; **sessão** = só sessão válida; demais = `exigir(...)`. Toda escrita com `exigir` exige CSRF, salvo onde marcado. Erros de domínio viram 422 (ValueError), 404 (inexistente), 409 (conflito/bloqueio), 403 (permissão/CSRF), 401 (sessão), 503 (banco ocupado, `main.py:72-87`).

| # | Método | Caminho | Permissão | Entrada | Devolve |
|---|---|---|---|---|---|
| 1 | POST | `/api/auth/login` | **—** | `LoginIn{email≤254, senha}` | `{nome, perfil, csrf}` + cookie; 401 |
| 2 | POST | `/api/auth/logout` | **— (sem CSRF)** | cookie | `{ok}` |
| 3 | GET | `/api/auth/eu` | sessão | — | `{id, nome, email, perfil, csrf}` |
| 4 | GET | `/api/health` | **—** | — | `{status, banco, backup{ultimo_snapshot, *_erro, ...}}`; 503 |
| 5 | GET | `/api/inicio` | ver_paineis | — | `{avisos (recorte por perfil), resumo}` |
| 6 | GET | `/api/inicio/painel` | ver_paineis | — | painel do Início |
| 7 | GET | `/api/medicoes/andamento` | ver_paineis | `?contrato_id` (int sem teto), `?estado` (≤30) | lista em andamento |
| 8 | GET | `/api/medicoes/resumo` | ver_paineis | — | `{hoje, contagens, linhas, obras}` |
| 9 | GET | `/api/admin/auditoria` | administrar | `?limite` 1..500 | `{cadeia_integra, eventos}` |
| 10 | GET | `/api/admin/contas-microsoft` | administrar | — | lista |
| 11 | GET | `/api/admin/usuarios` | administrar | — | lista (sem hash) |
| 12 | POST | `/api/admin/usuarios` | administrar | `UsuarioIn` | 201 `{id}`; 409 e-mail |
| 13 | PUT | `/api/admin/usuarios/{id}` | administrar | `UsuarioPatch` | `{ok}` |
| 14 | GET | `/api/contratos/{id}/aditivos` | ver_paineis | — | lista |
| 15 | GET | `/api/aditivos/{id}/conferencia` | ver_paineis | — | conferência (sem UI) |
| 16 | GET | `/api/entidades` | ver_paineis | — | lista |
| 17 | GET | `/api/certidoes/tipos` | ver_paineis | — | lista (sem UI) |
| 18 | GET | `/api/certidoes/{id}/arquivo` | ver_paineis | — | PDF (nosniff) |
| 19 | GET | `/api/contratos` | ver_paineis | — | obras + resumo de prazos |
| 20 | GET | `/api/contratos/{id}` | ver_paineis | — | contrato vigente |
| 21 | GET | `/api/contratos/{id}/cabecalho` | ver_paineis | — | cabeçalho + faturado/a receber |
| 22 | GET | `/api/contratos/{id}/cadastro` | ver_paineis | — | cadastro, instrumentos |
| 23 | GET | `/api/contratos/{id}/notas` | ver_paineis | — | notas por medição (sem UI) |
| 24 | GET | `/api/correio/status` | editar_cadastros | — | `{configurado, conectado, login, assinatura}` |
| 25 | POST | `/api/correio/conectar` | editar_cadastros | — | status (código de dispositivo); 422/502 |
| 26 | POST | `/api/correio/teste` | editar_cadastros | — | **envia e-mail**; `{envio_id, remetente}` |
| 27 | GET | `/api/correio/remetente` | editar_cadastros | — | `{remetente, erro}` |
| 28 | GET | `/api/correio/contatos` | editar_cadastros | `?q≤100&todos` | ≤10 ou ≤200 contatos |
| 29 | GET | `/api/correio/assinatura` | editar_cadastros | — | imagem; 404 |
| 30 | POST | `/api/correio/assinatura` | editar_cadastros | multipart `arquivo` | status; 422 |
| 31 | DELETE | `/api/correio/assinatura` | editar_cadastros | — | status |
| 32 | GET | `/api/contratos/{id}/cronograma` | ver_paineis | — | versão vigente |
| 33 | POST | `/api/contratos/{id}/cronograma` | editar_cadastros | `VersaoIn{itens 1..600 {competencia, valor≤40}}` | 201 `{versao}` (sem UI) |
| 34 | GET | `/api/contratos/{id}/espelho` | ver_paineis | — | `{regra, espelhos}` |
| 35 | POST | `/api/contratos/{id}/espelho/previa` | editar_cadastros | `EspelhoIn` | prévia (não grava) |
| 36 | POST | `/api/contratos/{id}/espelho` | editar_cadastros | `EspelhoIn` | 201 `{espelho_id}`; **grava .docx** |
| 37 | GET | `/api/espelhos/{id}` | ver_paineis | — | espelho (sem UI) |
| 38 | GET | `/api/espelhos/{id}/arquivos/{doc}` | ver_paineis | — | .docx |
| 39 | GET | `/api/espelhos/{id}/envio` | editar_cadastros (sem CSRF, GET) | — | prévia do e-mail |
| 40 | POST | `/api/espelhos/{id}/enviar` | editar_cadastros | `EnvioIn` | **envia e-mail**; `{envio_id}` |
| 41 | POST | `/api/medicoes/{id}/documentos` | editar_cadastros | multipart `arquivo`, `tipo_doc` | 201 `{documento_id, repetido}`; **grava PDF** |
| 42 | GET | `/api/medicoes/{id}/documentos/{doc}` | ver_paineis | — | PDF ou (qualquer outro, inclusive .eml) servido como DOCX |
| 43 | GET | `/api/contratos/{id}/medicoes` | ver_paineis | — | medições com protocolos, notas, documentos |
| 44 | POST | `/api/contratos/{id}/medicoes` | editar_cadastros | `MedicaoIn` | 201 `{id}` |
| 45 | GET | `/api/medicoes/{id}` | ver_paineis | — | detalhe (sem UI) |
| 46 | PUT | `/api/medicoes/{id}/valor` | editar_cadastros | `ValorIn` | `{ok}` |
| 47 | POST | `/api/medicoes/{id}/protocolo` | editar_cadastros | `ProtocoloIn` | 201 `{id, ressalva}` |
| 48 | POST | `/api/medicoes/{id}/estado` | editar_cadastros | `EstadoIn` | `{ok}` |
| 49 | POST | `/api/medicoes/{id}/final` | editar_cadastros | `FinalIn` | detalhe |
| 50 | POST | `/api/medicoes/{id}/final/desmarcar` | editar_cadastros | `{motivo 1..500}` | detalhe |
| 51 | GET | `/api/documentos` | ver_paineis | — | painel de documentos |
| 52 | POST | `/api/documentos/certidoes/ler` | editar_cadastros | multipart `arquivo` | `{ok, leitura}` ou `{ok:false, motivo, digitavel}` |
| 53 | POST | `/api/documentos/certidoes` | editar_cadastros | multipart (ver 2.10) | 201; 409 repetida; **grava PDF** |
| 54 | POST | `/api/documentos/regularidades` | editar_cadastros | multipart `arquivo`, `entidade_id`, `competencia?` | 201 `{id}`; **grava PDF** |
| 55 | GET | `/api/documentos/regularidades/{rid}/arquivo` | ver_paineis | — | PDF |
| 56 | GET | `/api/documentos/zip` | ver_paineis | `?entidade_id` (sem teto) `&data` | zip |
| 57 | GET | `/api/contratos/{id}/checklist-protocolo` | ver_paineis | `?natureza` execucao\|projeto\|reajuste | veredito + itens |
| 58 | GET | `/api/contratos/{id}/protocolos` | ver_paineis | — | protocolos com corpo padrão |
| 59 | POST | `/api/contratos/{id}/protocolos` | editar_cadastros | `CriarIn` | 201 detalhe |
| 60 | GET | `/api/protocolos/{pid}` | ver_paineis | — | detalhe (sem UI) |
| 61 | POST | `/api/protocolos/{pid}/pecas` | editar_cadastros | multipart `tipo`, `arquivo` | detalhe; **grava arquivo** |
| 62 | POST | `/api/protocolos/{pid}/links` | editar_cadastros | `LinkIn` | detalhe |
| 63 | POST | `/api/protocolos/{pid}/links/{link_id}/remover` | editar_cadastros | — | detalhe |
| 64 | POST | `/api/protocolos/{pid}/pecas/{peca_id}/remover` | editar_cadastros | — | detalhe |
| 65 | POST | `/api/protocolos/{pid}/montar` | editar_cadastros | `{corpo≤20000}` | detalhe; **grava PDF** |
| 66 | GET | `/api/protocolos/{pid}/pacote` | ver_paineis | — | PDF montado |
| 67 | GET | `/api/protocolos/{pid}/assinado` | ver_paineis | — | PDF assinado |
| 68 | POST | `/api/protocolos/{pid}/assinado` | editar_cadastros | multipart `arquivo` | detalhe; **grava PDF** |
| 69 | POST | `/api/protocolos/envio/previa` | editar_cadastros | `{protocolo_ids 1..10}` | prévia |
| 70 | POST | `/api/protocolos/envio` | editar_cadastros | `EnvioIn` (ids, para, copia, cco, assunto, corpo, justificativa) | **envia e-mail**; `{envio_id}` |
| 71 | POST | `/api/protocolos/{pid}/numero-orgao` | editar_cadastros | form `numero≤100`, `comprovante?` | detalhe; **grava PDF** |
| 72 | POST | `/api/protocolos/{pid}/descartar` | editar_cadastros | `{motivo 1..500}` | `{ok}` |
| 73 | GET | `/api/contratos/{id}/reajuste` | ver_paineis | — | `{ciclos, pleitos}` |
| 74 | GET | `/api/contratos/{id}/prazos` | ver_paineis | — | `{situacao, historico, pleitos}` |
| 75 | POST | `/api/contratos/{id}/pleitos` | editar_cadastros | `CriarIn` (pleito) | 201 detalhe |
| 76 | GET | `/api/pleitos/{pid}` | ver_paineis | — | detalhe (sem UI) |
| 77 | POST | `/api/pleitos/{pid}/anexos` | editar_cadastros | multipart `tipo`, `arquivo` | detalhe; **grava arquivo** |
| 78 | POST | `/api/pleitos/{pid}/anexos/{aid}/remover` | editar_cadastros | — | detalhe |
| 79 | POST | `/api/pleitos/{pid}/montar` | editar_cadastros | `{corpo≤20000}` | detalhe; **grava PDF** |
| 80 | GET | `/api/pleitos/{pid}/documento` | ver_paineis | — | PDF |
| 81 | POST | `/api/pleitos/{pid}/assinado` | editar_cadastros | multipart `arquivo` | detalhe; **grava PDF** |
| 82 | POST | `/api/pleitos/{pid}/previa` | editar_cadastros | — | prévia |
| 83 | POST | `/api/pleitos/{pid}/enviar` | editar_cadastros | `EnvioIn` (com cco) | **envia e-mail**; `{envio_id}` |
| 84 | POST | `/api/pleitos/{pid}/descartar` | editar_cadastros | `{motivo 1..500}` | `{ok}` |
| 85 | GET | `/api/diretoria` | ver_paineis | — | painel (engenharia também vê) |
| 86 | GET | `/api/diretoria/qdop.xlsx` | ver_paineis | — | xlsx |
| 87 | GET | `/api/medicoes/{id}/notas` | ver_paineis | — | `{esperadas, notas, faltam, documentos_sem_nota, pode_declarar}` |
| 88 | POST | `/api/medicoes/{id}/notas` | editar_cadastros | multipart `arquivo`, `tipo_doc` | leitura + conferência; **grava PDF**; pode gerar FRC |
| 89 | POST | `/api/medicoes/{id}/notas/manual` | editar_cadastros | `ManualIn` | `{nota_id, conferencia, faltam, estado}` |
| 90 | POST | `/api/medicoes/{id}/notas/completa` | editar_cadastros | `{justificativa 1..1000}` | `{ok, estado}` |
| 91 | GET | `/api/medicoes/{id}/frc` | ver_paineis | — | situação da FRC |
| 92 | POST | `/api/medicoes/{id}/frc` | editar_cadastros | `{numero 1..99999}` | situação; **grava PDF+XLSX** |
| 93 | GET | `/api/medicoes/{id}/frc/{formato}` | ver_paineis | pdf\|xlsx | arquivo |
| 94 | POST | `/api/notas/{nota_id}/justificar` | editar_cadastros | `{justificativa 1..1000}` | `{ok}` |
| 95 | GET | `/api/notas/a-enviar` | ver_paineis | — | `{envios, contadores}` |
| 96 | POST | `/api/notas/envio/iniciar` | editar_cadastros | `IniciarIn` | `{protocolo_id}` |
| 97 | GET | `/api/notas/envio/{pid}` | ver_paineis | — | detalhe do envio + prévia |
| 98 | POST | `/api/notas/envio/{pid}/enviar` | editar_cadastros | `EnviarIn` (sem cco) | **envia e-mail**; 409 bloqueio |
| 99 | POST | `/api/notas/envio-externo` | editar_cadastros | form (ver 2.7) | `{ok}`; **grava .eml** |
| 100 | GET | `/api/notas/aguardando-pagamento` | ver_paineis | — | lista |
| 101 | POST | `/api/notas/{medicao_id}/numero-orgao` | editar_cadastros | `{numero≤100}` | `{ok}` |
| 102 | GET | `/api/paineis/alertas` | ver_paineis | — | alertas (sem UI) |
| 103 | GET | `/api/contratos/{id}/curva` | ver_paineis | — | `{curva, saldo}` |
| 104 | GET | `/api/contratos/{id}/medicoes.csv` | ver_paineis | — | CSV `;` UTF-8 BOM (texto do cadastro com prefixo `'` anti-fórmula) |
| 105 | GET | `/api/rm/status` | ver_paineis | — | frescor, rodadas |
| 106 | POST | `/api/rm/sincronizar` | administrar | — | rodada; 409/422 |
| 107 | GET | `/api/rm/reconciliacao` | administrar | — | reconciliação |

Mais o mount estático em `/` (`main.py:19-42`): caminho sem extensão vira `index.html`; `/api/*` inexistente continua 404.

**Rotas sem autenticação: 3** — `/api/auth/login`, `/api/auth/logout` (também sem CSRF), `/api/health` (expõe carimbos e a mensagem de erro do backup).

---

## 4. Máquina de estados

### 4.1 Medição (`medicoes.py:20-38`)

Estados: `prevista`, `espelho_gerado`, `espelho_enviado`, `nota_emitida`, `protocolada`, `nf_emitida` (legado, só saída), `recebida`, `cancelada`, `desistida`. Finais: `recebida`, `cancelada`, `desistida`. Etapas da página (`Etapas.tsx:14-24`): prevista=1, espelho_gerado=2, espelho_enviado=3, nota_emitida=4, protocolada/nf_emitida=5, recebida=6 (tudo feito); cancelada/desistida=0.

| De → Para | Quem dispara (rota) | Perfil | E-mail | Arquivo |
|---|---|---|---|---|
| ∅ → `prevista` | POST `/api/contratos/{id}/medicoes` | engenharia, admin | — | — |
| ∅ ou `espelho_*` → `espelho_gerado` (ou mantém `espelho_enviado` atualizando valor) | POST `/api/contratos/{id}/espelho` (`espelhos.gerar` → `medicoes.criar_para_espelho`) | engenharia, admin | — | `.docx` em `dados/espelhos/` |
| `espelho_gerado` → `espelho_enviado` | POST `/api/espelhos/{id}/enviar` (sistema, depois do e-mail) | engenharia, admin | **sim** (`tipo=espelho`) | — |
| `espelho_gerado`/`espelho_enviado` → `nota_emitida` | automático quando não falta nota (`notas.fechar_se_completa`): POST `/notas`, `/notas/manual`, rodada do RM; ou POST `/notas/completa` (justificativa) | engenharia, admin, sistema (RM) | — | PDF em `dados/notas/` |
| `prevista`/`espelho_*`/`nota_emitida` → `protocolada` (+ `congelada=1`) | (a) POST `/api/medicoes/{id}/protocolo` (manual, checklist trava); (b) POST `/api/protocolos/envio` ou `/api/notas/envio/{pid}/enviar` quando a etapa marca protocolada (sistema, depois do e-mail; `apesar_das_pendencias=True`); (c) POST `/api/notas/envio-externo` (`apesar=True`) | engenharia, admin | (b) **sim** (`tipo=protocolo`) | (b) PDF montado já gravado; (c) `.eml` em `dados/evidencias/` |
| `protocolada`/`nf_emitida` → (mesmo estado) reprotocolo | mesmas rotas | idem | idem | idem |
| `protocolada`/`nf_emitida` → `recebida` | POST `/api/medicoes/{id}/estado` ou rodada do RM (título quitado) | engenharia, admin, sistema | — | — |
| `prevista`/`espelho_gerado`/`espelho_enviado`/`nota_emitida`/`protocolada`/`nf_emitida` → `cancelada` | POST `/estado` | engenharia, admin | — | — |
| `prevista`/`protocolada`/`nf_emitida` → `desistida` | POST `/estado` | engenharia, admin | — | — |
| marcar/desmarcar final (não é estado; põe/tira o contrato em encerramento) | POST `/final`, `/final/desmarcar` | engenharia, admin | — | — |

Invariantes: `protocolada` só por `registrar_protocolo` (nunca por `/estado`); protocolado congela no 1º protocolo (`medicoes.py:114-115`); toda transição é `UPDATE ... WHERE estado=?` (corrida perdida → 422 "mudou concorrentemente"); nada volta para trás; cancelar não desfaz a marca de final (o contrato continua em encerramento).

### 4.2 Protocolo de envio (`protocolo.py`) e pleito (`pleitos.py`)

`rascunho` → (montar) `montado` → (assinado) `assinado` → (enviar) `enviado`; qualquer não enviado → `descartado`. Peça não-anexo adicionada/removida em `montado`/`assinado` volta a `rascunho` e apaga o assinado (`protocolo.py:192-197`). Enviar exige montado (etapa com carta), não exige assinado: falta de assinatura é pendência que passa com justificativa ≥10 caracteres. Certidão vencida (D8) bloqueia só o envio pelo sistema (409), não o envio por fora nem o protocolo manual com justificativa. Iniciar envio com outra composição descarta os ativos.

### 4.3 Outros

- Espelho: `vigente` → `substituido` ao gerar de novo o mesmo número (`espelhos.py:122-128`).
- Nota fiscal: `confirmacao` `aguardando_rm` → `confirmada`|`divergente` pelo RM; alocação desfeita quando cancelada no RM.
- E-mails enviados por `correio.enviar_e_registrar`: espelho (#40), protocolo (#70, #98), pleito (#83), teste (#26), e a cobrança agendada de certidões só para o e-mail do dono (`cobranca_certidoes.py:18,73`).

---

## 5. Regras de negócio (comportamento correto)

| Regra | Fonte |
|---|---|
| A última versão enviada é a vigente (destinatários, assunto, texto, nomes) | `docs/mapeamento-envio-nota-2026-10-08.md:3` |
| Envia e só então registra: falha de envio não deixa rastro de envio | `correio.py:207`, `espelhos.py:268` |
| Quem envia não vai em cópia/Cco de si mesmo (compara com a conta do Outlook, não com o login); só Cc e Cco são filtrados, não Para | `correio.py:212-214`, `protocolo.py:722-724`, `espelhos.py:225` |
| Tudo que recusa vem antes do e-mail; depois do e-mail nada recusa (medição que não pôde ser marcada fica na auditoria) | `protocolo.py:772`, `protocolo.py:796-819`, `pleitos.py:351` |
| Anexos por e-mail ≤ 25 MB brutos; acima de 3 MB sobe em sessão de upload | `correio.py:33-37` |
| Máx. 2 leituras de PDF simultâneas, 10 s de parede cada, a 3ª espera até 10 s e é recusada (422/415); OCR 1 por vez, 40 s; ≤20 páginas, 60 mil caracteres, bomba >50:1 | `leitura_pdf.py:31-75`, `docs/runbook.md:493` |
| Upload: 10 MB (certidão, nota, evidência); 40 MB (pacote, peças); 25 MB (xlsx, .eml); 1 MB (assinatura) | `arquivos.py:24`, `pdfs.py:11`, `api_protocolos.py:19`, `notas_envio.py:15`, `correio.py:30` |
| Lockout: 5 senhas erradas seguidas bloqueiam 15 min; no bloqueio o contador volta a 0; tentativa durante o bloqueio não conta; e-mail inexistente/bloqueado gasta o mesmo tempo; sessão 12 h | `auth.py:11-13`, `auth.py:43-71` |
| Senha ≥ 10 caracteres; sem reset pela tela | `api_usuarios.py:42-43`, `docs/runbook.md:54` |
| Admin não se desativa nem tira o próprio perfil | `api_usuarios.py:66-70` |
| Valor protocolado congela no 1º protocolo; atestado segue editável (glosa) exceto cancelada/desistida | `medicoes.py:1-5`, `medicoes.py:103-115` |
| Medição do espelho tem o valor da regra (não se edita à mão) | `MedicaoAtos.tsx:22-29` (só cliente) |
| Protocolo com certidão pendente é travado, salvo "apesar das pendências" + justificativa (auditada) | `medicoes.py:148-179` |
| Certidão "vencendo" não impede protocolo | `checklist.py:13-15` |
| Envio da nota: aviso com certidão a <15 dias; bloqueio com vencida (D8) | `notas_envio.py:13`, `protocolo.py:556-558`, `mapeamento...:161` |
| SINFRA e Pref. VG juntam medição+reajuste no mesmo e-mail; MTPAR e SES separam (D9) | `mapeamento...:162`, `notas_envio.py:200-201` |
| MTPAR: registrar só o nº do SIGA (D10) | `mapeamento...:163`, `notas_envio.py:374-387` |
| Certidões no zip: as 5, sem falência (D7) | `mapeamento...:160` |
| Ofício repetido é aviso (pendência), não trava | `oficios.py:30-31`, `protocolo.py:500-503`, `docs/runbook.md:272` |
| Conferência do assinado é aviso, não trava | `docs/runbook.md:284` |
| Nota conferida ao centavo; diferença ≤1 centavo num tributo = "arredondamento"; valor bruto, município, tomador = "divergente" | `notas.py:96-113`, `docs/runbook.md:175` |
| Nota protocolada ausente do RM há 5 dias = aviso | `notas.py:15`, `notas.py:356-368` |
| Envio por fora: data não pode ser futura; observação obrigatória | `notas_envio.py:293-301` |
| Gerar espelho de novo = versão nova; a anterior fica `substituido` com motivo; não depois de protocolada | `espelhos.py:1-6`, `medicoes.py:279-281`, `docs/runbook.md:107` |
| Espelho: período tem de tocar o mês da competência, ≤1 ano | `espelhos.py:36-59` |
| Teto de valor do espelho R$ 99.999.999.999,99 | `espelho.py:41`, `espelho.py:278-279` |
| FRC: nº único por consórcio; soma bruto−INSS−IRRF−ISS = líquido | `frc.py:256-270` |
| Reajuste vale a partir do MÊS do aniversário; aviso 30 dias antes; ciclo fecha com o apostilamento | `reajuste.py:1-6`, `docs/reajuste-pleitos-2026-09-17.md:68` |
| Aditivo: novo = anterior + delta; datas novas posteriores; assinado congela | `aditivos.py:1-15` |
| Prazo: aviso a 60 dias, crítico a 30; instrumento assinado depois do fim da execução é "retroativo" e nunca recusado | `docs/runbook.md:354-362`, `docs/prazos-vigencia-execucao-2026-09-17.md:188` |
| Vigência = execução + 90 dias (recebimento definitivo) | `docs/prazos-vigencia-execucao-2026-09-17.md:127` |
| Medição final põe o contrato em encerramento; desmarcar exige motivo e só tira se nenhuma outra for final | `medicoes.py:466-502`, `docs/runbook.md:371` |
| Conclusão só com contrato em encerramento | `pleitos.py:108-110` |
| Contrato e medições guardam valor CHEIO; a cota é derivada | memória do projeto "Base cheia x cota" |
| Toda mutação + linha de auditoria no mesmo commit; auditoria append-only com cadeia verificável | `db.py:53-72`, `api_admin.py:10-17` |
| Dinheiro sempre em centavos inteiros; pt-BR só com vírgula decimal | `dinheiro.py:1-6`, `dinheiro.py:13-29` |
| CSV com BOM, `;`, CRLF e texto prefixado com `'` contra fórmula | `api_paineis.py:1-55` |

---

## 6. Pontos suspeitos (não provados)

| # | Suspeita | Onde | Como testar |
|---|---|---|---|
| S1 | **Envio duplicado por corrida**: as checagens de situação ficam fora de transação e o e-mail sai antes do UPDATE; dois POST simultâneos (duas abas, duplo clique fora da trava do botão, retry de rede) mandam **dois e-mails reais** e registram dois envios | `protocolo.py:765-819`, `espelhos.py:249-279`, `pleitos.py:347-373` | dois POST paralelos em `/api/protocolos/envio`, `/api/notas/envio/{pid}/enviar`, `/api/espelhos/{id}/enviar`, `/api/pleitos/{pid}/enviar` (com simulador `DASH_GRAPH_SIMULADOR`) |
| S2 | **Ids acima de 2^63-1 → 500** nas rotas sem teto | `api_medicoes.py:75-87` (todas as rotas de medição e as de notas/FRC que reusam `_medicao_existe`), `api_contratos.py:13`, `api_cronograma.py:50`, `api_paineis.py:58`, `api_aditivos.py:18`, `api_inicio.py:30` (`contrato_id`), `api_documentos.py:159` (`entidade_id`), `api_usuarios.py:71` | GET `/api/medicoes/9223372036854775808`, `/api/contratos/99999999999999999999` |
| S3 | **Nota manual sem teto int64** → 500 no INSERT | `api_notas.py:73-75` | POST `/notas/manual` com `valor="99999999999999999999,00"` |
| S4 | **Atalhos de etapa só barrados no cliente**: protocolo manual a partir de `prevista`/`espelho_*` (pula nota e envio); editar o protocolado de medição nascida do espelho; cronograma por API sem tela; envio por fora contorna o bloqueio de certidão vencida (D8) | `medicoes.py:184-187`, `medicoes.py:91-141`, `api_cronograma.py:75-76`, `notas_envio.py:317-319` | chamar as rotas direto com sessão de engenharia |
| S5 | **Cco silenciosamente descartado** no envio da nota (UI tem o campo, API não aceita) | `api_notas_envio.py:24-29`, `EnviarNota.tsx:208` | preencher Cco em "Enviar a nota" e conferir o e-mail simulado |
| S6 | **Lockout contornável por concorrência**: lê `tentativas_falhas` e grava `+1` sem condição; N tentativas paralelas gravam o mesmo valor → mais de 5 senhas por janela; senha sem teto de tamanho (não autenticado) | `auth.py:43-56`, `api_auth.py:43` | 20 POST `/api/auth/login` paralelos com senha errada; senha de 5 MB |
| S7 | **Esgotamento do pool de threads**: cada leitura de PDF segura uma thread do uvicorn até 10 s esperando vaga + 10 s lendo; ~40 uploads simultâneos param o site inteiro; a regularidade abre subprocesso antes de checar tipo | `leitura_pdf.py:630`, `api_documentos.py:115-117` | 40+ uploads paralelos de PDF lento; medir `/api/health` |
| S8 | **Envio por fora mistura contratos** e aceita lista sem teto | `api_notas_envio.py:83-90`, `notas_envio.py:288-309` | `medicao_ids` de duas obras diferentes |
| S9 | **Certidão manual com validade em 2099** fica vigente e destrava protocolos; emissão futura aceita | `documentos.py:252-276`, `api_documentos.py:84-89` | PDF sem texto + validade 2099-12-31 |
| S10 | Link de OneDrive aceita **qualquer domínio https** e vira `<a href>` no e-mail oficial ao órgão | `protocolo.py:234`, `protocolo.py:747-755` | `url=https://exemplo-malicioso.test/x` |
| S11 | `.eml` sem validação, servido depois com `media_type` DOCX; anexar a medição cancelada; evidência aceita em medição cancelada | `notas_envio.py:311-325`, `api_espelhos.py:203`, `api_espelhos.py:159-185` | subir HTML/EXE como .eml e baixar |
| S12 | Desmarcar/marcar final: cancelar a medição final não tira o contrato do encerramento; marcar duas vezes regrava `final_em` | `medicoes.py:466-480` | marcar final, cancelar a medição, ver contrato |
| S13 | `$search` do Graph com aspas do usuário sem escape | `correio.py:312`, `correio.py:318` | `q=a" OR "x` em `/api/correio/contatos` |
| S14 | Regex com `\d` aceita dígito Unicode (competência da regularidade, `data_base_mes`, `parse_brl`) | `api_documentos.py:110`, `api_pleitos.py:23`, `dinheiro.py:16` | `competencia=٢٠٢٦-٠٨`, `valor=١٢٣,٤٥` |
| S15 | Logout sem CSRF (mitigado por `samesite=strict`); `/api/health` aberto mostra texto de exceção do backup | `api_auth.py:74-86`, `main.py:53-70`, `backup.py:197,212` | GET `/api/health` sem cookie |
| S16 | Diretoria vê e clica em botões de escrita em Enviar nota, Aguardando pagamento e `/conta` (403 do servidor, mensagem crua) | `NotasAEnviar.tsx`, `EnviarNota.tsx`, `AguardandoPagamento.tsx` (sem `podeEditar`) | navegar logado como diretoria |
| S17 | Número do órgão: enviar vazio apaga o já gravado, sem confirmação | `protocolo.py:829`, `notas_envio.py:383-385` | POST `numero=""` após gravar um número |
| S18 | Peça PDF só com `%PDF-` vai solta ao órgão sem nunca ser aberta (nota SINFRA); `.xlsx` aceita qualquer zip renomeado | `api_protocolos.py:111-116`, `arquivos.py:83-90` | peça `%PDF-lixo`, `.docx` renomeado para `.xlsx` |
| S19 | Usuário com e-mail sem formato e nome vazio; senha gigante (argon2 sobre MBs) | `api_usuarios.py:17-21`, `api_usuarios.py:40-56` | POST `/api/admin/usuarios` com `email="x"`, `nome=""` |

Sem achados de: concatenação de SQL com entrada do cliente (todo f-string de SQL usa nomes fixos ou placeholders; `api_usuarios.py:84` e `medicoes.py:131` montam coluna só a partir de Literal/lista fixa); `dangerouslySetInnerHTML` no frontend; texto de usuário em HTML de e-mail sem escape (`espelhos.py:245`, `protocolo.py:750-755`, `pleitos.py:343-344` escapam; a assinatura é só PNG/JPG); texto do usuário entrando em `str.format` (o corpo da carta não passa por `carta.preencher`).
