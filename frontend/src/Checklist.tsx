import { useEffect, useState } from "react";
import ConfirmarRemocao from "./ConfirmarRemocao";
import { IconeSeta } from "./icones";
import Selo from "./Selo";

// Checklist de pecas e anexos (F-67), o mesmo no protocolo e no oficio: tres colunas, peca, situacao em Selo
// e acao alinhada a' direita, com o nome do arquivo sob a peca. A situacao
// vem de quem chama: "falta" e' Atencao porque o servidor trata peca exigida sem anexo como pendencia que
// se envia com justificativa (nunca como bloqueio), e so' a certidao e' Critico (D10, Pendencias.tsx).

export type ArquivoChecklist = { id: number; nome: string; tamanho: number };
export type ItemChecklist = {
  chave: string; rotulo: string;
  situacao: "anexada" | "falta" | "opcional";
  arquivos: ArquivoChecklist[];
  aceita?: string;                                // extensoes do seletor de arquivo
  semAnexar?: boolean;                            // grupo que so' lista arquivos (tipo que a familia nao pede)
};

function SeloSituacao({ situacao }: { situacao: ItemChecklist["situacao"] }) {
  return situacao === "anexada" ? <Selo classe="selo--ok">Anexada</Selo>
    : situacao === "falta" ? <Selo classe="selo--atencao">Falta</Selo>
    : <Selo>Opcional</Selo>;
}

export default function Checklist({ itens, legenda, editavel, ocupado, aoAnexar, aoRemover }: {
  itens: ItemChecklist[]; legenda: string; editavel: boolean; ocupado: boolean;
  aoAnexar: (chave: string, input: HTMLInputElement) => void; aoRemover: (arquivoId: number) => void;
}) {
  return (
    <table className="checklist-pecas">
      <caption className="sr-only">{legenda}</caption>
      <thead>
        <tr>
          <th scope="col">Peça</th>
          <th scope="col">Situação</th>
          <th scope="col" className="checklist-pecas__acao">Ação</th>
        </tr>
      </thead>
      <tbody>
        {itens.map(it => (
          <tr key={it.chave}>
            <th scope="row">
              <span className="checklist-pecas__nome">{it.rotulo}</span>
              {it.arquivos.map(a => (
                <span key={a.id} className="checklist-pecas__arquivo" title={a.nome}>
                  {a.nome}
                </span>
              ))}
            </th>
            <td><SeloSituacao situacao={it.situacao} /></td>
            <td className="checklist-pecas__acao">
              {editavel && (
                <div className="checklist-pecas__botoes">
                  {!it.semAnexar && (
                    <label className="btn btn--pequeno espelho__anexar">
                      Anexar
                      <input type="file" className="espelho__arquivo" aria-label={`Anexar ${it.rotulo}`}
                        name={`anexo-${it.chave}`} accept={it.aceita ?? ".xlsx,application/pdf"} disabled={ocupado}
                        onChange={ev => aoAnexar(it.chave, ev.currentTarget)} />
                    </label>
                  )}
                  {it.arquivos.map(a => (
                    <ConfirmarRemocao key={a.id} alvo={a.nome} ocupado={ocupado} aoConfirmar={() => aoRemover(a.id)} />
                  ))}
                </div>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Texto da carta (protocolo e oficio): aberto enquanto o pacote nao foi montado; montado, fica recolhido
 *  (F-67) e o botao de baixar/montar fica FORA daqui, sempre a' vista. O rotulo visivel e' o proprio
 *  resumo, que da o nome acessivel ao campo. */
export function CartaRecolhivel({ id, linhas, valor, desabilitado, aoMudar, montada }: {
  id: string; linhas: number; valor: string; desabilitado: boolean; aoMudar: (v: string) => void;
  montada: boolean;
}) {
  const [aberta, setAberta] = useState(!montada);
  // o pacote acabou de ser montado: a carta recolhe, e reabrir e' escolha de quem vai editar
  useEffect(() => { if (montada) setAberta(false); }, [montada]);
  return (
    <details className="carta-rec" open={aberta} onToggle={ev => setAberta(ev.currentTarget.open)}>
      <summary>
        <IconeSeta className="icone icone--p seta" />
        <span className="campo__rotulo" id={`${id}-titulo`}>Texto da carta</span>
      </summary>
      <div className="campo">
        <textarea id={id} name={id} autoComplete="off" rows={linhas} value={valor} disabled={desabilitado}
          aria-labelledby={`${id}-titulo`} onChange={e => aoMudar(e.target.value)} />
      </div>
    </details>
  );
}
