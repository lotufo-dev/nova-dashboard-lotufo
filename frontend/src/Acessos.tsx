import { useEffect, useState } from "react";
import { api, mensagemDeErro } from "./api";
import { IconeAlerta } from "./icones";
import Rolagem from "./Rolagem";
import Selo from "./Selo";
import { fmtDataHora } from "./tempo";

// #418: um acesso e' um login certo ou uma tentativa recusada. `data` e' o instante UTC (a tela mostra Cuiaba);
// origem e navegador vem nulos nos eventos gravados antes do registro de acesso.
export type Acesso = { data: string; sucesso: boolean; origem: string | null; navegador: string | null };

/** Entrou (ponto e palavra, o comum) ou recusada (selo de atencao, a excecao). */
function ResultadoAcesso({ sucesso }: { sucesso: boolean }) {
  return sucesso
    ? <span className="estado"><span className="estado__ponto" aria-hidden="true" />Entrou</span>
    : <Selo classe="selo--atencao">recusada</Selo>;
}

/** Os ultimos acessos de uma pessoa, lidos quando o componente monta: quem chama o monta so' quando a pessoa abre. */
export default function UltimosAcessos({ url, rotulo }: { url: string; rotulo: string }) {
  const [acessos, setAcessos] = useState<Acesso[] | null>(null);
  const [erro, setErro] = useState("");
  useEffect(() => {
    api<Acesso[]>(url).then(l => { setAcessos(l); setErro(""); }).catch(e => setErro(mensagemDeErro(e)));
  }, [url]);

  if (erro) return <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>;
  if (acessos === null) return <p>Carregando…</p>;
  if (acessos.length === 0) return <p>Nenhum acesso.</p>;
  return (
    <Rolagem rotulo={rotulo}>
      <table className="tabela">
        <caption className="sr-only">{rotulo}, do mais recente ao mais antigo</caption>
        <thead>
          <tr><th scope="col">Data e hora</th><th scope="col">Origem</th><th scope="col">Navegador</th><th scope="col">Resultado</th></tr>
        </thead>
        <tbody>
          {acessos.map((a, i) => (
            <tr key={`${a.data}-${i}`} className={`linha${i % 2 === 1 ? " par" : ""}`}>
              <td className="num">{fmtDataHora(a.data)}</td>
              <td className="num">{a.origem ?? "—"}</td>
              <td>{a.navegador ?? "—"}</td>
              <td><ResultadoAcesso sucesso={a.sucesso} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </Rolagem>
  );
}
