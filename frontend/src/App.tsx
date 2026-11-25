import { useEffect, useState } from "react";
import Admin from "./Admin";
import { api, setCsrf } from "./api";
import AReceber from "./AReceber";
import { BarraSuperior, Trilho } from "./Casca";
import DocumentosCertidoes from "./DocumentosCertidoes";
import DocumentosEmpresa from "./DocumentosEmpresa";
import DocumentosGarantias from "./DocumentosGarantias";
import DocumentosRegularidade from "./DocumentosRegularidade";
import AbrirEnvio from "./AbrirEnvio";
import { ABAS_PRONTAS } from "./abasDoContratante";
import ContratantePagina from "./ContratantePagina";
import ContratoPagina from "./ContratoPagina";
import Contratos from "./Contratos";
import Inicio from "./Inicio";
import Login, { type Usuario } from "./Login";
import MedicaoPagina from "./MedicaoPagina";
import MedicoesPagina from "./MedicoesPagina";
import MinhaConta from "./MinhaConta";
import MedicaoNova from "./MedicaoNova";
import Fechamento from "./Fechamento";
import ResumoDasMedicoes from "./ResumoDasMedicoes";
import { entradaDe, itemDe, ROTULO, tituloDe, vistaDe } from "./navegacao";
import { useVistaPublicada } from "./nomesDoCaminho";
import { pode } from "./permissoes";
import SigaPagina from "./SigaPagina";
import LicitacoesFavoritas from "./LicitacoesFavoritas";
import LicitacoesTriagem from "./LicitacoesTriagem";
import AncorasDocusign from "./AncorasDocusign";
import AvisoRespostas from "./AvisoRespostas";
import AvisosPagina from "./AvisosPagina";
import { useLeituraDasRespostas } from "./respostasOrgao";
import { buscaDosAvisos, caminhoDe, ehDetalhe, useRolarAteSecao, useRota } from "./rota";

// O menu em areas, a entrada por perfil e o caminho de cada rota moram em navegacao.ts; o menu e a barra do topo, em
// Casca.tsx. O App so' escolhe a tela. Todo perfil entra pelo Inicio (decisao do dono, 08/10/2026).

// Issue #417: fora do servidor oficial a dashboard sobe em modo copia (sem envio de e-mail e sem RM) e o
// /api/health diz `instalacao: nao-autorizada`. A faixa fica em toda tela, inclusive no login, presa ao pe da janela.
function FaixaInstalacao() {
  return (
    <p className="faixa-instalacao" role="alert">
      Instalação não autorizada da Dashboard Lotufo. Envio de e-mail e sincronização com o RM estão desligados.
    </p>
  );
}

