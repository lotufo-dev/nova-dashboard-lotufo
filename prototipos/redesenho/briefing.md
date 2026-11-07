# Briefing comum do redesenho (#150)

Vale para toda geração de tela no Higgsfield e para a crítica de cada opção. Cada tela soma a este briefing o
seu próprio (seção "Por tela", abaixo). Imagens com dados fictícios: nada de obra, órgão, pessoa, CNPJ ou valor
real; os nomes de exemplo abaixo já são os usados nos protótipos aprovados.

## O produto, em uma frase para o gerador

Sistema web interno de uma construtora para acompanhar contratos de obras públicas e o ciclo da medição
(espelho, faturamento, nota, envio ao órgão, pagamento). Quem usa confere mais do que digita: a tela mostra
o que está pronto, o que falta e o próximo passo.

## Identidade (resumo de `docs/identidade-visual.md`)

- **Ideia:** livro-razão — "cada valor no seu lugar". Claro, dados em primeiro plano, espírito Stripe.
- **Cor da marca:** só o índigo `#4F46E5` (botão principal, link, item ativo, barra de progresso), com a tinta
  clara `#EEF0FF` para hover e selecionado.
- **Neutros:** fundo `#F6F8FB`, superfície branca, texto `#0F172A`, secundário `#64748B`, linhas `#E2E8F0`.
- **Regra de cor da informação (06/11/2026):** número e data pretos por padrão; verde `#10B981` = feito ou
  recebido, azul `#3B82F6` = em andamento, âmbar `#F59E0B` = vence em breve ou faltando, vermelho `#EF4444` =
  crítico, vencido ou sem registro; o que não é urgente fica preto. A cor é da informação, nunca do desenho da
  página. Legenda pequena no topo direito: "feito · em andamento · vence em breve · crítico". Pílula = fundo
  tingido claro + ponto colorido + texto escuro. Detalhe em `docs/identidade-visual.md`.
- **Tipo (06/11/2026):** uma fonte geométrica arredondada e larga (Lexend), títulos e valores em negrito; valores
  em reais na MESMA fonte do texto, alinhados à direita, algarismos tabulares. Escala 12 / 14 / 16 / 24 / 32–40.
- **Menu lateral largo:** ícone e nome em cada item, item ativo em pílula branca, recolhível.
- **Telas aprovadas:** as imagens têm dado real e ficam no repositório privado `lotufo-cadastro`, pasta `telas/`
  (`~/dev/lotufo-cadastro/telas` no Mac; `C:\DashboardLotufo\cadastro\telas` no servidor); o `README.md` de lá
  explica. Trate a imagem como a fonte.
- **Forma:** raio 8 em cartão e botão, 10 em janela e menu, 999 em pílula; sombra suave; base de 8 px,
  16–24 px entre cartões. Página sem sombra nem raio.
- **Tabela é o elemento principal** onde há lista de valores: cabeçalho 12 px cinza, linhas de 44 px, um ponto
  colorido por situação.
- **Modo claro só.** Sem modo escuro.

## Referências aprovadas (mandar junto em toda geração)

| Ref. | O que é | Onde está |
|---|---|---|
| R1 | Medições › Resumo, menu lateral e barra superior (em produção) | `prototipos/medicoes-opcoes/1-resumo-cartoes.png` (fora do git) |
| R2 | Iniciar processo de medição (imagem 5, 09/10/2026) | `prototipos/iniciar/imagem-5-aprovada-2026-10-09.png` |
| R3 | Fluxo da medição (imagem 6, 09/10/2026) | `prototipos/medicoes-opcoes/prototipo-v4/fluxo-da-medicao.png` (fora do git) |
| R4 | As cinco abas de Medições aprovadas em 14/10/2026 | `prototipos/` das abas (fora do git) |

As que estão fora do git ficam na máquina do Leo; antes de gerar um lote, elas são anexadas à sessão.

## Vocabulário de componentes que já existe (reaproveitar, não inventar)

Menu lateral e barra superior (R1) · cartão com valor grande · tabela com ponto de situação · pílula de
situação · abas com contagem · trilho de etapas com setas (R3) · janela (diálogo) com rodapé de ações (R2) ·
caixa de aviso âmbar com frase única · botão primário índigo, secundário com contorno · menu "Mais ações" ·
campo de competência MM/AAAA · busca no topo da lista · grupos recolhíveis por contratante.

## O que nunca entra

- Cores da marca Lotufo Engenharia, logotipo da empresa ou de órgão público.
- Gradiente, vidro fosco, brilho, ilustração 3D, ícone decorativo grande, emoji.
- Fontes de "cara de IA" (Inter genérica, script). Só a fonte geométrica arredondada aprovada (Lexend).
- Texto em inglês, lorem ipsum, código interno ou nome de campo do banco na tela.
- Cor de situação usada como enfeite; mais de um botão primário por área.
- Dado real (obra, órgão, pessoa, e-mail, CNPJ, valor).

