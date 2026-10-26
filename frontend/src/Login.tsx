import { useEffect, useRef, useState } from "react";
import { api, ApiErro, setCsrf } from "./api";
import { IconeAlerta } from "./icones";
import "./login.css";

export interface Usuario { id: number; nome: string; perfil: string; email: string; }   // /api/auth/eu

export default function Login({ aoEntrar }: { aoEntrar: (u: Usuario) => void }) {
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState("");
  const [enviando, setEnviando] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [sem3d, setSem3d] = useState(false);

  // O App so' titula as telas depois do login; sem isto a aba herdava "Início".
  useEffect(() => { document.title = "Entrar · grupolotufo"; }, []);

  // Fundo 3D em import() dinamico: o Three so' baixa nesta tela. Sem WebGL (ou erro num quadro)
  // fica o fundo estatico do CSS, sem aviso — o formulario nao depende dele.
  useEffect(() => {
    let limpar: (() => void) | undefined;
    let cancelado = false;
    const parado = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    import("./LoginFundo3D").then(({ iniciarFundo }) => {
      if (cancelado || !canvasRef.current) return;
      try { limpar = iniciarFundo(canvasRef.current, parado, () => setSem3d(true)); }
      catch { setSem3d(true); }
    }).catch(() => { if (!cancelado) setSem3d(true); });
    return () => { cancelado = true; limpar?.(); };
  }, []);

  async function entrar(e: React.FormEvent) {
    e.preventDefault();
    setErro("");
    setEnviando(true);
    try {
      const r = await api<{ nome: string; perfil: string; csrf: string }>(
        "/api/auth/login", { method: "POST", body: JSON.stringify({ email, senha }) });
      setCsrf(r.csrf);
      const eu = await api<Usuario>("/api/auth/eu");
      aoEntrar(eu);
    } catch (falha) {
      // credencial recusada (4xx) e servidor fora do ar pedem coisas diferentes de quem tenta entrar.
      // 429 (#3, limite de login por origem): o computador estourou a cota; "senha errada" levaria a
      // pedir desbloqueio, que nao resolve. Vale o texto do servidor, ja' em portugues.
      setErro(falha instanceof ApiErro && falha.status === 429 ? falha.message
        : falha instanceof ApiErro && falha.status >= 400 && falha.status < 500
        ? "E-mail ou senha inválidos, ou usuário bloqueado. Confira os dois e tente de novo."
        : "Não foi possível falar com o servidor. Tente de novo em instantes.");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <main className="entrar">
      <div className="entrar__visual">
        <canvas ref={canvasRef} className="entrar__canvas" aria-hidden="true" hidden={sem3d} />
      </div>
      <aside className="entrar__painel">
        <div className="entrar__topo">
          <div className="entrar__marca">
            <div className="entrar__simbolo" aria-hidden="true"><i /><i className="v" /><i /><i className="v" /><i /><i /></div>
            <div className="entrar__nome">
              <span className="entrar__marca-nome">grupolotufo</span>
            </div>
          </div>
          <div className="entrar__bloco">
            <div className="entrar__cabeca">
              <h1 className="entrar__titulo">Entrar</h1>
            </div>
            <form className="entrar__form" onSubmit={entrar}>
              <label className="entrar__campo">
                E-mail
                <input type="email" name="email" autoComplete="username" spellCheck={false} required
                       value={email} onChange={e => setEmail(e.target.value)} />
              </label>
              <label className="entrar__campo">
                Senha
                <input type="password" name="senha" autoComplete="current-password" required
                       placeholder="••••••••"
                       value={senha} onChange={e => setSenha(e.target.value)} />
              </label>
              {erro && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
              <button type="submit" className="entrar__botao" disabled={enviando}>{enviando ? "Entrando…" : "Entrar"}</button>
            </form>
          </div>
        </div>
      </aside>
    </main>
  );
}