export default function App() {
  const [usuario, setUsuario] = useState<Usuario | null>(null);
  const { rota, busca, secao, origem, ir, substituir } = useRota();
  const [carregando, setCarregando] = useState(true);
  const [copia, setCopia] = useState(false);

  useEffect(() => {
    // O health e' aberto (sem login). Relido a cada 5 minutos: a leitura que falhou (servidor reiniciando) e o servidor
    // que reiniciou em modo copia com a aba aberta aparecem sem F5; a falha mantem o que ja' se sabia.
    const ler = () => api<{ instalacao?: string }>("/api/health")
      .then(s => setCopia(s?.instalacao === "nao-autorizada")).catch(() => {});
    ler();
    const id = window.setInterval(ler, 5 * 60_000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    // apos F5 a sessao volta pelo cookie, mas o token CSRF vive so em memoria:
    // restaurar aqui, senao toda mutacao da 403 ate o proximo login.
    api<Usuario & { csrf: string }>("/api/auth/eu")
      .then(eu => { setCsrf(eu.csrf); setUsuario(eu); })
      .catch(() => {}).finally(() => setCarregando(false));
  }, []);

  // "/" (ou caminho desconhecido) vira a entrada do perfil SEM empilhar historico: quem entrou por "/" e
  // clica em Voltar sai do app, como em qualquer site. A admin so' existe para admin — outro perfil que cole
  // a URL cai na propria entrada, nao numa tela que o servidor recusaria pedido a pedido. Caminho antigo
  // (/contratos/7, /diretoria, /certidoes) abre a tela nova e a barra de endereco passa a mostrar o caminho
  // canonico, com os filtros e a secao que vieram.
  useEffect(() => {
    if (!usuario) return;
    // O SIGA (tela e aba do contratante) e' de quem tem `ver_siga`, a permissao que o servidor informa (#829)
    if (rota.tela === "raiz" || (rota.tela === "admin" && usuario.perfil !== "admin")
      || (rota.tela === "siga" && !pode(usuario, "ver_siga"))
      // as Licitacoes (#908) seguem o SIGA: quem nao tem `ver_licitacoes` cai na entrada do perfil
      || ((rota.tela === "licitacoes" || rota.tela === "licitacoes-favoritas") && !pode(usuario, "ver_licitacoes"))
      || (rota.tela === "ancoras-docusign" && usuario.perfil === "diretoria")) {
      substituir(entradaDe(usuario.perfil));
    } else if (rota.tela === "contratante" && rota.aba
      && (!ABAS_PRONTAS.includes(rota.aba) || (rota.aba === "siga" && !pode(usuario, "ver_siga")))) {
      // A aba do contratante que a pagina ainda nao desenha (ABAS_PRONTAS, abasDoContratante.ts) abre a pagina como ela e'
      // hoje. E a aba do SIGA segue a tela SIGA: quem nao a ve cai na pagina do contratante.
      substituir({ tela: "contratante", chave: rota.chave });
    } else if (rota.tela === "obras" && busca.avisos === "1") {
      // os Avisos tem pagina propria (#805): o link de antes, de quando abriam dentro de Obras, leva para la'
      substituir({ tela: "avisos" }, { busca: buscaDosAvisos(busca) });
    } else if (rota.tela === "documentos" && (busca.aba === "regularidade" || busca.aba === "garantias" || busca.aba === "certidoes")) {
      // Documentos tem tres enderecos (#814): o de antes, com a aba na busca ("/documentos?aba=garantias"), abre a pagina
      const { aba, ...resto } = busca;
      substituir(aba === "certidoes" ? { tela: "documentos" } : { tela: "documentos", pagina: aba }, { busca: resto });
    } else if (rota.tela === "documentos" && /^[1-9][0-9]{0,14}$/.test(busca.empresa ?? "")) {
      // O link salvo da tela antiga ("/documentos?empresa=3#emp-3") abre a pagina da empresa. Mora aqui, e nao na
      // pagina Certidoes: o efeito da pagina roda antes deste e o App devolvia o endereco para /documentos.
      substituir({ tela: "documentos-empresa", id: Number(busca.empresa) }, { semBusca: true });
    } else if (caminhoDe(rota) !== window.location.pathname) {
      substituir(rota);
    }
    // `substituir` e' do modulo (estavel); listar so' o que decide o redirecionamento.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [usuario, rota, busca]);

  // a vista que se chama pelo dado (a comparacao do Fechamento, "2026 × 2025") chega ao titulo quando a pagina a publica
  const vistaPublicada = useVistaPublicada();
  useEffect(() => {
    // A obra e a medicao poem o proprio titulo ("MT-388 · Prazos"), quando o cabecalho delas chega.
    // O contratante tambem ("SINFRA · Obras"), quando a lista chega.
    if (rota.tela === "obra" || rota.tela === "medicao" || rota.tela === "documentos-empresa" || rota.tela === "contratante") return;
    // a vista entra no titulo ("Obras · QDOP", "Medições · Quadro do mês"), como a aba da obra ("MT-388 · Prazos"); as
    // tres paginas de Documentos dizem a pagina e a area ("Garantias · Documentos")
    const aba = vistaDe(rota, { vista: vistaPublicada });
    const item = rota.tela === "documentos" ? itemDe(rota) : null;
    const nome = item ? `${ROTULO[item]} · ${tituloDe("documentos")}` : tituloDe(rota.tela);
    document.title = rota.tela === "raiz" ? tituloDe("raiz") : `${nome}${aba ? ` · ${aba}` : ""} · grupolotufo`;
  }, [rota, vistaPublicada]);

  // #644: quem envia e-mail le as respostas do orgao ao entrar e a cada 5 minutos; quem so' consulta nao dispara leitura.
  useLeituraDasRespostas(!!usuario && usuario.perfil !== "diretoria");

  // A ancora (#emp-3) leva a secao quando a tela terminar de montar.
  useRolarAteSecao(usuario ? secao : "", caminhoDe(rota));

  const faixa = copia ? <FaixaInstalacao /> : null;
  if (carregando) return faixa;
  // Depois do login a URL que a pessoa abriu continua valendo (o efeito acima so'
  // troca "/" e o que ela nao pode ver): o link do e-mail leva a obra, nao a entrada.
  if (!usuario) return <><Login aoEntrar={setUsuario} />{faixa}</>;

  // A barra do topo escreve o caminho, e o trecho da pagina e' o titulo. Quem tem titulo proprio (o objeto, ou o "Bom
  // dia" do Inicio) fica com o h1 da pagina, e a barra nao repete um segundo h1.
  const tituloProprio = ehDetalhe(rota) || rota.tela === "inicio" || rota.tela === "obras" || rota.tela === "contratante"
    || (rota.tela === "siga" && /^\d+$/.test(busca.processo ?? ""));   // o historico do processo tem o h1 dele

  return (
    <div className="casca">
      {/* Primeira parada de Tab: pula o trilho e a barra (menu, conta) direto para a tela. So' move o foco: a
          navegacao por fragmento empilharia historico sem a origem e poria "conteudo" como secao na URL. */}
      <a className="pular" href="#conteudo" onClick={ev => {
        ev.preventDefault();
        document.getElementById("conteudo")?.focus();
      }}>Pular para o conteúdo</a>
      <Trilho perfil={usuario.perfil} permissoes={usuario.permissoes} marcado={itemDe(rota, usuario.perfil)} ir={ir} />

      <div className="coluna">
        <BarraSuperior rota={rota} busca={busca} origem={origem} ehH1={!tituloProprio} usuario={usuario} ir={ir} />
        <main className="principal" id="conteudo" tabIndex={-1}>
          {rota.tela === "inicio" && <div className="pagina"><Inicio usuario={usuario} ir={ir} /></div>}
          {rota.tela === "medicoes" && <MedicoesPagina usuario={usuario} aba={rota.aba} busca={busca} />}
          {/* a diretoria le o SIGA sem botao de escrita: o servidor nega a ela toda rota que grava (#829) */}
          {rota.tela === "siga" && pode(usuario, "ver_siga") && <SigaPagina busca={busca} podeEditar={pode(usuario, "editar_cadastros")} />}
          {/* Licitacoes (#908): duas paginas so' de leitura, de quem tem `ver_licitacoes` */}
          {rota.tela === "licitacoes" && pode(usuario, "ver_licitacoes") && <LicitacoesTriagem />}
          {rota.tela === "licitacoes-favoritas" && pode(usuario, "ver_licitacoes") && <LicitacoesFavoritas />}
          {rota.tela === "ancoras-docusign" && usuario.perfil !== "diretoria" && <div className="pagina"><AncorasDocusign /></div>}
          {rota.tela === "notas-envio" && <AbrirEnvio key={rota.id} protocoloId={rota.id} />}
          {rota.tela === "fechamento" && <div className="pagina"><Fechamento ir={ir} /></div>}
          {/* A receber (#805): a pagina-casca; o contratante vem na busca (?contratante=) */}
          {rota.tela === "a-receber" && <div className="pagina"><AReceber busca={busca} ir={ir} /></div>}
          {rota.tela === "resumo-medicoes" && <div className="pagina"><ResumoDasMedicoes ir={ir} busca={busca} /></div>}
          {rota.tela === "avisos" && <div className="pagina"><AvisosPagina busca={busca} /></div>}
          {rota.tela === "obras" && <Contratos ir={ir} busca={busca} aba={rota.aba} />}
          {rota.tela === "obra" && (
            // `key` no id: trocar de obra REMONTA a pagina em vez de reaproveitar a
            // instancia. Sem isso, o painel aberto e os rascunhos de formulario da
            // obra anterior sobreviviam a troca — e um cronograma digitado para a
            // obra A podia ser publicado na B. A aba vem da URL: cada aba tem link; sem aba, a pagina abre na primeira (#646).
            <ContratoPagina key={rota.id} contratoId={rota.id} usuario={usuario} aba={rota.aba} origem={origem} busca={busca} />
          )}
          {/* a pagina do contratante (#805), entre a lista de Obras e a obra; `key` na chave: outro contratante remonta */}
          {rota.tela === "contratante" && (
            <ContratantePagina key={rota.chave} chave={rota.chave} aba={rota.aba ?? "obras"} perfil={usuario.perfil}
              permissoes={usuario.permissoes} busca={busca} ir={ir} />
          )}
          {rota.tela === "medicao" && (
            // `key` na medicao: trocar de medicao (a da mesma competencia) remonta a pagina e os formularios dela.
            <MedicaoPagina key={`${rota.obra}-${rota.id}`} contratoId={rota.obra} medicaoId={rota.id} usuario={usuario} origem={origem} />
          )}
          {rota.tela === "nova-medicao" && <MedicaoNova key={rota.obra} contratoId={rota.obra} usuario={usuario} origem={origem} busca={busca} />}
          {/* as tres paginas de Documentos (#814, #820), cada uma no proprio endereco */}
          {rota.tela === "documentos" && (rota.pagina ?? "certidoes") === "certidoes" && <DocumentosCertidoes usuario={usuario} />}
          {rota.tela === "documentos" && rota.pagina === "regularidade" && <DocumentosRegularidade usuario={usuario} />}
          {rota.tela === "documentos" && rota.pagina === "garantias" && <DocumentosGarantias />}
          {rota.tela === "documentos-empresa" && (
            // `key` na empresa: trocar de empresa (pelo link de consorciada) remonta a pagina e o formulario da regularidade.
            <DocumentosEmpresa key={rota.id} usuario={usuario} id={rota.id} aba={rota.aba ?? "certidoes"} origem={origem} />
          )}
          {rota.tela === "conta" && <div className="pagina"><MinhaConta usuario={usuario} /></div>}
          {rota.tela === "admin" && usuario.perfil === "admin" && (
            <div className="pagina">
              <Admin aba={rota.aba ?? "saude"} busca={busca} eu={usuario.id} />
            </div>
          )}
        </main>
      </div>
      {/* #654: o aviso de resposta do orgao e' de quem envia; quem so' consulta (diretoria) nao tem */}
      {usuario.perfil !== "diretoria" && <AvisoRespostas ir={ir} />}
      {faixa}
    </div>
  );
}
