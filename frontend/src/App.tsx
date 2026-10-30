import { useEffect, useState } from "react";
import Admin from "./Admin";
import { api, setCsrf } from "./api";
import AReceberPagina from "./AReceberPagina";
import { ABAS_ADMIN } from "./administracao";
import { ABAS_CARTEIRA } from "./carteira";
import { BarraSuperior, Trilho } from "./Casca";
import Documentos from "./Documentos";
import DocumentosEmpresa from "./DocumentosEmpresa";
import AbrirEnvio from "./AbrirEnvio";
import ContratoPagina from "./ContratoPagina";
import Contratos from "./Contratos";
import Inicio from "./Inicio";
import Login, { type Usuario } from "./Login";
import MedicaoPagina from "./MedicaoPagina";
import MedicoesPagina from "./MedicoesPagina";
import MinhaConta from "./MinhaConta";
import MedicaoNova from "./MedicaoNova";
import Diretoria from "./Diretoria";
import { entradaDe, itemDe, tituloDaSecao, tituloDe } from "./navegacao";
import { ABAS_MEDICOES } from "./resumoMedicoes";
import SigaPagina from "./SigaPagina";
import { buscaDosAvisosEmObras, caminhoDe, ehDetalhe, useRolarAteSecao, useRota } from "./rota";

// Menu e entrada por perfil moram em navegacao.ts (NAVEGACAO.md › Perfis e tela de entrada); o trilho e a barra
// superior, em Casca.tsx. O App so' escolhe a tela. Todo perfil entra pelo Inicio (decisao do Leonardo, 08/10/2026).

export default function App() {
  const [usuario, setUsuario] = useState<Usuario | null>(null);
  const { rota, busca, secao, origem, ir, substituir } = useRota();
  const [carregando, setCarregando] = useState(true);

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
    if (rota.tela === "raiz" || (rota.tela === "admin" && usuario.perfil !== "admin")
      || (rota.tela === "siga" && usuario.perfil === "diretoria")) {
      substituir(entradaDe(usuario.perfil));
    } else if (rota.tela === "avisos") {
      // os Avisos moram dentro de Obras (09/10/2026): o item do menu e o link de antes levam para la'
      substituir({ tela: "obras" }, { busca: buscaDosAvisosEmObras(busca) });
    } else if (caminhoDe(rota) !== window.location.pathname) {
      substituir(rota);
    }
    // `substituir` e' do modulo (estavel); listar so' o que decide o redirecionamento.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [usuario, rota, busca]);

  useEffect(() => {
    // A obra e a medicao poem o proprio titulo ("MT-388 · Prazos"), quando o cabecalho delas chega.
    if (rota.tela === "obra" || rota.tela === "medicao" || rota.tela === "documentos-empresa") return;
    // a aba da Carteira, da Administracao e de Medicoes entram no titulo ("Carteira · QDOP"), como a da obra
    // ("MT-388 · Prazos")
    const aba = rota.tela === "carteira" && rota.aba && rota.aba !== "resumo" ? ABAS_CARTEIRA.find(a => a.id === rota.aba)?.rotulo
      : rota.tela === "admin" && rota.aba && rota.aba !== "saude" ? ABAS_ADMIN.find(a => a.id === rota.aba)?.rotulo
      : rota.tela === "medicoes" && rota.aba && rota.aba !== "resumo" ? ABAS_MEDICOES.find(a => a.id === rota.aba)?.rotulo : undefined;
    document.title = rota.tela === "raiz" ? tituloDe("raiz") : `${tituloDe(rota.tela)}${aba ? ` · ${aba}` : ""} · grupolotufo`;
  }, [rota]);

  // A ancora (#emp-3) leva a secao quando a tela terminar de montar.
  useRolarAteSecao(usuario ? secao : "", caminhoDe(rota));

  if (carregando) return null;
  // Depois do login a URL que a pessoa abriu continua valendo (o efeito acima so'
  // troca "/" e o que ela nao pode ver): o link do e-mail leva a obra, nao a entrada.
  if (!usuario) return <Login aoEntrar={setUsuario} />;

  // A barra superior diz a SECAO; quem tem titulo proprio (o objeto, ou o "Bom dia" do Inicio) fica com o h1 da
  // pagina, e a barra nao repete um segundo h1.
  const tituloProprio = ehDetalhe(rota) || rota.tela === "inicio" || rota.tela === "obras";

  return (
    <div className="shell">
      {/* Primeira parada de Tab: pula o trilho e a barra (menu, conta) direto para a tela. So' move o foco: a
          navegacao por fragmento empilharia historico sem a origem e poria "conteudo" como secao na URL. */}
      <a className="pular" href="#conteudo" onClick={ev => {
        ev.preventDefault();
        document.getElementById("conteudo")?.focus();
      }}>Pular para o conteúdo</a>
      <Trilho perfil={usuario.perfil} marcado={itemDe(rota, busca)} ir={ir} />

      <div className="coluna">
        <BarraSuperior titulo={tituloDaSecao(rota)} ehH1={!tituloProprio} usuario={usuario} ir={ir} />
        <main className="principal" id="conteudo" tabIndex={-1}>
          {rota.tela === "inicio" && <div className="pagina"><Inicio usuario={usuario} ir={ir} /></div>}
          {rota.tela === "medicoes" && <MedicoesPagina aba={rota.aba ?? "resumo"} busca={busca} usuario={usuario} />}
          {rota.tela === "siga" && usuario.perfil !== "diretoria" && <SigaPagina busca={busca} />}
          {rota.tela === "notas-envio" && <AbrirEnvio key={rota.id} protocoloId={rota.id} />}
          {rota.tela === "a-receber" && (
            <div className="pagina">
              <AReceberPagina />
            </div>
          )}
          {rota.tela === "carteira" && (
            <div className="pagina">
              <Diretoria ir={ir} aba={rota.aba ?? "resumo"} />
            </div>
          )}
          {rota.tela === "obras" && <Contratos ir={ir} busca={busca} />}
          {rota.tela === "obra" && (
            // `key` no id: trocar de obra REMONTA a pagina em vez de reaproveitar a
            // instancia. Sem isso, o painel aberto e os rascunhos de formulario da
            // obra anterior sobreviviam a troca — e um cronograma digitado para a
            // obra A podia ser publicado na B. A aba vem da URL: cada aba tem link.
            <ContratoPagina key={rota.id} contratoId={rota.id} usuario={usuario} aba={rota.aba} origem={origem} busca={busca} />
          )}
          {rota.tela === "medicao" && (
            // `key` na medicao: trocar de medicao (a da mesma competencia) remonta a pagina e os formularios dela.
            <MedicaoPagina key={`${rota.obra}-${rota.id}`} contratoId={rota.obra} medicaoId={rota.id} usuario={usuario} origem={origem} />
          )}
          {rota.tela === "nova-medicao" && <MedicaoNova key={rota.obra} contratoId={rota.obra} usuario={usuario} origem={origem} busca={busca} />}
          {rota.tela === "documentos" && <Documentos usuario={usuario} busca={busca} />}
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
    </div>
  );
}
