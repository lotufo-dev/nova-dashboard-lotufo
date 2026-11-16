// Roteiros das tarefas aprovadas (.ui-review/arquitetura/tarefas.md) no mapa aprovado (NAVEGACAO.md ›
// Caminhos das tarefas). São o teste de navegação da Fase C do /ui-architecture: scripts/ui-tasks/percorrer.mjs
// entra por "/" (confere a entrada do perfil), clica os passos e procura a resposta.
//
// Campos: perfil (quem entra; troca o /api/auth/eu das fixtures) · inicio (a entrada do perfil no mapa) ·
// passos (cada clique, com o seletor do Playwright) · resposta (um ou mais alvos: seletor e, se preciso, o
// texto que a resposta contém; cada alvo precisa aparecer) · cliques (o custo do NAVEGACAO.md; mais que isso
// é falha) · desde (a fatia que torna o caminho possível; antes dela a tarefa fica "pendente") ·
// manterRolagem (o link leva a uma seção: mede de onde a âncora deixou a página, porque essa rolagem a
// pessoa não faz) · base e proposto (rolagem até ver o fim da resposta, em alturas de tela por viewport, de
// custos-propostos.md: passar da base é regressão e falha; passar do proposto × 1,3 é aviso).
export const ENG = { id: 2, nome: "Engenheira", perfil: "engenharia" };
export const DIR = { id: 3, nome: "Diretoria", perfil: "diretoria" };
export const ADM = { id: 1, nome: "Admin Exemplo", perfil: "admin" };

// Entrada de cada perfil no mapa e a fatia que a põe no lugar (a engenharia e o admin entram pelo Início
// até a S6, quando a fila de Medições absorve os números do mês).
export const ENTRADA = { engenharia: { rota: "/medicoes", desde: 6 }, admin: { rota: "/medicoes", desde: 6 },
  diretoria: { rota: "/carteira", desde: 1 } };

const menu = nome => ({ clicar: `nav[aria-label="Navegação principal"] >> role=link[name=/^${nome}$/]`, rotulo: `menu ${nome}` });
// seção com título (<section aria-labelledby> ou aria-label): o nome acessível começa pelo título
const regiao = titulo => `role=region[name=/^${titulo}/]`;
const fila = regiao("Em andamento");
const r = (a, b) => ({ "1920x1080": a, "1366x768": b });

