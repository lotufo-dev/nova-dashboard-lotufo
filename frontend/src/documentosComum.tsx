import { forwardRef, useImperativeHandle, useRef, useState } from "react";
import { apiForm, mensagemDeErro } from "./api";
import { IconeEnviarNuvem } from "./icones";
import { NOME_CURTO, type EmpresaDoc } from "./matriz";
import Selo from "./Selo";
// emissao/validade sao DATAS PURAS do papel que o orgao emitiu: fmtDataPura nao passa por fuso.
import { fmtDataPura } from "./tempo";
import type { Nivel } from "./matriz";
import { cnpjBR, NATUREZA, ROTULO_TIPO, TIPOS, type ItemFila, type RespostaLer } from "./documentosDados";
import "./documentos.css";

/* Pecas comuns das duas telas de Documentos (#161): a lista de empresas (Documentos.tsx) e a pagina da empresa
 * (DocumentosEmpresa.tsx). Os dados vem de `documentos.painel` (GET /api/documentos); a regra (o que e' exigido, a
 * situacao de cada certidao) e' do servidor, e a tela so' mostra. */

// D15: "em dia" e' o estado normal e vira ponto e palavra, sem fundo; o selo com fundo fica para Atencao e Critico.
// A maiuscula inicial do selo vem do CSS; o `.estado` nao a poe, entao ela sai daqui.
export function EmDia({ texto }: { texto: string }) {
  return (
    <span className="estado estado--ok">
      <span className="estado__ponto" aria-hidden="true" />{texto.charAt(0).toUpperCase() + texto.slice(1)}
    </span>
  );
}

/** A situacao de uma celula: "em dia" sem fundo, o resto no selo do nivel. */
export function SituacaoSelo({ nivel, texto, forte }: { nivel: Nivel; texto: string; forte?: boolean }) {
  return nivel === "ok" ? <EmDia texto={texto} />
    : <Selo classe={nivel === "neutro" ? "" : `selo--${nivel}`} forte={forte}>{texto}</Selo>;
}

/** A pilula da situacao geral (sempre com fundo): no cartao da empresa e no cabecalho da pagina dela. */
export function Pilula({ nivel, texto }: { nivel: Nivel; texto: string }) {
  return (
    <span className={`selo doc-pilula${nivel === "neutro" ? "" : ` selo--${nivel}`}`}>
      <span className="selo__ponto" aria-hidden="true" /><span className="selo__texto">{texto}</span>
    </span>
  );
}

export function Ponto({ nivel }: { nivel: Nivel }) {
  return <span className={`doc-ponto doc-ponto--${nivel}`} aria-hidden="true" />;
}

