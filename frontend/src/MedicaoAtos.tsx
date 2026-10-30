import { useEffect, useState } from "react";
import CaixaAviso from "./CaixaAviso";
import CampoValor from "./CampoValor";
import ErroCampo from "./ErroCampo";
import { api } from "./api";
import { IconeAlerta } from "./icones";
import { Link } from "./Link";
import { DO_ESPELHO, EXCECOES, type Metade } from "./medicao";
import type { Medicao } from "./Medicoes";
import Selo from "./Selo";

// Os atos de UMA medicao (valor, recebimento, cancelar ou desistir, medicao final), num formulario
// que a pagina da medicao abre numa janela. O protocolo feito fora virou o "Registrar envio feito fora do sistema"
// da etapa 4 (RegistrarFora.tsx). Mesmas chamadas de API
// de antes; quem abre passa `agir`, que grava, recarrega e diz se a gravacao foi aceita.

// `feito`: a frase de sucesso que a tela anuncia (role=status) quando a gravacao e' aceita.
export type Agir = (fn: () => Promise<unknown>, feito?: string) => Promise<boolean>;

// Valor para o campo de texto: "50.000,00" (sem "R$"), no formato que o parse_brl do servidor aceita.
export function brlCampo(centavos: number | null): string {
  if (centavos === null) return "";
  return (centavos / 100).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** O protocolado congela no 1o protocolo (marco externo); o atestado segue editavel para registrar glosa --
 *  exceto em cancelada/desistida, onde o servidor recusa os dois campos. Congelada AINDA SEM valor e' a
 *  excecao: o servidor aceita esse primeiro preenchimento, e so' ele. Valor que veio do espelho nao se edita
 *  a mao em estado nenhum: muda gerando o espelho de novo (testes de quebra 10/10/2026, A-16). */
export function valorEditavel(m: Medicao, campo: "protocolado" | "atestado", podeEditar: boolean): boolean {
  return podeEditar && !EXCECOES.includes(m.estado)
    && !(campo === "protocolado" && DO_ESPELHO.includes(m.estado))
    && !(campo === "protocolado" && m.valor_protocolado_origem === "espelho")
    && !(campo === "protocolado" && m.congelada === 1 && m.valor_protocolado_centavos !== null);
}

// `erro`: a recusa do servidor aparece DENTRO do formulario, perto de onde se agiu (a pagina da medicao e'
// longa, e o aviso no topo ficaria fora da vista).
type Base = { m: Medicao; salvando: boolean; agir: Agir; aoFechar: () => void; erro?: string };

function Erro({ erro }: { erro?: string }) {
  return erro ? <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p> : null;
}

type PropsValor = Base & { campo: "protocolado" | "atestado" };

// Trocar de "Editar o valor" para "Editar o atestado" com o painel aberto reaproveitaria o formulario, e o
// useState guardaria o valor do outro campo (gate Sol S2, #190): a chave faz um formulario novo por campo.
export function FormValor(props: PropsValor) {
  return <FormValorDoCampo key={`${props.m.id}-${props.campo}`} {...props} />;
}

function FormValorDoCampo({ m, campo, salvando, agir, aoFechar, erro }: PropsValor) {
  const [valor, setValor] = useState(brlCampo(campo === "protocolado" ? m.valor_protocolado_centavos : m.valor_atestado_centavos));
  const [data, setData] = useState(m.atestado_em ?? "");
  async function salvar(ev: React.FormEvent) {
    ev.preventDefault();
    const ok = await agir(() => api(`/api/medicoes/${m.id}/valor`, {
      method: "PUT", body: JSON.stringify({
        campo, valor,
        // A data so' viaja com o atestado (o servidor recusa a combinacao com o protocolado) e so' quando
        // preenchida: vazia, a anterior fica.
        ...(campo === "atestado" && data ? { data } : {}),
      }),
    }), campo === "protocolado" ? "Valor protocolado gravado." : "Valor atestado gravado.");
    if (ok) aoFechar();
  }
  return (
    <form onSubmit={salvar} onKeyDown={ev => ev.key === "Escape" && aoFechar()}>
      <p className="painel__titulo">
        {campo === "protocolado" ? `Valor protocolado da ${m.numero}ª medição` : `Valor atestado da ${m.numero}ª medição`}
      </p>
      <Erro erro={erro} />
      <div className="form-inline">
        <div className="campo">
          <label className="campo__rotulo" htmlFor="campo-valor">Valor (R$)</label>
          <CampoValor id="campo-valor" name="valor" required autoFocus value={valor} onChange={setValor} />
        </div>
        {campo === "atestado" && (
          <div className="campo">
            <label className="campo__rotulo" htmlFor="campo-data-atesto">Atestada em (opcional)</label>
            <input id="campo-data-atesto" name="data_atesto" autoComplete="off" type="date" className="entrada--media" value={data}
              onChange={ev => setData(ev.target.value)} />
          </div>
        )}
        <button type="submit" className="btn btn--primario" disabled={salvando}>{salvando ? "Salvando…" : "Salvar valor"}</button>
        <button type="button" className="btn" onClick={aoFechar}>Cancelar</button>
      </div>
    </form>
  );
}

// Recorte do checklist "pronto para protocolar" (app/checklist.py) que o ato precisa: o veredito e os
// documentos pendentes. A regra mora no servidor.
// gate Sol S6 (10/10/2026): o servidor recusa menos que isso ao protocolar com pendencia (protocolo.MIN_JUSTIFICATIVA)
const MIN_JUSTIFICATIVA = 10;

type Checklist = {
  entidade: string | null; pronto: boolean;
  itens: { entidade_id: number; entidade: string | null; tipo: string; situacao: string }[];
};

/** Registrar protocolo feito FORA do sistema (o "Protocolar" antigo da linha): data, oficio, processo e o
 *  checklist do ato, que trava com certidao pendente ate' o operador assumir e justificar. */
export function FormProtocoloManual({ contratoId, m, salvando, agir, aoFechar, erro }: Base & { contratoId: number }) {
  const [proto, setProto] = useState({ data: "", oficio: "", processo: "", siga: "" });
  // `undefined` = ainda lendo; `null` = a leitura falhou (o servidor decide sozinho ao gravar).
  const [checklist, setChecklist] = useState<Checklist | null | undefined>(undefined);
  const [apesar, setApesar] = useState(false);
  const [justificativa, setJustificativa] = useState("");
  const [tentou, setTentou] = useState(false);   // clicou em Registrar: so' ai' os campos mostram o que falta

  useEffect(() => {
    let vivo = true;
    // A exigencia depende da natureza: o reajuste pode pedir menos que a medicao.
    api<Checklist>(`/api/contratos/${contratoId}/checklist-protocolo?natureza=${m.tipo}`)
      .then(c => { if (vivo) setChecklist(c); })
      .catch(() => { if (vivo) setChecklist(null); });
    return () => { vivo = false; };
  }, [contratoId, m.tipo]);

  const pendentes = checklist ? checklist.itens.filter(i => i.situacao === "pendente") : [];

  // O botao nao fica apagado esperando o formulario valer (issue #11): o clique diz o que falta, junto do campo.
  const faltas = {
    data: !proto.data ? "Informe a data do protocolo." : undefined,
    apesar: pendentes.length > 0 && !apesar
      ? "Marque “Protocolar apesar das pendências” e justifique, ou anexe os documentos em Documentos." : undefined,
    justificativa: pendentes.length > 0 && apesar && justificativa.trim().length < MIN_JUSTIFICATIVA
      ? `Escreva a justificativa, com pelo menos ${MIN_JUSTIFICATIVA} caracteres.` : undefined,
  };
  const erroDe = (campo: keyof typeof faltas) => tentou ? faltas[campo] : undefined;
  const ligacao = (campo: keyof typeof faltas, id: string) =>
    erroDe(campo) ? { "aria-invalid": true as const, "aria-describedby": `${id}-erro` } : {};

  async function salvar(ev: React.FormEvent) {
    ev.preventDefault();
    setTentou(true);
    const primeira = faltas.data ? "campo-data" : faltas.apesar ? "campo-apesar" : faltas.justificativa ? "campo-justificativa" : null;
    if (primeira) { document.getElementById(primeira)?.focus(); return; }
    const ok = await agir(() => api(`/api/medicoes/${m.id}/protocolo`, {
      method: "POST",
      body: JSON.stringify({
        data: proto.data, numero_oficio: proto.oficio || null, numero_processo: proto.processo || null,
        ...(proto.siga.trim() ? { link_siga: proto.siga.trim() } : {}),
        // So' quando o operador assumiu a pendencia: sem isso o servidor trava o protocolo com certidao
        // pendente (422) e a mensagem dele aparece aqui.
        ...(apesar ? { apesar_das_pendencias: true, justificativa } : {}),
      }),
    }), "Protocolo registrado.");
    if (ok) aoFechar();
  }

  return (
    <form onSubmit={salvar} noValidate onKeyDown={ev => ev.key === "Escape" && aoFechar()}>
      <p className="painel__titulo">Registrar protocolo feito fora do sistema: {m.numero}ª medição</p>
      <Erro erro={erro} />
      <div className="form-inline">
        <div className="campo">
          <label className="campo__rotulo" htmlFor="campo-data">Data do protocolo</label>
          <input id="campo-data" name="data_protocolo" autoComplete="off" type="date" className="entrada--media" required autoFocus
            {...ligacao("data", "campo-data")}
            value={proto.data} onChange={ev => setProto({ ...proto, data: ev.target.value })} />
          <ErroCampo id="campo-data-erro" erro={erroDe("data")} />
        </div>
        <div className="campo">
          <label className="campo__rotulo" htmlFor="campo-oficio">Nº do ofício (opcional)</label>
          <input id="campo-oficio" name="numero_oficio" autoComplete="off" spellCheck={false} className="entrada--media" maxLength={100}
            value={proto.oficio} onChange={ev => setProto({ ...proto, oficio: ev.target.value })} />
        </div>
        {/* O orgao devolve um numero de PROCESSO quando protocola, e e' por ele que se cobra andamento
            depois — o oficio e' o nosso lado da conversa. */}
        <div className="campo">
          <label className="campo__rotulo" htmlFor="campo-processo">Nº do processo no órgão (opcional)</label>
          <input id="campo-processo" name="numero_processo" autoComplete="off" spellCheck={false} className="entrada--media" maxLength={100}
            value={proto.processo} onChange={ev => setProto({ ...proto, processo: ev.target.value })} />
        </div>
        <div className="campo">
          <label className="campo__rotulo" htmlFor="campo-siga">Link do SIGA (opcional)</label>
          <input id="campo-siga" name="link_siga" autoComplete="off" spellCheck={false} className="entrada--larga" maxLength={500}
            placeholder="https://…?n=…" value={proto.siga} onChange={ev => setProto({ ...proto, siga: ev.target.value })} />
        </div>
      </div>

      {/* F-69: a condicao que libera o botao vem ANTES dele. O resultado da conferencia chega depois e muda o
          que o botao aceita: anuncia-se quando chega */}
      <div className="painel__rodape checklist-ato" aria-live="polite">
        {checklist === undefined && <span className="campo__nota">Conferindo os documentos exigidos…</span>}
        {checklist === null && (
          <CaixaAviso nivel="atencao" como="span">
            Não foi possível conferir os documentos agora — o servidor confere de novo ao registrar.
          </CaixaAviso>
        )}
        {checklist && pendentes.length === 0 && (
          <Selo classe="selo--ok">Documentos em dia</Selo>
        )}
        {checklist && pendentes.length > 0 && (
          <>
            <CaixaAviso nivel="critico" como="span">
                {pendentes.length === 1 ? "1 documento sem validade hoje" : `${pendentes.length} documentos sem validade hoje`} —{" "}
                {pendentes.map(i => new Set(pendentes.map(x => x.entidade_id)).size > 1 ? `${i.entidade}: ${i.tipo}` : i.tipo).join(", ")}.{" "}
                <Link className="link" para={{ tela: "documentos" }}>Anexar em Documentos</Link>
            </CaixaAviso>
            <label className="marcar">
              <input id="campo-apesar" type="checkbox" name="apesar_das_pendencias" checked={apesar} {...ligacao("apesar", "campo-apesar")}
                onChange={ev => setApesar(ev.target.checked)} />
              Protocolar apesar das pendências
            </label>
            <ErroCampo id="campo-apesar-erro" erro={erroDe("apesar")} />
            {apesar && (
              <div className="campo">
                <label className="campo__rotulo" htmlFor="campo-justificativa">Justificativa</label>
                <input id="campo-justificativa" name="justificativa" autoComplete="off" className="entrada--larga" required maxLength={500}
                  value={justificativa} {...ligacao("justificativa", "campo-justificativa")}
                  onChange={ev => setJustificativa(ev.target.value)} />
                <ErroCampo id="campo-justificativa-erro" erro={erroDe("justificativa")} />
              </div>
            )}
          </>
        )}
      </div>

      <div className="form-inline painel__rodape">
        <button type="submit" className="btn btn--primario" disabled={salvando}>
          {salvando ? "Registrando…" : "Registrar protocolo"}
        </button>
        <button type="button" className="btn" onClick={aoFechar}>Cancelar</button>
      </div>
    </form>
  );
}

// Issue #53 (decisao do dono, 15/10/2026): o recebimento vem do RM; a mao, so' o admin, quando o RM falhar, e com
// motivo obrigatorio, que vai para a auditoria. O servidor recusa sem o motivo (422) e para outro perfil (403).
const MIN_MOTIVO_RECEBIMENTO = 10;   // o servidor recusa menos que isso (api_medicoes.MOTIVO_RECEBIMENTO_MINIMO)

export function FormRecebimento({ m, salvando, agir, aoFechar, erro }: Base) {
  const [data, setData] = useState("");
  const [motivo, setMotivo] = useState("");
  const [tentou, setTentou] = useState(false);
  // Conta por caractere (code point), como o len() do servidor, e nao por unidade UTF-16.
  const falta = [...motivo.trim()].length < MIN_MOTIVO_RECEBIMENTO
    ? `Escreva o motivo, com pelo menos ${MIN_MOTIVO_RECEBIMENTO} caracteres.` : undefined;
  const erroMotivo = tentou ? falta : undefined;
  async function salvar(ev: React.FormEvent) {
    ev.preventDefault();
    setTentou(true);
    if (falta) { document.getElementById("campo-motivo-recebimento")?.focus(); return; }
    const corpo = { estado: "recebida", motivo: motivo.trim(), ...(data ? { data } : {}) };
    const ok = await agir(() => api(`/api/medicoes/${m.id}/estado`, {
      method: "POST", body: JSON.stringify(corpo),
    }), "Recebimento registrado.");
    if (ok) aoFechar();
  }
  return (
    <form onSubmit={salvar} noValidate onKeyDown={ev => ev.key === "Escape" && aoFechar()}>
      <p className="painel__titulo">Registrar à mão o recebimento da {m.numero}ª medição</p>
      <Erro erro={erro} />
      <div className="form-inline">
        <div className="campo">
          <label className="campo__rotulo" htmlFor="campo-data-marco">Data da baixa (opcional)</label>
          <input id="campo-data-marco" name="data_baixa" autoComplete="off" type="date" className="entrada--media" autoFocus value={data}
            onChange={ev => setData(ev.target.value)} />
        </div>
        <div className="campo">
          <label className="campo__rotulo" htmlFor="campo-motivo-recebimento">Motivo</label>
          <input id="campo-motivo-recebimento" name="motivo" autoComplete="off" className="entrada--larga" required maxLength={1000}
            value={motivo}
            {...(erroMotivo ? { "aria-invalid": true as const, "aria-describedby": "campo-motivo-recebimento-erro" } : {})}
            onChange={ev => setMotivo(ev.target.value)} />
          <ErroCampo id="campo-motivo-recebimento-erro" erro={erroMotivo} />
        </div>
        <button type="submit" className="btn btn--primario" disabled={salvando}>{salvando ? "Registrando…" : "Registrar recebimento"}</button>
        <button type="button" className="btn" onClick={aoFechar}>Cancelar</button>
      </div>
    </form>
  );
}

export function FormEstado({ m, estado, salvando, agir, aoFechar, erro }: Base & { estado: "cancelada" | "desistida" }) {
  const [motivo, setMotivo] = useState("");
  async function salvar(ev: React.FormEvent) {
    ev.preventDefault();
    const ok = await agir(() => api(`/api/medicoes/${m.id}/estado`, {
      method: "POST", body: JSON.stringify(motivo ? { estado, motivo } : { estado }),
    }), estado === "cancelada" ? "Medição cancelada." : "Desistência registrada.");
    if (ok) aoFechar();
  }
  return (
    <form onSubmit={salvar} onKeyDown={ev => ev.key === "Escape" && aoFechar()}>
      <p className="painel__titulo">
        {estado === "cancelada" ? `Cancelar a ${m.numero}ª medição` : `Registrar desistência da ${m.numero}ª medição`}
      </p>
      <Erro erro={erro} />
      <div className="form-inline">
        <div className="campo">
          <label className="campo__rotulo" htmlFor="campo-motivo">Motivo (opcional)</label>
          <input id="campo-motivo" name="motivo" autoComplete="off" className="entrada--media" maxLength={1000} autoFocus
            value={motivo} onChange={ev => setMotivo(ev.target.value)} />
        </div>
        {/* "Cancelar a medição", nunca so "Cancelar": ao lado de um botao de sair do formulario, "Cancelar"
            seria ambiguo. */}
        <button type="submit" className="btn btn--destrutivo" disabled={salvando}>
          {salvando ? "Aplicando…" : estado === "cancelada" ? "Cancelar a medição" : "Registrar desistência"}
        </button>
        <button type="button" className="btn" onClick={aoFechar}>Voltar</button>
      </div>
    </form>
  );
}

/** Issue #188, saida de emergencia: onde o orgao junta medicao e reajuste no mesmo e-mail, a metade pronta segue
 *  sozinha com uma justificativa (obrigatoria, fica na linha do tempo). A outra vai depois, num envio proprio. */
export function FormSemAOutra({ pronta, salvando, agir, aoFechar, erro }: {
  pronta: Metade; salvando: boolean; agir: Agir; aoFechar: () => void; erro?: string;
}) {
  const [texto, setTexto] = useState("");
  const execucao = pronta.tipo === "execucao";
  async function salvar(ev: React.FormEvent) {
    ev.preventDefault();
    const ok = await agir(() => api(`/api/medicoes/${pronta.medicao_id}/envio-sem-a-outra`, {
      method: "POST", body: JSON.stringify({ justificativa: texto.trim() }),
    }), execucao ? "Envio liberado: a medição segue sem o reajuste. O reajuste vai num envio próprio quando as notas chegarem."
      : "Envio liberado: o reajuste segue sem a medição. A medição vai num envio próprio quando as notas chegarem.");
    if (ok) aoFechar();
  }
  return (
    <form onSubmit={salvar} onKeyDown={ev => ev.key === "Escape" && aoFechar()}>
      <p className="painel__titulo">{execucao ? "Enviar a medição sem o reajuste" : "Enviar o reajuste sem a medição"}</p>
      <Erro erro={erro} />
      <div className="form-inline">
        <div className="campo">
          <label className="campo__rotulo" htmlFor="campo-sem-a-outra">Justificativa (obrigatória)</label>
          <textarea id="campo-sem-a-outra" name="justificativa" className="entrada--larga" rows={2} required minLength={10}
            maxLength={2000} autoFocus value={texto} onChange={ev => setTexto(ev.target.value)} />
        </div>
        <button type="submit" className="btn btn--primario" disabled={salvando || texto.trim().length < 10}>
          {salvando ? "Liberando…" : execucao ? "Liberar o envio só da medição" : "Liberar o envio só do reajuste"}
        </button>
        <button type="button" className="btn" onClick={aoFechar}>Voltar</button>
      </div>
    </form>
  );
}

/** Formulario em linha com um motivo (F-92): descartar protocolo ou oficio, desmarcar a medicao final. E' o
 *  mesmo painel do `FormEstado`: titulo, campo e as acoes no fim, com o destrutivo em `btn--destrutivo`. Quem
 *  chama grava; a recusa do servidor aparece onde quem chama mostra o erro dele. */
export function FormMotivo({ id, titulo, rotulo, placeholder, acao, acaoOcupada, ocupado, aoConfirmar, aoFechar, destrutivo = true }: {
  id: string; titulo: string; rotulo: string; placeholder?: string; acao: string; acaoOcupada: string;
  ocupado: boolean; aoConfirmar: (motivo: string) => void; aoFechar: () => void; destrutivo?: boolean;
}) {
  const [motivo, setMotivo] = useState("");
  function enviar(ev: React.FormEvent) {
    ev.preventDefault();
    if (motivo.trim()) aoConfirmar(motivo.trim());
  }
  return (
    <form className="painel-inline" onSubmit={enviar} onKeyDown={ev => ev.key === "Escape" && aoFechar()}>
      <p className="painel__titulo">{titulo}</p>
      <div className="form-inline">
        <div className="campo">
          <label className="campo__rotulo" htmlFor={id}>{rotulo}</label>
          <input id={id} name="motivo" autoComplete="off" className="entrada--larga" required maxLength={1000} autoFocus
            placeholder={placeholder} value={motivo} onChange={ev => setMotivo(ev.target.value)} />
        </div>
        <button type="submit" className={`btn ${destrutivo ? "btn--destrutivo" : "btn--primario"}`} disabled={ocupado || !motivo.trim()}>
          {ocupado ? acaoOcupada : acao}
        </button>
        <button type="button" className="btn" onClick={aoFechar}>Voltar</button>
      </div>
    </form>
  );
}

/** Marcar a medicao final (F-92): confirmacao em linha, no lugar de `window.confirm`; o botao diz o que faz. */
export function FormFinal({ m, salvando, agir, aoFechar, erro }: Base) {
  async function salvar(ev: React.FormEvent) {
    ev.preventDefault();
    const ok = await agir(() => api(`/api/medicoes/${m.id}/final`, { method: "POST", body: JSON.stringify({}) }),
      "Medição marcada como final: o contrato entrou em encerramento.");
    if (ok) aoFechar();
  }
  return (
    <form className="painel-inline" onSubmit={salvar} onKeyDown={ev => ev.key === "Escape" && aoFechar()}>
      <p className="painel__titulo">Marcar a {m.numero}ª como medição final</p>
      <Erro erro={erro} />
      <div className="form-inline painel__rodape">
        <button type="submit" className="btn btn--primario" disabled={salvando}>{salvando ? "Marcando…" : "Marcar como medição final"}</button>
        <button type="button" className="btn" onClick={aoFechar}>Voltar</button>
      </div>
    </form>
  );
}

/** Desmarcar a medicao final (F-92): o motivo e' obrigatorio, como era no `window.prompt`. */
export function FormDesmarcarFinal({ m, salvando, agir, aoFechar, erro }: Base) {
  return (
    <div>
      <Erro erro={erro} />
      <FormMotivo id="campo-motivo-final" titulo={`Desmarcar a medição final: ${m.numero}ª medição`} rotulo="Motivo (obrigatório)"
        acao="Desmarcar a medição final" acaoOcupada="Desmarcando…"
        ocupado={salvando} destrutivo={false} aoFechar={aoFechar}
        aoConfirmar={async motivo => {
          const ok = await agir(() => api(`/api/medicoes/${m.id}/final/desmarcar`, { method: "POST", body: JSON.stringify({ motivo }) }),
            "Marcação de medição final desfeita.");
          if (ok) aoFechar();
        }} />
    </div>
  );
}


/** Issue #287: registrar que o boletim foi assinado no DocuSign (data e envelope do e-mail de conclusao).
 *  Evento informativo: opcional, nao muda o estado e nao gera aviso. */
function hojeLocal(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function FormAssinatura({ m, salvando, agir, aoFechar, erro }: Base) {
  const [data, setData] = useState("");
  const [envelope, setEnvelope] = useState("");
  const [tentou, setTentou] = useState(false);
  const hoje = hojeLocal();
  const falta = !data ? "Informe a data da assinatura." : data > hoje ? "A data da assinatura não pode ser futura." : undefined;
  const erroData = tentou ? falta : undefined;
  async function salvar(ev: React.FormEvent) {
    ev.preventDefault();
    setTentou(true);
    if (falta) { document.getElementById("campo-data-assinatura")?.focus(); return; }
    const ok = await agir(() => api(`/api/medicoes/${m.id}/assinatura`, {
      method: "POST", body: JSON.stringify({ data, envelope: envelope.trim() || null }),
    }), "Assinatura registrada.");
    if (ok) aoFechar();
  }
  return (
    <form onSubmit={salvar} noValidate onKeyDown={ev => ev.key === "Escape" && aoFechar()}>
      <p className="painel__titulo">Registrar a assinatura da {m.numero}ª medição no DocuSign</p>
      <Erro erro={erro} />
      <div className="form-inline">
        <div className="campo">
          <label className="campo__rotulo" htmlFor="campo-data-assinatura">Data da assinatura</label>
          <input id="campo-data-assinatura" name="data_assinatura" autoComplete="off" type="date" className="entrada--media" autoFocus
            max={hoje} value={data}
            {...(erroData ? { "aria-invalid": true as const, "aria-describedby": "campo-data-assinatura-erro" } : {})}
            onChange={ev => setData(ev.target.value)} />
          <ErroCampo id="campo-data-assinatura-erro" erro={erroData} />
        </div>
        <div className="campo">
          <label className="campo__rotulo" htmlFor="campo-envelope-assinatura">Nome do envelope (opcional)</label>
          <input id="campo-envelope-assinatura" name="envelope" autoComplete="off" className="entrada--larga" maxLength={200}
            value={envelope}
            onChange={ev => setEnvelope(ev.target.value)} />
        </div>
        <button type="submit" className="btn btn--primario" disabled={salvando}>{salvando ? "Registrando…" : "Registrar assinatura"}</button>
        <button type="button" className="btn" onClick={aoFechar}>Cancelar</button>
      </div>
    </form>
  );
}
