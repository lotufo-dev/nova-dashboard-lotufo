import { useState } from "react";
import { api, apiForm, ApiErro } from "./api";
import ConfirmarFaltas from "./ConfirmarFaltas";
import { IconeAlerta } from "./icones";
import Janela from "./Janela";
import { avisoPorFora, mensagem, notasDe, type Envio, type Irma } from "./NotasAEnviar";
import { hojeLocal } from "./tempo";

// "Registrar envio feito fora do sistema" (16/10/2026): UMA acao so', na etapa 4 da pagina da medicao, para o que ja'
// saiu por fora (e-mail pelo Outlook, protocolo no balcao do orgao). Junta o antigo "Registrar envio feito por fora"
// (Notas a enviar) e o "Registrar protocolo feito fora" (pagina da medicao): data, oficio e processo opcionais, o
// e-mail (.eml) opcional. As notas vao para Aguardando pagamento.
//
// O registro grava pelo mesmo POST de antes (/api/notas/envio-externo, que congela o valor protocolado, descarta o
// rascunho do envio e guarda o .eml). O nº do processo no orgao segue por /api/notas/{id}/numero-orgao, que e'
// onde o servidor guarda esse numero nos protocolos feitos por fora. O nº do oficio vai no campo proprio
// (`numero_oficio`, issue #231), que o servidor normaliza e grava no protocolo da medicao; a observacao vai como digitada.
// Issue #230: o registro segue a regra do envio (#213). Falta documento nao bloqueia: o servidor responde 422
// CONFIRMAR_PENDENCIAS com a lista, o aviso "ATENÇÃO" (ConfirmarFaltas) pede a confirmacao e o registro daquele envio
// vai de novo com a lista confirmada (`confirmadas`), que o servidor confere outra vez sob o lock.

