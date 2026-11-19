import type { AbaContratante, AbaDocumentos, AbaFechamento, Busca, PaginaDocumentos, Rota } from "./rota";

// Menu, entrada e caminho por perfil. Funcoes puras: a casca (Casca.tsx, Caminho.tsx) so' desenha o que sai daqui.
//
// MENU EM AREAS (decisao do dono de 18/11/2026, #805; issue #814): o menu tem areas, cada uma com o nome escrito e as
// paginas dentro, na ordem Painel, Medicoes, Obras, Financeiro, Prazos e avisos, Orgaos, Documentos e Sistema. Esta
// decisao SUBSTITUI a de 09/10/2026 (o "trilho de icones": uma lista so', sem rotulos de grupo), que valeu ate' aqui.
// Continuam valendo: cada perfil ve o recorte dele (DO_PERFIL); as Notas nao estao no menu (sao da pagina da
// medicao); os Avisos tem pagina propria ("/avisos"). Custos entra na area Financeiro quando a #804 tiver dado.
//
// CAMINHO (a mesma decisao): toda pagina diz no alto onde se esta', da area ate' o objeto, cada trecho um link
// ("Obras › SINFRA › MT-388 › Medições › 15ª Medição"). `trechosDe` monta o caminho de qualquer rota; o nome do
// objeto (obra, contratante, medicao, empresa, processo) vem da pagina que ja' o tem carregado (nomesDoCaminho.ts).

export type Perfil = "engenharia" | "diretoria" | "admin";

/** As paginas do menu. */
export type ItemMenu = "inicio" | "medicoes" | "resumo-medicoes" | "obras" | "fechamento" | "a-receber" | "avisos" | "siga"
  | "certidoes" | "regularidade" | "garantias" | "ancoras-docusign" | "admin" | "conta";
export type IdArea = "painel" | "medicoes" | "obras" | "financeiro" | "prazos" | "orgaos" | "documentos" | "sistema";

export const ROTULO: Record<ItemMenu, string> = {
  inicio: "Início", medicoes: "Medições", "resumo-medicoes": "Resumo das medições", obras: "Obras", fechamento: "Fechamento",
  "a-receber": "Em aberto", avisos: "Avisos", siga: "SIGA", certidoes: "Certidões", regularidade: "Regularidade mensal",
  garantias: "Garantias", "ancoras-docusign": "Âncoras DocuSign", admin: "Administração", conta: "Minha conta",
};

export type Area = { id: IdArea; rotulo: string; paginas: readonly ItemMenu[] };

/** As areas, na ordem do menu, cada uma com as paginas dela. */
export const AREAS: readonly Area[] = [
  { id: "painel", rotulo: "Painel", paginas: ["inicio"] },
  { id: "medicoes", rotulo: "Medições", paginas: ["medicoes", "resumo-medicoes"] },
  { id: "obras", rotulo: "Obras", paginas: ["obras"] },
  { id: "financeiro", rotulo: "Financeiro", paginas: ["fechamento", "a-receber"] },
  { id: "prazos", rotulo: "Prazos e avisos", paginas: ["avisos"] },
  { id: "orgaos", rotulo: "Órgãos", paginas: ["siga"] },
  { id: "documentos", rotulo: "Documentos", paginas: ["certidoes", "regularidade", "garantias"] },
  { id: "sistema", rotulo: "Sistema", paginas: ["ancoras-docusign", "admin", "conta"] },
];

