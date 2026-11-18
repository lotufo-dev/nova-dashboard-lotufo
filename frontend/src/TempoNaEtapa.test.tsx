import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import TempoNaEtapa from "./TempoNaEtapa";

const HOJE = "2026-11-16";
const selo = (desde: string | null, diasUteis: number | null) => {
  const { container } = render(<TempoNaEtapa desde={desde} diasUteis={diasUteis} hoje={HOJE} />);
  const el = container.querySelector(".selo");
  return el ? [el.className, el.textContent] : null;
};

describe("TempoNaEtapa (#805, família tempo parado)", () => {
  afterEach(cleanup);

  it("os limites são os do SIGA: menos de 5 dias úteis em andamento, 5 ou mais vence em breve, 10 ou mais crítico", () => {
    expect(selo("2026-11-13", 1)).toEqual(["selo selo--andamento", "há 1 dia útil"]);
    expect(selo("2026-11-10", 4)).toEqual(["selo selo--andamento", "há 4 dias úteis"]);
    expect(selo("2026-11-09", 5)).toEqual(["selo selo--breve", "há 5 dias úteis"]);
    expect(selo("2026-11-03", 9)).toEqual(["selo selo--breve", "há 9 dias úteis"]);
    expect(selo("2026-10-30", 10)).toEqual(["selo selo--critico", "há 10 dias úteis"]);
  });

  it("chegou hoje é feito; o evento no fim de semana ainda não completou um dia útil", () => {
    expect(selo(HOJE, 0)).toEqual(["selo selo--feito", "desde hoje"]);
    expect(selo("2026-11-14", 0)).toEqual(["selo selo--andamento", "há menos de 1 dia útil"]);
  });

  it("sem a data do evento, nada aparece: o tempo não conta da competência", () => {
    expect(selo(null, null)).toBeNull();
    expect(selo("2026-11-10", null)).toBeNull();
    expect(selo(null, 4)).toBeNull();
  });
});
