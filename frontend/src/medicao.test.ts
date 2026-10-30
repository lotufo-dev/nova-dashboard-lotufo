import { describe, expect, it } from "vitest";
import { eventosDaMedicao, itensOQueFalta, larDoEspelho, metadeQueEspera, protocolosDa, resumoNotas,
         rotuloDoBloco, separarMedicoes, tituloMedicao,
         type EspelhoResumo, type MedicaoBase, type Metade, type ProtocoloResumo } from "./medicao";

// issue #188: medicao e reajuste na mesma pagina
describe("medição e reajuste na mesma página", () => {
  const metade = (tipo: string, extra: Partial<Metade> = {}): Metade => ({ medicao_id: tipo === "execucao" ? 1 : 2, tipo,
    titulo: "", estado: "nota_emitida", faltam: 0, esperadas: [], completa: true, espera: null, liberacao: null, ...extra });

  it("rótulo do bloco e a metade que espera só onde o órgão junta", () => {
    expect(rotuloDoBloco({ numero: 14, tipo: "execucao" })).toBe("Execução · 14ª Medição");
    expect(rotuloDoBloco({ numero: 14, tipo: "reajuste" })).toBe("Reajuste da 14ª Medição");
    const espera = { medicao_id: 2, titulo: "Reajuste da 14ª Medição", tipo: "reajuste", texto: "esperando as notas do reajuste" };
    const metades = [metade("execucao", { espera }), metade("reajuste", { completa: false })];
    expect(metadeQueEspera({ junta: true, orgao: "SINFRA", metades })?.medicao_id).toBe(1);
    expect(metadeQueEspera({ junta: false, orgao: "MTPAR", metades })).toBeNull();
    expect(metadeQueEspera(null)).toBeNull();
  });
});

const m23: MedicaoBase = {
  id: 723, numero: 23, tipo: "execucao", competencia: "2026-07", estado: "nota_emitida",
  valor_protocolado_centavos: 312456789, valor_atestado_centavos: null, atestado_em: null, recebida_em: null,
  nota_emitida_em: "2026-08-14", protocolos: [],
  notas: [{ nota_id: 5501, numero: "0001843", serie: null, emissao: "2026-08-14", valor_centavos: 100,
            conferencia: [{ campo: "iss", espelho: 1562283, nota: 1571283, grau: "divergente" }] },
          { nota_id: 5503, numero: "0001844", serie: null, emissao: "2026-08-14", valor_centavos: 100,
            conferencia: [{ campo: "irrf", espelho: 1, nota: 2, grau: "arredondamento" }] }],
};
const espelho71: EspelhoResumo = { id: 71, numero: 23, versao: 2, situacao: "vigente", criado_em: "2026-08-06 12:00:00",
  criado_por_nome: "Maria Exemplo", medicoes: [{ id: 763, tipo: "reajuste" }, { id: 723, tipo: "execucao" }],
  envio: { enviado_em: "2026-08-06 22:22:00", remetente: "maria@lotufo" } };
const prot = (id: number, medicoes: number[], extra: Partial<ProtocoloResumo> = {}): ProtocoloResumo => ({
  id, etapa_rotulo: "Medição assinada", numero_oficio: "CT-201-LT-2026", situacao: "montado", criado_em: "2026-08-20 10:00:00",
  medicoes: medicoes.map(x => ({ id: x, titulo: `${x}` })), pendencias: [], ...extra });

