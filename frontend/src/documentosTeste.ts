// Painel de exemplo (dados inventados) das duas telas de Documentos: usado so' pelos testes (Documentos.test.tsx e
// DocumentosEmpresa.test.tsx). A ordem do servidor poe a empresa em dia primeiro, para o teste ver a pendencia subir.
import type { LinhaCertidao } from "./matriz";

const base = (chave: string, tipo: string, extra: Partial<LinhaCertidao>): LinhaCertidao => ({
  tipo_id: 1, chave, tipo, link_emissao: `https://emissao.exemplo.com.br/${chave}`, exigida: true, situacao: "ok", dias: 120,
  certidao: { id: 1, emissao: "2026-08-01", validade: "2027-01-20", natureza: "negativa" }, ...extra,
});

export const PAINEL = {
  hoje: "2026-09-23",
  empresas: [
    {
      // consorcio cujo orgao nao exige certidao nenhuma: a obra dele (garantia vencida) tem de continuar visivel
      entidade_id: 4, entidade: "Consórcio Sem Certidão", cnpj: "31200808000144", papel: "consorcio", regularidade_exigida: false,
      regularidade: null, consorciadas: [], consorcios: [], obras: [], regularidades_anexadas: [], certidoes: [],
    },
    {
      entidade_id: 3, entidade: "Beta Ltda", cnpj: "31200606000102", papel: "consorciada", regularidade_exigida: false,
      regularidade: null, consorcios: [2], consorciadas: [], obras: [{ contrato_id: 7, obra: "Obra Gama" }],
      regularidades_anexadas: [],
      certidoes: [base("fgts", "CRF/FGTS", { tipo_id: 2 })],
    },
    {
      entidade_id: 2, entidade: "Consórcio Alfa", cnpj: "31200404000152", papel: "consorcio", regularidade_exigida: false,
      regularidade: null, consorciadas: [1, 3], consorcios: [], obras: [{ contrato_id: 7, obra: "Obra Gama" }],
      regularidades_anexadas: [],
      certidoes: [base("fgts", "CRF/FGTS", { tipo_id: 2 })],
    },
    {
      entidade_id: 1, entidade: "Lotufo", cnpj: "31200101000130", papel: "lotufo", regularidade_exigida: true,
      regularidade: { situacao: "atrasada", competencia: "2026-06", esperada: "2026-07" },
      consorciadas: [], consorcios: [2],
      obras: [{ contrato_id: 5, obra: "Obra Alfa" }, { contrato_id: 6, obra: "Obra Beta" }],
      regularidades_anexadas: [{ id: 9, competencia: "2026-06", anexada_em: "2026-07-08" }],
      certidoes: [
        base("fgts", "CRF/FGTS", { tipo_id: 2, situacao: "vencendo", dias: 4,
          certidao: { id: 7, emissao: "2026-08-29", validade: "2026-09-27", natureza: "negativa", leitura: "manual" } }),
        base("municipal", "Certidão de Débitos Gerais (Prefeitura de Cuiabá)", { tipo_id: 5, situacao: "vencida", dias: null,
          certidao: { id: 8, emissao: "2026-08-20", validade: "2026-09-20", natureza: "negativa" } }),
        base("falencia", "Certidão de Falência e Recuperação Judicial (TJMT)", { tipo_id: 6, exigida: false, situacao: "faltando",
          dias: null, certidao: null }),
        base("federal", "Federal", { tipo_id: 1, certidao: { id: 10, emissao: "2026-08-01", validade: "2027-01-20", natureza: "negativa" } }),
      ],
    },
  ],
  contratos: [
    { contrato_id: 5, obra: "Obra Alfa", entidade_id: 1,
      garantia: { apolice: "AP-9", vigencia_fim: "2026-10-05", dias: 12, origem: "endosso" as const, situacao: "vencendo" as const } },
    { contrato_id: 6, obra: "Obra Beta", entidade_id: 1, garantia: null },
    { contrato_id: 8, obra: "Obra Delta", entidade_id: 4,
      garantia: { apolice: null, vigencia_fim: "2026-09-01", dias: -22, origem: "contrato" as const, situacao: "vencida" as const } },
    { contrato_id: 7, obra: "Obra Gama", entidade_id: 2, garantia: null },
  ],
};
