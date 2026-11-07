import { describe, expect, it } from "vitest";
import { frasePrazo, processoDa } from "./PassoAnalise";
import { diaMes, passoDe, passoInicial, passosDa, situacaoDoPasso } from "./Passos";
import type { ProcessoSiga } from "./siga";

// issue #508: a barra de passos da pagina da obra em medicao
describe("passoDe", () => {
  it("com a planilha/carta indo ao órgão: planilha e carta, análise, espelhos, notas, envio da nota e pagamento", () => {
    expect(["prevista", "planilha_gerada", "planilha_enviada", "boletim_recebido", "espelho_gerado", "espelho_enviado",
      "nota_emitida", "protocolada", "nf_emitida", "recebida"].map(e => passoDe(e, true))).toEqual([1, 1, 2, 3, 3, 4, 5, 6, 6, 7]);
  });

  it("sem os passos da planilha (MT-PAR, reajuste, obra fora do espelho): começa em Espelhos", () => {
    expect(["prevista", "planilha_gerada", "planilha_enviada", "boletim_recebido"].map(e => passoDe(e, false))).toEqual([3, 3, 3, 3]);
    expect(passosDa(false)).toEqual([3, 4, 5, 6]);
    expect(passosDa(true)).toEqual([1, 2, 3, 4, 5, 6]);
  });

  it("cancelada e desistida ficam encerradas (todos os passos feitos, nenhum da vez)", () => {
    expect(passoDe("cancelada", true)).toBe(0);
    expect(passoDe("desistida", false)).toBe(0);
    expect(situacaoDoPasso(6, 0)).toBe("feito");
  });

  it("a página abre o passo da vez; tudo feito abre o pagamento; encerrada abre as notas ou o primeiro da barra", () => {
    expect(passoInicial(2, false, passosDa(true))).toBe(2);
    expect(passoInicial(7, true, passosDa(true))).toBe(6);
    expect(passoInicial(0, true, passosDa(false))).toBe(4);
    expect(passoInicial(0, false, passosDa(false))).toBe(3);
  });
});

describe("textos do passo 2", () => {
  it("dd/mm da data pura e do carimbo UTC (o dia em Cuiabá)", () => {
    expect(diaMes("2026-11-05")).toBe("05/11");
    expect(diaMes("2026-11-06T02:30:00Z")).toBe("05/11");      // 22h30 do dia 5 em Cuiabá
    expect(diaMes(null)).toBeNull();
  });

  it("com o órgão há N dias úteis", () => {
    expect(frasePrazo(0)).toBe("Com o órgão há menos de 1 dia útil");
    expect(frasePrazo(1)).toBe("Com o órgão há 1 dia útil");
    expect(frasePrazo(4)).toBe("Com o órgão há 4 dias úteis");
    expect(frasePrazo(null)).toBe("Com o órgão");
  });

  it("o processo do SIGA: o ligado à medição (o do nº, se houver), senão o do nº", () => {
    const p = (id: number, medicao_id: number | null, numero: string) => ({ id, medicao_id, numero }) as ProcessoSiga;
    const lista = [p(1, 5, "A"), p(2, 5, "B"), p(3, null, "C")];
    expect(processoDa(lista, 5, "B")!.id).toBe(2);
    expect(processoDa(lista, 5, null)!.id).toBe(1);
    expect(processoDa(lista, 9, "C")!.id).toBe(3);
    expect(processoDa(lista, 9, null)).toBeNull();
    // o processo ligado a outra medicao nunca aparece, nem pelo mesmo nº (code-review)
    expect(processoDa(lista, 9, "B")).toBeNull();
  });
});
