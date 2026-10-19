import { useEffect, useMemo, useRef, useState } from "react";
import { IconeAlerta, IconeRelogio } from "./icones";
import { Link } from "./Link";
import type { Usuario } from "./Login";
import {
  certidoesOrdenadas, JANELA_DIAS, matriz, NOME_CURTO, pendenciasDa, proximaAVencer, resumoEmpresa, situacaoCertidao,
  situacaoGarantia, type EmpresaDoc, type Nivel, type ObraDoc,
} from "./matriz";
import { substituir, trocarBusca, type Busca } from "./rota";
import { fmtCompetencia as mesBR, fmtDataPura } from "./tempo";
import { AnexarCertidoes, CnpjCopiar, Pilula, Ponto } from "./documentosComum";
import { useCopiarCnpj, usePainel } from "./documentosDados";

/* Documentos (#161, redesenho aprovado em 16/10/2026): UM CARTAO POR EMPRESA, com a situacao geral, um ponto por
 * certidao e a proxima a vencer; o cartao inteiro leva a pagina da empresa (DocumentosEmpresa.tsx). Quem tem
 * pendencia vem primeiro. O que e' exigido vem do cadastro do orgao; a tela so' mostra o que o servidor respondeu
 * (`documentos.painel`), sem recalcular regra. Filtro na URL: ?pendentes=1.
 */

const PAPEL: Record<string, string> = { lotufo: "Empresa", consorcio: "Consórcio", consorciada: "Consorciada" };

// Garantia que pede algo da empresa, como linhas do cartao ("Garantia de Obra X: vence em 20 dias").
function avisosDeObras(e: EmpresaDoc, contratos: ObraDoc[]): { nivel: Nivel; texto: string }[] {
  const out: { nivel: Nivel; texto: string }[] = [];
  for (const k of contratos) {
    if (k.entidade_id !== e.entidade_id) continue;
    const g = situacaoGarantia(k.garantia, k.garantia ? fmtDataPura(k.garantia.vigencia_fim) : "");
    if (g.nivel === "acao" || g.nivel === "atencao") out.push({ nivel: g.nivel, texto: `Garantia de ${k.obra}: ${g.texto}` });
  }
  return out;
}

/** A janela do ZIP: a data vale para todas e sai um ZIP por empresa marcada. */
function JanelaZip({ empresas, hoje, aoFechar }: { empresas: EmpresaDoc[]; hoje: string; aoFechar: () => void }) {
  const janela = useRef<HTMLDialogElement>(null);
  const [data, setData] = useState(hoje);
  const [marcadas, setMarcadas] = useState<Set<number>>(() => new Set(empresas.map(e => e.entidade_id)));
  const [baixando, setBaixando] = useState(false);
  const [resultado, setResultado] = useState<{ ok: boolean; texto: string } | null>(null);

  useEffect(() => {
    const d = janela.current;
    if (!d || d.open) return;
    // jsdom (testes) nao implementa showModal: la' a janela so' abre
    if (typeof d.showModal === "function") d.showModal(); else d.setAttribute("open", "");
  }, []);

  const baixar = async () => {
    const lista = empresas.filter(e => marcadas.has(e.entidade_id));
    if (lista.length === 0) { setResultado({ ok: false, texto: "Marque ao menos uma empresa." }); return; }
    setBaixando(true); setResultado(null);
    const falhas: string[] = [];
    let feitos = 0;
    // Um por vez: o servidor monta cada ZIP na hora, e a empresa sem certidao vigente naquele dia responde com o
    // motivo (que a janela mostra), em vez de baixar uma pagina de erro.
    for (const e of lista) {
      try {
        const r = await fetch(`/api/documentos/zip?entidade_id=${e.entidade_id}&data=${data}`, { credentials: "same-origin" });
        if (!r.ok) {
          const corpo = await r.json().catch(() => null) as { detail?: unknown } | null;
          falhas.push(`${e.entidade}: ${typeof corpo?.detail === "string" ? corpo.detail : "não deu para montar o ZIP"}.`);
          continue;
        }
        const nome = /filename\*=UTF-8''([^;]+)/i.exec(r.headers.get("Content-Disposition") ?? "")?.[1];
        const url = URL.createObjectURL(await r.blob());
        const a = document.createElement("a");
        a.href = url; a.download = nome ? decodeURIComponent(nome) : `Certidoes - ${e.entidade}.zip`;
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
        feitos++;
      } catch { falhas.push(`${e.entidade}: não deu para baixar.`); }
    }
    setBaixando(false);
    setResultado({
      ok: falhas.length === 0,
      texto: [feitos ? `${feitos === 1 ? "1 ZIP baixado" : `${feitos} ZIPs baixados`}.` : "", ...falhas].filter(Boolean).join(" "),
    });
  };

  return (
    <dialog ref={janela} className="doc-janela" aria-labelledby="titulo-zip" onClose={aoFechar}
      // clique no fundo (fora da caixa) fecha, como numa janela comum
      onClick={ev => { if (ev.target === ev.currentTarget) janela.current?.close(); }}>
      <div className="doc-janela__cabeca"><h2 id="titulo-zip">ZIP das certidões vigentes</h2></div>
      <div className="doc-janela__corpo">
        <div className="campo">
          <label className="campo__rotulo" htmlFor="data-zip">Certidões vigentes em</label>
          <input id="data-zip" type="date" className="entrada--media" value={data} onChange={ev => setData(ev.target.value)} />
          <span className="campo__nota">Para licitação ou protocolo: junta as certidões válidas nessa data.</span>
        </div>
        <fieldset>
          <legend>Empresas (um ZIP por empresa)</legend>
          {empresas.map(e => (
            <label key={e.entidade_id} className="doc-marca">
              <input type="checkbox" checked={marcadas.has(e.entidade_id)}
                onChange={ev => setMarcadas(m => { const n = new Set(m); if (ev.target.checked) n.add(e.entidade_id); else n.delete(e.entidade_id); return n; })} />
              {e.entidade}
            </label>
          ))}
        </fieldset>
        <p className={resultado ? (resultado.ok ? "notas__ok" : "notas__diverge") : "sr-only"} role="status">{resultado?.texto ?? ""}</p>
      </div>
      <div className="doc-janela__rodape">
        <button type="button" className="btn" onClick={() => janela.current?.close()}>{resultado ? "Fechar" : "Cancelar"}</button>
        <button type="button" className="btn btn--primario" disabled={baixando || !data} onClick={() => void baixar()}>
          {baixando ? "Baixando…" : "Baixar ZIP"}
        </button>
      </div>
    </dialog>
  );
}

