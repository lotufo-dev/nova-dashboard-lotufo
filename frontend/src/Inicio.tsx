import { useEffect, useState } from "react";
import { api, mensagemDeErro } from "./api";
import { brl, contar } from "./formato";
import type { Usuario } from "./Login";
import { type Ir, type Rota } from "./rota";
import { Link } from "./Link";
import Selo from "./Selo";
import { fmtDataPura, fmtMesExtenso } from "./tempo";
import "./inicio.css";

// Inicio do redesenho (decisoes do Leonardo de 08/10/2026; prototipo Inicio-v3 e Inicio-sem-medicao). Tudo vem
// de GET /api/inicio/painel; as regras de cada numero moram em `backend/app/inicio.py`. A tela so' desenha.

type Certidao = { tipo: string; entidade: string; validade: string | null; dias: number | null; vencida: boolean };
type Reajuste = { contrato_id: number; obra: string; data_base_mes: string; aniversario: string; dias: number };
type Prazo = { contrato_id: number; obra: string; contratante: string; tipo: "execucao" | "vigencia" | "data_base"; data: string; dias: number };
type Contratante = { contratante: string; atual_centavos: number; anterior_centavos: number };
export type PainelInicio = {
  hoje: string;
  notas_a_enviar: number;
  certidoes: { vencidas: number; vencendo: number; itens: Certidao[] };
  reajustes: Reajuste[];
  protocoladas: { obras_protocoladas: number; obras_ativas: number; ultima: string | null };
  medido: { competencia: string; anterior_competencia: string; valor_centavos: number;
            anterior_centavos: number; quantidade: number; ultimo_lancamento: string | null };
  por_contratante: Contratante[];
  recebido_ano: { valor_centavos: number | null; mes_centavos: number; sem_data: number };
  a_receber: { liberado: boolean; valor_centavos: number | null; mais_60_centavos: number | null };
  prazos: Prazo[];
};

const PRAZOS_VISIVEIS = 6;
const ROTULO_PRAZO = { execucao: "Execução", vigencia: "Vigência", data_base: "Data-base" };

/** "Bom dia" / "Boa tarde" / "Boa noite" pela hora de Cuiaba. */
export function saudacao(agora: Date = new Date()): string {
  const h = Number(new Intl.DateTimeFormat("pt-BR", { hour: "numeric", hourCycle: "h23", timeZone: "America/Cuiaba" }).format(agora));
  return h >= 5 && h < 12 ? "Bom dia" : h >= 12 && h < 18 ? "Boa tarde" : "Boa noite";
}

/** Faixa do prazo: vermelho ate' 15 dias (ou vencido), ambar ate' 45, cinza depois. */
function faixa(dias: number): "acao" | "atencao" | "neutro" {
  return dias <= 15 ? "acao" : dias <= 45 ? "atencao" : "neutro";
}

function Cartao({ para, ir, numero, rotulo, tom }:
    { para: Rota; ir: Ir; numero: number; rotulo: string; tom: "primario" | "acao" | "atencao" | "neutro" }) {
  return (
    <Link para={para} ir={ir} className={`ini-cartao ini-cartao--${tom}`}>
      <span className="ini-cartao__numero">{numero.toLocaleString("pt-BR")}</span>
      <span className="ini-cartao__texto"><span className="ini-cartao__rotulo">{rotulo}</span></span>
      <span className="ini-cartao__seta" aria-hidden="true">→</span>
    </Link>
  );
}

function Numero({ rotulo, valor, children }: { rotulo: string; valor: React.ReactNode; children?: React.ReactNode }) {
  return (
    <div className="ini-numero">
      <span className="ini-numero__rotulo">{rotulo}</span>
      <span className="ini-numero__valor">{valor}</span>
      {children}
    </div>
  );
}

