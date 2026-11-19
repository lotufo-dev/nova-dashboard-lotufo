import { describe, expect, it } from "vitest";
import { areaDe, AREAS, areaEhAPagina, entradaDe, itemDe, menuDe, paginasDe, ROTULO, rotaDoItem, tituloDe, trechosDe, vistaDe,
  type ItemMenu, type Trecho } from "./navegacao";
import { caminhoDe, hrefDe, parseRota, type Rota } from "./rota";

const rotulos = (ts: Trecho[]) => ts.map(t => t.rotulo);
const enderecos = (ts: Trecho[]) => ts.map(t => (t.para ? hrefDe(t.para, t.busca) : null));

describe("navegação por perfil", () => {
  it("todo perfil entra pelo Início (08/10/2026)", () => {
    expect(entradaDe("diretoria")).toEqual({ tela: "inicio" });
    expect(entradaDe("engenharia")).toEqual({ tela: "inicio" });
    expect(entradaDe("admin")).toEqual({ tela: "inicio" });
  });

  it("o menu tem as oito áreas, na ordem, cada uma com as páginas dela (#814); Custos espera a #804", () => {
    expect(AREAS.map(a => [a.rotulo, a.paginas.map(i => ROTULO[i])])).toEqual([
      ["Painel", ["Início"]],
      ["Medições", ["Medições", "Resumo das medições"]],
      ["Obras", ["Obras"]],
      ["Financeiro", ["Fechamento", "Em aberto"]],
      ["Prazos e avisos", ["Avisos"]],
      ["Órgãos", ["SIGA"]],
      ["Documentos", ["Certidões", "Regularidade mensal", "Garantias"]],
      ["Sistema", ["Âncoras DocuSign", "Administração", "Minha conta"]],
    ]);
    // toda página do menu está em uma área, e só em uma
    const todas = AREAS.flatMap(a => a.paginas);
    expect([...todas].sort()).toEqual((Object.keys(ROTULO) as ItemMenu[]).sort());
    expect(new Set(todas).size).toBe(todas.length);
    // só Obras é a área que é a própria página: aparece uma vez, sem o nome repetido
    expect(AREAS.filter(areaEhAPagina).map(a => a.id)).toEqual(["obras"]);
  });

  it("cada perfil vê o recorte dele; área sem página do perfil não aparece", () => {
    const menu = (perfil: string) => menuDe(perfil).map(a => [a.rotulo, a.paginas]);
    expect(menu("admin")).toEqual([
      ["Painel", ["inicio"]], ["Medições", ["medicoes", "resumo-medicoes"]], ["Obras", ["obras"]],
      ["Financeiro", ["fechamento", "a-receber"]], ["Prazos e avisos", ["avisos"]], ["Órgãos", ["siga"]],
      ["Documentos", ["certidoes", "regularidade", "garantias"]], ["Sistema", ["ancoras-docusign", "admin", "conta"]],
    ]);
    expect(menu("engenharia")).toEqual([
      ["Painel", ["inicio"]], ["Medições", ["medicoes", "resumo-medicoes"]], ["Obras", ["obras"]],
      ["Financeiro", ["fechamento", "a-receber"]], ["Prazos e avisos", ["avisos"]], ["Órgãos", ["siga"]],
      ["Documentos", ["certidoes", "regularidade", "garantias"]], ["Sistema", ["ancoras-docusign", "conta"]],
    ]);
    // decisão 3: a diretoria sem Medições (a tela de quem opera); sem SIGA, sem Âncoras e sem Administração
    expect(menu("diretoria")).toEqual([
      ["Painel", ["inicio"]], ["Medições", ["resumo-medicoes"]], ["Obras", ["obras"]],
      ["Financeiro", ["fechamento", "a-receber"]], ["Prazos e avisos", ["avisos"]],
      ["Documentos", ["certidoes", "regularidade", "garantias"]], ["Sistema", ["conta"]],
    ]);
  });

  it("nenhum perfil ganhou tela com as áreas: o que entrou no menu abre o que o perfil já abria", () => {
    // o menu de antes das áreas (09/10/2026), por perfil
    const ANTES: Record<string, string[]> = {
      engenharia: ["inicio", "medicoes", "resumo-medicoes", "obras", "avisos", "siga", "documentos", "fechamento", "ancoras-docusign"],
      diretoria: ["inicio", "resumo-medicoes", "obras", "avisos", "documentos", "fechamento"],
      admin: ["inicio", "medicoes", "resumo-medicoes", "obras", "avisos", "siga", "documentos", "fechamento", "ancoras-docusign", "admin"],
    };
    // de onde vem cada página que nasceu com as áreas: Em aberto é de quem vê o Fechamento; as três de Documentos eram
    // as abas da tela Documentos; a Minha conta sempre foi de todos (pelo avatar do topo)
    const VEM_DE: Partial<Record<ItemMenu, string | null>> = {
      "a-receber": "fechamento", certidoes: "documentos", regularidade: "documentos", garantias: "documentos", conta: null };
    for (const perfil of ["engenharia", "diretoria", "admin"]) {
      const exigidas = paginasDe(perfil).map(i => (i in VEM_DE ? VEM_DE[i] : i)).filter(x => x !== null);
      for (const tela of exigidas) expect(ANTES[perfil], `${perfil} não via ${tela}`).toContain(tela);
      // e nada do que o perfil via sumiu
      for (const tela of ANTES[perfil]) expect(exigidas, `${perfil} perdeu ${tela}`).toContain(tela);
    }
    // o que o servidor nega à diretoria (`editar_cadastros`, `administrar`) e a tela SIGA continuam fora do menu dela
    for (const i of ["siga", "ancoras-docusign", "admin", "medicoes"] as ItemMenu[]) expect(paginasDe("diretoria")).not.toContain(i);
    expect(paginasDe("engenharia")).not.toContain("admin");
  });

  it("cada página do menu tem o próprio endereço", () => {
    const enderecosDoMenu = paginasDe("admin").map(i => caminhoDe(rotaDoItem(i)));
    expect(enderecosDoMenu).toEqual(["/inicio", "/medicoes", "/resumo-medicoes", "/obras", "/fechamento", "/a-receber", "/avisos", "/siga",
      "/documentos", "/documentos/regularidade", "/documentos/garantias", "/ancoras-docusign", "/admin", "/conta"]);
    expect(new Set(enderecosDoMenu).size).toBe(enderecosDoMenu.length);
    // e o endereço acende a própria página
    for (const i of paginasDe("admin")) expect(itemDe(rotaDoItem(i))).toBe(i);
  });

  it("a página fica acesa também abaixo dela na hierarquia", () => {
    expect(itemDe({ tela: "obra", id: 7, aba: "prazos" })).toBe("obras");
    expect(itemDe({ tela: "fechamento" })).toBe("fechamento");
    expect(itemDe({ tela: "a-receber" })).toBe("a-receber");
    expect(itemDe({ tela: "obras", aba: "qdop" })).toBe("obras");
    expect(itemDe({ tela: "obras" })).toBe("obras");
    expect(itemDe({ tela: "avisos" })).toBe("avisos");   // os Avisos têm página própria (#805)
    expect(itemDe({ tela: "inicio" })).toBe("inicio");
    expect(itemDe({ tela: "conta" })).toBe("conta");
    // a medição, a nova medição e o envio da nota ficam sob Medições, a área de quem opera
    expect(itemDe({ tela: "medicao", obra: 7, id: 723 })).toBe("medicoes");
    expect(itemDe({ tela: "medicao", obra: 7, id: 723 }, "engenharia")).toBe("medicoes");
    expect(itemDe({ tela: "nova-medicao", obra: 7 }, "admin")).toBe("medicoes");
    expect(itemDe({ tela: "notas-envio", id: 55 })).toBe("medicoes");
    // a diretoria não tem Medições no menu: para ela a medição acende Obras, por onde ela chega
    expect(itemDe({ tela: "medicao", obra: 7, id: 723 }, "diretoria")).toBe("obras");
    // a página do contratante fica dentro de Obras (#805), em qualquer aba
    expect(itemDe({ tela: "contratante", chave: "sinfra" })).toBe("obras");
    expect(itemDe({ tela: "contratante", chave: "sinfra", aba: "a-receber" })).toBe("obras");
    // Documentos: cada endereço acende a página dele; a empresa (#161), a página do assunto da aba
    expect(itemDe({ tela: "documentos" })).toBe("certidoes");
    expect(itemDe({ tela: "documentos", pagina: "regularidade" })).toBe("regularidade");
    expect(itemDe({ tela: "documentos", pagina: "garantias" })).toBe("garantias");
    expect(itemDe({ tela: "documentos-empresa", id: 3 })).toBe("certidoes");
    expect(itemDe({ tela: "documentos-empresa", id: 3, aba: "regularidade" })).toBe("regularidade");
    expect(itemDe({ tela: "documentos-empresa", id: 3, aba: "garantia" })).toBe("garantias");
    expect(itemDe({ tela: "medicoes" })).toBe("medicoes");
    expect(itemDe({ tela: "resumo-medicoes" })).toBe("resumo-medicoes");                            // #749
    expect(itemDe({ tela: "raiz" })).toBeNull();
  });

  it("a área acesa é a da página acesa", () => {
    expect(areaDe({ tela: "inicio" })).toBe("painel");
    expect(areaDe({ tela: "resumo-medicoes" })).toBe("medicoes");
    expect(areaDe({ tela: "obra", id: 7, aba: "ficha" })).toBe("obras");
    expect(areaDe({ tela: "a-receber" })).toBe("financeiro");
    expect(areaDe({ tela: "avisos" })).toBe("prazos");
    expect(areaDe({ tela: "siga" })).toBe("orgaos");
    expect(areaDe({ tela: "documentos-empresa", id: 3, aba: "garantia" })).toBe("documentos");
    expect(areaDe({ tela: "conta" })).toBe("sistema");
    expect(areaDe({ tela: "medicao", obra: 7, id: 1 }, "diretoria")).toBe("obras");
    expect(areaDe({ tela: "raiz" })).toBeNull();
  });

  it("o nome da tela, para a aba do navegador e o “← origem”", () => {
    expect(tituloDe("siga")).toBe("SIGA");
    expect(tituloDe("a-receber")).toBe("Em aberto");
    expect(tituloDe("documentos")).toBe("Documentos");
    expect(tituloDe("contratante")).toBe("Obras");
    expect(tituloDe("conta")).toBe("Minha conta");
    expect(vistaDe({ tela: "obras", aba: "qdop" })).toBe("QDOP");
    expect(vistaDe({ tela: "obras" })).toBeUndefined();
    expect(vistaDe({ tela: "obras", aba: "contratantes" })).toBeUndefined();
    expect(vistaDe({ tela: "medicoes", aba: "quadro" })).toBe("Quadro do mês");
    expect(vistaDe({ tela: "admin", aba: "usuarios" })).toBe("Usuários");
    expect(vistaDe({ tela: "admin", aba: "saude" })).toBeUndefined();
    // as abas do Fechamento (#815): a de comparação se chama pelos anos que a página publica; sem eles, "Comparação"
    expect(vistaDe({ tela: "fechamento" })).toBeUndefined();
    expect(vistaDe({ tela: "fechamento", aba: "meses" })).toBeUndefined();
    expect(vistaDe({ tela: "fechamento", aba: "contratantes" })).toBe("Por contratante");
    expect(vistaDe({ tela: "fechamento", aba: "comparacao" })).toBe("Comparação");
    expect(vistaDe({ tela: "fechamento", aba: "comparacao" }, { vista: "2026 × 2025" })).toBe("2026 × 2025");
  });
});

