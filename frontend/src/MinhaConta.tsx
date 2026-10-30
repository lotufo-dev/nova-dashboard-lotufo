import { useEffect, useRef, useState } from "react";
import { api, apiForm, mensagemDeErro } from "./api";
import ConfirmarRemocao from "./ConfirmarRemocao";
import { IconeAlerta, IconeOlho, IconeOlhoFechado } from "./icones";
import type { Usuario } from "./Login";
import { rotuloPerfil } from "./navegacao";
import Selo from "./Selo";

type Login = { estado: string; user_code: string | null; verification_uri: string | null; erro?: string };
type Status = { configurado: boolean; conectado: boolean; login: Login; assinatura: boolean };
type CampoSenha = "atual" | "nova" | "confirmar";

export default function MinhaConta({ usuario }: { usuario: Usuario }) {
  // B-09 (10/10/2026): a diretoria nao manda e-mail pela dashboard: ve o e-mail de login e troca a senha
  const podeEditar = usuario.perfil === "engenharia" || usuario.perfil === "admin";
  const [st, setSt] = useState<Status | null>(null);
  const [erro, setErro] = useState("");            // erro do carregamento e da conta Microsoft
  const [erroAss, setErroAss] = useState("");      // erro da assinatura e do e-mail de teste
  const [arrastando, setArrastando] = useState(false);
  const [teste, setTeste] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [trocandoSenha, setTrocandoSenha] = useState(false);   // so' o botao da troca de senha muda o rotulo
  const timer = useRef<number | undefined>(undefined);
  const arquivo = useRef<HTMLInputElement>(null);
  const [versao, setVersao] = useState(() => Date.now());
  // A-05/B-10 (10/10/2026): trocar a propria senha. Redesenho (#165): erro embaixo de cada campo.
  const [senha, setSenha] = useState({ atual: "", nova: "", confirmar: "" });
  const [errosCampo, setErrosCampo] = useState<Partial<Record<CampoSenha, string>>>({});
  const [vendo, setVendo] = useState({ atual: false, nova: false, confirmar: false });
  const [erroSenha, setErroSenha] = useState("");  // erro que vem do servidor
  const [senhaTrocada, setSenhaTrocada] = useState("");

  const carregar = () => api<Status>("/api/correio/status").then(s => { setSt(s); setErro(""); }).catch(e => setErro(mensagemDeErro(e)));
  useEffect(() => { if (podeEditar) carregar(); return () => window.clearInterval(timer.current); }, [podeEditar]);

  // Enquanto a Microsoft espera a pessoa digitar o codigo, consultar o estado a cada 5 s.
  useEffect(() => {
    window.clearInterval(timer.current);
    if (st?.login.estado === "aguardando") timer.current = window.setInterval(carregar, 5000);
  }, [st?.login.estado]);

  async function conectar() {
    setErro(""); setOcupado(true);
    try { setSt(await api<Status>("/api/correio/conectar", { method: "POST" })); }
    catch (e) { setErro(mensagemDeErro(e)); }
    finally { setOcupado(false); }
  }

  async function enviarTeste() {
    setErroAss(""); setTeste(""); setOcupado(true);
    try {
      const r = await api<{ remetente: string }>("/api/correio/teste", { method: "POST" });
      setTeste(`E-mail de teste enviado para ${r.remetente}. Confira a caixa de entrada e os itens enviados.`);
    } catch (e) { setErroAss(mensagemDeErro(e)); }
    finally { setOcupado(false); }
  }

  async function subirAssinatura(ev: React.ChangeEvent<HTMLInputElement>) {
    const f = ev.target.files?.[0];
    if (f) await enviarImagem(f);
  }

  // Colar (Ctrl+V) ou arrastar a imagem: o Outlook na web nao deixa salvar a imagem da assinatura.
  function imagemDe(dados: DataTransfer | null): File | null {
    const f = [...(dados?.files ?? [])].find(x => x.type === "image/png" || x.type === "image/jpeg");
    return f ?? null;
  }

  async function enviarImagem(f: File) {
    setErroAss("");
    const limpar = () => { if (arquivo.current) arquivo.current.value = ""; };   // escolher o mesmo arquivo de novo tem que disparar
    if (f.type !== "image/png" && f.type !== "image/jpeg") { setErroAss("A imagem precisa ser PNG ou JPG."); limpar(); return; }
    if (f.size > 1024 * 1024) {   // o mesmo limite do servidor (ASSINATURA_MAX)
      setErroAss(`A imagem passa de 1 MB (${(f.size / 1048576).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} MB). Use uma menor.`);
      limpar();
      return;
    }
    setOcupado(true);
    try {
      const fd = new FormData(); fd.append("arquivo", f);
      setSt(await apiForm<Status>("/api/correio/assinatura", fd));
      setVersao(Date.now());
    } catch (e) { setErroAss(mensagemDeErro(e)); }
    finally { setOcupado(false); if (arquivo.current) arquivo.current.value = ""; }
  }

  function colar(ev: React.ClipboardEvent<HTMLDivElement>) {
    const f = imagemDe(ev.clipboardData);
    if (f) { ev.preventDefault(); void enviarImagem(f); }
    else setErroAss("A área de transferência não tem imagem. Copie a imagem da assinatura (ou o arquivo) e cole de novo.");
  }

  async function removerAssinatura() {
    setErroAss(""); setOcupado(true);
    try { setSt(await api<Status>("/api/correio/assinatura", { method: "DELETE" })); }
    catch (e) { setErroAss(mensagemDeErro(e)); }
    finally { setOcupado(false); }
  }

  function digitar(campo: CampoSenha, valor: string) {
    setSenha(s => ({ ...s, [campo]: valor }));
    // mexer na senha nova invalida tambem o erro da confirmacao (que comparava com o valor antigo)
    setErrosCampo(e => ({ ...e, [campo]: undefined, ...(campo === "nova" ? { confirmar: undefined } : {}) }));
    setErroSenha(""); setSenhaTrocada("");
  }

  async function trocarSenha(ev: React.FormEvent) {
    ev.preventDefault();
    setErroSenha(""); setSenhaTrocada("");
    const erros: Partial<Record<CampoSenha, string>> = {
      atual: senha.atual ? undefined : "Digite a sua senha atual.",
      nova: !senha.nova ? "Digite a senha nova."
        : [...senha.nova].length < 10 ? `A senha nova precisa de pelo menos 10 caracteres (tem ${[...senha.nova].length}).` : undefined,
      confirmar: !senha.confirmar ? "Repita a senha nova."
        : senha.confirmar !== senha.nova ? "A confirmação não bate com a senha nova." : undefined,
    };
    setErrosCampo(erros);
    if (erros.atual || erros.nova || erros.confirmar) {
      document.getElementById(erros.atual ? "senha-atual" : erros.nova ? "senha-nova" : "senha-confirmar")?.focus();
      return;
    }
    setOcupado(true); setTrocandoSenha(true);
    try {
      await api("/api/auth/senha", { method: "POST", body: JSON.stringify({ senha_atual: senha.atual, senha_nova: senha.nova }) });
      setSenha({ atual: "", nova: "", confirmar: "" });
      setVendo({ atual: false, nova: false, confirmar: false });
      setSenhaTrocada("Senha trocada. As outras sessões abertas com a sua conta foram encerradas.");
    } catch (e) { setErroSenha(mensagemDeErro(e)); }
    finally { setOcupado(false); setTrocandoSenha(false); }
  }

  if (podeEditar && !st) return <p className="vazio">{erro || "Carregando…"}</p>;

  // Campo de senha com o olho dentro e o erro embaixo
  const campoSenha = (campo: CampoSenha, id: string, rotulo: string, auto: string, nomeOlho: string) => (
    <div className="campo">
      <label className="campo__rotulo" htmlFor={id}>{rotulo}</label>
      <div className="senha">
        <input id={id} type={vendo[campo] ? "text" : "password"} autoComplete={auto}
               value={senha[campo]} aria-invalid={errosCampo[campo] ? true : undefined}
               aria-describedby={errosCampo[campo] ? `${id}-erro` : undefined}
               onChange={e => digitar(campo, e.target.value)} />
        <button type="button" className="btn olho" aria-pressed={vendo[campo]}
                aria-label={`Mostrar ${nomeOlho}`}
                onClick={() => setVendo(v => ({ ...v, [campo]: !v[campo] }))}>
          {vendo[campo] ? <IconeOlhoFechado /> : <IconeOlho />}
        </button>
      </div>
      <p className="campo__erro" id={`${id}-erro`} role={errosCampo[campo] ? "alert" : undefined}>{errosCampo[campo]}</p>
    </div>
  );

  return (
    <div className="coluna-conta">
      {/* gate Sol S6 (10/10/2026): sem e-mail, sem a linha */}
      <section className="cartao" aria-labelledby="t-sua">
        <header className="cartao__cabeca"><h2 className="cartao__titulo" id="t-sua">Sua conta</h2></header>
        <div className="cartao__corpo">
          {usuario.email && <p>E-mail: <strong>{usuario.email}</strong></p>}
          <p>Perfil: <strong>{rotuloPerfil(usuario.perfil)}</strong></p>
        </div>
      </section>
      <section className="cartao" aria-labelledby="t-senha">
        <header className="cartao__cabeca"><h2 className="cartao__titulo" id="t-senha">Trocar senha</h2></header>
        <form className="cartao__corpo form-senha" onSubmit={trocarSenha} noValidate>
          {campoSenha("atual", "senha-atual", "Senha atual", "current-password", "a senha atual")}
          {campoSenha("nova", "senha-nova", "Senha nova (mínimo de 10 caracteres)", "new-password", "a senha nova")}
          {campoSenha("confirmar", "senha-confirmar", "Confirmar a senha nova", "new-password", "a confirmação")}
          {erroSenha && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erroSenha}</p>}
          <button type="submit" className="btn btn--primario botao-largo" disabled={ocupado}>
            {trocandoSenha ? "Trocando…" : "Trocar senha"}
          </button>
          <p className={senhaTrocada ? "feito-caixa" : "sr-only"} role="status">{senhaTrocada}</p>
        </form>
      </section>
      {st && <>
        <section className="cartao" aria-labelledby="t-ms">
          <header className="cartao__cabeca">
            <h2 className="cartao__titulo" id="t-ms">Conta Microsoft</h2>
            {st.conectado ? <Selo classe="selo--ok">Conectada</Selo> : <Selo classe="selo--atencao">Não conectada</Selo>}
          </header>
          <div className="cartao__corpo">
            {!st.configurado && (
              <p className="aviso" role="alert"><span className="aviso__ponto" aria-hidden="true" />
                <span>O Microsoft 365 ainda não foi configurado neste servidor.</span></p>
            )}
            {st.login.estado === "aguardando" && st.login.user_code && (
              <div className="codigo">
                <span>
                  Abra <a href={st.login.verification_uri ?? "#"} target="_blank" rel="noreferrer">{st.login.verification_uri}</a> e
                  digite o código:
                </span>
                <span className="codigo__valor">{st.login.user_code}</span>
              </div>
            )}
            {st.login.estado === "expirado" && (
              <p className="aviso" role="alert"><span className="aviso__ponto" aria-hidden="true" /><span>O código expirou. Peça outro.</span></p>
            )}
            {st.login.estado === "recusado" && (
              <p className="aviso aviso--critico" role="alert"><IconeAlerta className="icone icone--p" /><span>A Microsoft recusou o acesso. Tente de novo.</span></p>
            )}
            {st.login.estado === "erro" && (
              <p className="aviso aviso--critico" role="alert"><IconeAlerta className="icone icone--p" /><span>{st.login.erro}</span></p>
            )}
            {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
            <button type="button" className={`btn botao-largo${st.conectado ? "" : " btn--primario"}`}
                    disabled={ocupado || !st.configurado} onClick={conectar}>
              {st.conectado ? "Conectar de novo"
                : st.login.estado === "aguardando" ? "Pedir outro código" : "Conectar minha conta Microsoft"}
            </button>
          </div>
        </section>
        <section className="cartao" aria-labelledby="t-ass">
          <header className="cartao__cabeca">
            <h2 className="cartao__titulo" id="t-ass">Assinatura de e-mail</h2>
            {st.assinatura ? <Selo classe="selo--ok">Cadastrada</Selo> : <Selo>Não cadastrada</Selo>}
          </header>
          <div className="cartao__corpo">
            <div className={`assinatura-alvo${arrastando ? " arrastando" : ""}`} tabIndex={0} role="button"
                 aria-label="Colar ou arrastar a imagem da assinatura" aria-describedby="alvo-dica"
                 onPaste={colar} onDragOver={ev => { ev.preventDefault(); setArrastando(true); }}
                 onDragLeave={ev => { if (!ev.currentTarget.contains(ev.relatedTarget as Node | null)) setArrastando(false); }}
                 onDrop={ev => {
                   ev.preventDefault(); setArrastando(false);
                   const f = imagemDe(ev.dataTransfer);
                   if (f) void enviarImagem(f); else setErroAss("Arraste um arquivo PNG ou JPG.");
                 }}>
              {st.assinatura && <img src={`/api/correio/assinatura?v=${versao}`} alt="Sua assinatura" />}
              <span className="assinatura-alvo__dica" id="alvo-dica">Cole (Ctrl+V) ou arraste a imagem</span>
            </div>
            {erroAss && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erroAss}</p>}
            <details className="detalhes">
              <summary>Onde achar a imagem</summary>
              <p className="campo__nota"><code className="caminho">%APPDATA%\Microsoft\Signatures</code>, na pasta que termina
                em “_arquivos” (image001.png)</p>
            </details>
            <div className="par-botoes">
              <label className="btn btn--primario">
                {st.assinatura ? "Trocar a imagem" : "Enviar a imagem da assinatura"}
                <input ref={arquivo} type="file" accept="image/png,image/jpeg" className="sr-only" disabled={ocupado}
                       onChange={subirAssinatura} />
              </label>
              <button type="button" className="btn" disabled={ocupado || !st.conectado} onClick={enviarTeste}
                      aria-describedby={st.conectado ? undefined : "teste-motivo"}>Enviar e-mail de teste</button>
            </div>
            {!st.conectado && <p className="campo__nota" id="teste-motivo">Conecte a sua conta Microsoft para enviar o teste.</p>}
            <p className={teste ? "feito-caixa" : "sr-only"} role="status">{teste}</p>
            {st.assinatura && (
              <div className="acoes acoes--inicio">
                <ConfirmarRemocao alvo="a assinatura" classe="btn" ocupado={ocupado} aoConfirmar={() => void removerAssinatura()} />
              </div>
            )}
          </div>
        </section>
      </>}
    </div>
  );
}