// O RECORTE de cada perfil, o mesmo de antes do menu em areas: nenhuma permissao mudou com ele (#814).
// Medicoes (#643): um item so' no menu, que abre a fila de trabalho.
// Decisao 3 do mapa: a diretoria sem Medicoes no menu (a rota continua abrindo). #748: o Fechamento para todos os perfis.
// #749: o Resumo das medicoes (so' leitura: a etapa da medicao de cada obra na competencia) para todos os perfis; a
// diretoria continua sem o item Medicoes, que e' a tela de quem opera.
// O Inicio voltou (decisao do dono, 08/10/2026): e' a entrada de todos os perfis, no alto do menu.
type Recorte = "inicio" | "medicoes" | "resumo-medicoes" | "obras" | "avisos" | "siga" | "documentos" | "fechamento" | "ancoras-docusign" | "admin";
const DO_PERFIL: Record<Perfil, readonly Recorte[]> = {
  engenharia: ["inicio", "medicoes", "resumo-medicoes", "avisos", "siga", "documentos", "obras", "fechamento", "ancoras-docusign"],
  diretoria: ["inicio", "resumo-medicoes", "avisos", "documentos", "obras", "fechamento"],
  admin: ["inicio", "medicoes", "resumo-medicoes", "avisos", "siga", "documentos", "obras", "fechamento", "ancoras-docusign", "admin"],
};
// De que recorte cada pagina depende. As paginas que nasceram com as areas herdam o de uma tela que o perfil ja' via:
// Em aberto (ate' 19/11/2026, "A receber") e' de quem ve o Fechamento (o em aberto nota a nota morava no fim dele); Certidoes, Regularidade mensal e
// Garantias eram as tres abas de Documentos; a Minha conta sempre foi de todos (pelo avatar do topo).
const RECORTE_DA_PAGINA: Record<ItemMenu, Recorte | null> = {
  inicio: "inicio", medicoes: "medicoes", "resumo-medicoes": "resumo-medicoes", obras: "obras", fechamento: "fechamento",
  "a-receber": "fechamento", avisos: "avisos", siga: "siga", certidoes: "documentos", regularidade: "documentos",
  garantias: "documentos", "ancoras-docusign": "ancoras-docusign", admin: "admin", conta: null,
};

function perfilDe(p: string): Perfil {
  return p === "diretoria" || p === "admin" ? p : "engenharia";
}

/** Tela de entrada do perfil: "/" e caminho desconhecido levam a ela. O Inicio, para todos (08/10/2026). */
export function entradaDe(_perfil: string): Rota {
  return { tela: "inicio" };
}

/** O perfil tem a pagina no menu? */
export function temPagina(perfil: string, i: ItemMenu): boolean {
  const recorte = RECORTE_DA_PAGINA[i];
  return recorte === null || DO_PERFIL[perfilDe(perfil)].includes(recorte);
}

/** O menu do perfil: as areas, na ordem, cada uma com as paginas que o perfil ve. Area sem pagina nao aparece. */
export function menuDe(perfil: string): Area[] {
  return AREAS.map(a => ({ ...a, paginas: a.paginas.filter(i => temPagina(perfil, i)) })).filter(a => a.paginas.length > 0);
}

/** As paginas do menu do perfil, em fila, na ordem do menu. */
export function paginasDe(perfil: string): ItemMenu[] {
  return menuDe(perfil).flatMap(a => a.paginas);
}

/** A area que so' tem uma pagina, com o mesmo nome dela (Obras): no menu e no caminho aparece uma vez so'. */
export function areaEhAPagina(a: Area): boolean {
  return a.paginas.length === 1 && ROTULO[a.paginas[0]] === a.rotulo;
}

const PAGINA_DOCUMENTOS: Record<PaginaDocumentos, ItemMenu> = { certidoes: "certidoes", regularidade: "regularidade", garantias: "garantias" };
// a aba da pagina da empresa e a pagina de Documentos que trata do mesmo assunto
const PAGINA_DA_ABA_DA_EMPRESA: Record<AbaDocumentos, PaginaDocumentos> = { certidoes: "certidoes", regularidade: "regularidade", garantia: "garantias" };

/** O endereco de cada pagina do menu. */
export function rotaDoItem(i: ItemMenu): Rota {
  switch (i) {
    case "certidoes": return { tela: "documentos" };
    case "regularidade": return { tela: "documentos", pagina: "regularidade" };
    case "garantias": return { tela: "documentos", pagina: "garantias" };
    default: return { tela: i };
  }
}

/** A pagina do menu que fica acesa: a propria tela e tudo abaixo dela (Obras no contratante e na obra; a pagina de
 *  Documentos na empresa, pela aba). A medicao, a nova medicao e o envio da nota sao da area Medicoes, de quem opera;
 *  para o perfil sem Medicoes no menu (a diretoria), a medicao acende Obras, por onde ele chega a ela. */
export function itemDe(r: Rota, perfil?: string): ItemMenu | null {
  switch (r.tela) {
    case "raiz": return null;
    case "obra": case "contratante": return "obras";
    case "documentos": return PAGINA_DOCUMENTOS[r.pagina ?? "certidoes"];
    case "documentos-empresa": return PAGINA_DOCUMENTOS[PAGINA_DA_ABA_DA_EMPRESA[r.aba ?? "certidoes"]];
    case "medicao": case "nova-medicao": return perfil !== undefined && !temPagina(perfil, "medicoes") ? "obras" : "medicoes";
    case "notas-envio": return "medicoes";
    default: return r.tela;
  }
}

