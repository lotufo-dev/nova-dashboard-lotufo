import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fraseDoTempo, textoDoTempo, type Parada } from "./parada";
import TempoParado from "./TempoParado";

// O tempo parado como o servidor manda: os dias úteis, a situação e, no Pagamento, o prazo do órgão. Datas inventadas.
const parada = (extra: Partial<Parada>): Parada => ({
  desde: "2026-11-04", dias_uteis: 10, hoje: false, situacao: "critico", prazo_orgao_dias: null, esperada: null, alem_do_prazo: false, revisao: null, ...extra });

describe("TempoParado (#805)", () => {
  // so' a data e' falsa: o ano de hoje decide se a data esperada leva o ano (#816)
  beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date("2026-11-18T15:00:00Z")); });
  afterEach(() => { cleanup(); vi.useRealTimers(); });

  it("o texto dos dias úteis: hoje, menos de um dia útil, singular e plural", () => {
    expect(textoDoTempo({ dias_uteis: 0, hoje: true })).toBe("hoje");
    expect(textoDoTempo({ dias_uteis: 0, hoje: false })).toBe("menos de 1 dia útil");
    expect(textoDoTempo({ dias_uteis: 1, hoje: false })).toBe("1 dia útil");
    expect(textoDoTempo({ dias_uteis: 12, hoje: false })).toBe("12 dias úteis");
    expect(textoDoTempo({ dias_uteis: null, hoje: false })).toBe("—");
  });

  it("o selo leva a situação que o servidor leu, com o glifo dela", () => {
    for (const s of ["feito", "andamento", "breve", "critico"] as const) {
      const { container } = render(<TempoParado parada={parada({ situacao: s })} />);
      expect(container.querySelector(`.selo--${s} .glifo--${s}`)).not.toBeNull();
      expect(container.querySelector(".selo__texto")?.textContent).toBe("10 dias úteis");
      cleanup();
    }
  });

  it("no Pagamento com prazo do órgão, a data esperada vai escrita: dentro do prazo e depois dele", () => {
    const dentro = render(<TempoParado parada={parada({ dias_uteis: 4, situacao: "andamento", prazo_orgao_dias: 45, esperada: "2026-12-27" })} />);
    expect(dentro.container.querySelector(".tempo-parado__prazo")?.textContent).toBe("prazo do órgão: 27/12");
    cleanup();
    const alem = render(<TempoParado parada={parada({ dias_uteis: 41, prazo_orgao_dias: 45, esperada: "2026-11-09", alem_do_prazo: true })} />);
    expect(alem.container.querySelector(".tempo-parado__prazo")?.textContent).toBe("prazo do órgão venceu em 09/11");
    expect(alem.container.querySelector(".selo--critico")).not.toBeNull();
  });

  it("a data esperada de outro ano leva o ano: a do ano que vem não se lê como passada, e a vencida no ano anterior também diz o ano (#816)", () => {
    const longe = render(<TempoParado parada={parada({ dias_uteis: 98, situacao: "andamento", prazo_orgao_dias: 210, esperada: "2027-01-30" })} />);
    expect(longe.container.querySelector(".tempo-parado__prazo")?.textContent).toBe("prazo do órgão: 30/01/2027");
    cleanup();
    const antiga = render(<TempoParado parada={parada({ dias_uteis: 230, prazo_orgao_dias: 38, esperada: "2025-12-20", alem_do_prazo: true })} />);
    expect(antiga.container.querySelector(".tempo-parado__prazo")?.textContent).toBe("prazo do órgão venceu em 20/12/2025");
    cleanup();
    // virou o ano: a data do ano corrente perde o ano, a do anterior ganha
    vi.setSystemTime(new Date("2027-01-05T15:00:00Z"));
    expect(render(<TempoParado parada={parada({ situacao: "andamento", prazo_orgao_dias: 210, esperada: "2027-01-30" })} />)
      .container.querySelector(".tempo-parado__prazo")?.textContent).toBe("prazo do órgão: 30/01");
    cleanup();
    expect(render(<TempoParado parada={parada({ prazo_orgao_dias: 45, esperada: "2026-12-27", alem_do_prazo: true })} />)
      .container.querySelector(".tempo-parado__prazo")?.textContent).toBe("prazo do órgão venceu em 27/12/2026");
  });

  it("em frase, para o cartão do Resumo das medições: o mesmo selo e o mesmo prazo, e nada sem a data do evento", () => {
    expect(fraseDoTempo({ dias_uteis: 0, hoje: true })).toBe("desde hoje");
    expect(fraseDoTempo({ dias_uteis: 0, hoje: false })).toBe("há menos de 1 dia útil");
    expect(fraseDoTempo({ dias_uteis: 1, hoje: false })).toBe("há 1 dia útil");
    expect(fraseDoTempo({ dias_uteis: 12, hoje: false })).toBe("há 12 dias úteis");
    const { container } = render(<TempoParado frase parada={parada({ dias_uteis: 41, prazo_orgao_dias: 45, esperada: "2026-11-09", alem_do_prazo: true })} />);
    expect(container.querySelector(".selo--critico .selo__texto")?.textContent).toBe("há 41 dias úteis");
    expect(container.querySelector(".tempo-parado__prazo")?.textContent).toBe("prazo do órgão venceu em 09/11");
    cleanup();
    expect(render(<TempoParado frase parada={parada({ desde: null, dias_uteis: null, situacao: null })} />).container.textContent).toBe("");
  });

  it("a medição reapresentada leva a revisão embaixo: 1º protocolo, quantas vezes e o último envio; a de protocolo único, nada (#914)", () => {
    const revisao = { primeiro_protocolo_em: "2026-11-03", reapresentacoes: 2, ultimo_envio_em: "2026-11-17" };
    const r = render(<TempoParado parada={parada({ dias_uteis: 11, situacao: "andamento", prazo_orgao_dias: 45, esperada: "2026-12-18", revisao })} />);
    expect([...r.container.querySelectorAll(".tempo-parado__revisao > span")].map(e => e.textContent)).toEqual([
      "1º protocolo em 03/11", "reapresentada 2 vezes", "último envio em 17/11"]);
    expect(r.container.querySelector(".tempo-parado__prazo")?.textContent).toBe("prazo do órgão: 18/12");
    cleanup();
    const uma = render(<TempoParado frase parada={parada({ revisao: { ...revisao, reapresentacoes: 1, primeiro_protocolo_em: "2025-12-29" } })} />);
    expect(uma.container.querySelector(".tempo-parado__revisao")?.textContent).toBe(
      "1º protocolo em 29/12/2025reapresentada 1 vezúltimo envio em 17/11");
    cleanup();
    expect(render(<TempoParado parada={parada({ prazo_orgao_dias: 45, esperada: "2026-12-18" })} />)
      .container.querySelector(".tempo-parado__revisao")).toBeNull();
    cleanup();
    // onde a linha ja' tem a data do protocolo (pagina Em aberto), sem o "1º protocolo em"
    expect([...render(<TempoParado comPrimeiro={false} parada={parada({ revisao })} />).container
      .querySelectorAll(".tempo-parado__revisao > span")].map(e => e.textContent)).toEqual(["reapresentada 2 vezes", "último envio em 17/11"]);
  });

  it("fora do Pagamento não há prazo escrito; sem a data do evento, só o traço", () => {
    const sem = render(<TempoParado parada={parada({})} />);
    expect(sem.container.querySelector(".tempo-parado__prazo")).toBeNull();
    cleanup();
    const { container } = render(<TempoParado parada={parada({ desde: null, dias_uteis: null, situacao: null })} />);
    expect(container.textContent).toBe("—");
    expect(container.querySelector(".selo")).toBeNull();
  });
});