export function CnpjCopiar({ e, copia, aoCopiar }: {
  e: EmpresaDoc; copia: { entidade_id: number; ok: boolean } | null; aoCopiar: () => void;
}) {
  return (
    <div className="doc-cnpj">
      CNPJ <span className="num">{cnpjBR(e.cnpj)}</span>
      <button type="button" onClick={aoCopiar} aria-label={`Copiar o CNPJ de ${e.entidade}`}>Copiar</button>
      {/* retorno visivel da copia: some quando outra empresa e' copiada (o anuncio falado e' o status da pagina) */}
      {copia?.entidade_id === e.entidade_id && (
        <span className="doc-copia" aria-hidden="true">{copia.ok ? "CNPJ copiado" : "Não copiou: selecione o número"}</span>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------------------------------------ anexar */

export type AnexarRef = { escolher: (tipo?: string) => void };

/** A area tracejada de arrastar os PDFs das certidoes e a fila de leitura de hoje (lendo, conferir, digitar,
 *  recusada, gravada, descartar). O sistema le o PDF e a pessoa confere; na pagina da empresa, `empresaPadrao` abre
 *  a digitacao ja' nela e a leitura de outra empresa vem com aviso. */
export const AnexarCertidoes = forwardRef<AnexarRef, {
  empresas: EmpresaDoc[]; empresaPadrao?: EmpresaDoc; aoGravar: () => Promise<void>; anunciar: (t: string) => void;
}>(function AnexarCertidoes({ empresas, empresaPadrao, aoGravar, anunciar }, ref) {
  const [fila, setFila] = useState<ItemFila[]>([]);
  const [ocupado, setOcupado] = useState(false);
  const [sobre, setSobre] = useState(false);
  const [erro, setErro] = useState("");
  const seq = useRef(0);
  const entrada = useRef<HTMLInputElement>(null);
  const pedido = useRef<string | undefined>(undefined);

  useImperativeHandle(ref, () => ({
    escolher: (tipo?: string) => { pedido.current = tipo; entrada.current?.click(); },
  }));

  const atualizar = (chave: number, mudanca: Partial<ItemFila>) =>
    setFila(f => f.map(i => (i.chave === chave ? { ...i, ...mudanca } : i)));

  const receber = async (arquivos: File[], tipoPedido?: string) => {
    if (arquivos.length === 0) return;
    setErro("");
    const novos = arquivos.map(arquivo => ({ chave: ++seq.current, arquivo, estado: "lendo" as const, pedido: tipoPedido }));
    setFila(f => [...novos, ...f]);
    // Um por vez, na ordem: a leitura roda em subprocesso no servidor com vagas limitadas.
    for (const item of novos) {
      const fd = new FormData();
      fd.append("arquivo", item.arquivo);
      try {
        const r = await apiForm<RespostaLer>("/api/documentos/certidoes/ler", fd);
        if (r.ok) { atualizar(item.chave, { estado: "conferir", leitura: r.leitura }); anunciar(`${item.arquivo.name}: lida, confira e grave.`); }
        else if (r.digitavel) {
          atualizar(item.chave, {
            estado: "digitar", mensagem: r.mensagem,
            manual: r.lidos
              ? { entidade_id: String(r.lidos.entidade_id), tipo: r.lidos.tipo, emissao: r.lidos.emissao,
                  validade: r.lidos.validade, natureza: r.lidos.natureza }
              : { entidade_id: empresaPadrao ? String(empresaPadrao.entidade_id) : "", tipo: tipoPedido ?? "",
                  emissao: "", validade: "", natureza: "negativa" },
          });
          anunciar(`${item.arquivo.name}: não deu para ler; digite os dados.`);
        } else { atualizar(item.chave, { estado: "recusada", mensagem: r.mensagem }); anunciar(`${item.arquivo.name}: recusada. ${r.mensagem}`); }
      } catch (e) {
        atualizar(item.chave, { estado: "recusada", mensagem: mensagemDeErro(e) });
        anunciar(`${item.arquivo.name}: recusada. ${mensagemDeErro(e)}`);
      }
    }
  };

  const gravar = async (item: ItemFila) => {
    setOcupado(true);
    const fd = new FormData();
    fd.append("arquivo", item.arquivo);
    if (item.estado === "digitar" && item.manual) {
      for (const [k, v] of Object.entries(item.manual)) if (v) fd.append(k, v);
    }
    try {
      const r = await apiForm<{ entidade: string; tipo: string; validade: string }>("/api/documentos/certidoes", fd);
      const texto = `${r.entidade} · ${ROTULO_TIPO[r.tipo] ?? r.tipo} · válida até ${fmtDataPura(r.validade)}`;
      atualizar(item.chave, { estado: "gravada", mensagem: texto });
      anunciar(`Gravada: ${texto}.`);
      await aoGravar();
    } catch (e) {
      atualizar(item.chave, { mensagem: mensagemDeErro(e), ...(item.estado === "conferir" ? { estado: "recusada" as const } : {}) });
    } finally { setOcupado(false); }
  };

  const descartar = (chave: number) => setFila(f => f.filter(i => i.chave !== chave));

  // O que a leitura achou que difere do que a pessoa pediu (outra empresa, outro tipo): vira nota antes de gravar.
  const avisoDe = (item: ItemFila): string[] => {
    const l = item.leitura;
    if (!l) return [];
    const avisos: string[] = [];
    if (empresaPadrao && l.entidade_id !== empresaPadrao.entidade_id) {
      avisos.push(`Este PDF é de ${l.entidade}, não de ${empresaPadrao.entidade}: ao gravar, a certidão vai para ${l.entidade}.`);
    }
    if (item.pedido && l.tipo !== item.pedido) {
      avisos.push(`Você clicou em Anexar na certidão ${NOME_CURTO[item.pedido] ?? item.pedido}, mas o PDF é ${NOME_CURTO[l.tipo] ?? l.tipo_nome}.`);
    }
    return avisos;
  };

  return (
    <>
      {erro && <p className="erro" role="alert">{erro}</p>}
      <div className={`doc-zona${sobre ? " doc-zona--sobre" : ""}`}
        onDragEnter={ev => { ev.preventDefault(); setSobre(true); }}
        onDragOver={ev => { ev.preventDefault(); setSobre(true); }}
        onDragLeave={ev => { ev.preventDefault(); setSobre(false); }}
        onDrop={ev => {
          ev.preventDefault(); setSobre(false);
          const pdfs = Array.from(ev.dataTransfer.files).filter(f => f.type === "application/pdf" || /\.pdf$/i.test(f.name));
          if (pdfs.length === 0) { setErro("Só PDF: arraste o arquivo da certidão."); return; }
          void receber(pdfs);
        }}>
        <IconeEnviarNuvem className="icone doc-zona__icone" />
        <p>Arraste os PDFs das certidões aqui ou{" "}
          <button type="button" className="doc-zona__link" onClick={() => { pedido.current = undefined; entrada.current?.click(); }}>escolher os arquivos</button></p>
        <input ref={entrada} type="file" accept="application/pdf" multiple hidden aria-label="Escolher PDFs de certidões para anexar"
          onChange={ev => {
            const input = ev.currentTarget;
            const arquivos = Array.from(input.files ?? []);
            input.value = "";
            const tipo = pedido.current;
            pedido.current = undefined;
            void receber(arquivos, tipo);
          }} />
      </div>

      {fila.length > 0 && (
        <ul className="documentos__fila doc-fila">
          {fila.map(item => (
            <li key={item.chave} className="documentos__item">
              <span className="documentos__arquivo">{item.arquivo.name}</span>
              {item.estado === "lendo" && <span className="campo__nota">lendo…</span>}
              {item.estado === "conferir" && item.leitura && (
                <>
                  <span>
                    {item.leitura.entidade} · {ROTULO_TIPO[item.leitura.tipo] ?? item.leitura.tipo_nome} · {NATUREZA[item.leitura.natureza]}
                    {" "}· emitida em {fmtDataPura(item.leitura.emissao)} · válida até {fmtDataPura(item.leitura.validade)}
                    {item.leitura.validade_calculada ? " (30 dias úteis)" : ""}
                    {item.leitura.numero ? ` · nº ${item.leitura.numero}` : ""}
                  </span>
                  {item.leitura.ocr && (
                    <span className="campo__nota">PDF sem texto, lido por OCR: confira empresa e datas com o PDF antes de gravar.</span>
                  )}
                  {avisoDe(item).map(a => <span key={a} className="notas__diverge">{a}</span>)}
                  <span className="form-inline">
                    {/* botao comum: o primario da pagina fica para a pendencia mais urgente */}
                    <button type="button" className="btn btn--pequeno" disabled={ocupado}
                      onClick={() => gravar(item)}>Gravar certidão<span className="sr-only"> de {item.arquivo.name}</span></button>
                    <button type="button" className="btn btn--pequeno" onClick={() => descartar(item.chave)}>Descartar</button>
                  </span>
                </>
              )}
              {item.estado === "recusada" && (
                <>
                  <span className="notas__diverge">{item.mensagem}</span>
                  <span className="form-inline">
                    <button type="button" className="btn btn--pequeno" onClick={() => descartar(item.chave)}>Descartar</button>
                  </span>
                </>
              )}
              {item.estado === "gravada" && <span className="notas__ok">gravada: {item.mensagem}</span>}
              {item.estado === "digitar" && item.manual && (
                <form className="form-inline" onSubmit={ev => { ev.preventDefault(); void gravar(item); }}>
                  <span className="campo__nota doc-digitar__msg">{item.mensagem}</span>
                  <div className="campo">
                    <label className="campo__rotulo" htmlFor={`d-ent-${item.chave}`}>Empresa</label>
                    <select id={`d-ent-${item.chave}`} required value={item.manual.entidade_id}
                      onChange={ev => atualizar(item.chave, { manual: { ...item.manual!, entidade_id: ev.target.value } })}>
                      <option value="">—</option>
                      {empresas.map(e => <option key={e.entidade_id} value={e.entidade_id}>{e.entidade}</option>)}
                    </select>
                  </div>
                  <div className="campo">
                    <label className="campo__rotulo" htmlFor={`d-tipo-${item.chave}`}>Tipo</label>
                    <select id={`d-tipo-${item.chave}`} required value={item.manual.tipo}
                      onChange={ev => atualizar(item.chave, { manual: { ...item.manual!, tipo: ev.target.value } })}>
                      <option value="">—</option>
                      {TIPOS.map(t => <option key={t.chave} value={t.chave}>{t.rotulo}</option>)}
                    </select>
                  </div>
                  <div className="campo">
                    <label className="campo__rotulo" htmlFor={`d-em-${item.chave}`}>Emissão</label>
                    <input id={`d-em-${item.chave}`} type="date" required value={item.manual.emissao}
                      onChange={ev => atualizar(item.chave, { manual: { ...item.manual!, emissao: ev.target.value } })} />
                  </div>
                  <div className="campo">
                    <label className="campo__rotulo" htmlFor={`d-val-${item.chave}`}>
                      Validade{item.manual.tipo === "falencia" ? " (vazia: 30 dias úteis)" : ""}
                    </label>
                    <input id={`d-val-${item.chave}`} type="date" required={item.manual.tipo !== "falencia"}
                      value={item.manual.validade}
                      onChange={ev => atualizar(item.chave, { manual: { ...item.manual!, validade: ev.target.value } })} />
                  </div>
                  <div className="campo">
                    <label className="campo__rotulo" htmlFor={`d-nat-${item.chave}`}>Natureza</label>
                    <select id={`d-nat-${item.chave}`} value={item.manual.natureza}
                      onChange={ev => atualizar(item.chave, { manual: { ...item.manual!, natureza: ev.target.value } })}>
                      <option value="negativa">negativa</option>
                      <option value="positiva_efeito_negativa">positiva com efeito de negativa</option>
                    </select>
                  </div>
                  <button type="submit" className="btn btn--pequeno" disabled={ocupado}>Gravar certidão<span className="sr-only"> de {item.arquivo.name}</span></button>
                  <button type="button" className="btn btn--pequeno" onClick={() => descartar(item.chave)}>Descartar</button>
                </form>
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  );
});
