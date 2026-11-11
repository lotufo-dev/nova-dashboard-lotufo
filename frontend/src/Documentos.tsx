import { useEffect, useMemo, useRef, useState } from "react";
import { IconeAlerta, IconeCheck, IconeEnviarNuvem, IconeRelogio, IconeTraco } from "./icones";
import { Link } from "./Link";
import type { Usuario } from "./Login";
import {
  certidoesVencendo, chipCertidao, chipValidadeGarantia, competenciasRegularidade, empresasComCertidaoExigida, empresasComFolha,
  estadosRegularidade, garantiasAConferir, obrasPorOrgao, regularidadesFaltando, type CorChip, type EmpresaDoc, type ObraDoc,
} from "./matriz";
import { substituir, trocarBusca, type Busca } from "./rota";
import { fmtCompetencia, fmtDataPura, fmtMesCurto, fmtMesExtenso } from "./tempo";
import { AnexarCertidoes, type AnexarRef } from "./documentosComum";
import { usePainel } from "./documentosDados";

/* Documentos (#513, redesenho aprovado em 07/11/2026): tres abas com contador, uma linha por empresa (ou por obra)
 * e chips coloridos. Certidoes (dias que faltam), Regularidade mensal (os seis ultimos meses do DP) e Garantias
 * (por orgao). O "Anexar PDF" do topo recebe qualquer PDF; o servidor decide pelo conteudo se e' certidao ou
 * regularidade (`/api/documentos/anexar`). A regra (o que e' exigido, a situacao) e' do servidor
 * (`documentos.painel`); a tela so' mostra. Aba na URL: ?aba=regularidade|garantias.
 */

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

const ABAS = [
  { id: "certidoes", rotulo: "Certidões", sufixo: (n: number) => `${n} vencendo`, cor: "critico" },
  { id: "regularidade", rotulo: "Regularidade mensal", sufixo: (n: number) => `${n} faltando`, cor: "critico" },
  // #651: do ultimo documento vencido so' se sabe a data; o contador pede conferencia, sem vermelho
  { id: "garantias", rotulo: "Garantias", sufixo: (n: number) => `${n} a conferir`, cor: "breve" },
] as const;
type IdAba = (typeof ABAS)[number]["id"];

const ICONE_ESTADO = { anexada: IconeCheck, faltando: IconeTraco, aguardando: IconeRelogio } as const;
const COR_ESTADO = { anexada: "feito", faltando: "breve", aguardando: "andamento", sem: "neutro" } as const;
const TEXTO_ESTADO = { anexada: "anexada", faltando: "faltando", aguardando: "aguardando o DP", sem: "sem registro" } as const;

function Chip({ cor, rotulo, valor, data, href, titulo, semRotulo }: {
  cor: CorChip; rotulo: string; valor: string; data?: string; href?: string; titulo?: string; semRotulo?: boolean;
}) {
  const corpo = (
    <>
      <span className={semRotulo ? "sr-only" : "doc-chip__rotulo"}>{rotulo}</span>
      <span className="doc-chip__valor"><b>{valor}</b>{data ? <small>{data}</small> : null}</span>
    </>
  );
  const classe = `doc-chip doc-chip--${cor}${semRotulo ? " doc-chip--linha" : ""}`;
  return href
    ? <a className={classe} href={href} target="_blank" rel="noreferrer" title={titulo}>{corpo}</a>
    : <div className={classe} title={titulo}>{corpo}</div>;
}

const PAPEL: Record<string, string> = { lotufo: "própria", consorcio: "consórcio", consorciada: "consorciada" };

