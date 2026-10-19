import { useCallback, useEffect, useRef, useState } from "react";
import { api, mensagemDeErro } from "./api";
import type { EmpresaDoc, ObraDoc } from "./matriz";

/* Dados e ganchos comuns das duas telas de Documentos (#161); as pecas de tela ficam em documentosComum.tsx. */

export type Painel = { hoje: string; empresas: EmpresaDoc[]; contratos?: ObraDoc[] };
export type Lida = {
  tipo: string; tipo_nome: string; natureza: string; entidade_id: number; entidade: string;
  emissao: string; validade: string; numero: string | null; validade_calculada: boolean; ocr?: boolean;
};
// `lidos` (gate Sol S6, 10/10/2026): datas lidas fora do prazo normal; a digitacao abre ja' preenchida com elas.
export type RespostaLer = { ok: true; leitura: Lida } | { ok: false; motivo: string; mensagem: string; digitavel: boolean;
  lidos?: { entidade_id: number; tipo: string; emissao: string; validade: string; natureza: string } };

export type Manual = { entidade_id: string; tipo: string; emissao: string; validade: string; natureza: string };
export type ItemFila = {
  chave: number; arquivo: File; estado: "lendo" | "conferir" | "digitar" | "recusada" | "gravada";
  leitura?: Lida; mensagem?: string; manual?: Manual;
  pedido?: string;      // o tipo da linha em que a pessoa clicou "Anexar" (a leitura do PDF e' quem decide o tipo)
};

export const TIPOS: { chave: string; rotulo: string }[] = [
  { chave: "federal", rotulo: "Federal (RFB/PGFN)" }, { chave: "fgts", rotulo: "FGTS (CRF)" },
  { chave: "trabalhista", rotulo: "Trabalhista (CNDT)" }, { chave: "estadual", rotulo: "Estadual (SEFAZ/PGE-MT)" },
  { chave: "municipal", rotulo: "Municipal (Cuiabá)" }, { chave: "falencia", rotulo: "Falência (TJMT)" },
];
export const ROTULO_TIPO: Record<string, string> = Object.fromEntries(TIPOS.map(t => [t.chave, t.rotulo]));
export function cnpjBR(c: string): string {
  return c.length === 14 ? `${c.slice(0, 2)}.${c.slice(2, 5)}.${c.slice(5, 8)}/${c.slice(8, 12)}-${c.slice(12)}` : c;
}

// "042026 - LOTUFO ENGENHARIA.pdf" -> "2026-04": o DP nomeia o PDF pela competencia.
export function competenciaDoNome(nome: string): string {
  const m = /^(0[1-9]|1[0-2])(\d{4})\b/.exec(nome.trim());
  return m ? `${m[2]}-${m[1]}` : "";
}

/** O painel de Documentos, carregado uma vez; `carregar` o refaz (depois de gravar). */
export function usePainel() {
  const [painel, setPainel] = useState<Painel | null>(null);
  const [erro, setErro] = useState("");
  const carregar = useCallback(async () => { setPainel(await api<Painel>("/api/documentos")); }, []);
  useEffect(() => { carregar().catch(e => setErro(mensagemDeErro(e))); }, [carregar]);
  return { painel, erro, setErro, carregar };
}

/** O CNPJ com o botao Copiar. `navigator.clipboard` so' existe em contexto seguro, e a producao roda em http: sem ele,
 *  a copia antiga (textarea + execCommand). O resultado e' anunciado; se nada funcionar, a pessoa seleciona o numero. */
export function useCopiarCnpj(anunciar: (t: string) => void) {
  const [copia, setCopia] = useState<{ entidade_id: number; ok: boolean } | null>(null);
  const ultima = useRef<{ id: number; n: number } | null>(null);   // a mesma empresa copiada de novo muda o texto anunciado
  const copiar = async (id: number, cnpj: string, nome: string) => {
    let ok = false;
    try { if (navigator.clipboard) { await navigator.clipboard.writeText(cnpj); ok = true; } } catch { ok = false; }
    if (!ok) {
      const area = document.createElement("textarea");
      area.value = cnpj; area.setAttribute("readonly", ""); area.style.position = "fixed"; area.style.opacity = "0";
      document.body.appendChild(area); area.select();
      try { ok = document.execCommand("copy"); } catch { ok = false; }
      area.remove();
    }
    // A regiao viva so' fala quando o texto muda: a 2a copia do mesmo CNPJ alterna a frase (N05-09).
    const n = ultima.current?.id === id ? ultima.current.n + 1 : 1;
    ultima.current = { id, n };
    const de = n === 1 ? "" : n % 2 === 0 ? " de novo" : " outra vez";
    anunciar(ok ? `CNPJ de ${nome} copiado${de}.` : `Não deu para copiar o CNPJ de ${nome}${de}: selecione o número.`);
    setCopia({ entidade_id: id, ok });
  };
  return { copiar, copia };
}


export const NATUREZA: Record<string, string> = { negativa: "negativa", positiva_efeito_negativa: "positiva com efeito de negativa" };

