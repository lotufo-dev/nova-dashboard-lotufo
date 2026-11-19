/// <reference types="node" />
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { Aviso } from "./Alertas";
import { FAMILIAS, familiaDaBusca, familiaDoAviso, filtrarAvisos, porFamilia, porObra, porSecao, quandoDoAviso, secaoDoAviso, daAgenda, diasAteOAviso,
  ASSUNTOS, ASSUNTO_DO_TIPO, assuntoDaBusca, assuntoDoAviso, diasPorExtenso, ondeEstao, rotuloDoAssunto, vencidosPorObra } from "./avisos";

const av = (tipo: string, nivel: Aviso["nivel"], contrato_id: number | null, aba: string | null, data: string | null = null): Aviso => ({
  tipo, nivel, publico: ["operacao"], contrato_id, obra: contrato_id ? `Obra ${contrato_id}` : null, dias: null,
  valor_centavos: null, mensagem: tipo, data,
  destino: aba === "documentos" ? { tela: "documentos" } : aba && contrato_id ? { tela: "contrato", id: contrato_id, aba } : null });

describe("avisos", () => {
  const lista = [
    av("reajuste_apostilamento", "atencao", 7, "reajuste", "2026-03-22"),
    av("execucao_vencendo", "critico", 12, "prazos", "2026-09-13"),
    { ...av("documentos_empresa", "critico", null, "documentos", "2026-07-26"), entidade_id: 2, entidade: "Oriundi" },
    av("nota_divergente", "critico", 7, "notas"),
    av("aviso_de_medicao", "acao", 9, "medicoes", "2026-06-01"),
    av("folga_quebrada", "acao", 15, "prazos"),
    av("tipo_novo", "atencao", 3, null),
  ];

  it("a família vem do lar do aviso (o destino); lar desconhecido é Outros", () => {
    expect(lista.map(familiaDoAviso)).toEqual(["reajuste", "prazo", "documentos", "nota", "outros", "prazo", "outros"]);
  });

  it("o pagamento atrasado saiu (#255): sem família Dinheiro e sem destino próprio", () => {
    expect(FAMILIAS.map(f => f.id)).toEqual(["prazo", "reajuste", "nota", "siga", "documentos", "outros"]);
    const antigo = { ...av("pagamento_atrasado", "acao", 9, "medicoes"), medicao_id: 722 };
    expect(familiaDoAviso(antigo)).toBe("outros");
  });

  it("os avisos do SIGA (#330) formam a família SIGA, entre Nota e Documentos", () => {
    const parado: Aviso = { ...av("siga_parado", "atencao", 7, null), destino: { tela: "siga", processo: 4 } };
    const sem: Aviso = { ...av("siga_sem_leitura", "acao", null, null), destino: { tela: "siga" } };
    expect([parado, sem].map(familiaDoAviso)).toEqual(["siga", "siga"]);
    expect(porFamilia([...lista, parado, sem]).map(g => g.rotulo)).toEqual(
      ["Prazo", "Reajuste", "Nota", "SIGA", "Documentos", "Outros"]);
  });

  it("por família, na ordem do mapa, do mais grave ao mais atrasado", () => {
    expect(porFamilia(lista).map(g => `${g.rotulo}: ${g.itens.map(a => a.tipo).join(", ")}`)).toEqual([
      "Prazo: execucao_vencendo, folga_quebrada", "Reajuste: reajuste_apostilamento", "Nota: nota_divergente",
      "Documentos: documentos_empresa", "Outros: aviso_de_medicao, tipo_novo"]);
  });

  it("por obra, a do aviso mais grave primeiro; os de empresa por empresa (A11), na posição do mais grave", () => {
    expect(porObra(lista).map(g => `${g.rotulo} (${g.itens.length})`)).toEqual([
      "Documentos · Oriundi (1)", "Obra 12 (1)", "Obra 7 (2)", "Obra 9 (1)", "Obra 15 (1)", "Obra 3 (1)"]);
  });

  it("quando, pelos dias e o sentido do servidor (A8)", () => {
    expect(quandoDoAviso({ ...lista[1], dias: -12, sentido: "prazo" }).replace(/\u00a0/g, " ")).toBe("venceu há 12 dias");
    expect(quandoDoAviso({ ...lista[1], dias: 3, sentido: "prazo" }).replace(/\u00a0/g, " ")).toBe("vence em 3 dias");
    expect(quandoDoAviso({ ...lista[0], dias: 187, sentido: "desde" }).replace(/\u00a0/g, " ")).toBe("há 187 dias");
  });

  it("filtra por família, nível e obra, como a URL pede", () => {
    expect(filtrarAvisos(lista, { familia: "prazo", nivel: "critico" }).map(a => a.tipo)).toEqual(["execucao_vencendo"]);
    expect(filtrarAvisos(lista, { obra: 7 }).map(a => a.tipo)).toEqual(["reajuste_apostilamento", "nota_divergente"]);
  });
});