function AbaCertidoes({ empresas, podeBaixar, aoZip }: {
  empresas: EmpresaDoc[]; podeBaixar: boolean; aoZip: (e: EmpresaDoc) => void;
}) {
  return (
    <ul className="doc-linhas" aria-label="Certidões por empresa">
      {empresas.map(e => (
        <li key={e.entidade_id} className="doc-linha">
          <div className="doc-linha__nome">
            <Link para={{ tela: "documentos-empresa", id: e.entidade_id }}>{e.entidade}</Link>
            <span>{PAPEL[e.papel] ?? e.papel}</span>
            {podeBaixar && (
              <button type="button" className="doc-linha__zip" onClick={() => aoZip(e)}
                aria-label={`ZIP das certidões vigentes de ${e.entidade}`}>ZIP das vigentes</button>
            )}
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
  );
}

const CHIPS_CERTIDAO = ["federal", "fgts", "trabalhista", "estadual", "municipal"] as const;
const NOME_CHIP: Record<string, string> = { federal: "Federal", fgts: "FGTS", trabalhista: "CNDT", estadual: "Estadual", municipal: "Municipal" };

function AbaRegularidade({ empresas, hoje }: { empresas: EmpresaDoc[]; hoje: string }) {
  const comFolha = empresasComFolha(empresas);
  const semFolha = empresas.filter(e => !comFolha.includes(e));
  const meses = competenciasRegularidade(hoje);
  const ultimoMes = meses[meses.length - 1].competencia;
  const seguinte = `${ultimoMes.slice(5, 7) === "12" ? String(Number(ultimoMes.slice(0, 4)) + 1) : ultimoMes.slice(0, 4)}-${String(Number(ultimoMes.slice(5, 7)) % 12 + 1).padStart(2, "0")}`;
  return (
    <>
      <ul className="doc-linhas" aria-label="Regularidade mensal por empresa">
        {comFolha.map(e => {
          const ultima = (e.regularidades_anexadas ?? [])[0];
          return (
            <li key={e.entidade_id} className="doc-linha">
              <div className="doc-linha__nome">
                <Link para={{ tela: "documentos-empresa", id: e.entidade_id, aba: "regularidade" }}>{e.entidade}</Link>
                <span>{PAPEL[e.papel] ?? e.papel}</span>
              </div>
              <div className="doc-chips doc-chips--6">
                {estadosRegularidade(e, hoje).map(x => {
                  const nome = `${fmtCompetencia(x.competencia)}: ${TEXTO_ESTADO[x.estado]}`;
                  const Icone = x.estado === "sem" ? null : ICONE_ESTADO[x.estado];
                  const interior = (
                    <>
                      <span className="doc-chip__rotulo">{fmtMesCurto(x.competencia)}</span>
                      {/* #651: mes que ninguem cobra (antes do primeiro PDF da empresa) e' so' "—" */}
                      {Icone ? <Icone className="icone doc-chip__icone" titulo={nome} />
                        : <b className="doc-chip__icone" role="img" aria-label={nome}>—</b>}
                    </>
                  );
                  return x.id !== undefined
                    ? <a key={x.competencia} className={`doc-chip doc-chip--icone doc-chip--${COR_ESTADO[x.estado]}`}
                        href={`/api/documentos/regularidades/${x.id}/arquivo`} target="_blank" rel="noreferrer">{interior}</a>
                    : <div key={x.competencia} className={`doc-chip doc-chip--icone doc-chip--${COR_ESTADO[x.estado]}`}>{interior}</div>;
                })}
              </div>
              <p className="doc-linha__ultima">
                {ultima ? `última: ${fmtMesExtenso(ultima.competencia)}, ${ultima.anexada_em.slice(8, 10)}/${ultima.anexada_em.slice(5, 7)}` : "—"}
              </p>
            </li>
          );
        })}
      </ul>
      {semFolha.length > 0 && <p className="doc-nota">Não exigida: {semFolha.map(e => e.entidade).join(", ")}</p>}
      <p className="doc-nota">{(() => { const m = fmtMesExtenso(ultimoMes); return m.charAt(0).toUpperCase() + m.slice(1); })()} esperada a partir de 10/{seguinte.slice(5, 7)}.</p>
    </>
  );
}

const OBRAS_POR_GRUPO = 8;

function GrupoGarantias({ orgao, obras }: { orgao: string; obras: ObraDoc[] }) {
  const [tudo, setTudo] = useState(false);
  const vistas = tudo ? obras : obras.slice(0, OBRAS_POR_GRUPO);
  return (
    <section className="doc-grupo" aria-label={`Garantias de ${orgao}`}>
      <div className="doc-linha doc-linha--cabeca">
        <h2 className="doc-grupo__cabeca">{orgao} <span>· {obras.length} {obras.length === 1 ? "obra" : "obras"}</span></h2>
        <div className="doc-chips doc-chips--5" aria-hidden="true">
          {["Apólice", "Válida até", "Cobre a execução", "CNO"].map(r => <span key={r}>{r}</span>)}
        </div>
      </div>
      <ul className="doc-linhas">
        {vistas.map(o => {
          const g = o.garantia;
          const valida = chipValidadeGarantia(g, g ? fmtDataPura(g.vigencia_fim) : "");
          const cob = o.cobre_execucao;
          return (
            <li key={o.contrato_id} className="doc-linha doc-linha--obra">
              <div className="doc-linha__nome"><span className="doc-linha__obra">{o.obra}</span></div>
              <div className="doc-chips doc-chips--5">
                <Chip semRotulo cor={g?.apolice ? "feito" : "critico"} rotulo="Apólice" valor={g?.apolice || "sem registro"} />
                <Chip semRotulo cor={valida.cor} rotulo="Válida até" valor={valida.valor} />
                <Chip semRotulo cor={!g ? "critico" : cob?.cobre === true ? "feito" : cob?.cobre === false && cob.ate ? "breve" : "neutro"}
                  rotulo="Cobre a execução"
                  valor={!g ? "sem registro" : cob?.cobre === true ? "sim" : cob?.cobre === false && cob.ate ? `não, até ${fmtDataPura(cob.ate)}` : "—"} />
                <Chip semRotulo cor={o.cno ? "feito" : "critico"} rotulo="CNO" valor={o.cno ? "registrado" : "sem registro"} />
              </div>
            </li>
          );
        })}
      </ul>
      {obras.length > OBRAS_POR_GRUPO && (
        <button type="button" className="doc-grupo__mais" onClick={() => setTudo(t => !t)}>
          {tudo ? "mostrar menos" : `+${obras.length - OBRAS_POR_GRUPO} obras`}
        </button>
      )}
    </section>
  );
}

const LEGENDAS: Record<IdAba, { classe: string; texto: string }[]> = {
  certidoes: [{ classe: "feito", texto: "em dia" }, { classe: "breve", texto: "vence em até 7 dias" }, { classe: "critico", texto: "vencida" }],
  regularidade: [{ classe: "feito", texto: "anexada" }, { classe: "andamento", texto: "aguardando o DP" }, { classe: "breve", texto: "faltando" }],
  garantias: [{ classe: "feito", texto: "em dia" }, { classe: "breve", texto: "não cobre" }, { classe: "critico", texto: "sem registro" }],
};

function LegendaAba({ aba }: { aba: IdAba }) {
  return (
    <ul className="legenda-cor" aria-label="Legenda das cores">
      {LEGENDAS[aba].map(i => <li key={i.texto}><span className={`pilula-info__ponto ponto--${i.classe}`} />{i.texto}</li>)}
    </ul>
  );
}

export default function Documentos({ usuario, busca = {} }: { usuario: Usuario; busca?: Busca }) {
  const podeEditar = usuario.perfil !== "diretoria";
  const { painel, erro, carregar } = usePainel();
  const [anuncio, setAnuncio] = useState("");
  const [zip, setZip] = useState<EmpresaDoc | null>(null);
  const anexar = useRef<AnexarRef>(null);
  const aba: IdAba = busca.aba === "regularidade" || busca.aba === "garantias" ? busca.aba : "certidoes";
  // Link salvo da tela antiga (/documentos?empresa=N): abre a pagina da empresa, trocando o endereco no lugar.
  const empresaAntiga = /^[1-9][0-9]{0,14}$/.test(busca.empresa ?? "") ? Number(busca.empresa) : null;
  useEffect(() => {
    if (empresaAntiga !== null) substituir({ tela: "documentos-empresa", id: empresaAntiga }, { semBusca: true });
  }, [empresaAntiga]);

  const empresas = useMemo(() => painel?.empresas ?? [], [painel]);
  // #651: a aba Certidoes so' lista quem tem certidao exigida; o "Anexar PDF" e a aba Regularidade seguem com todas
  const comCertidao = useMemo(() => empresasComCertidaoExigida(empresas), [empresas]);
  const obras = painel?.contratos ?? [];
  const hoje = painel?.hoje ?? "";
  const contadores: Record<IdAba, number> = painel ? {
    certidoes: certidoesVencendo(comCertidao),
    regularidade: regularidadesFaltando(empresas),
    garantias: garantiasAConferir(obras),
  } : { certidoes: 0, regularidade: 0, garantias: 0 };

  return (
    <div className="pagina">
      {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
      <p className="sr-only" role="status">{anuncio}</p>

      <div className="doc-topo">
        <LegendaAba aba={aba} />
        <div className="doc-topo__acoes">
          {podeEditar && (
            <button type="button" className="btn btn--primario" disabled={!painel} onClick={() => anexar.current?.escolher()}>
              <IconeEnviarNuvem className="icone" />Anexar PDF
            </button>
          )}
        </div>
      </div>

      {painel && (
        <div className="doc-abas" role="tablist" aria-label="Documentos">
          {ABAS.map(a => (
            <button key={a.id} type="button" role="tab" id={`aba-${a.id}`} aria-selected={aba === a.id}
              aria-controls="painel-documentos" className="doc-aba"
              onClick={() => trocarBusca({ aba: a.id === "certidoes" ? null : a.id })}>
              {a.rotulo}{contadores[a.id] > 0 && <> · <span className={`info--${a.cor}`}>{a.sufixo(contadores[a.id])}</span></>}
            </button>
          ))}
        </div>
      )}

      {!painel && !erro && <p className="campo__nota">Carregando…</p>}
      {painel && (aba === "certidoes" ? comCertidao : empresas).length === 0 && aba !== "garantias" && (
        <div className="vazio"><p className="vazio__titulo">Nenhuma empresa.</p></div>
      )}
      {painel && (
        <div id="painel-documentos" role="tabpanel" aria-labelledby={`aba-${aba}`} className="doc-painel-aba">
          {aba === "certidoes" && <AbaCertidoes empresas={comCertidao} podeBaixar={true} aoZip={setZip} />}
          {aba === "regularidade" && <AbaRegularidade empresas={empresas} hoje={hoje} />}
          {aba === "garantias" && (
            obras.length === 0 ? <div className="vazio"><p className="vazio__titulo">Nenhuma obra ativa.</p></div>
              : obrasPorOrgao(obras).map(g => <GrupoGarantias key={g.orgao} orgao={g.orgao} obras={g.obras} />)
          )}
        </div>
      )}

      {/* a fila de leitura do "Anexar PDF" (fica montada para o botao do topo sempre ter onde abrir) */}
      {painel && podeEditar && (
        <AnexarCertidoes ref={anexar} empresas={empresas} aoGravar={carregar} anunciar={setAnuncio} unificado semZona />
      )}

      {zip && painel && <JanelaZip empresas={[zip]} hoje={painel.hoje} aoFechar={() => setZip(null)} />}
    </div>
  );
}
