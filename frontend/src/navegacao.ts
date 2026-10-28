import type { Rota } from "./rota";

// Menu e entrada por perfil (NAVEGACAO.md › Perfis e tela de entrada; Menu principal). Funcoes puras: o App
// so' desenha o que sai daqui.
//
// Trilho de icones (09/10/2026, prototipo aprovado pelo Leo): uma lista so', sem rotulos de grupo, na ordem do
// trabalho. Cada perfil ve o recorte dele. As Notas (A enviar, Aguardando pagamento) sairam do menu: viraram abas
// de Medicoes. Os Avisos moram dentro de Obras (redesenho #159): o item e a rota /avisos continuam, e o App os leva
// para "Obras" com os Avisos abertos.

export type Perfil = "engenharia" | "diretoria" | "admin";
export type ItemMenu = "inicio" | "medicoes" | "obras" | "avisos" | "siga" | "documentos" | "a-receber" | "carteira" | "admin";

export const ROTULO: Record<ItemMenu, string> = {
  inicio: "Início", medicoes: "Medições", obras: "Obras", avisos: "Avisos", siga: "SIGA", documentos: "Documentos", "a-receber": "A receber",
  carteira: "Carteira", admin: "Administração",
};

// Ordem do trilho.
const ORDEM: readonly ItemMenu[] = ["inicio", "medicoes", "obras", "avisos", "siga", "documentos", "a-receber", "carteira", "admin"];

// Decisao 3 do mapa: a diretoria sem Medicoes no menu (a rota continua abrindo), e a engenharia com A receber.
// O Inicio voltou (decisao do Leonardo, 08/10/2026): e' a entrada de todos os perfis, no alto do menu.
const DO_PERFIL: Record<Perfil, readonly ItemMenu[]> = {
  engenharia: ["inicio", "medicoes", "avisos", "siga", "documentos", "obras", "a-receber"],
  diretoria: ["inicio", "carteira", "avisos", "documentos", "obras", "a-receber"],
  admin: ["inicio", "medicoes", "avisos", "siga", "documentos", "obras", "a-receber", "carteira", "admin"],
};

function perfilDe(p: string): Perfil {
  return p === "diretoria" || p === "admin" ? p : "engenharia";
}

/** Tela de entrada do perfil: "/" e caminho desconhecido levam a ela. O Inicio, para todos (08/10/2026). */
export function entradaDe(_perfil: string): Rota {
  return { tela: "inicio" };
}

/** Os itens do trilho do perfil, na ordem do trilho. */
export function menuDe(perfil: string): ItemMenu[] {
  const meus = new Set(DO_PERFIL[perfilDe(perfil)]);
  return ORDEM.filter(i => meus.has(i));
}

/** Todo item do menu e' uma tela sem parametro. */
export function rotaDoItem(i: ItemMenu): Rota {
  return { tela: i } as Rota;
}

/** O item do menu que fica marcado: a tela e tudo abaixo dela na hierarquia (Obras na obra; Medicoes na medicao,
 *  na nova medicao e no envio da nota, que nasce da aba Enviar nota). */
export function itemDe(r: Rota, busca: Record<string, string> = {}): ItemMenu | "conta" | null {
  switch (r.tela) {
    case "raiz": return null;
    // os Avisos moram em Obras (?avisos=1): com eles abertos, o item aceso e' o dos Avisos
    case "obras": return busca.avisos === "1" ? "avisos" : "obras";
    case "obra": return "obras";
    case "documentos-empresa": return "documentos";
    case "medicao": case "nova-medicao": case "notas-envio": return "medicoes";
    default: return r.tela;
  }
}

/** Nome da tela, como o menu e o titulo da aba do navegador dizem. */
export function tituloDe(tela: Rota["tela"]): string {
  switch (tela) {
    case "raiz": return "grupolotufo";
    case "obra": return "Obra";
    case "documentos-empresa": return "Documentos";
    case "medicao": return "Medição";
    case "nova-medicao": return "Nova medição";
    case "inicio": return "Início";
    case "conta": return "Minha conta";
    case "notas-envio": return "Enviar a nota";
    default: return ROTULO[tela];
  }
}

/** Titulo da barra superior: o nome da SECAO (o item aceso do trilho), nao o do objeto. Na obra "Obras", na medicao
 *  "Medições"; o objeto (MT-388, 14ª Medição) e' o titulo da propria pagina, logo abaixo. */
export function tituloDaSecao(r: Rota): string {
  const item = itemDe(r);
  return item === null ? tituloDe(r.tela) : item === "conta" ? tituloDe("conta") : ROTULO[item];
}

/** O perfil por extenso, como a tela de Usuarios escreve (F-51): "admin" cru nao aparece na interface. */
const ROTULO_PERFIL: Record<string, string> = { engenharia: "Engenharia", diretoria: "Diretoria", admin: "Administrador" };
export function rotuloPerfil(perfil: string): string { return ROTULO_PERFIL[perfil] ?? perfil; }