describe("avisos pelo tempo (#511)", () => {
  const com = (dias: number | null, sentido: Aviso["sentido"] = "prazo"): Aviso => ({ ...av("x", "atencao", 1, "prazos"), dias, sentido });

  it("classifica a seção pelos dias e pelo sentido; sem data ou além de 90 dias fica fora da agenda (#656)", () => {
    expect(secaoDoAviso(com(-3))).toBe("vencido");
    expect(secaoDoAviso(com(130, "desde"))).toBe("vencido");
    expect(secaoDoAviso(com(-900))).toBe("vencido");
    expect(secaoDoAviso(com(0))).toBe("semana");
    expect(secaoDoAviso(com(5))).toBe("semana");
    expect(secaoDoAviso(com(20))).toBe("mes");
    expect(secaoDoAviso(com(60))).toBe("depois");
    expect(secaoDoAviso(com(90))).toBe("depois");
    expect(secaoDoAviso(com(91))).toBeNull();
    expect(secaoDoAviso(com(null))).toBeNull();
  });

  it("aviso com data e sem dias é posicionado pela data (#656)", () => {
    const naData = (data: string): Aviso => ({ ...av("documento_vencido", "critico", null, "documentos", data), sentido: "prazo" });
    expect(diasAteOAviso(naData("2026-11-01"), "2026-11-11")).toBe(-10);
    expect(secaoDoAviso(naData("2026-11-01"), "2026-11-11")).toBe("vencido");
    expect(secaoDoAviso(naData("2026-11-30"), "2026-11-11")).toBe("mes");
    expect(secaoDoAviso(naData("2027-02-09"), "2026-11-11")).toBe("depois");      // 90 dias
    expect(secaoDoAviso(naData("2027-02-10"), "2026-11-11")).toBeNull();          // 91 dias
  });

  it("ordena: vencido do mais antigo, a vencer do mais próximo; sem data e além de 90 dias não entram", () => {
    const lista = [com(-3), com(-40), com(30), com(10), com(null), com(120)];
    const g = porSecao(lista);
    expect(g.map(s => s.id)).toEqual(["vencido", "semana", "mes", "depois"]);
    expect(g[0].itens.map(a => a.dias)).toEqual([-40, -3]);
    expect(g[2].itens.map(a => a.dias)).toEqual([10, 30]);
    expect(g.flatMap(s => s.itens)).toHaveLength(4);
    expect(daAgenda(lista).map(a => a.dias)).toEqual([-3, -40, 30, 10]);
  });

  it("a categoria da rota aceita o plural do Início e o id da família", () => {
    expect(familiaDaBusca("reajustes")).toBe("reajuste");
    expect(familiaDaBusca("certidoes")).toBe("documentos");
    expect(familiaDaBusca("prazo")).toBe("prazo");
    expect(familiaDaBusca("x")).toBeNull();
  });

  it("os dias por extenso, como o selo os escreve", () => {
    const sem = (t: string) => t.replace(/ /g, " ");
    expect([-1200, -1, 0, 1, 45].map(d => sem(diasPorExtenso(d)))).toEqual(["há 1.200 dias", "há 1 dia", "hoje", "em 1 dia", "em 45 dias"]);
  });
});

