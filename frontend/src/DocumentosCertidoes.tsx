import { useEffect, useMemo, useRef, useState } from "react";
import Contador from "./Contador";
import { IconeClipe, IconeLinkExterno } from "./icones";
import type { ItemLegenda } from "./LegendaCor";
import { Link } from "./Link";
import type { Usuario } from "./Login";
import { certidoesVencendo, chipCertidao, empresasComCertidaoExigida, type EmpresaDoc, type RenovarDoc } from "./matriz";
import { fmtDataPura } from "./tempo";
import { Chip, MolduraDocumentos, type AnexarRef } from "./documentosComum";
import { NOME_CHIP, PAPEL, usePainel } from "./documentosDados";

/* Certidoes (#513, #658; pagina propria na #820): "o que vence antes do proximo protocolo?". O "Renovar agora" (a
 * lista do servidor) e a matriz empresa x certidao de hoje, uma linha por empresa com a certidao exigida. O "Anexar
 * PDF" do alto recebe qualquer PDF; o servidor decide pelo conteudo se e' certidao ou regularidade
 * (`/api/documentos/anexar`). Endereco: "/documentos", o que a tela Documentos sempre teve. */

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
    <dialog ref={janela} className="doc-janela cartao" aria-labelledby="titulo-zip" onClose={aoFechar}
      // clique no fundo (fora da caixa) fecha, como numa janela comum
      onClick={ev => { if (ev.target === ev.currentTarget) janela.current?.close(); }}>
      <div className="doc-janela__cabeca"><h2 id="titulo-zip">ZIP das certidões vigentes</h2></div>
      <div className="doc-janela__corpo">
        <div className="campo">
          <label className="campo__rotulo" htmlFor="data-zip">Certidões vigentes em</label>
          <input id="data-zip" type="date" className="entrada--media" value={data} onChange={ev => setData(ev.target.value)} />
        </div>
        <fieldset>
          <legend>Empresas</legend>
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

const CHIPS_CERTIDAO = ["federal", "fgts", "trabalhista", "estadual", "municipal"] as const;

/** A matriz empresa x certidao: uma linha por empresa, o chip de cada certidao abre o PDF; o ZIP das vigentes na
 *  linha (todos os perfis baixam). */
function PorEmpresa({ empresas, aoZip }: { empresas: EmpresaDoc[]; aoZip: (e: EmpresaDoc) => void }) {
  return (
    <section className="cartao doc-bloco" aria-labelledby="titulo-por-empresa">
      <h2 id="titulo-por-empresa" className="doc-bloco__titulo">Por empresa</h2>
      <ul className="doc-linhas" aria-label="Certidões por empresa">
      {empresas.map(e => (
        <li key={e.entidade_id} className="doc-linha">
          <div className="doc-linha__nome">
            <Link para={{ tela: "documentos-empresa", id: e.entidade_id }}>{e.entidade}</Link>
            <span>{PAPEL[e.papel] ?? e.papel}</span>
            <button type="button" className="doc-linha__zip" onClick={() => aoZip(e)}
              aria-label={`ZIP das certidões vigentes de ${e.entidade}`}>ZIP das vigentes</button>
          </div>
          <div className="doc-chips doc-chips--5">
            {CHIPS_CERTIDAO.map(chave => {
              const l = e.certidoes.find(x => x.chave === chave);
              const c = chipCertidao(l, l?.certidao ? fmtDataPura(l.certidao.validade) : "");
              return (
                <Chip key={chave} cor={c.cor} rotulo={NOME_CHIP[chave]} valor={c.valor} data={c.data}
                  href={l?.certidao && c.cor !== "neutro" ? `/api/certidoes/${l.certidao.id}/arquivo` : undefined}
                  titulo={l?.certidao ? "Abrir o PDF (o histórico está na página da empresa)" : undefined} />
              );
            })}
            {/* falência: só onde exigida */}
            {e.certidoes.some(l => l.chave === "falencia" && l.exigida) && (() => {
              const l = e.certidoes.find(x => x.chave === "falencia")!;
              const c = chipCertidao(l, l.certidao ? fmtDataPura(l.certidao.validade) : "");
              return <Chip cor={c.cor} rotulo="Falência" valor={c.valor} data={c.data}
                href={l.certidao ? `/api/certidoes/${l.certidao.id}/arquivo` : undefined} />;
            })()}
          </div>
        </li>
      ))}
      </ul>
    </section>
  );
}