/** A area da pagina acesa. */
export function areaDe(r: Rota, perfil?: string): IdArea | null {
  const item = itemDe(r, perfil);
  return item === null ? null : AREAS.find(a => a.paginas.includes(item))?.id ?? null;
}

/** Nome da tela, como o menu e o titulo da aba do navegador dizem. */
export function tituloDe(tela: Rota["tela"]): string {
  switch (tela) {
    case "raiz": return "grupolotufo";
    case "obra": return "Obra";
    case "documentos": case "documentos-empresa": return "Documentos";
    case "medicao": return "Medição";
    case "nova-medicao": return "Nova medição";
    case "notas-envio": return "Enviar a nota";
    case "contratante": return "Obras";
    default: return ROTULO[tela];
  }
}

/* ------------------------------------------------------------------ caminho */

/** Um trecho do caminho. `para` e' o endereco dele (com a `busca`, quando o trecho guarda filtro); `titulo` marca o
 *  trecho da pagina ou do objeto em que se esta', que a barra do topo escreve como titulo; depois dele so' vem a
 *  vista (a aba). `area` marca o trecho que e' so' a area: ele leva a' primeira pagina dela. */
export type Trecho = { rotulo: string; para?: Rota; busca?: Busca; titulo?: boolean; area?: boolean };

/** Os nomes que so' a pagina sabe, porque ja' carregou o objeto. Sem eles o trecho sai com o nome do tipo ("Obra"). */
export type NomesDoCaminho = {
  contratante?: { nome: string; chave?: string | null } | null;
  obra?: string | null;
  medicao?: string | null;
  empresa?: string | null;
  processo?: string | null;
  /** o nome da vista que sai do dado: a comparacao do Fechamento se chama pelos dois anos que o servidor manda
   *  ("2026 × 2025"). So' vale na rota dessa vista (`vistaDe`). */
  vista?: string | null;
};

// As vistas (abas) que entram no caminho como ultimo trecho. A vista padrao de cada pagina nao entra, como nao entra na
// URL. Os nomes sao os das abas de cada pagina.
const VISTAS_DE_MEDICOES: Record<string, string> = { quadro: "Quadro do mês", anteriores: "Meses anteriores" };
const VISTAS_DE_OBRAS: Record<string, string> = { todas: "Todas as obras", andamento: "Andamento", qdop: "QDOP" };
const ABAS_DA_OBRA: Record<string, string> = { medicoes: "Medições", prazos: "Prazos", reajuste: "Reajuste", documentos: "Documentos", contrato: "Contrato" };
const ABAS_DO_CONTRATANTE: Record<Exclude<AbaContratante, "obras">, string> = {
  medicoes: "Medições", "a-receber": "Em aberto", siga: "Processos no SIGA", avisos: "Avisos",
};
const ABAS_DA_ADMINISTRACAO: Record<string, string> = {
  reconciliacao: "Reconciliação", usuarios: "Usuários", auditoria: "Auditoria", pendencias: "Pendências de cadastro",
};
// A aba de comparacao do Fechamento se chama pelos anos que o servidor manda ("2026 × 2025"): a pagina publica o nome
// (`NomesDoCaminho.vista`) quando o dado chega; ate' la', e se a leitura falhar, o caminho diz "Comparação".
const VISTAS_DO_FECHAMENTO: Record<Exclude<AbaFechamento, "meses">, string> = { comparacao: "Comparação", contratantes: "Por contratante" };

/** O nome da vista da rota, quando ela nao e' a padrao: e' o ultimo trecho do caminho e entra no titulo da aba do
 *  navegador ("Obras · QDOP"). `nomes.vista`: o nome que a pagina publicou, para a vista que se chama pelo dado. */
export function vistaDe(r: Rota, nomes: NomesDoCaminho = {}): string | undefined {
  switch (r.tela) {
    case "medicoes": return r.aba ? VISTAS_DE_MEDICOES[r.aba] : undefined;
    case "obras": return r.aba ? VISTAS_DE_OBRAS[r.aba] : undefined;
    case "obra": return ABAS_DA_OBRA[r.aba];
    case "contratante": return r.aba && r.aba !== "obras" ? ABAS_DO_CONTRATANTE[r.aba] : undefined;
    case "admin": return r.aba ? ABAS_DA_ADMINISTRACAO[r.aba] : undefined;
    case "fechamento":
      if (r.aba === "comparacao") return nomes.vista || VISTAS_DO_FECHAMENTO.comparacao;
      return r.aba === "contratantes" ? VISTAS_DO_FECHAMENTO.contratantes : undefined;
    default: return undefined;
  }
}

