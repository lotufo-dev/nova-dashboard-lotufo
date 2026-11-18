import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { textoDoTempo, type Parada } from "./parada";
import TempoParado from "./TempoParado";

// O tempo parado como o servidor manda: os dias úteis, a situação e, no Pagamento, o prazo do órgão. Datas inventadas.
const parada = (extra: Partial<Parada>): Parada => ({
  desde: "2026-11-04", dias_uteis: 10, hoje: false, situacao: "critico", prazo_orgao_dias: null, esperada: null, alem_do_prazo: false, ...extra });

describe("TempoParado (#805)", () => {
  afterEach(cleanup);

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

  it("fora do Pagamento não há prazo escrito; sem a data do evento, só o traço", () => {
    const sem = render(<TempoParado parada={parada({})} />);
    expect(sem.container.querySelector(".tempo-parado__prazo")).toBeNull();
    cleanup();
    const { container } = render(<TempoParado parada={parada({ desde: null, dias_uteis: null, situacao: null })} />);
    expect(container.textContent).toBe("—");
    expect(container.querySelector(".selo")).toBeNull();
  });
});