/** "Renovar agora" (#658): o que trava o proximo protocolo, uma linha por certidao. A lista e' do servidor; sem nada
 *  a renovar o bloco nao existe. Quem so' consulta ve as linhas, sem Emitir nem Anexar. */
function RenovarAgora({ itens, podeEditar, aoAnexar }: { itens: RenovarDoc[]; podeEditar: boolean; aoAnexar: (chave: string) => void }) {
  if (itens.length === 0) return null;
  return (
    <section className="cartao doc-bloco doc-renovar" aria-labelledby="titulo-renovar">
      <h2 id="titulo-renovar" className="doc-bloco__titulo">Renovar agora</h2>
      <ul className="doc-linhas">
        {itens.map(x => {
          const nome = NOME_CHIP[x.chave] ?? (x.chave === "falencia" ? "Falência" : x.tipo);
          const critico = x.situacao === "vencida" || x.situacao === "faltando" || x.dias === 0;
          const valor = !x.validade ? "sem registro" : x.situacao === "vencida" ? "vencida" : x.dias === 0 ? "hoje" : `${x.dias} d`;
          return (
            <li key={`${x.entidade_id}-${x.chave}`} className="doc-linha doc-linha--renovar">
              <div className="doc-linha__nome"><span className="doc-linha__obra">{x.entidade}</span></div>
              <span className="doc-renovar__certidao">{nome}</span>
              <Chip semRotulo cor={critico ? "critico" : "breve"} rotulo="Validade" valor={valor}
                data={x.validade ? fmtDataPura(x.validade) : undefined} />
              {podeEditar && (
                <div className="doc-renovar__acoes">
                  {x.link_emissao && (
                    <a href={x.link_emissao} target="_blank" rel="noreferrer" className="btn btn--pequeno btn--primario"
                      aria-label={`Emitir ${nome} de ${x.entidade} (abre o site do órgão)`}>
                      <IconeLinkExterno className="icone" />Emitir
                    </a>
                  )}
                  <button type="button" className="btn btn--pequeno" aria-label={`Anexar ${nome} de ${x.entidade}`}
                    onClick={() => aoAnexar(x.chave)}>
                    <IconeClipe className="icone" />Anexar
                  </button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

const LEGENDA: ItemLegenda[] = [
  { situacao: "feito", texto: "em dia" }, { situacao: "breve", texto: "vence antes do próximo protocolo" }, { situacao: "critico", texto: "vencida" },
];

export default function DocumentosCertidoes({ usuario }: { usuario: Usuario }) {
  const podeEditar = usuario.perfil !== "diretoria";
  const { painel, erro, carregar } = usePainel();
  const [zip, setZip] = useState<EmpresaDoc | null>(null);
  const anexar = useRef<AnexarRef>(null);
  // O link salvo da tela antiga (/documentos?empresa=N) e' trocado pelo App (App.tsx), ao lado do ?aba=.

  const empresas = useMemo(() => painel?.empresas ?? [], [painel]);
  // #651: a matriz so' lista quem tem certidao exigida; o "Anexar PDF" segue com todas
  const comCertidao = useMemo(() => empresasComCertidaoExigida(empresas), [empresas]);
  // #658: o contador e' o que esta' em "Renovar agora" (a lista do servidor)
  const renovar = painel?.renovar_agora;
  const n = painel ? (renovar ? renovar.length : certidoesVencendo(comCertidao)) : 0;

  return (
    <MolduraDocumentos classe="doc-certidoes" erro={erro} carregado={!!painel} legenda={LEGENDA}
      contador={n > 0 ? <Contador situacao="critico">{`${n} a renovar`}</Contador> : null}
      anexar={podeEditar ? (painel ? { empresas, aoGravar: carregar } : null) : undefined} refAnexar={anexar}>
      {comCertidao.length === 0 && <div className="vazio"><p className="vazio__titulo">Nenhuma empresa.</p></div>}
      <RenovarAgora itens={renovar ?? []} podeEditar={podeEditar} aoAnexar={chave => anexar.current?.escolher(chave)} />
      {comCertidao.length > 0 && <PorEmpresa empresas={comCertidao} aoZip={setZip} />}
      {zip && painel && <JanelaZip empresas={[zip]} hoje={painel.hoje} aoFechar={() => setZip(null)} />}
    </MolduraDocumentos>
  );
}