describe("assunto do aviso (#805): as abas da página Avisos", () => {
  const doTipo = (tipo: string, aba: string | null = "medicoes"): Aviso => av(tipo, "atencao", 7, aba);

  it("os assuntos aprovados, nesta ordem, mais o SIGA e o Outros de reserva", () => {
    expect(ASSUNTOS.map(a => a.rotulo)).toEqual(["Prazos", "Reajustes", "Garantias", "Certidões", "Medições", "SIGA", "Outros"]);
    expect(rotuloDoAssunto("certidoes")).toBe("Certidões");
  });

  it("o assunto sai do tipo, não do destino: a garantia não cai com a certidão, nem o aviso de medição em Outros", () => {
    // os dois abrem Documentos; o servidor manda o aprovado abaixo do pedido com o destino padrão (a aba Medições)
    expect(assuntoDoAviso(doTipo("garantia_aquem_execucao", "documentos"))).toBe("garantias");
    expect(assuntoDoAviso(doTipo("documentos_empresa", "documentos"))).toBe("certidoes");
    expect(assuntoDoAviso(doTipo("aprovado_abaixo_do_pedido"))).toBe("medicoes");
    // o endosso da garantia nasce com os prazos (destino: a aba Prazos) e é assunto de garantia
    expect(assuntoDoAviso(doTipo("endosso_garantia", "prazos"))).toBe("garantias");
    expect(assuntoDoAviso(doTipo("instrumento_pendente", "prazos"))).toBe("prazos");
    expect(assuntoDoAviso(doTipo("reajuste_sem_resposta", "reajuste"))).toBe("reajustes");
    expect(assuntoDoAviso(doTipo("nota_divergente", "notas"))).toBe("medicoes");
    expect(assuntoDoAviso({ ...doTipo("siga_parado", null), destino: { tela: "siga", processo: 4 } })).toBe("siga");
  });

  it("tipo que o mapa não conhece fica em Outros, para nada sumir; nome herdado de objeto não vira assunto", () => {
    expect(assuntoDoAviso(doTipo("tipo_que_nao_existe"))).toBe("outros");
    expect(assuntoDoAviso(doTipo("toString"))).toBe("outros");
    expect(assuntoDoAviso(doTipo("constructor"))).toBe("outros");
  });

  it("o mapa só aponta para assunto que tem aba, e nunca para Outros", () => {
    const ids = new Set(ASSUNTOS.map(a => a.id));
    for (const [tipo, assunto] of Object.entries(ASSUNTO_DO_TIPO)) {
      expect(ids.has(assunto), tipo).toBe(true);
      expect(assunto, tipo).not.toBe("outros");
    }
  });

  it("?familia= dos links de antes abre a aba equivalente; os ids novos valem; valor desconhecido não filtra", () => {
    expect(["prazos", "reajustes", "certidoes"].map(assuntoDaBusca)).toEqual(["prazos", "reajustes", "certidoes"]);      // o plural do Início
    expect(["prazo", "reajuste", "documentos", "nota", "siga"].map(assuntoDaBusca)).toEqual(["prazos", "reajustes", "certidoes", "medicoes", "siga"]);
    expect(["garantias", "medicoes", "outros"].map(assuntoDaBusca)).toEqual(["garantias", "medicoes", "outros"]);
    expect([undefined, "", "x", "toString"].map(assuntoDaBusca)).toEqual([null, null, null, null]);
  });

  // Os tipos que o servidor emite, lidos do codigo dele (o vitest roda na pasta frontend). Tres formas no codigo:
  // `aviso("tipo", ...)`, o dicionario `{"tipo": "tipo", ...}` dos modulos que so' montam a lista (o tipo passa por
  // `avisos.py` como variavel) e os dois do espelho, escolhidos numa linha de `avisos.py`.
  const BACKEND = join(process.cwd(), "..", "backend", "app");
  const ler = (nome: string) => readFileSync(join(BACKEND, nome), "utf8");
  const COM_DICIONARIO = ["documentos.py", "notas.py", "garantias.py", "capa_smo.py"];
  // as fontes da fila (`FONTES`, em avisos.py): fonte nova pode trazer os tipos de outra forma, e este teste precisa saber
  const FONTES = ["_de_documentos", "_de_notas", "_de_prazos", "_de_reajuste", "_de_garantias", "_de_siga", "_de_espelhos",
    "_de_motor_medicao", "_de_capa_smo"];

  function tiposDoServidor(): Set<string> {
    const tipos = new Set<string>();
    for (const nome of readdirSync(BACKEND).filter(n => n.endsWith(".py"))) {
      for (const m of ler(nome).matchAll(/\baviso\(\s*"([a-z_]+)"/g)) tipos.add(m[1]);
    }
    for (const nome of COM_DICIONARIO) {
      for (const m of ler(nome).matchAll(/\{"tipo":\s*"([a-z_]+)"/g)) tipos.add(m[1]);
    }
    for (const m of ler("avisos.py").matchAll(/\btipo = "([a-z_]+)" if .* else "([a-z_]+)"/g)) { tipos.add(m[1]); tipos.add(m[2]); }
    return tipos;
  }

  it("todo tipo de aviso que o servidor emite tem assunto no mapa, e o mapa não guarda tipo que o servidor não emite", () => {
    const fontes = /^FONTES = \[([^\]]*)\]/m.exec(ler("avisos.py"))?.[1].split(",").map(f => f.trim()).filter(Boolean);
    // fonte nova em `avisos.py`: confira como ela escreve o tipo (e ponha o arquivo em COM_DICIONARIO se for o caso)
    expect(fontes).toEqual(FONTES);
    const doServidor = [...tiposDoServidor()].sort();
    expect(doServidor.length).toBeGreaterThanOrEqual(36);
    // tipo novo no servidor: ponha o assunto dele em ASSUNTO_DO_TIPO (avisos.ts), para ele não cair calado em "Outros"
    expect(doServidor.filter(t => !Object.prototype.hasOwnProperty.call(ASSUNTO_DO_TIPO, t))).toEqual([]);
    expect(Object.keys(ASSUNTO_DO_TIPO).filter(t => !doServidor.includes(t))).toEqual([]);
  });
});

describe("vencidos por obra (#805)", () => {
  const venc = (contrato_id: number | null, dias: number, tipo: string, extra: Partial<Aviso> = {}): Aviso => ({
    ...av(tipo, "atencao", contrato_id, tipo === "documentos_empresa" || tipo === "garantia_vencendo" ? "documentos" : "prazos"),
    dias, sentido: "prazo", ...extra });
  const lista = [
    venc(7, -3, "execucao_vencendo"), venc(7, -400, "reajuste_sem_resposta"), venc(7, -50, "vigencia_vencendo"),
    venc(7, -20, "aprovado_abaixo_do_pedido"),
    venc(8, -90, "reajuste_sem_resposta"),
    { ...venc(null, -10, "documentos_empresa"), entidade_id: 2, entidade: "Construtora Alfa" },
    { ...venc(null, -10, "regularidade_mes"), entidade_id: 2, entidade: "Construtora Alfa" },
    venc(null, -5, "siga_sem_leitura"),
    venc(9, 5, "execucao_vencendo"), venc(9, null as unknown as number, "folga_quebrada"),       // a vencer e sem data: fora
  ];

  it("agrupa pela obra, o aviso sem obra pela empresa e o resto num grupo só; da maior idade para a menor", () => {
    const g = vencidosPorObra(lista);
    expect(g.map(x => [x.chave, x.nome, x.itens.length, x.maisAntigo])).toEqual([
      ["obra-7", "Obra 7", 4, 400], ["obra-8", "Obra 8", 1, 90], ["empresa-2", "Construtora Alfa", 2, 10], ["sem-obra", "Sem obra", 1, 5]]);
    // dentro do grupo, do mais antigo ao mais novo; os assuntos, na ordem das abas, sem repetir
    expect(g[0].itens.map(a => a.dias)).toEqual([-400, -50, -20, -3]);
    expect(g[0].assuntos).toEqual(["prazos", "reajustes", "medicoes"]);
    expect(g[2].assuntos).toEqual(["certidoes"]);
    expect(g[3].assuntos).toEqual(["siga"]);
    expect([g[0].contratoId, g[0].entidadeId, g[2].contratoId, g[2].entidadeId]).toEqual([7, null, null, 2]);
    // todo vencido entra, sem limite de idade (#656)
    expect(g.flatMap(x => x.itens)).toHaveLength(8);
  });

  it("no empate de idade, o grupo com mais avisos primeiro e depois o nome", () => {
    const g = vencidosPorObra([venc(3, -20, "execucao_vencendo"), venc(2, -20, "execucao_vencendo"), venc(1, -20, "execucao_vencendo"),
      venc(1, -2, "vigencia_vencendo")]);
    expect(g.map(x => x.nome)).toEqual(["Obra 1", "Obra 2", "Obra 3"]);
  });

  it("a garantia traz a obra e a empresa: fica no grupo da obra, com o assunto Garantias", () => {
    const g = vencidosPorObra([{ ...venc(7, -30, "garantia_vencendo"), entidade_id: 2, entidade: "Construtora Alfa" }]);
    expect(g.map(x => [x.chave, x.entidadeId, x.assuntos])).toEqual([["obra-7", null, ["garantias"]]]);
  });

  it("diz em quantas obras e empresas os vencidos estão", () => {
    expect(ondeEstao(vencidosPorObra(lista))).toBe("em 2 obras e 1 empresa");
    expect(ondeEstao(vencidosPorObra([venc(7, -3, "execucao_vencendo")]))).toBe("em 1 obra");
    expect(ondeEstao(vencidosPorObra([{ ...venc(null, -3, "documentos_empresa"), entidade_id: 2 },
      { ...venc(null, -3, "documentos_empresa"), entidade_id: 3 }]))).toBe("em 2 empresas");
    expect(ondeEstao(vencidosPorObra([venc(null, -3, "siga_sem_leitura")]))).toBe("");
    expect(ondeEstao([])).toBe("");
  });
});
