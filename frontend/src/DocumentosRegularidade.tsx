import { useMemo, useRef } from "react";
import Contador from "./Contador";
import type { ItemLegenda } from "./LegendaCor";
import { Link } from "./Link";
import type { Usuario } from "./Login";
import { competenciasRegularidade, empresasComFolha, estadosRegularidade, regularidadesFaltando, type EmpresaDoc } from "./matriz";
import { Glifo } from "./Selo";
import { fmtCompetencia, fmtMesCurto, fmtMesExtenso } from "./tempo";
import { MolduraDocumentos, type AnexarRef } from "./documentosComum";
import { PAPEL, usePainel } from "./documentosDados";

/* Regularidade mensal (#513, #651, #699; pagina propria na #820): "de quem falta a folha do DP?". Os seis ultimos
 * meses de cada empresa com folha, cada mes com o glifo da situacao e o PDF dele. O "Anexar PDF" do alto e' o mesmo
 * das Certidoes (o servidor decide pelo conteudo). Endereco: "/documentos/regularidade". */

const COR_ESTADO = { anexada: "feito", faltando: "breve", aguardando: "andamento", sem: "neutro" } as const;
const TEXTO_ESTADO = { anexada: "anexada", faltando: "faltando", aguardando: "aguardando o DP", sem: "sem registro" } as const;

const LEGENDA: ItemLegenda[] = [
  { situacao: "feito", texto: "anexada" }, { situacao: "andamento", texto: "aguardando o DP" }, { situacao: "breve", texto: "faltando" },
];

function UltimosSeisMeses({ empresas, hoje }: { empresas: EmpresaDoc[]; hoje: string }) {
  const comFolha = empresasComFolha(empresas);
  const semFolha = empresas.filter(e => !comFolha.includes(e));
  const meses = competenciasRegularidade(hoje);
  const ultimoMes = meses[meses.length - 1].competencia;
  const seguinte = `${ultimoMes.slice(5, 7) === "12" ? String(Number(ultimoMes.slice(0, 4)) + 1) : ultimoMes.slice(0, 4)}-${String(Number(ultimoMes.slice(5, 7)) % 12 + 1).padStart(2, "0")}`;
  return (
    <>
      <section className="cartao doc-bloco" aria-labelledby="titulo-regularidade">
      <h2 id="titulo-regularidade" className="doc-bloco__titulo">Últimos seis meses</h2>
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
                  const interior = (
                    <>
                      <span className="doc-chip__rotulo">{fmtMesCurto(x.competencia)}</span>
                      {/* #651: mes que ninguem cobra (antes do primeiro PDF da empresa) e' so' "—" */}
                      {x.estado === "sem" ? <b className="doc-chip__icone" role="img" aria-label={nome}>—</b>
                        : <span className="doc-chip__icone" role="img" aria-label={nome}><Glifo situacao={COR_ESTADO[x.estado]} /></span>}
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
      </section>
      {semFolha.length > 0 && <p className="doc-nota">Não exigida: {semFolha.map(e => e.entidade).join(", ")}</p>}
      <p className="doc-nota">{(() => { const m = fmtMesExtenso(ultimoMes); return m.charAt(0).toUpperCase() + m.slice(1); })()} esperada a partir de 10/{seguinte.slice(5, 7)}.</p>
    </>
  );
}

export default function DocumentosRegularidade({ usuario }: { usuario: Usuario }) {
  const podeEditar = usuario.perfil !== "diretoria";
  const { painel, erro, carregar } = usePainel();
  const anexar = useRef<AnexarRef>(null);
  const empresas = useMemo(() => painel?.empresas ?? [], [painel]);
  const n = painel ? regularidadesFaltando(empresas) : 0;

  return (
    <MolduraDocumentos classe="doc-regularidade" erro={erro} carregado={!!painel} legenda={LEGENDA}
      contador={n > 0 ? <Contador situacao="critico">{`${n} faltando`}</Contador> : null}
      anexar={podeEditar ? (painel ? { empresas, aoGravar: carregar } : null) : undefined} refAnexar={anexar}>
      {empresas.length === 0
        ? <div className="vazio"><p className="vazio__titulo">Nenhuma empresa.</p></div>
        : <UltimosSeisMeses empresas={empresas} hoje={painel!.hoje} />}
    </MolduraDocumentos>
  );
}