## Dados de exemplo (inventados)

Contratantes "Secretaria de Obras", "Agência de Parcerias", "Prefeitura Municipal", "Secretaria de Saúde".
Obras "Ponte do Ribeirão", "Avenida das Palmeiras", "Terminal Norte", "Hospital Regional", "Parque Linear",
"Anel Viário Sul", "Escola Modelo", "Centro Esportivo". Competência no formato "09/2026"; medição "7ª";
valores "R$ 1.234.567,89" na fonte do texto, tabulares. Nada copiado do banco ou do cadastro.

## Como gerar

- Mesmo modelo e mesmas referências (R1–R4) para todas as telas de um lote, para as opções conversarem.
- Duas ou três opções por tela, a 1440 px; a opção escolhida ganha também a de 375 px.
- Prompt = este briefing (resumido) + o briefing da tela + as referências.
- Antes de ir ao Leo, a orquestradora critica o lote contra este arquivo e contra R1–R4; opção que destoa
  volta.
- Imagens salvas em `prototipos/<tela>/`; a escolha do Leo é registrada na issue da tela.

## Por tela

| Issue | Tela | O que o Leo precisa ver | Já decidido |
|---|---|---|---|
| #152 | Página da medição | Uma página "Nª Medição + Reajuste"; trilho de 5 etapas; só a atual aberta; "Mais ações" em menu; "Enviar a nota" ativo com o motivo ao lado (só bloqueio desabilita) | Imagem 6 aprovada; etapa feita abre no lugar da atual com faixa "Você está vendo a etapa N, já feita · Voltar à etapa atual"; nome da obra no caminho leva à página da obra; medição e reajuste num fluxo só (etapa 4 com um envio na SINFRA/Pref. VG e dois lado a lado na MTPAR/SES; etapa 5 com o pagamento de cada). Ajustes do envio vindos da #157: certidões com validade, uma linha por nota, pendências numa frase, botão no fim. Próximo passo: atualizar o protótipo v4, não gerar imagem nova. |
| #153 | Nova medição | Vira a etapa 1 (Espelho) da #152 | Não tem tela própria; sai junto com a #152. |
| #157 | Medições › Enviar nota | Lista da aba no padrão das abas aprovadas (R4) | Imagem nova para a lista; o envio entra na #152. |
| #159 | Obras (lista) com os Avisos | Acompanhamento: medido, acumulado, curva S, previsto; Avisos dentro de Obras | Feita depois de Medições; lote gerado numa sessão com o Leo (15/10). |
| #160 | Página da obra | Mesmo espírito de acompanhamento; hoje cinco abas (Medições, Prazos, Reajuste, Documentos, Contrato) | A medição mora sob Medições; lote junto com a #159. |
| #161 | Documentos | Certidões e documentos da empresa com validade e situação | Nada decidido. |
| #162 | A receber | Valores a receber por obra/contratante, mono e à direita | Nada decidido. |
| #163 | Carteira | Financeiro, curva S e cartões por contratante, com menos informação | Objetivos de 06/10/2026; hoje Resumo, QDOP e Produção. |
| #164 | Administração | Saúde, Reconciliação, Usuários e Auditoria | Nada decidido. |
| #165 | Minha conta | Conta e troca de senha | Minha conta e Sair ficam na barra superior (09/10/2026). |

Regra de todas: a tela nova não perde nenhuma ação nem número que alguém usa para decidir. Frase de apoio, legenda
sob número, explicação de regra e contador secundário não contam como dado e não passam para a tela nova
(`.claude/rules/texto-na-tela.md`, 26/10/2026).

### Leva de 06 e 07/11/2026 (telas aprovadas por imagem)

| Issue | Tela | Já decidido |
|---|---|---|
| #505 (base) | Fonte nova, regra de cor da informação, menu lateral largo | Feita nesta leva; as telas abaixo dependem dela. |
| #506 | Início | Imagem `telas/inicio/APROVADA-inicio-2026-11-06.png`. |
| #507 | Medições: menu, Iniciar medição com busca, Em andamento | Os dois subitens do menu (com contagem) entram aqui. |
| #508 | Medições: página da obra, fluxo único, passos 1 e 2 | |
| #514 | Medições: passos 3 a 6 (Espelhos, Notas, Envio da nota, Pagamento) | |
| #509 | Obras (lista), posição financeira | |
| #510 | Página da obra, ficha executiva | Aplica a regra de cor da informação. |
| #511 | Avisos, o que vence quando | |
| #512 | SIGA, tabela e histórico do processo | |
| #513 | Documentos, três abas com chips | |