export default function RegistrarFora({ envios, medicaoId, aoFechar, aoFeito, aoRecarregar }: {
  envios: Envio[]; aoFechar: () => void; aoFeito: (aviso: string) => void;
  /** a medicao da pagina: so' o envio dela comeca marcado */
  medicaoId: number;
  /** falha no meio, com algo ja' gravado: a pagina le de novo */
  aoRecarregar: () => void;
}) {
  const [data, setData] = useState(hojeLocal());
  const [oficio, setOficio] = useState("");
  const [processo, setProcesso] = useState("");
  const [obs, setObs] = useState("");
  const [eml, setEml] = useState<File | null>(null);
  const dela = envios.filter(e => e.medicao_ids.includes(medicaoId));
  const [marcados, setMarcados] = useState<string[]>((dela.length > 0 ? dela : envios.slice(0, 1)).map(e => e.chave));
  const [parcial, setParcial] = useState(false);
  const [irmasFora, setIrmasFora] = useState<number[]>([]);   // irmas desmarcadas
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");
  // issue #230: a lista confirmada de cada envio, e o envio esperando a confirmacao no aviso
  const [confirmadas, setConfirmadas] = useState<Record<string, string[]>>({});
  const [confirmar, setConfirmar] = useState<{ chave: string; itens: string[]; mudou: boolean } | null>(null);

  const fechar = () => { if (parcial) aoRecarregar(); aoFechar(); };

  function registrar(ev: React.FormEvent) {
    ev.preventDefault();
    void executar(confirmadas);
  }

  async function executar(conf: Record<string, string[]>) {
    setConfirmar(null);
    const escolhidos = envios.filter(e => marcados.includes(e.chave));
    if (escolhidos.length === 0) { setErro("Marque o que saiu neste envio."); return; }
    // a observacao vira a justificativa da ressalva na auditoria: nao ha' texto padrao
    const observacao = obs.trim();
    setOcupado(true); setErro("");
    const feitos: string[] = [];
    const semNumero: string[] = [];
    let todasJuntas: Irma[] = [];
    try {
      for (const e of escolhidos) {
        const juntas = (e.irmas ?? []).filter(i => !irmasFora.includes(i.medicao_id));
        const fd = new FormData();
        for (const id of e.medicao_ids) fd.append("medicao_ids", String(id));
        // a irma vai a' parte: o servidor confere de novo se ela pode ir junto (revisor da PR #178)
        for (const i of juntas) fd.append("irma_ids", String(i.medicao_id));
        fd.append("enviado_em", data);
        fd.append("observacao", observacao);
        // como o processo: cada envio tem o seu oficio, entao so' vai com um envio marcado
        if (oficio.trim() && escolhidos.length === 1) fd.append("numero_oficio", oficio.trim());
        if (eml) fd.append("eml", eml);
        for (const x of conf[e.chave] ?? []) fd.append("confirmadas", x);
        await apiForm("/api/notas/envio-externo", fd);
        feitos.push(e.chave);
        todasJuntas = [...todasJuntas, ...juntas];
        if (processo.trim() && escolhidos.length === 1) {
          // o envio ja' esta' gravado: se o numero nao entrar, a pessoa o registra na etapa 4 (nao refaz o envio)
          for (const id of [...e.medicao_ids, ...juntas.map(i => i.medicao_id)]) {
            try { await api(`/api/notas/${id}/numero-orgao`, { method: "POST", body: JSON.stringify({ numero: processo.trim() }) }); }
            catch (x) { semNumero.push(mensagem(x)); }
          }
        }
      }
      // depois de um registro parcial (o aviso "ATENÇÃO" no meio), o que sobrou e' um so', mas foram varios envios
      const aviso = escolhidos.length === 1 && !parcial ? avisoPorFora(todasJuntas, escolhidos[0].medicao_ids.length)
        : "Envios registrados: as notas foram para Aguardando pagamento.";
      aoFeito(semNumero.length > 0 ? `${aviso} O nº do processo não foi gravado (${semNumero[0]}): registre-o na etapa 4, depois do envio.` : aviso);
    } catch (x) {
      const pendente = escolhidos[feitos.length];
      if (x instanceof ApiErro && x.status === 422 && x.corpo?.codigo === "CONFIRMAR_PENDENCIAS" && pendente) {
        // falta documento neste envio: o aviso pede a confirmacao; os ja' registrados saem da lista e ficam ditos
        if (feitos.length > 0) {
          setMarcados(marcados.filter(c => !feitos.includes(c))); setParcial(true);
          setErro(`Já registrados: ${escolhidos.filter(e => feitos.includes(e.chave)).map(e => e.descricao).join(", ")}.`);
        }
        setConfirmar({ chave: pendente.chave, itens: x.corpo.pendencias ?? [], mudou: (conf[pendente.chave] ?? []).length > 0 });
        setOcupado(false);
        return;
      }
      setErro(feitos.length > 0 ? `${mensagem(x)} Já registrados: ${escolhidos.filter(e => feitos.includes(e.chave)).map(e => e.descricao).join(", ")}.`
        : mensagem(x));
      if (feitos.length > 0) { setMarcados(marcados.filter(c => !feitos.includes(c))); setParcial(true); }
      setOcupado(false);
      return;
    }
    setOcupado(false);
  }

  return (
    <Janela titulo="Registrar envio feito fora do sistema" aoFechar={fechar}>
      <form className="pilha" onSubmit={registrar}>
        <p className="campo__nota">Para o que já saiu por fora: e-mail pelo Outlook ou protocolo no balcão do órgão. As notas vão
          para Aguardando pagamento.</p>
        <div className="form-inline">
          <div className="campo">
            <label className="campo__rotulo" htmlFor="porfora-data">Data do envio (obrigatória)</label>
            <input id="porfora-data" type="date" required autoFocus className="entrada--media" value={data} max={hojeLocal()}
              onChange={e => setData(e.target.value)} />
          </div>
          <div className="campo">
            <label className="campo__rotulo" htmlFor="porfora-oficio">Nº do ofício (opcional)</label>
            <input id="porfora-oficio" name="numero_oficio" type="text" autoComplete="off" spellCheck={false} maxLength={40} placeholder="Ex.: 1234/2026…"
              value={oficio} disabled={marcados.length !== 1} onChange={e => setOficio(e.target.value)} />
          </div>
          <div className="campo">
            <label className="campo__rotulo" htmlFor="porfora-processo">Nº do processo no órgão (opcional)</label>
            <input id="porfora-processo" name="numero_processo" type="text" autoComplete="off" spellCheck={false} maxLength={100} placeholder="Ex.: 0001234-56.2026…"
              value={processo} disabled={marcados.length !== 1} onChange={e => setProcesso(e.target.value)} />
            {marcados.length > 1 && <span className="campo__nota">Cada envio tem o seu ofício e o seu processo: marque um só para informá-los.</span>}
          </div>
        </div>
        <div className="campo">
          <label className="campo__rotulo" htmlFor="porfora-eml">E-mail enviado (.eml, opcional)</label>
          <input id="porfora-eml" type="file" accept=".eml,message/rfc822" onChange={e => setEml(e.target.files?.[0] ?? null)} />
        </div>
        <div className="campo">
          <label className="campo__rotulo" htmlFor="porfora-obs">Como e para quem a nota foi enviada</label>
          <textarea id="porfora-obs" rows={2} maxLength={2000} required value={obs} placeholder="Ex.: pelo Outlook, ao fiscal do contrato…"
            onChange={e => setObs(e.target.value)} />
        </div>
        <fieldset className="opcoes">
          <legend className="campo__rotulo">O que saiu neste envio</legend>
          {envios.map(e => (
            <div key={e.chave} className="pilha">
              <label className="campo--linha">
                <input type="checkbox" checked={marcados.includes(e.chave)}
                  onChange={ev => { const novo = ev.target.checked ? [...marcados, e.chave] : marcados.filter(c => c !== e.chave); setMarcados(novo); if (novo.length > 1) { setProcesso(""); setOficio(""); } }} />
                {e.descricao} · {notasDe(e)}
              </label>
              {(e.irmas ?? []).map(i => (
                <label key={i.medicao_id} className="campo--linha">
                  <input type="checkbox" checked={!irmasFora.includes(i.medicao_id)}
                    onChange={ev => {
                      setIrmasFora(ev.target.checked ? irmasFora.filter(x => x !== i.medicao_id) : [...irmasFora, i.medicao_id]);
                      setConfirmadas({});     // outra composicao: a lista confirmada era a das medicoes de antes
                    }} />
                  Incluir também {i.tipo === "reajuste" ? "o" : "a"} {i.titulo} (saiu no mesmo e-mail)
                </label>
              ))}
            </div>
          ))}
        </fieldset>
        <p className="campo__nota">Registrar congela o valor protocolado das medições marcadas.</p>
        {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
        <div className="iniciar__rodape">
          <button type="submit" className="btn btn--primario" disabled={ocupado || !data || !obs.trim()}>{ocupado ? "Gravando…" : "Registrar"}</button>
          <button type="button" className="btn" onClick={fechar}>Cancelar</button>
        </div>
      </form>
      {confirmar && <ConfirmarFaltas itens={confirmar.itens} mudou={confirmar.mudou}
        aoCancelar={() => {
          // cancelou: o proximo Registrar pergunta de novo (nao reaproveita uma confirmacao que nao valeu)
          setConfirmadas(c => Object.fromEntries(Object.entries(c).filter(([k]) => k !== confirmar.chave)));
          setConfirmar(null);
        }}
        pergunta="Deseja continuar com o registro do envio?" rotuloContinuar="Continuar com o registro"
        aoContinuar={() => {
          const conf = { ...confirmadas, [confirmar.chave]: confirmar.itens };
          setConfirmadas(conf);
          void executar(conf);
        }} />}
    </Janela>
  );
}
