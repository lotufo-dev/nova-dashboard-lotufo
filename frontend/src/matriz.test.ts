import { describe, expect, it } from "vitest";
import {
  certidoesOrdenadas, colunas, matriz, pendenciaMaisUrgente, pendenciasDa, proximaAVencer, resumoEmpresa, situacaoArt,
  situacaoCertidao, situacaoGarantia, type EmpresaDoc, type LinhaCertidao,
} from "./matriz";

const l = (chave: string, situacao: LinhaCertidao["situacao"], dias: number | null, exigida = true): LinhaCertidao => ({
  tipo_id: chave.length, chave, tipo: chave, link_emissao: null, exigida, situacao, dias, certidao: null });
const e = (id: number, certidoes: LinhaCertidao[], reg: EmpresaDoc["regularidade"] = null): EmpresaDoc => ({
  entidade_id: id, entidade: `E${id}`, cnpj: "", papel: "lotufo", certidoes, regularidade_exigida: reg !== null, regularidade: reg });

describe("matriz de documentos", () => {
  const empresas = [
    e(1, [l("federal", "ok", 80), l("fgts", "ok", 25)]),                         // vence em 25 dias: pendência (decisão 5)
    e(2, [l("federal", "ok", 90), l("municipal", "faltando", null, false)]),     // não exigida não pesa
    e(3, [l("federal", "vencida", null), l("estadual", "faltando", null)],
      { situacao: "atrasada", competencia: "2026-07", esperada: "2026-08" }),
  ];

  it("pendência é certidão exigida vencida, faltando ou vencendo em até 30 dias, e a regularidade fora do dia", () => {
    expect(empresas.map(x => pendenciasDa(x))).toEqual([1, 0, 3]);
  });

  it("pela gravidade: o que já trava, depois o que vence (o mais urgente antes); o filtro deixa só as pendentes", () => {
    const mais = [...empresas, e(4, [l("federal", "ok", 20), l("fgts", "vencendo", 12)]), e(5, [l("trabalhista", "vencida", null)])];
    expect(matriz(mais, false).map(x => x.entidade_id)).toEqual([3, 5, 4, 1, 2]);
    expect(matriz(mais, true).map(x => x.entidade_id)).toEqual([3, 5, 4, 1]);
  });

  it("as colunas são os tipos que alguma empresa tem, na ordem dada", () => {
    expect(colunas(empresas, ["federal", "fgts", "trabalhista", "estadual", "municipal"])).toEqual(["federal", "fgts", "estadual", "municipal"]);
  });
});