export default function Inicio({ usuario, ir }: { usuario: Usuario; ir: Ir }) {
  const [p, setP] = useState<PainelInicio | null>(null);
  const [erro, setErro] = useState("");

  useEffect(() => {
    let vivo = true;
    api<PainelInicio>("/api/inicio/painel")
      .then(d => { if (vivo) setP(d); })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    return () => { vivo = false; };
  }, []);

  const nome = usuario.nome.trim().split(/\s+/)[0] ?? "";
  const titulo = <h1 className="ini-titulo">{saudacao()}{nome ? `, ${nome}` : ""}</h1>;
  if (!p) {
    return (
      <div className="ini">
        {titulo}
        {erro ? <p className="erro" role="alert">Não foi possível carregar o início: {erro}</p>
          : <p className="ini-carregando">Carregando…</p>}
      </div>
    );
  }

  // B-01 (10/10/2026): medido pela competencia (a regra da Carteira), contra o mes anterior inteiro
  const m = p.medido;
  const nomeMes = fmtMesExtenso(m.competencia);
  const nomeAnterior = fmtMesExtenso(m.anterior_competencia);

  // cartao 2: certidoes
  const c = p.certidoes;
  const totalCert = c.vencidas + c.vencendo;
  const rotuloCert = c.vencidas && c.vencendo ? "certidões vencidas ou vencendo" : c.vencidas ? (c.vencidas === 1 ? "certidão vencida" : "certidões vencidas")
    : totalCert === 1 ? "certidão vencendo" : "certidões vencendo";

  // cartao 3: reajuste a pedir
  const r = p.reajustes;
  const paraReaj: Rota = r.length === 1 ? { tela: "obra", id: r[0].contrato_id, aba: "reajuste" } : { tela: "avisos" };

  const maior = Math.max(1, ...p.por_contratante.map(x => Math.max(x.atual_centavos, x.anterior_centavos)));
  const pr = p.protocoladas;

  return (
    <div className="ini">
      {titulo}

      <section aria-label="O que fazer agora" className="ini-cartoes">
        <Cartao para={{ tela: "medicoes", aba: "enviar-nota" }} ir={ir} tom="primario" numero={p.notas_a_enviar}
          rotulo={p.notas_a_enviar === 1 ? "nota a enviar" : "notas a enviar"} />
        <Cartao para={{ tela: "documentos" }} ir={ir} numero={totalCert} rotulo={rotuloCert}
          tom={c.vencidas ? "acao" : c.vencendo ? "atencao" : "neutro"} />
        <Cartao para={paraReaj} ir={ir} numero={r.length} rotulo={r.length === 1 ? "reajuste a pedir" : "reajustes a pedir"}
          tom={r.some(x => x.dias < 0) ? "acao" : r.length ? "atencao" : "neutro"} />
      </section>

      <section aria-label="Números do mês" className="ini-numeros">
        <Numero rotulo={`Medido em ${nomeMes}`} valor={brl(m.valor_centavos)} />
        <Numero rotulo={`Obras protocoladas em ${nomeMes}`}
          valor={<>{pr.obras_protocoladas.toLocaleString("pt-BR")} <span className="ini-numero__de">de {contar(pr.obras_ativas, "obra ativa", "obras ativas")}</span></>}>
          <span className="ini-barra" role="presentation">
            <span style={{ width: `${pr.obras_ativas ? Math.round(100 * pr.obras_protocoladas / pr.obras_ativas) : 0}%` }} /></span>
        </Numero>
        <Numero rotulo={`Recebido em ${p.hoje.slice(0, 4)}`} valor={brl(p.recebido_ano.valor_centavos)} />
        <Numero rotulo="A receber" valor={brl(p.a_receber.valor_centavos)}>
          {p.a_receber.liberado && (p.a_receber.mais_60_centavos ?? 0) > 0 && (
            <span><Selo classe="selo--acao" title={brl(p.a_receber.mais_60_centavos)}>mais de 60 dias</Selo></span>)}
        </Numero>
      </section>

      <div className="ini-colunas">
        <section aria-labelledby="ini-medido" className="ini-painel ini-painel--grafico">
          <div className="ini-painel__topo">
            <h2 id="ini-medido">Medido por contratante</h2>
            <span className="ini-legenda">
              <span><i className="ini-chave ini-chave--anterior" />{nomeAnterior}</span>
              <span><i className="ini-chave ini-chave--atual" />{nomeMes}</span>
            </span>
          </div>
          {m.quantidade === 0 && (
            <div className="ini-sem-medicao" role="status">
              <strong>Nenhuma medição da competência de {nomeMes}.</strong>
              <Link para={{ tela: "medicoes" }} ir={ir} className="ini-sem-medicao__botao">Lançar medição →</Link>
            </div>
          )}
          {p.por_contratante.length > 0 && (
            <ul className="ini-barras">
              {p.por_contratante.map(x => (
                <li key={x.contratante} className="ini-barras__linha">
                  <span className="ini-barras__nome">{x.contratante}</span>
                  <svg className="ini-barras__svg" viewBox="0 0 100 23" preserveAspectRatio="none" role="img"
                    aria-label={`${nomeAnterior}: ${brl(x.anterior_centavos)}; ${nomeMes}: ${brl(x.atual_centavos)}`}>
                    <rect className="ini-barras__anterior" x="0" y="0" height="10" rx="1.5" width={100 * x.anterior_centavos / maior} />
                    <rect className="ini-barras__atual" x="0" y="13" height="10" rx="1.5" width={100 * x.atual_centavos / maior} />
                  </svg>
                  <span className="ini-barras__valor">{brl(x.atual_centavos)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-labelledby="ini-prazos" className="ini-painel ini-painel--prazos">
          <div className="ini-painel__topo">
            <h2 id="ini-prazos">Prazos chegando</h2>
            <Link para={{ tela: "avisos" }} ir={ir} className="ini-ver-todos">Ver todos</Link>
          </div>
          {p.prazos.length === 0 ? <p className="ini-vazio">Nenhum prazo chegando.</p> : (
            <>
              <div className="ini-prazos__cabeca" aria-hidden="true"><span>Obra</span><span>Prazo</span><span>Faltam</span></div>
              {p.prazos.slice(0, PRAZOS_VISIVEIS).map(x => (
                <Link key={`${x.contrato_id}-${x.tipo}-${x.data}`} ir={ir} className="ini-prazos__linha"
                  para={{ tela: "obra", id: x.contrato_id, aba: x.tipo === "data_base" ? "reajuste" : "prazos" }}>
                  <span className="ini-prazos__obra"><span className="ini-prazos__nome">{x.obra}</span>
                    <span className="ini-prazos__sub">{x.contratante} · {fmtDataPura(x.data)}</span></span>
                  <span>{ROTULO_PRAZO[x.tipo]}</span>
                  <span className={`ini-pilula ini-pilula--${faixa(x.dias)}`}><i className="ini-ponto" />
                    {x.dias < 0 ? <>vencido há <span className="ini-mono">{-x.dias}</span> {-x.dias === 1 ? "dia" : "dias"}</>
                      : <><span className="ini-mono">{x.dias}</span> {x.dias === 1 ? "dia" : "dias"}</>}</span>
                </Link>
              ))}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
