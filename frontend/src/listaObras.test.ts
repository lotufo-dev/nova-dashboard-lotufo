import { describe, expect, it } from "vitest";
import type { Aviso } from "./Alertas";
import { avisoPrincipal, contratantesDe, escopoDaUrl, filtrarObras, pctExecutado, prazoDaObra, resumoContratante, type ObraLista } from "./listaObras";

const o = (id: number, nome: string, extra: Partial<ObraLista> = {}): ObraLista => ({
  id, orgao: "SINFRA", numero_instrumento: `${id}/2026`, nome_curto: nome, estado: "ativo", ...extra });

describe("lista de obras", () => {
  const lista = [
    o(1, "MT-388", { dias_execucao: 187, dias_vigencia: 277 }),
    o(2, "5 Bairros", { dias_execucao: 9, dias_vigencia: 3 }),
    o(3, "Granito", { dias_execucao: 150, dias_vigencia: 60 }),
    o(4, "Deciolândia", { estado: "encerrado", dias_execucao: -300 }),
    o(5, "Maternidade VG", { orgao: "SMS-VG", dias_execucao: 80, dias_vigencia: 40, vigencia_automatica: true }),
  ];

  it("em andamento por padrão, na ordem do nome; todas com o filtro", () => {
    expect(filtrarObras(lista, {}).map(x => x.nome_curto)).toEqual(["5 Bairros", "Granito", "Maternidade VG", "MT-388"]);
    expect(filtrarObras(lista, { todas: true })).toHaveLength(5);
  });

  it("terminam em 90 dias: execução ou vigência (a que o órgão não prorroga junto), a vencida na frente", () => {
    const comVencida = [...lista, o(6, "Terminais BRT", { dias_execucao: -24, dias_vigencia: -4 })];
    expect(filtrarObras(comVencida, { termina: 90 }).map(x => x.nome_curto)).toEqual(["Terminais BRT", "5 Bairros", "Granito", "Maternidade VG"]);
    // a encerrada, com prazo vencido ha' muito, nao entra mesmo com "todas"
    expect(filtrarObras(comVencida, { termina: 90, todas: true }).map(x => x.id)).not.toContain(4);
  });

  it("busca sem acento e sem caixa", () => {
    expect(filtrarObras([o(9, "Coxipó 2ª Etapa")], { q: "coxipo 2a" }).map(x => x.id)).toEqual([9]);
  });

  it("busca por nome ou instrumento, e órgão", () => {
    expect(filtrarObras(lista, { q: "mt-3" }).map(x => x.id)).toEqual([1]);
    expect(filtrarObras(lista, { q: "4/2026", todas: true }).map(x => x.id)).toEqual([4]);
    expect(filtrarObras(lista, { orgao: "SMS-VG" }).map(x => x.id)).toEqual([5]);
  });
});

describe("prazo da obra paralisada", () => {
  it("a data da paralisação vem da própria lista, também para obra suspensa sem aviso", () => {
    const p = prazoDaObra(o(7, "Parada", { estado: "suspenso", paralisada_desde: "2026-02-01" }), []);
    expect(p).toMatchObject({ paralisada: true, paralisadaDesde: "2026-02-01" });
  });

  it("obra sem paralisação não tem data", () => {
    expect(prazoDaObra(o(8, "Andando"), []).paralisadaDesde).toBeNull();
  });
});