describe("medição", () => {
  it("título como o servidor escreve", () => {
    expect(tituloMedicao({ numero: 23, tipo: "reajuste" })).toBe("Reajuste da 23ª Medição");
    expect(tituloMedicao({ numero: 3, tipo: "projeto" })).toBe("3ª Medição de Projeto");
  });

  it("a obra separa as abertas das anteriores, da mais nova para a mais antiga, e resume as notas", () => {
    const m = (numero: number, tipo: string, estado: string) => ({ numero, tipo, estado });
    const { emAndamento, anteriores } = separarMedicoes([m(22, "execucao", "recebida"), m(23, "reajuste", "nota_emitida"),
      m(24, "execucao", "espelho_gerado"), m(23, "execucao", "nota_emitida"), m(21, "execucao", "cancelada")]);
    expect(emAndamento.map(x => `${x.numero}${x.tipo[0]}`)).toEqual(["24e", "23e", "23r"]);
    expect(anteriores.map(x => x.numero)).toEqual([22, 21]);
    expect(resumoNotas({ ...m23, notas: [...m23.notas!, { ...m23.notas![1], nota_id: 9, confirmacao: "confirmada" }] }))
      .toBe("NF 1843, 1844");
    expect(resumoNotas({ ...m23, notas: [] })).toBe("—");
  });

  it("o espelho e o protocolo com várias medições têm um lar só", () => {
    expect(larDoEspelho(espelho71)).toBe(723);
    // issue #208: execucao superada (desmembramento inverso) deixa o lar com o Projeto
    expect(larDoEspelho({ medicoes: [{ id: 1, tipo: "execucao", superado: true }, { id: 2, tipo: "projeto" }] })).toBe(2);
    const p = prot(9, [723, 763]);
    expect(protocolosDa([p], 723)).toEqual({ daqui: [p], deOutra: [] });
    expect(protocolosDa([p], 763)).toEqual({ daqui: [], deOutra: [p] });
  });

  it("o que falta junta notas que divergem, documentos e pendências do protocolo que não são documento", () => {
    const checklist = [{ entidade_id: 1, entidade: "Lotufo", tipo: "CND estadual", chave: "estadual", situacao: "pendente", dias: null },
                       { entidade_id: 1, entidade: "Lotufo", tipo: "FGTS", chave: "fgts", situacao: "ok", dias: 40 }];
    const p = prot(41, [723], { pendencias: [{ codigo: "certidao", mensagem: "certidão pendente" },
                                            { codigo: "nao_assinado", mensagem: "falta o PDF assinado" }] });
    // o R$ vem com espaço inquebrável (Intl); a comparação usa o espaço comum
    expect(itensOQueFalta(m23, 0, checklist, p).map(i => i.texto.replace(/ /g, " "))).toEqual([
      "Nota 1843 diverge do espelho: ISS R$ 15.622,83 no espelho e R$ 15.712,83 na nota",
      "Lotufo: CND estadual · sem validade hoje",
      "falta o PDF assinado",
    ]);
    // o liquido conferido (PR #97) sai com nome em portugues, nao "LIQUIDO"
    const soLiquido = { ...m23, notas: [{ ...m23.notas![0], conferencia: [{ campo: "liquido", espelho: 100, nota: 5100, grau: "divergente" }] }] };
    expect(itensOQueFalta(soLiquido, 0, [], null).map(i => i.texto.replace(/ /g, " ")))
      .toEqual(["Nota 1843 diverge do espelho: Líquido R$ 1,00 no espelho e R$ 51,00 na nota"]);
    expect(itensOQueFalta({ ...m23, estado: "espelho_gerado", notas: [] }, 2, [], null).map(i => i.texto))
      .toEqual(["Enviar o espelho ao faturamento", "Anexar as notas (faltam 2)"]);
  });

  it("linha do tempo em ordem, sem repetir o protocolo enviado pelo sistema", () => {
    const enviado = prot(38, [723], { situacao: "enviado", enviado_em: "2026-08-21 13:00:00", enviado_por: "Maria Exemplo" });
    const m = { ...m23, protocolos: [{ id: 1, data: "2026-08-21", numero_oficio: "CT-201-LT-2026", numero_processo: null,
                                       origem: "manual", protocolo_id: 38 }] };
    expect(eventosDaMedicao(m, [espelho71], [enviado]).map(e => e.texto)).toEqual([
      "Espelho nº 23, versão 2 gerado por Maria Exemplo", "Espelho enviado ao faturamento por maria@lotufo", "Nota emitida",
      "Protocolo criado (Medição assinada · CT-201-LT-2026)", "Protocolo enviado (Medição assinada · CT-201-LT-2026) por Maria Exemplo",
    ]);
  });

  it("linha do tempo traz a edição de valor que o servidor manda (B-02, 10/10/2026)", () => {
    const m = { ...m23, edicoes_valor: [{ data: "2026-08-15 10:00:00", texto: "Valor protocolado alterado de R$ 1,00 para R$ 2,00 por Maria Exemplo" }] };
    expect(eventosDaMedicao(m, [], []).map(e => e.texto)).toEqual([
      "Nota emitida", "Valor protocolado alterado de R$ 1,00 para R$ 2,00 por Maria Exemplo"]);
  });

  it("linha do tempo mostra o nº do SIGA da planilha/carta, que não é protocolo da nota (issue #283)", () => {
    const m = { ...m23, nota_emitida_em: null, estado: "planilha_enviada", protocolos: [],
      planilha_siga: { data: "2026-08-03", numero: "123.456/2026" } };
    const textos = eventosDaMedicao(m, [], []).map(e => e.texto);
    expect(textos).toEqual(["Nº do SIGA da planilha/carta: 123.456/2026"]);
    expect(textos.some(t => t.startsWith("Protocolada"))).toBe(false);
  });
});

describe("itensOQueFalta: o espelho a enviar", () => {
  it("o passo “Enviar o espelho ao faturamento” leva à etapa 2 da página da medição", () => {
    const m = { id: 1, numero: 3, tipo: "execucao", competencia: "2026-09", estado: "espelho_gerado", valor_protocolado_centavos: 1,
      valor_atestado_centavos: null, atestado_em: null, recebida_em: null, protocolos: [] };
    const passo = itensOQueFalta(m, null, [], null).find(i => i.texto === "Enviar o espelho ao faturamento");
    expect(passo && "secao" in passo ? passo.secao : null).toBe("etapa-2");
  });
});