function Cartao({ e, nomes, contratos, copia, aoCopiar }: {
  e: EmpresaDoc; nomes: Map<number, string>; contratos: ObraDoc[];
  copia: { entidade_id: number; ok: boolean } | null; aoCopiar: () => void;
}) {
  const r = resumoEmpresa(e, contratos);
  const proxima = proximaAVencer(e);
  const extras: { nivel: Nivel | null; texto: string; titulo?: string }[] = [];
  if (e.regularidade) {
    const g = e.regularidade;
    extras.push({ nivel: g.situacao === "ok" ? "ok" : "atencao",
      texto: `Regularidade do mês (DP): ${g.situacao === "ok" ? "em dia" : g.situacao === "faltando" ? "nenhuma anexada" : "atrasada"}${
        g.situacao === "ok" ? ` · ${mesBR(g.competencia)}` : ` · esperada ${mesBR(g.esperada)}`}` });
  }
  const consorciadas = (e.consorciadas ?? []).map(id => nomes.get(id)).filter((n): n is string => !!n);
  if (consorciadas.length) extras.push({ nivel: null, texto: `Consorciadas: ${consorciadas.join(", ")}` });
  extras.push(...avisosDeObras(e, contratos));
  const obras = (e.obras ?? []).map(o => o.obra);
  if (obras.length) {
    const lista = obras.length > 3 ? `${obras.slice(0, 3).join(", ")} e mais ${obras.length - 3}` : obras.join(", ");
    extras.push({ nivel: null, texto: `Exigida em ${obras.length === 1 ? "1 obra" : `${obras.length} obras`}: ${lista}`, titulo: obras.join(", ") });
  }
  return (
    <article className="cartao emp-cartao" id={`emp-${e.entidade_id}`}>
      <div className="emp-cartao__cabeca">
        <span className="emp-cartao__papel">{PAPEL[e.papel] ?? e.papel}</span>
        <h2 className="emp-cartao__nome">
          <Link para={{ tela: "documentos-empresa", id: e.entidade_id }}>{e.entidade}</Link>
        </h2>
        <CnpjCopiar e={e} copia={copia} aoCopiar={aoCopiar} />
      </div>
      <Pilula nivel={r.nivel} texto={r.texto} />
      <ul className="doc-pontos" aria-label="Certidões">
        {certidoesOrdenadas(e).map(l => {
          const s = situacaoCertidao(l, l.certidao ? fmtDataPura(l.certidao.validade) : "");
          return (
            <li key={l.chave} title={`${l.tipo}: ${s.texto}${l.certidao && l.exigida ? ` · até ${fmtDataPura(l.certidao.validade)}` : ""}`}>
              <Ponto nivel={s.nivel} />{NOME_CURTO[l.chave] ?? l.tipo}<span className="sr-only">: {s.texto}</span>
            </li>
          );
        })}
      </ul>
      <div className="emp-cartao__extra">
        {extras.map(x => (
          <p key={x.texto} title={x.titulo}>{x.nivel && <Ponto nivel={x.nivel} />}<span>{x.texto}</span></p>
        ))}
      </div>
      <div className="emp-cartao__rodape">
        <IconeRelogio className="icone icone--p" />
        <span>{proxima
          ? <>Próxima a vencer: <strong>{NOME_CURTO[proxima.chave] ?? proxima.tipo} em {fmtDataPura(proxima.certidao!.validade)}</strong></>
          : "Nenhuma certidão vigente"}</span>
        <svg className="icone icone--p doc-seta" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l6 6-6 6" /></svg>
      </div>
    </article>
  );
}