describe("o caminho de cada rota (#814)", () => {
  const de = (r: Rota, perfil = "admin") => trechosDe(r, { perfil });

  it("página do menu: a área e a página; a área leva à primeira página dela", () => {
    expect(rotulos(de({ tela: "inicio" }))).toEqual(["Painel", "Início"]);
    expect(rotulos(de({ tela: "fechamento" }))).toEqual(["Financeiro", "Fechamento"]);
    expect(rotulos(de({ tela: "a-receber" }))).toEqual(["Financeiro", "Em aberto"]);
    expect(enderecos(de({ tela: "a-receber" }))).toEqual(["/fechamento", "/a-receber"]);
    expect(rotulos(de({ tela: "avisos" }))).toEqual(["Prazos e avisos", "Avisos"]);
    expect(rotulos(de({ tela: "siga" }))).toEqual(["Órgãos", "SIGA"]);
    expect(rotulos(de({ tela: "resumo-medicoes" }))).toEqual(["Medições", "Resumo das medições"]);
    expect(rotulos(de({ tela: "ancoras-docusign" }))).toEqual(["Sistema", "Âncoras DocuSign"]);
    expect(rotulos(de({ tela: "conta" }))).toEqual(["Sistema", "Minha conta"]);
    expect(rotulos(de({ tela: "documentos" }))).toEqual(["Documentos", "Certidões"]);
    expect(rotulos(de({ tela: "documentos", pagina: "garantias" }))).toEqual(["Documentos", "Garantias"]);
    expect(enderecos(de({ tela: "documentos", pagina: "garantias" }))).toEqual(["/documentos", "/documentos/garantias"]);
    // o trecho da página é o título, e só a área leva a marca de área
    expect(de({ tela: "fechamento" }).map(t => [!!t.area, !!t.titulo])).toEqual([[true, false], [false, true]]);
  });

  it("a área leva à primeira página que o perfil tem nela", () => {
    expect(enderecos(de({ tela: "resumo-medicoes" }, "engenharia"))).toEqual(["/medicoes", "/resumo-medicoes"]);
    expect(enderecos(de({ tela: "resumo-medicoes" }, "diretoria"))).toEqual(["/resumo-medicoes", "/resumo-medicoes"]);
    expect(enderecos(de({ tela: "conta" }, "admin"))).toEqual(["/ancoras-docusign", "/conta"]);
    expect(enderecos(de({ tela: "conta" }, "diretoria"))).toEqual(["/conta", "/conta"]);
  });

  it("a área que é a própria página aparece uma vez; a vista padrão não entra, as outras são o último trecho", () => {
    expect(rotulos(de({ tela: "obras" }))).toEqual(["Obras"]);
    expect(rotulos(de({ tela: "medicoes" }))).toEqual(["Medições"]);
    expect(rotulos(de({ tela: "medicoes", aba: "fila" }))).toEqual(["Medições"]);
    expect(rotulos(de({ tela: "medicoes", aba: "quadro" }))).toEqual(["Medições", "Quadro do mês"]);
    expect(rotulos(de({ tela: "medicoes", aba: "anteriores" }))).toEqual(["Medições", "Meses anteriores"]);
    expect(rotulos(de({ tela: "obras", aba: "todas" }))).toEqual(["Obras", "Todas as obras"]);
    expect(rotulos(de({ tela: "obras", aba: "andamento" }))).toEqual(["Obras", "Andamento"]);
    expect(enderecos(de({ tela: "obras", aba: "qdop" }))).toEqual(["/obras", "/obras/qdop"]);
    expect(rotulos(de({ tela: "admin" }))).toEqual(["Sistema", "Administração"]);
    expect(rotulos(de({ tela: "admin", aba: "usuarios" }))).toEqual(["Sistema", "Administração", "Usuários"]);
    // o título é a página, e a vista vem depois dele
    expect(de({ tela: "obras", aba: "qdop" }).map(t => !!t.titulo)).toEqual([true, false]);
  });

  it("as abas do Fechamento (#815): a padrão fora; as outras no fim, e a página leva à padrão", () => {
    const vista = { vista: "2026 × 2025" };
    expect(rotulos(trechosDe({ tela: "fechamento" }, { nomes: vista }))).toEqual(["Financeiro", "Fechamento"]);
    expect(rotulos(trechosDe({ tela: "fechamento", aba: "contratantes" }, { nomes: vista }))).toEqual(["Financeiro", "Fechamento", "Por contratante"]);
    const comparacao = trechosDe({ tela: "fechamento", aba: "comparacao" }, { nomes: vista });
    expect(rotulos(comparacao)).toEqual(["Financeiro", "Fechamento", "2026 × 2025"]);
    expect(enderecos(comparacao)).toEqual(["/fechamento", "/fechamento", "/fechamento/comparacao"]);
    expect(comparacao.map(t => !!t.titulo)).toEqual([false, true, false]);
    // enquanto a página não diz os anos, o nome fixo
    expect(rotulos(de({ tela: "fechamento", aba: "comparacao" }))).toEqual(["Financeiro", "Fechamento", "Comparação"]);
    // o nome publicado só vale para a vista que se chama pelo dado: noutra rota, cada uma diz o dela
    expect(rotulos(trechosDe({ tela: "obras", aba: "qdop" }, { nomes: vista }))).toEqual(["Obras", "QDOP"]);
    expect(rotulos(trechosDe({ tela: "medicoes" }, { nomes: vista }))).toEqual(["Medições"]);
  });

  it("Obras em níveis: contratante, obra e medição, cada trecho com o endereço dele", () => {
    const nomes = { contratante: { nome: "SINFRA", chave: "sinfra" }, obra: "MT-388", medicao: "15ª Medição" };
    const contratante = trechosDe({ tela: "contratante", chave: "sinfra" }, { nomes });
    expect(rotulos(contratante)).toEqual(["Obras", "SINFRA"]);
    expect(enderecos(contratante)).toEqual(["/obras", "/obras/contratante/sinfra"]);
    expect(rotulos(trechosDe({ tela: "contratante", chave: "sinfra", aba: "a-receber" }, { nomes }))).toEqual(["Obras", "SINFRA", "Em aberto"]);
    expect(rotulos(trechosDe({ tela: "contratante", chave: "sinfra", aba: "siga" }, { nomes }))).toEqual(["Obras", "SINFRA", "Processos no SIGA"]);

    const obra = trechosDe({ tela: "obra", id: 7, aba: "ficha" }, { nomes });
    expect(rotulos(obra)).toEqual(["Obras", "SINFRA", "MT-388"]);
    expect(enderecos(obra)).toEqual(["/obras", "/obras/contratante/sinfra", "/obras/7"]);
    const prazos = trechosDe({ tela: "obra", id: 7, aba: "prazos" }, { nomes });
    expect(rotulos(prazos)).toEqual(["Obras", "SINFRA", "MT-388", "Prazos"]);
    expect(enderecos(prazos)).toEqual(["/obras", "/obras/contratante/sinfra", "/obras/7", "/obras/7/prazos"]);
    expect(prazos.map(t => !!t.titulo)).toEqual([false, false, true, false]);

    // o exemplo da proposta aprovada: Obras › SINFRA › MT-388 › Medições › 15ª
    const medicao = trechosDe({ tela: "medicao", obra: 7, id: 723 }, { nomes });
    expect(rotulos(medicao)).toEqual(["Obras", "SINFRA", "MT-388", "Medições", "15ª Medição"]);
    expect(enderecos(medicao)).toEqual(["/obras", "/obras/contratante/sinfra", "/obras/7", "/obras/7/medicoes", "/obras/7/medicoes/723"]);
    expect(medicao.map(t => !!t.titulo)).toEqual([false, false, false, false, true]);
    const nova = trechosDe({ tela: "nova-medicao", obra: 7 }, { nomes: { ...nomes, medicao: "Nova medição de Projeto" } });
    expect(rotulos(nova)).toEqual(["Obras", "SINFRA", "MT-388", "Medições", "Nova medição de Projeto"]);
    expect(enderecos(nova).slice(-2)).toEqual(["/obras/7/medicoes", "/obras/7/medicoes/nova"]);
  });

  it("enquanto a página não disse o nome, o trecho sai com o nome do tipo; sem contratante, o trecho não existe", () => {
    expect(rotulos(de({ tela: "contratante", chave: "sinfra" }))).toEqual(["Obras", "Contratante"]);
    expect(rotulos(de({ tela: "obra", id: 7, aba: "ficha" }))).toEqual(["Obras", "Obra"]);
    expect(rotulos(de({ tela: "medicao", obra: 7, id: 1 }))).toEqual(["Obras", "Obra", "Medições", "Medição"]);
    expect(rotulos(de({ tela: "nova-medicao", obra: 7 }))).toEqual(["Obras", "Obra", "Medições", "Nova medição"]);
    expect(rotulos(de({ tela: "documentos-empresa", id: 3 }))).toEqual(["Documentos", "Certidões", "Empresa"]);
    // o órgão sem chave no cadastro aparece só com o nome, sem link; o nome vazio não vira trecho
    const semChave = trechosDe({ tela: "obra", id: 7, aba: "ficha" }, { nomes: { obra: "Hospital", contratante: { nome: "SES", chave: null } } });
    expect([rotulos(semChave), enderecos(semChave)]).toEqual([["Obras", "SES", "Hospital"], ["/obras", null, "/obras/7"]]);
    expect(rotulos(trechosDe({ tela: "obra", id: 7, aba: "ficha" }, { nomes: { obra: "Hospital", contratante: { nome: "" } } })))
      .toEqual(["Obras", "Hospital"]);
  });

  it("a empresa em Documentos fica sob a página do assunto da aba", () => {
    const nomes = { empresa: "Construtora Alfa" };
    const certidoes = trechosDe({ tela: "documentos-empresa", id: 3 }, { nomes });
    expect(rotulos(certidoes)).toEqual(["Documentos", "Certidões", "Construtora Alfa"]);
    expect(enderecos(certidoes)).toEqual(["/documentos", "/documentos", "/documentos/3"]);
    const garantia = trechosDe({ tela: "documentos-empresa", id: 3, aba: "garantia" }, { nomes });
    expect(rotulos(garantia)).toEqual(["Documentos", "Garantias", "Construtora Alfa"]);
    expect(enderecos(garantia)).toEqual(["/documentos", "/documentos/garantias", "/documentos/3/garantia"]);
  });

  it("o histórico do SIGA: o trecho SIGA volta para a categoria de onde se veio", () => {
    const busca = { categoria: "aditivos", processo: "21" };
    const historico = trechosDe({ tela: "siga" }, { busca, nomes: { processo: "Obra Alfa · Aditivo de prazo" } });
    expect(rotulos(historico)).toEqual(["Órgãos", "SIGA", "Obra Alfa · Aditivo de prazo"]);
    expect(enderecos(historico)).toEqual(["/siga", "/siga?categoria=aditivos", "/siga?categoria=aditivos&processo=21"]);
    expect(historico.map(t => !!t.titulo)).toEqual([false, false, true]);
    // sem processo na busca (ou com lixo nela), é a lista
    expect(rotulos(trechosDe({ tela: "siga" }, { busca: { categoria: "aditivos" } }))).toEqual(["Órgãos", "SIGA"]);
    expect(rotulos(trechosDe({ tela: "siga" }, { busca: { processo: "x" } }))).toEqual(["Órgãos", "SIGA"]);
  });

  it("o envio da nota e a raiz", () => {
    expect(rotulos(de({ tela: "notas-envio", id: 55 }))).toEqual(["Medições", "Enviar a nota"]);
    expect(de({ tela: "raiz" })).toEqual([]);
  });

  it("toda rota tem caminho, com um título só, e o último trecho é o endereço dela", () => {
    const rotas: Rota[] = [
      { tela: "inicio" }, { tela: "medicoes" }, { tela: "medicoes", aba: "quadro" }, { tela: "resumo-medicoes" }, { tela: "avisos" },
      { tela: "siga" }, { tela: "documentos" }, { tela: "documentos", pagina: "regularidade" }, { tela: "documentos-empresa", id: 3 },
      { tela: "obras" }, { tela: "obras", aba: "todas" }, { tela: "contratante", chave: "sinfra" },
      { tela: "contratante", chave: "sinfra", aba: "medicoes" }, { tela: "a-receber" }, { tela: "fechamento" }, { tela: "notas-envio", id: 5 },
      { tela: "obra", id: 7, aba: "ficha" }, { tela: "obra", id: 7, aba: "contrato" }, { tela: "medicao", obra: 7, id: 9 },
      { tela: "nova-medicao", obra: 7 }, { tela: "ancoras-docusign" }, { tela: "admin" }, { tela: "admin", aba: "auditoria" }, { tela: "conta" },
    ];
    for (const r of rotas) {
      const ts = de(r);
      expect(ts.filter(t => t.titulo), caminhoDe(r)).toHaveLength(1);
      expect(ts[ts.length - 1].para, caminhoDe(r)).toEqual(r);
      // cada trecho com endereço leva a uma rota que existe
      for (const t of ts) if (t.para) expect(parseRota(caminhoDe(t.para))).toEqual(t.para);
    }
  });
});