/** O caminho da rota, da area ate' onde se esta'. O ultimo trecho e' onde se esta'; os de antes sao links.
 *  - A area leva a' primeira pagina dela no menu do perfil; a area que e' a propria pagina (Obras; Medicoes na
 *    pagina Medicoes) aparece uma vez so'.
 *  - A medicao fica dentro da obra, que fica dentro do contratante: "Obras › SINFRA › MT-388 › Medições › 15ª Medição".
 *  - `busca` so' serve ao historico do SIGA: o processo aberto vai na busca (?processo=7), e o trecho "SIGA" volta
 *    para a categoria de onde se veio. */
export function trechosDe(r: Rota, opcoes: { perfil?: string; nomes?: NomesDoCaminho; busca?: Busca } = {}): Trecho[] {
  const { perfil = "admin", nomes = {}, busca = {} } = opcoes;
  if (r.tela === "raiz") return [];
  const vista = vistaDe(r, nomes);
  const fim: Trecho[] = vista ? [{ rotulo: vista, para: r }] : [];

  // os tres niveis de Obras, comuns ao contratante, a' obra e a' medicao
  const obras: Trecho = { rotulo: ROTULO.obras, para: { tela: "obras" } };
  // a obra sem orgao no cadastro nao tem contratante (o trecho nao aparece); o orgao sem chave, so' o nome, sem link
  const contratante = (): Trecho[] => nomes.contratante?.nome
    ? [{ rotulo: nomes.contratante.nome, para: nomes.contratante.chave ? { tela: "contratante", chave: nomes.contratante.chave } : undefined }]
    : [];
  switch (r.tela) {
    case "contratante":
      return [obras, { rotulo: nomes.contratante?.nome ?? "Contratante", para: { tela: "contratante", chave: r.chave }, titulo: true }, ...fim];
    case "obra":
      return [obras, ...contratante(), { rotulo: nomes.obra ?? "Obra", para: { tela: "obra", id: r.id, aba: "ficha" }, titulo: true }, ...fim];
    case "medicao": case "nova-medicao":
      return [obras, ...contratante(), { rotulo: nomes.obra ?? "Obra", para: { tela: "obra", id: r.obra, aba: "ficha" } },
        { rotulo: ABAS_DA_OBRA.medicoes, para: { tela: "obra", id: r.obra, aba: "medicoes" } },
        { rotulo: nomes.medicao ?? tituloDe(r.tela), para: r, titulo: true }];
    default: break;
  }

  // as outras: a area, a pagina do menu e o que houver abaixo dela
  const item = itemDe(r) as ItemMenu;
  const area = AREAS.find(a => a.paginas.includes(item))!;
  const pagina: Trecho = { rotulo: ROTULO[item], para: rotaDoItem(item) };
  const inicio: Trecho[] = [];
  if (area.rotulo !== ROTULO[item]) {
    const primeira = area.paginas.find(i => temPagina(perfil, i));
    inicio.push({ rotulo: area.rotulo, para: primeira ? rotaDoItem(primeira) : undefined, area: true });
  }
  if (r.tela === "notas-envio") return [...inicio, pagina, { rotulo: tituloDe("notas-envio"), para: r, titulo: true }];
  if (r.tela === "documentos-empresa") return [...inicio, pagina, { rotulo: nomes.empresa ?? "Empresa", para: r, titulo: true }];
  if (r.tela === "siga" && /^\d+$/.test(busca.processo ?? "")) {
    const { processo: _processo, ...resto } = busca;
    return [...inicio, { ...pagina, busca: resto }, { rotulo: nomes.processo ?? "Processo", para: r, busca, titulo: true }];
  }
  return [...inicio, { ...pagina, titulo: true }, ...fim];
}

/** O perfil por extenso, como a tela de Usuarios escreve (F-51): "admin" cru nao aparece na interface. */
const ROTULO_PERFIL: Record<string, string> = { engenharia: "Engenharia", diretoria: "Diretoria", admin: "Administrador" };
export function rotuloPerfil(perfil: string): string { return ROTULO_PERFIL[perfil] ?? perfil; }