export default function Documentos({ usuario, busca = {} }: { usuario: Usuario; busca?: Busca }) {
  const soPendentes = busca.pendentes === "1";
  const podeEditar = usuario.perfil !== "diretoria";
  const { painel, erro, carregar } = usePainel();
  const [anuncio, setAnuncio] = useState("");
  const [zip, setZip] = useState(false);
  const { copiar, copia } = useCopiarCnpj(setAnuncio);
  // Link salvo da tela antiga (/documentos?empresa=N): abre a pagina da empresa, trocando o endereco no lugar.
  const empresaAntiga = /^[1-9][0-9]{0,14}$/.test(busca.empresa ?? "") ? Number(busca.empresa) : null;
  useEffect(() => {
    if (empresaAntiga !== null) substituir({ tela: "documentos-empresa", id: empresaAntiga }, { semBusca: true });
  }, [empresaAntiga]);

  // A ordem (e, com ?pendentes=1, quem aparece) e' a da carga e a de cada troca de filtro; o que muda depois de
  // gravar fica no lugar ate' a pagina recarregar, para a pessoa ver o resultado no cartao em que estava.
  const carregado = painel !== null;
  const ordem = useMemo(() => painel ? matriz(painel.empresas, soPendentes, painel.contratos ?? []).map(e => e.entidade_id) : [],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [carregado, soPendentes]);

  const empresas = painel?.empresas ?? [];
  const porId = new Map(empresas.map(e => [e.entidade_id, e]));
  const lista = ordem.map(id => porId.get(id)).filter((e): e is EmpresaDoc => e !== undefined);
  const nomes = new Map(empresas.map(e => [e.entidade_id, e.entidade]));
  const pendentes = empresas.filter(e => pendenciasDa(e, painel?.contratos ?? []) > 0).length;
  const qtd = empresas.length === 1 ? "1 empresa" : `${empresas.length} empresas`;
  const recorte = soPendentes
    ? `Mostrando ${pendentes === 1 ? "a única" : `as ${pendentes}`} com pendência, de ${qtd}`
    : `${qtd} · ${pendentes === 1 ? "1 com pendência" : `${pendentes} com pendência`}`;

  return (
    <div className="pagina">
      <p className="pagina__descricao">
        Certidões e regularidade de cada empresa. Clique no cartão para ver as certidões, a regularidade do mês e a garantia
        das obras.
      </p>
      {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
      {/* sempre montada: o Copiar aparece para todos os perfis e anuncia aqui */}
      <p className="sr-only" role="status">{anuncio}</p>

      <div className="doc-topo">
        <div className="doc-topo__texto">
          {painel && painel.empresas.length > 0 && (
            <p className="campo__nota num" role="status">
              {recorte} (pendência: vencida, falta ou vence em até {JANELA_DIAS}{" "}dias; a regularidade do mês fora do dia
              também conta). Empresa com problema primeiro.
            </p>
          )}
        </div>
        <div className="doc-topo__acoes">
          <label className="doc-chave">
            <input type="checkbox" checked={soPendentes}
              onChange={ev => trocarBusca({ pendentes: ev.target.checked ? "1" : null })} />
            <span className="doc-chave__trilho" aria-hidden="true" />
            Só as com pendência
          </label>
          <button type="button" className="btn btn--primario" disabled={!painel || empresas.length === 0} onClick={() => setZip(true)}>
            ZIP das certidões vigentes
          </button>
        </div>
      </div>

      <p className="doc-legenda" aria-label="Legenda dos pontos">
        <span><Ponto nivel="ok" />em dia</span>
        <span><Ponto nivel="atencao" />vence em até {JANELA_DIAS} dias</span>
        <span><Ponto nivel="acao" />vencida ou falta</span>
        <span><Ponto nivel="neutro" />não exigida ou não se aplica</span>
      </p>

      {!painel && !erro && <p className="campo__nota">Carregando…</p>}
      {painel && empresas.length === 0 && (
        <div className="vazio"><p className="vazio__titulo">Nenhuma empresa com documento exigido</p></div>
      )}
      {painel && empresas.length > 0 && (
        <section aria-label="Empresas">
          {lista.length === 0 ? (
            <div className="cartao vazio">
              <p className="vazio__titulo">Nenhuma empresa com pendência.</p>
              <p>Desligue “Só as com pendência” para ver todas.</p>
            </div>
          ) : (
            <div className="emp-grade">
              {lista.map(e => (
                <Cartao key={e.entidade_id} e={e} nomes={nomes} contratos={painel.contratos ?? []} copia={copia}
                  aoCopiar={() => void copiar(e.entidade_id, e.cnpj, e.entidade)} />
              ))}
            </div>
          )}
        </section>
      )}

      {painel && empresas.length > 0 && podeEditar && (
        <section aria-labelledby="titulo-anexar" className="pilha">
          <h2 className="doc-secao-titulo" id="titulo-anexar">Anexar certidões de qualquer empresa</h2>
          <AnexarCertidoes empresas={empresas} aoGravar={carregar} anunciar={setAnuncio} />
        </section>
      )}

      {zip && painel && <JanelaZip empresas={empresas} hoje={painel.hoje} aoFechar={() => setZip(false)} />}
    </div>
  );
}