export const tarefas = [
  { id: "T01", perfil: ENG, inicio: "/medicoes", cliques: 0, desde: 6, base: r(1.1, 2.0), proposto: r(0, 0),
    resposta: { seletor: `${regiao("Avisos")} >> li`, texto: "Crítico" } },
  { id: "T01-todos", perfil: ENG, inicio: "/medicoes", cliques: 1, desde: 6, base: r(1.1, 2.0), proposto: r(0.3, 1.1),
    passos: [{ clicar: 'role=link[name=/^Ver todos os avisos/]', rotulo: "Ver todos os avisos" }],
    resposta: { seletor: "main tbody tr" } },
  { id: "T02", perfil: ENG, inicio: "/medicoes", cliques: 0, desde: 6, base: r(1.6, 2.7), proposto: r(0.2, 0.9),
    resposta: { seletor: `${fila} >> tbody tr` } },
  { id: "T02-abrir", perfil: ENG, inicio: "/medicoes", cliques: 1, desde: 6, manterRolagem: true, proposto: r(0, 0),
    // a primeira medicao da MT-388 na fila (a obra das fixtures): o custo e' o mesmo para qualquer linha
    passos: [{ clicar: `${fila} >> tr:has-text("MT-388") >> role=link[name=/ª Medição$/] >> nth=0`, rotulo: "primeira medição da MT-388 na fila" }],
    resposta: { seletor: "main h1", texto: /ª Medição/ } },
  { id: "T03", perfil: ENG, inicio: "/medicoes", cliques: 0, desde: 6, proposto: r(0.2, 0.8),
    resposta: { seletor: `${regiao("Protocolos de")} >> li` } },
  { id: "T04", perfil: ENG, inicio: "/medicoes", cliques: 1, desde: 6, manterRolagem: true, base: r(4.5, 7.1), proposto: r(0, 0),
    passos: [{ clicar: `${regiao("Protocolar")} >> tr:has-text("MT-388") >> role=link[name=/^23ª Medição$/]`, rotulo: "23ª no grupo Protocolar" }],
    resposta: { seletor: `${regiao("O que falta para protocolar")} >> li` } },
  { id: "T05", perfil: ENG, inicio: "/medicoes", cliques: 2, desde: 6, base: r(0, 0), proposto: r(0, 0),
    passos: [{ clicar: `${fila} >> tr:has-text("24ª Medição") >> role=link[name=/^MT-388$/]`, rotulo: "obra na linha da fila" },
             { clicar: 'main >> role=button[name=/^Gerar espelho$/]', rotulo: "Gerar espelho" }],
    resposta: { seletor: `${regiao("Nova medição")} >> role=form[name="Gerar espelho"] >> role=textbox` } },
  { id: "T06", perfil: ENG, inicio: "/medicoes", cliques: 1, desde: 6, manterRolagem: true, base: r(2.5, 4.1), proposto: r(0, 0),
    passos: [{ clicar: `${fila} >> tr:has-text("MT-388") >> role=link[name=/nota diverge/]`, rotulo: "marca nota diverge" }],
    resposta: [{ seletor: regiao("Notas"), texto: "diverge do espelho" }, { seletor: `${regiao("Notas")} >> role=button[name=/^Justificar/]` }] },
  { id: "T07", perfil: ENG, inicio: "/medicoes", cliques: 1, desde: 7, base: r(1.6, 2.7), proposto: r(0, 0.4),
    passos: [menu("Documentos")],
    resposta: { seletor: `${regiao("Certidões e regularidade")} >> td`, texto: /vence em|vencida|falta/ } },
  { id: "T08", perfil: ENG, inicio: "/medicoes", cliques: 1, desde: 1, base: r(2.1, 3.4), proposto: r(0, 0.8),
    passos: [menu("Documentos")],
    resposta: [{ seletor: "text=Escolher PDFs" }, { seletor: "role=button[name=/Anexar regularidade/]" }] },
  { id: "T09", perfil: ENG, inicio: "/medicoes", cliques: 2, desde: 6, manterRolagem: true, base: r(0, 0), proposto: r(0, 0),
    passos: [{ clicar: `${regiao("Avisos")} >> role=link[name=/^Reajuste/]`, rotulo: "Avisos › Reajuste" },
             { clicar: 'main >> role=link[name=/pleito da data-base 01\\/2023/]', rotulo: "aviso de apostilamento da MT-388" }],
    resposta: { seletor: regiao("Data-base 01\\/2023"), texto: "apostilamento pendente" } },
  { id: "T10-engenharia", perfil: ENG, inicio: "/medicoes", cliques: 2, desde: 8, proposto: r(0, 0),
    passos: [menu("Obras"), { clicar: 'main >> role=link[name=/^em 90 dias$/]', rotulo: "em 90 dias" }],
    resposta: { seletor: "main tbody tr" } },
  { id: "T10-diretoria", perfil: DIR, inicio: "/carteira", cliques: 1, desde: 10, proposto: r(0, 0),
    passos: [{ clicar: 'main >> role=link[name=/terminam em 90 dias/i]', rotulo: "Terminam em 90 dias" }],
    resposta: { seletor: "main tbody tr" } },
  { id: "T11-diretoria", perfil: DIR, inicio: "/carteira", cliques: 1, desde: 9, base: r(0, 0), proposto: r(0, 0),
    passos: [menu("A receber")],
    resposta: [{ seletor: `${regiao("Por órgão")} >> tbody tr` }, { seletor: `${regiao("Por órgão")} >> th`, texto: "31 a 60" }] },
  { id: "T11-engenharia", perfil: ENG, inicio: "/medicoes", cliques: 1, desde: 9, proposto: r(0, 0),
    passos: [menu("A receber")],
    resposta: [{ seletor: `${regiao("Por órgão")} >> tbody tr` }, { seletor: `${regiao("Por órgão")} >> th`, texto: "31 a 60" }] },
  { id: "T11-orgao", perfil: DIR, inicio: "/carteira", cliques: 2, desde: 9, proposto: r(0, 0.5),
    passos: [menu("A receber"), { clicar: `${regiao("Por órgão")} >> role=button[name=/^SINFRA - SUEF I$/]`, rotulo: "abrir a SINFRA - SUEF I" }],
    resposta: { seletor: `${regiao("Por órgão")} >> role=link[name=/^MT-388$/]` } },
  { id: "T12", perfil: DIR, inicio: "/carteira", cliques: 0, desde: 10, base: r(0, 0.3), proposto: r(0, 0),
    resposta: { seletor: `${regiao("O mês")} >> .kpi` } },
  { id: "T13", perfil: DIR, inicio: "/carteira", cliques: 0, desde: 10, base: r(2.1, 5.0), proposto: r(0, 0),
    resposta: { seletor: `${regiao("Obras com problema")} >> li` } },
  { id: "T13-obra", perfil: DIR, inicio: "/carteira", cliques: 1, desde: 10, proposto: r(0, 0),
    passos: [{ clicar: `${regiao("Obras com problema")} >> role=link >> nth=0`, rotulo: "a obra com problema" }],
    // o "por quê" da obra: os avisos dela (na diretoria, os motivos do farol), logo abaixo do resumo
    resposta: { seletor: `${regiao("Avisos desta obra")} >> li` } },
  { id: "T14", perfil: ADM, inicio: "/medicoes", cliques: 1, desde: 11, base: r(0, 0), proposto: r(0, 0),
    passos: [menu("Administração")],
    resposta: { seletor: regiao("TOTVS RM"), texto: /Última rodada.*(deu certo|falhou)/ } },
  { id: "T14-divergencias", perfil: ADM, inicio: "/medicoes", cliques: 2, desde: 11, base: r(6.1, 9.0), proposto: r(0, 0.5),
    passos: [menu("Administração"), { clicar: 'main >> role=link[name=/divergências de valor/]', rotulo: "divergências" }],
    resposta: { seletor: `${regiao("Divergências de valor")} >> tbody tr` } },
  { id: "T15", perfil: ADM, inicio: "/medicoes", cliques: 3, desde: 2, manterRolagem: true, proposto: r(0, 0),
    passos: [menu("Obras"), { clicar: 'main >> role=link[name=/^MT-388$/]', rotulo: "obra MT-388" },
             { clicar: 'main >> role=link[name=/^22ª Medição$/]', rotulo: "22ª Medição" }],
    resposta: { seletor: regiao("Protocolo"), texto: /enviado em .* por / } },
];