describe("redesenho de Documentos (#161)", () => {
  const cert = { id: 1, emissao: "2026-08-01", validade: "2026-12-01", natureza: "negativa" };
  const c = (chave: string, situacao: LinhaCertidao["situacao"], dias: number | null, exigida = true): LinhaCertidao => ({
    ...l(chave, situacao, dias, exigida), certidao: situacao === "faltando" ? null : cert });

  it("a situação geral diz o que trava, o que vence e a regularidade, e 'Em dia' quando nada pende", () => {
    expect(resumoEmpresa(e(1, [c("federal", "ok", 90), c("fgts", "ok", 200)]))).toEqual({ texto: "Em dia", nivel: "ok", pendencias: 0 });
    expect(resumoEmpresa(e(1, [c("federal", "ok", 90), c("fgts", "ok", 25)]))).toMatchObject({ texto: "1 vence em 25 dias", nivel: "atencao" });
    expect(resumoEmpresa(e(1, [c("federal", "ok", 20), c("fgts", "vencendo", 12)]))).toMatchObject({ texto: "2 vencem em até 20 dias", nivel: "atencao" });
    const r = resumoEmpresa(e(1, [c("federal", "vencida", null), c("estadual", "faltando", null), c("fgts", "faltando", null)],
      { situacao: "atrasada", competencia: "2026-06", esperada: "2026-07" }));
    expect(r).toEqual({ texto: "1 vencida · 2 faltam · regularidade atrasada", nivel: "acao", pendencias: 4 });
    // so' a regularidade fora do dia: atencao, e ainda e' pendencia
    expect(resumoEmpresa(e(1, [c("federal", "ok", 90)], { situacao: "faltando", competencia: null, esperada: "2026-07" })))
      .toEqual({ texto: "Regularidade não anexada", nivel: "atencao", pendencias: 1 });
    // nao exigida e nao se aplica nao pesam
    expect(resumoEmpresa(e(1, [c("federal", "ok", 90), c("falencia", "faltando", null, false), c("municipal", "nao_se_aplica", null)])).texto).toBe("Em dia");
  });

  it("a próxima a vencer é a vigente exigida que vence primeiro; sem vigente, nada", () => {
    expect(proximaAVencer(e(1, [c("federal", "ok", 90), c("fgts", "ok", 25), c("municipal", "vencida", null)]))!.chave).toBe("fgts");
    expect(proximaAVencer(e(1, [c("federal", "vencida", null), c("fgts", "ok", 10, false)]))).toBeNull();
  });

  it("os pontos seguem a ordem do desenho e a pendência mais urgente leva o botão principal", () => {
    const emp = e(1, [c("falencia", "ok", 100), c("fgts", "vencendo", 4), c("federal", "ok", 100), c("municipal", "vencida", null)]);
    expect(certidoesOrdenadas(emp).map(x => x.chave)).toEqual(["federal", "municipal", "fgts", "falencia"]);
    expect(pendenciaMaisUrgente(emp)!.chave).toBe("municipal");                  // vencida vem antes de quem ainda vigora
    expect(pendenciaMaisUrgente(e(1, [c("federal", "ok", 100)]))).toBeNull();
  });

  it("a situação de uma certidão segue a janela de 30 dias; não exigida fica neutra", () => {
    expect(situacaoCertidao(c("fgts", "ok", 25), "16/10/2026")).toEqual({ texto: "vence em 25 dias", data: "até 16/10/2026", nivel: "atencao" });
    expect(situacaoCertidao(c("fgts", "ok", 100), "16/10/2026").nivel).toBe("ok");
    expect(situacaoCertidao(c("fgts", "vencendo", 1), "x").texto).toBe("vence amanhã");
    expect(situacaoCertidao(c("fgts", "faltando", null), "")).toEqual({ texto: "falta", nivel: "acao" });
    expect(situacaoCertidao(c("falencia", "ok", 100, false), "x").nivel).toBe("neutro");
  });

  it("garantia e ART: a garantia vence com ação aos 15 dias; a ART só precisa estar anexada", () => {
    const g = (dias: number, situacao: "ok" | "vencendo" | "vencida" | "baixada") =>
      ({ apolice: "AP-1", vigencia_fim: "2026-12-01", dias, origem: "contrato" as const, situacao });
    expect(situacaoGarantia(null, "")).toMatchObject({ texto: "sem vigência no cadastro", nivel: "neutro" });
    expect(situacaoGarantia(g(20, "vencendo"), "01/12/2026")).toMatchObject({ texto: "vence em 20 dias", nivel: "atencao" });
    expect(situacaoGarantia(g(15, "vencendo"), "01/12/2026").nivel).toBe("acao");
    expect(situacaoGarantia(g(-3, "vencida"), "01/12/2026")).toMatchObject({ texto: "vencida", nivel: "acao", forte: true });
    expect(situacaoGarantia(g(-3, "vencida"), "01/12/2026").nota).toBe("venceu em 01/12/2026 · apólice AP-1");
    expect(situacaoGarantia(g(300, "baixada"), "01/12/2026").nivel).toBe("neutro");
    expect(situacaoArt({ numero: "9", anexada: true, exigida: true })).toEqual({ texto: "anexada", nota: "nº 9", nivel: "ok" });
    expect(situacaoArt({ numero: null, anexada: false, exigida: true }).nivel).toBe("atencao");
    expect(situacaoArt({ numero: null, anexada: false, exigida: false }).texto).toBe("não exigida");
  });
});

describe("garantia e ART como pendência da empresa (#161)", () => {
  const obra = (ent: number, dias: number, situacao: "ok" | "vencendo" | "vencida", artAnexada = true) => ({
    contrato_id: ent, obra: `O${ent}`, entidade_id: ent,
    garantia: { apolice: null, vigencia_fim: "2026-12-01", dias, origem: "contrato" as const, situacao },
    art: { numero: null, anexada: artAnexada, exigida: true } });
  const ok = (id: number) => e(id, [l("federal", "ok", 90)]);

  it("conta na pílula, na ordenação, no filtro e na contagem", () => {
    const obras = [obra(2, 20, "vencendo"), obra(3, -5, "vencida", false), obra(4, 200, "ok")];
    expect(resumoEmpresa(ok(2), obras)).toEqual({ texto: "Garantia vence em 20 dias", nivel: "atencao", pendencias: 1 });
    expect(resumoEmpresa(ok(3), obras)).toEqual({ texto: "Garantia vencida · ART não anexada", nivel: "acao", pendencias: 2 });
    expect(resumoEmpresa(ok(4), obras).texto).toBe("Em dia");
    expect(pendenciasDa(ok(3))).toBe(0);                                   // sem as obras, nada muda
    const lista = [ok(4), ok(2), ok(3)];
    expect(matriz(lista, false, obras).map(x => x.entidade_id)).toEqual([3, 2, 4]);
    expect(matriz(lista, true, obras).map(x => x.entidade_id)).toEqual([3, 2]);
  });
});