describe("contratantes (entrada de Obras, #159)", () => {
  const cheia = (id: number, orgao: string, vigente: number, medido: number, extra: Partial<ObraLista> = {}) =>
    o(id, `Obra ${id}`, { orgao, valor_vigente_centavos: vigente, medido_execucao_centavos: medido, ...extra });
  const lista = [
    cheia(1, "SINFRA", 1000_00, 250_00), cheia(2, "SINFRA", 3000_00, 750_00),
    cheia(3, "MTPAR", 2000_00, 1000_00), cheia(4, "MTPAR", 500_00, 500_00, { estado: "encerrado" }),
  ];

  it("% executado da obra: medido de execução ÷ valor vigente, inteiro; sem vigente, nulo", () => {
    expect(pctExecutado(lista[0])).toBe(25);
    expect(pctExecutado(cheia(9, "X", 0, 0))).toBeNull();
    expect(pctExecutado(o(9, "Sem valor"))).toBeNull();
  });

  it("o resumo conta só as obras em andamento; as encerradas só são contadas", () => {
    const r = resumoContratante(lista.filter(x => x.orgao === "MTPAR"));
    expect(r).toMatchObject({ obras: 1, encerradas: 1, vigente: 2000_00, medido: 1000_00, saldo: 1000_00, pct: 50 });
    // a rescindida também fica fora dos números e entra na contagem das encerradas
    expect(resumoContratante([...lista, cheia(5, "MTPAR", 100_00, 0, { estado: "rescindido" })].filter(x => x.orgao === "MTPAR")))
      .toMatchObject({ obras: 1, encerradas: 2, vigente: 2000_00 });
  });

  it("'Todas as obras' é a soma das linhas dos contratantes (obras e saldo)", () => {
    const todas = resumoContratante(lista);
    const partes = contratantesDe(lista).map(c => resumoContratante(lista.filter(x => x.orgao === c)));
    expect(partes.reduce((a, r) => a + r.obras, 0)).toBe(todas.obras);
    expect(partes.reduce((a, r) => a + r.saldo, 0)).toBe(todas.saldo);
    expect(todas.saldo).toBe((1000_00 - 250_00) + (3000_00 - 750_00) + (2000_00 - 1000_00));
    expect(contratantesDe(lista)).toEqual(["MTPAR", "SINFRA"]);
  });

  it("avisos do contratante: obras com aviso, críticos e o nível mais grave", () => {
    const av = (nivel: string, contrato_id: number) => ({ tipo: "x", nivel, contrato_id, mensagem: "m" }) as unknown as Aviso;
    const mapa = new Map<number, Aviso[]>([[1, [av("atencao", 1), av("critico", 1)]], [2, [av("acao", 2)]]]);
    expect(resumoContratante(lista.filter(x => x.orgao === "SINFRA"), mapa)).toMatchObject({ comAviso: 2, criticos: 1, nivelMax: "critico" });
    expect(resumoContratante(lista.filter(x => x.orgao === "MTPAR"), mapa)).toMatchObject({ comAviso: 0, criticos: 0, nivelMax: null });
    expect(avisoPrincipal(mapa.get(1)!)?.nivel).toBe("critico");
  });

  it("a URL: sem filtro é a escolha do contratante; ?c=, ?orgao= e os filtros de antes abrem a lista", () => {
    expect(escopoDaUrl({})).toEqual({ escolha: true, orgao: null });
    expect(escopoDaUrl({ c: "todas" })).toEqual({ escolha: false, orgao: null });
    expect(escopoDaUrl({ c: "SINFRA" })).toEqual({ escolha: false, orgao: "SINFRA" });
    expect(escopoDaUrl({ orgao: "SMS-VG" })).toEqual({ escolha: false, orgao: "SMS-VG" });
    expect(escopoDaUrl({ termina: "90" })).toEqual({ escolha: false, orgao: null });
    expect(escopoDaUrl({ q: "granito" }).escolha).toBe(false);
  });

  it("a busca também acha pela empresa e pelo órgão", () => {
    const l = [cheia(1, "SINFRA", 1, 0, { entidade_id: 5 }), cheia(2, "MTPAR", 1, 0, { entidade_id: 6 })];
    const empresas = new Map([[5, "Construtora Alfa"], [6, "Beta Engenharia"]]);
    expect(filtrarObras(l, { q: "alfa", empresas }).map(x => x.id)).toEqual([1]);
    expect(filtrarObras(l, { q: "mtpar", empresas }).map(x => x.id)).toEqual([2]);
    expect(filtrarObras(l, { q: "alfa" })).toHaveLength(0);
  });
});
