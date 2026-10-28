import { useEffect, useState } from "react";
import { contar } from "./formato";
import { rotuloPerfil } from "./navegacao";
import CaixaAviso from "./CaixaAviso";
import {
  ABAS_ADMIN, campoDoErroDeUsuario, CATEGORIAS_REC, contagemRec, contaRec, filtrarEventos, juntarPaginaRec, nfsPorEmissao, pessoaDoEvento, quantidadeRec,
  reconciliacaoDaObra, rotaDoObjeto, rotuloAcao, rotuloObjeto, rotuloRec, urlPaginaRec,
  type CategoriaRec, type Evento, type Reconciliacao,
} from "./administracao";
import { api, mensagemDeErro } from "./api";
import { IconeAlerta } from "./icones";
import { nomeDaObra, type ObraLista } from "./listaObras";
import { tituloMedicao } from "./medicao";
import { brl, ROTULO_ESTADO } from "./Medicoes";
import { trocarBusca, type AbaAdmin, type Busca } from "./rota";
import { Link } from "./Link";
import { fmtCompetencia, fmtDataHora, fmtDataPura, fmtDuracao, fmtHora } from "./tempo";
import "./admin.css";
import Rolagem from "./Rolagem";
import Selo from "./Selo";
import { Abas } from "./Topo";

// Administracao (NAVEGACAO.md › Administracao), em abas na URL: Saude (a padrao: o RM, a reconciliacao em contagens e
// o backup), Reconciliacao (?categoria=, ?obra=), Usuarios (com a conta Microsoft de cada um) e Auditoria (?acao=,
// ?pessoa=, ?desde=). So' o admin chega aqui: o App manda os outros perfis para a entrada deles.

// bloqueado_ate: so' o bloqueio em vigor (hora de Cuiaba), null sem bloqueio (A-05, 10/10/2026)
interface Usr { id: number; nome: string; email: string; perfil: string; ativo: number; bloqueado_ate?: string | null; }

// Fase 5: integracao com o RM. `configurado` vem do ambiente do servidor; as rodadas sao a tabela
// rm_sincronizacoes, da mais nova para a mais antiga.
type Rodada = {
  id: number; disparo: string; estado: string; iniciado_em: string; terminado_em: string | null;
  nfs: number; baixas: number; alocacoes: number; sugestoes: number; recebimentos: number; erro: string | null;
};
type StatusRm = {
  configurado: boolean; ultima_sincronizacao: string | null; ultimo_erro: string | null;
  em_andamento: boolean; rodadas: Rodada[];
};
// Bloco 9: fica so' quem conectou a propria conta para enviar e-mail; a conexao e' feita por cada pessoa em Minha conta.
type Conta = { usuario_id: number; nome: string; email: string; perfil: string; conectada: boolean; token_em: string | null };
// Issue #31: /api/admin/backup. O ultimo backup, o tamanho e a contagem vem do disco local; as tentativas e os erros
// (ultimo_*) moram na memoria do servidor e zeram quando ele reinicia. `atrasado` = mais de 2 h sem snapshot.
type Backup = { ultimo_backup: string | null; tamanho_bytes: number | null; guardados: number;
                copia_externa_configurada: boolean; atrasado: boolean;
                // *_erro: frase fixa em portugues (a excecao crua fica no log do servidor); *_erro_em: quando falhou
                ultimo_snapshot: string | null; ultimo_snapshot_erro: string | null; ultimo_snapshot_erro_em: string | null;
                ultima_copia_externa: string | null; ultima_copia_externa_erro: string | null;
                ultima_copia_externa_erro_em: string | null;
                // issue #55: copia de notas, espelhos, modelos e evidencias; aqui o *_erro ja' vem limpo do servidor
                // (o que faltou, ou "rodando ha N horas sem terminar"), sem caminho
                ultima_copia_arquivos?: string | null; ultima_copia_arquivos_erro?: string | null;
                ultima_copia_arquivos_erro_em?: string | null;
                ultima_copia_externa_arquivos?: string | null; ultima_copia_externa_arquivos_erro?: string | null;
                ultima_copia_externa_arquivos_erro_em?: string | null };

// Issue #330: /api/admin/saude. ultima_leitura = quando o monitor do SIGA mandou a leitura mais recente (nulo: nunca leu)
type SaudeSiga = { ultima_leitura: string | null; processos: number };

const ROTULO_ESTADO_RODADA: Record<string, string> = { success: "OK", failed: "Falhou", running: "Rodando" };
// A auditoria chega em paginas dos mais recentes; "Carregar mais" traz as anteriores e os filtros correm sobre
// tudo o que ja' chegou (a API aceita ate' 500 por pagina).
const LIMITE_AUDITORIA = 500;
type PaginaAuditoria = { cadeia_integra: boolean | null; ha_mais: boolean; eventos: Evento[] };
// Sem grupo escolhido, cada grupo da reconciliacao mostra as primeiras linhas; o resto abre pelo link dele.
const PRIMEIRAS = 10;

function mensagem(e: unknown): string {
  return mensagemDeErro(e);
}

// falha ao carregar: o proximo passo vai junto da mensagem da API
function falhaDeCarga(e: unknown): string {
  return `${mensagem(e)} Recarregue a página para tentar de novo.`;
}


function Erro({ texto, id }: { texto: string; id?: string }) {
  return <div className="cartao__corpo"><p className="erro" role="alert" id={id}><IconeAlerta className="icone icone--p" />{texto}</p></div>;
}

// F-65: o resultado de uma rodada ou de um servico no vocabulario unico OK / Falhou / Rodando (cabeca do cartao e tabela)
function SeloRodada({ estado }: { estado: string }) {
  return (
    <Selo classe={estado === "success" ? "selo--ok" : estado === "failed" ? "selo--acao" : ""}>
      {ROTULO_ESTADO_RODADA[estado] ?? estado}
    </Selo>
  );
}

// F-87: o estado da medicao em ponto + palavra (a mesma gramatica do `Estado` da medicao, sem o final e o cadeado)
function EstadoMedicao({ estado }: { estado: string }) {
  return (
    <span className={`estado estado--${estado}`}>
      <span className="estado__ponto" aria-hidden="true" />{ROTULO_ESTADO[estado] ?? estado}
    </span>
  );
}

/* ------------------------------------------------------------------- saude */

type Situacao = "ok" | "atencao" | "acao" | "neutra";
type Cartao = [titulo: string, valor: string, nota: string, situacao: Situacao];

/** Um cartao de situacao: ponto colorido + titulo + o valor (a hora) + a nota, so' quando ha' falha ou atraso. */
function CartaoSituacao({ titulo, valor, nota, situacao }: { titulo: string; valor: string; nota: string; situacao: Situacao }) {
  return (
    <li className={`cartao situacao situacao--${situacao}`}>
      <span className="situacao__ponto" aria-hidden="true" />
      <h2 className="situacao__titulo">{titulo}</h2>
      <span className="situacao__valor">{valor}</span>
      {nota && <span className="situacao__nota">{nota}</span>}
    </li>
  );
}

// o backup falhou: atrasado ou uma das tentativas de copia deu erro (o cartao de cima e o cartao Backup usam a mesma regra)
function backupFalhou(b: Backup | null | undefined): boolean {
  return !!b && (b.atrasado || !!b.ultimo_snapshot_erro || !!b.ultima_copia_externa_erro
    || !!b.ultima_copia_arquivos_erro || !!b.ultima_copia_externa_arquivos_erro);
}

function Situacoes({ status, erroCarga, rodando, b, siga }: {
  status: StatusRm | null; erroCarga: string; rodando: boolean; b: Backup | null | undefined; siga: SaudeSiga | null | undefined;
}) {
  const neutro = (t: string, v: string, n: string): Cartao => [t, v, n, "neutra"];
  const T_BACKUP = "Último backup", T_EXTERNA = "Última cópia externa dos arquivos", T_RM = "Sincronização com o RM", T_SIGA = "Monitor do SIGA";
  const NAO_LEU = "recarregue a página para tentar de novo";
  // 1. ultimo backup
  const backup: Cartao = b === undefined ? neutro(T_BACKUP, "carregando…", "")
    : b === null ? neutro(T_BACKUP, "não foi possível ler", NAO_LEU)
    : [
      T_BACKUP, b.ultimo_backup ? fmtDataHora(b.ultimo_backup) : "—",
      b.atrasado ? "atrasado: sem snapshot recente" : backupFalhou(b) ? "uma das cópias falhou" : "",
      backupFalhou(b) ? "acao" : "ok",
    ];
  // 2. ultima copia externa dos arquivos (so' existe com pasta externa)
  const externa: Cartao = b === undefined ? neutro(T_EXTERNA, "carregando…", "")
    : b === null ? neutro(T_EXTERNA, "não foi possível ler", NAO_LEU)
    : b.ultima_copia_externa_arquivos_erro
      ? [T_EXTERNA, b.ultima_copia_externa_arquivos ? fmtDataHora(b.ultima_copia_externa_arquivos) : "—", "a última tentativa falhou", "acao"]
    : !b.copia_externa_configurada ? neutro(T_EXTERNA, "—", "")
    : b.ultima_copia_externa_arquivos
      ? [T_EXTERNA, fmtDataHora(b.ultima_copia_externa_arquivos), "", "ok"]
    : [T_EXTERNA, "nenhuma", "", "atencao"];
  // 3. sincronizacao com o RM
  const rodadas = status?.rodadas ?? [];
  const ultima = rodadas[0] ?? null;
  const rm: Cartao = status === null ? neutro(T_RM, erroCarga ? "não foi possível ler" : "carregando…", erroCarga ? NAO_LEU : "")
    : !status.configurado ? neutro(T_RM, "não configurado", "")
    : rodando || status.em_andamento || ultima?.estado === "running" ? neutro(T_RM, "rodando", "")
    : ultima === null ? neutro(T_RM, "—", "")
    : ultima.estado === "failed"
      ? [T_RM, `falhou em ${fmtDataHora(ultima.iniciado_em)}`, "", "acao"]
    : [T_RM, fmtDataHora(ultima.terminado_em ?? ultima.iniciado_em), "", "ok"];
  // 4. monitor do SIGA (issue #330): a hora da ultima leitura e quantos processos ele acompanha
  const monitor: Cartao = siga === undefined ? neutro(T_SIGA, "carregando…", "")
    : siga === null ? neutro(T_SIGA, "não foi possível ler", NAO_LEU)
    : siga.ultima_leitura === null ? neutro(T_SIGA, "—", "")
    : [T_SIGA, fmtDataHora(siga.ultima_leitura), `${siga.processos} ${siga.processos === 1 ? "processo" : "processos"}`, "ok"];
  return (
    <ul className="situacoes" aria-label="Situação do servidor">
      {[backup, externa, rm, monitor].map(([titulo, valor, nota, situacao]) => (
        <CartaoSituacao key={titulo} titulo={titulo} valor={valor} nota={nota} situacao={situacao} />
      ))}
    </ul>
  );
}

function Rodadas({ status, erroCarga }: { status: StatusRm | null; erroCarga: string }) {
  const ultima = status?.rodadas[0] ?? null;
  return (
    <section className="cartao" aria-labelledby="titulo-rm">
      <div className="cartao__cabeca cartao__cabeca--quebra">
        <h2 className="cartao__titulo" id="titulo-rm">Rodadas de sincronização com o RM</h2>
      </div>
      {erroCarga && <Erro texto={erroCarga} />}

      {status?.configurado && ultima === null && <div className="vazio vazio--curto"><p>Nenhuma rodada.</p></div>}

      {status && status.rodadas.length > 0 && (
        <Rolagem rotulo="Rodadas de sincronização com o RM">
          <table className="tabela">
            <caption className="sr-only">Últimas rodadas de sincronização com o RM</caption>
            <thead>
              <tr>
                <th scope="col">Início</th><th scope="col">Disparo</th><th scope="col">Duração</th><th scope="col">Resultado</th>
                <th scope="col" className="col-num">NFs</th><th scope="col" className="col-num">Baixas</th>
                <th scope="col" className="col-num">Alocadas</th><th scope="col" className="col-num">Ambíguas</th>
                <th scope="col" className="col-num">Recebidas</th>
              </tr>
            </thead>
            <tbody>
              {status.rodadas.map((r, i) => (
                <tr key={r.id} className={`linha${i % 2 === 1 ? " par" : ""}`}>
                  <td className="num">{fmtDataHora(r.iniciado_em)}</td>
                  <td>{r.disparo}</td>
                  <td className="num">{r.terminado_em ? fmtDuracao(r.iniciado_em, r.terminado_em) : "—"}</td>
                  <td>
                    <SeloRodada estado={r.estado} />
                    {r.erro && <div className="campo__nota situacao__erro">{r.erro}</div>}
                  </td>
                  <td className="col-num num">{r.nfs.toLocaleString("pt-BR")}</td>
                  <td className="col-num num">{r.baixas.toLocaleString("pt-BR")}</td>
                  <td className="col-num num">{r.alocacoes.toLocaleString("pt-BR")}</td>
                  <td className="col-num num">{r.sugestoes.toLocaleString("pt-BR")}</td>
                  <td className="col-num num">{r.recebimentos.toLocaleString("pt-BR")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Rolagem>
      )}
    </section>
  );
}

/** As contagens da reconciliacao; cada uma leva ao grupo dela na aba Reconciliacao. */
function ReconciliacaoResumo({ versao }: { versao: number }) {
  const [rec, setRec] = useState<Reconciliacao | null>(null);
  const [erro, setErro] = useState("");
  useEffect(() => {
    api<Reconciliacao>("/api/rm/reconciliacao").then(r => { setRec(r); setErro(""); }).catch(e => setErro(falhaDeCarga(e)));
  }, [versao]);
  return (
    <section className="cartao" aria-labelledby="titulo-rec-resumo">
      <div className="cartao__cabeca cartao__cabeca--quebra">
        <h2 className="cartao__titulo" id="titulo-rec-resumo">Reconciliação RM × dashboard</h2>
      </div>
      {erro && <Erro texto={erro} />}
      {!rec && !erro && <div className="vazio"><p>Carregando…</p></div>}
      {rec && (
        <ul className="contagens cartao__corpo">
          {CATEGORIAS_REC.map(c => {
            const { n } = contaRec(rec, rec, c.id, false);
            const dado = (
              <>
                <span className="dado__valor num">{quantidadeRec(n)}</span>{" "}
                <span className="campo__nota">{rotuloRec(c.id, n)}</span>
              </>
            );
            return (
              <li key={c.id}>{n === 0 ? <div className="dado">{dado}</div> : (
                <Link className="dado contagem" para={{ tela: "admin", aba: "reconciliacao" }} busca={{ categoria: c.id }}
                  aria-label={contagemRec(c.id, n)}>{dado}</Link>
              )}</li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/** A falha de uma copia, so' quando ha' falha: a linha da copia que deu certo nao aparece. */
function LinhaBackup({ rotulo, em, erro, erroEm }: { rotulo: string; em: string | null; erro: string | null; erroEm: string | null }) {
  if (!erro) return null;
  return (
    <CaixaAviso nivel="critico">
      {rotulo}: a última tentativa{erroEm ? `, em ${fmtDataHora(erroEm)},` : ""} falhou ({erro}).{em ? ` A última que deu certo foi em ${fmtDataHora(em)}.` : ""}
    </CaixaAviso>
  );
}

// b: undefined = carregando; null = nao deu para ler
function Backup({ b }: { b: Backup | null | undefined }) {
  const falhou = backupFalhou(b);
  return (
    <section className="cartao" aria-labelledby="titulo-backup">
      <div className="cartao__cabeca cartao__cabeca--quebra">
        <h2 className="cartao__titulo" id="titulo-backup">Backup</h2>
        {/* o resultado de relance: Falhou se esta atrasado ou uma das tentativas falhou; OK com backup em dia */}
        {b && (falhou ? <SeloRodada estado="failed" /> : b.ultimo_backup ? <SeloRodada estado="success" /> : null)}
      </div>
      {(b === undefined || b === null || falhou) && (
        <div className="cartao__corpo pilha pilha--curta">
          {b === undefined ? <p>Carregando…</p>
            : b === null ? <p className="campo__nota">Não foi possível ler o estado do backup; recarregue a página para tentar de novo.</p>
            : <>
                {b.atrasado && (
                  <CaixaAviso nivel="critico" role="alert">
                    {`Backup atrasado: ${b.ultimo_backup ? `o último foi em ${fmtDataHora(b.ultimo_backup)}, há mais de 2 horas.`
                      : "nenhum backup guardado neste servidor."} Confira a tarefa do servidor e a pasta de backups.`}
                  </CaixaAviso>
                )}
                <LinhaBackup rotulo="Último snapshot" em={b.ultimo_snapshot} erro={b.ultimo_snapshot_erro} erroEm={b.ultimo_snapshot_erro_em} />
                <LinhaBackup rotulo="Última cópia externa" em={b.ultima_copia_externa} erro={b.ultima_copia_externa_erro} erroEm={b.ultima_copia_externa_erro_em} />
                {/* issue #55: notas, espelhos, modelos e evidencias */}
                <LinhaBackup rotulo="Última cópia dos arquivos" em={b.ultima_copia_arquivos ?? null} erro={b.ultima_copia_arquivos_erro ?? null}
                  erroEm={b.ultima_copia_arquivos_erro_em ?? null} />
                <LinhaBackup rotulo="Última cópia externa dos arquivos" em={b.ultima_copia_externa_arquivos ?? null}
                  erro={b.ultima_copia_externa_arquivos_erro ?? null} erroEm={b.ultima_copia_externa_arquivos_erro_em ?? null} />
              </>}
        </div>
      )}
    </section>
  );
}

function Saude() {
  const [status, setStatus] = useState<StatusRm | null>(null);
  // erroCarga: nao deu para ler o estado do RM; erro/concluida: o resultado de "Sincronizar agora"
  const [erroCarga, setErroCarga] = useState("");
  const [erro, setErro] = useState("");
  const [rodando, setRodando] = useState(false);
  const [concluida, setConcluida] = useState("");
  // undefined = carregando; null = nao deu para ler
  const [b, setB] = useState<Backup | null | undefined>(undefined);
  const [siga, setSiga] = useState<SaudeSiga | null | undefined>(undefined);
  // depois de "Sincronizar agora", as contagens da reconciliacao sao lidas de novo
  const [versao, setVersao] = useState(0);

  const carregar = () => api<StatusRm>("/api/rm/status").then(s => { setStatus(s); setErroCarga(""); }).catch(e => setErroCarga(falhaDeCarga(e)));
  useEffect(() => {
    carregar();
    api<Backup>("/api/admin/backup").then(setB).catch(() => setB(null));
    api<{ siga: SaudeSiga }>("/api/admin/saude").then(r => setSiga(r.siga)).catch(() => setSiga(null));
  }, []);

  async function sincronizar() {
    setErro(""); setConcluida(""); setRodando(true);
    try {
      const r = await api<{ estado: string; erro?: string }>("/api/rm/sincronizar", { method: "POST" });
      if (r.estado === "failed") setErro(`A sincronização falhou: ${r.erro ?? "erro desconhecido"}`);
      else if (r.estado === "success") setConcluida("Sincronização concluída.");
      await carregar();
      setVersao(v => v + 1);
    } catch (e) {
      setErro(mensagem(e));
    } finally { setRodando(false); }
  }

  const ultima = status?.rodadas[0] ?? null;
  // a ultima que deu certo: a rodada mais nova com sucesso (fica no banco); sem nenhuma entre as 10, a da memoria do
  // servidor (zera quando ele reinicia)
  const ultimaBoa = status?.rodadas.find(r => r.estado === "success") ?? null;
  const quandoBoa = ultimaBoa ? ultimaBoa.terminado_em ?? ultimaBoa.iniciado_em : status?.ultima_sincronizacao ?? null;
  return (
    <div className="saude pilha">
      <Situacoes status={status} erroCarga={erroCarga} rodando={rodando} b={b} siga={siga} />

      {status?.configurado && ultima?.estado === "failed" && !rodando && !erro && (
        <CaixaAviso nivel="critico">
          Última rodada: falhou em {fmtDataHora(ultima.iniciado_em)} ({ultima.disparo}). {ultima.erro ?? "Erro desconhecido."}
          {quandoBoa ? ` A última que deu certo foi em ${fmtDataHora(quandoBoa)}.` : ""}
        </CaixaAviso>
      )}

      <div className="acoes-saude">
        <button type="button" className="btn btn--primario" onClick={sincronizar} disabled={rodando || !status?.configurado || status.em_andamento || ultima?.estado === "running"}>
          {rodando ? "Sincronizando…" : "Sincronizar agora"}
        </button>
        {/* so' o motivo do bloqueio do botao, quando ha' */}
        {status && !status.configurado && <p>O RM não está configurado neste servidor.</p>}
        {status?.configurado && !rodando && (status.em_andamento || ultima?.estado === "running") && <p>Uma rodada está em andamento.</p>}
      </div>
      {erro && <section className="cartao"><Erro texto={erro} /></section>}
      <div role="status">{concluida && !erro && <p className="campo__nota">{concluida}</p>}</div>

      <Rodadas status={status} erroCarga={erroCarga} />

      <div className="saude-lado">
        <ReconciliacaoResumo versao={versao} />
        <Backup b={b} />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ reconciliacao */

// `conta`: o total do grupo (contaRec); `carregadas`: as linhas que ja' chegaram da API (no recorte da obra);
// `mostrando`: as que a tabela mostra. "Ver as N linhas" abre o grupo; "Carregar mais" (`mais`) traz a pagina seguinte.
function Grupo({ id, titulo, conta, carregadas, mostrando, verTodas, mais, children }: {
  id: CategoriaRec; titulo: string; conta: { n: number; piso: boolean; haMais: boolean }; carregadas: number; mostrando: number;
  verTodas: React.ReactNode; mais: React.ReactNode; children: React.ReactNode;
}) {
  const { piso, haMais } = conta;
  return (
    <section className="cartao" aria-labelledby={`titulo-rec-${id}`}>
      <div className="cartao__cabeca">
        <h2 className="cartao__titulo" id={`titulo-rec-${id}`}>{titulo}</h2>
      </div>
      {/* com `piso` ainda ha' linhas por carregar: o grupo nao esta' vazio, so' a pagina carregada */}
      {carregadas === 0 ? <div className="vazio vazio--curto"><p>{piso ? "Nenhuma linha entre as carregadas." : "Nenhuma linha."}</p></div> : children}
      {mostrando < carregadas && <div className="cartao__corpo">{verTodas}</div>}
      {mostrando === carregadas && haMais && <div className="cartao__corpo">{mais}</div>}
    </section>
  );
}

function ReconciliacaoAba({ busca }: { busca: Busca }) {
  const [rec, setRec] = useState<Reconciliacao | null>(null);
  const [erro, setErro] = useState("");
  // as obras dao o nome e o filtro; a alocacao desfeita acha a obra pelo instrumento (a API nao manda o id nela)
  const [obras, setObras] = useState<ObraLista[] | null | undefined>(undefined);
  // #22: o grupo cuja pagina seguinte esta' chegando, e o erro dela (fica junto do botao do grupo)
  const [carregando, setCarregando] = useState<CategoriaRec | null>(null);
  const [erroMais, setErroMais] = useState<{ c: CategoriaRec; texto: string } | null>(null);
  useEffect(() => {
    api<Reconciliacao>("/api/rm/reconciliacao").then(setRec).catch(e => setErro(falhaDeCarga(e)));
    api<ObraLista[]>("/api/contratos").then(setObras).catch(() => setObras(null));
  }, []);

  function carregarMais(c: CategoriaRec) {
    if (!rec || carregando) return;
    setCarregando(c); setErroMais(null);
    api<Reconciliacao>(urlPaginaRec(rec, c))
      .then(p => setRec(r => r && juntarPaginaRec(r, c, p)))
      .catch(e => setErroMais({ c, texto: mensagem(e) }))
      .finally(() => setCarregando(null));
  }

  const categoria = CATEGORIAS_REC.find(c => c.id === busca.categoria)?.id ?? null;
  const obraId = busca.obra && /^\d+$/.test(busca.obra) ? Number(busca.obra) : null;
  const porId = new Map((obras ?? []).map(o => [o.id, o]));
  const porInstrumento = new Map((obras ?? []).map(o => [o.numero_instrumento, o]));
  const obra = obraId === null ? null : porId.get(obraId) ?? null;
  const aqui = { tela: "admin" as const, aba: "reconciliacao" as const };
  const com = (m: Record<string, string | null>): Busca => {
    const b: Busca = { ...busca };
    for (const [k, v] of Object.entries(m)) { if (v === null) delete b[k]; else b[k] = v; }
    return b;
  };

  if (erro) return <section className="cartao"><Erro texto={erro} /></section>;
  // com obra na URL, espera a lista de obras: sem ela, as alocacoes desfeitas da obra nao se acham (o "0" seria falso)
  if (!rec || (obraId !== null && obras === undefined)) return <section className="cartao"><div className="vazio"><p>Carregando…</p></div></section>;
  // sem a lista de obras (falhou), o filtro por obra fica desligado
  const filtro = obraId !== null && obras !== null ? { id: obraId, numero_instrumento: obra?.numero_instrumento ?? null } : null;
  const d = reconciliacaoDaObra(rec, filtro);
  const mostra = (c: CategoriaRec) => categoria === null || categoria === c;
  const quantas = (n: number) => (categoria === null ? Math.min(n, PRIMEIRAS) : n);
  const conta = (c: CategoriaRec) => contaRec(rec, d, c, filtro !== null);
  const verTodas = (c: CategoriaRec) => {
    const { n, piso } = conta(c);
    return <Link para={aqui} busca={com({ categoria: c })}>Ver as {quantidadeRec(n, piso)} linhas</Link>;
  };
  const mais = (c: CategoriaRec) => (
    <>
      {erroMais?.c === c && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erroMais.texto}</p>}
      <button type="button" className="btn btn--pequeno" onClick={() => carregarMais(c)} disabled={carregando !== null}>
        {carregando === c ? "Carregando…" : "Carregar mais"}
      </button>
    </>
  );
  const nomeObra = (id: number, instrumento: string) => {
    const o = porId.get(id);
    return <Link className="nome-link" para={{ tela: "obra", id, aba: "medicoes" }}>{o ? nomeDaObra(o) : instrumento}</Link>;
  };
  const obrasOrdenadas = [...(obras ?? [])].sort((a, b) => nomeDaObra(a).localeCompare(nomeDaObra(b), "pt-BR"));
  const linhas = CATEGORIAS_REC.filter(c => mostra(c.id)).reduce((soma, c) => soma + d[c.campo].length, 0);

  return (
    <>
      <section className="cartao" aria-labelledby="titulo-rec-filtros">
        <div className="cartao__cabeca">
          <h2 className="cartao__titulo" id="titulo-rec-filtros">Reconciliação RM × dashboard</h2>
        </div>
        <div className="cartao__corpo filtros-avisos__linhas">
          <p className="filtros-avisos__linha">
            <span className="resumo__rotulo">Grupo</span>
            <Link para={aqui} busca={com({ categoria: null })} aria-current={categoria === null ? "true" : undefined}>todos</Link>
            {CATEGORIAS_REC.map(c => (
              <Link key={c.id} para={aqui} busca={com({ categoria: c.id })} aria-current={categoria === c.id ? "true" : undefined}>{c.titulo}</Link>
            ))}
          </p>
          <div className="form-inline">
            <div className="campo">
              <label className="campo__rotulo" htmlFor="rec-obra">Obra</label>
              <select id="rec-obra" value={obraId ?? ""} onChange={e => trocarBusca({ obra: e.target.value || null })}>
                <option value="">Todas</option>
                {obraId !== null && !obra && <option value={obraId}>obra {obraId}</option>}
                {obrasOrdenadas.map(o => <option key={o.id} value={o.id}>{nomeDaObra(o)}</option>)}
              </select>
            </div>
          </div>
          {/* so' a contagem do recorte na regiao viva: trocar o grupo ou a obra refaz as tabelas */}
          <span className="sr-only" role="status">{linhas === 1 ? "1 linha" : `${linhas.toLocaleString("pt-BR")} linhas`}</span>
          {obras === null && <p className="campo__nota">Não foi possível ler as obras: o filtro por obra fica desligado e as alocações desfeitas ficam sem link. Recarregue a página para tentar de novo.</p>}
        </div>
      </section>

      {mostra("nfs") && (
        <Grupo id="nfs" titulo="NFs sem medição" conta={conta("nfs")} carregadas={d.nfs_sem_medicao.length}
          mostrando={quantas(d.nfs_sem_medicao.length)} verTodas={verTodas("nfs")} mais={mais("nfs")}>
          <Rolagem rotulo="NFs sem medição">
            <table className="tabela">
              <caption className="sr-only">NFs do RM sem medição na dashboard</caption>
              <thead><tr><th scope="col">NF</th><th scope="col" className="col-num">Coligada</th><th scope="col">Emissão</th>
                <th scope="col" className="col-num">Valor</th><th scope="col">Campo livre 1 (RM)</th></tr></thead>
              <tbody>
                {nfsPorEmissao(d.nfs_sem_medicao).slice(0, quantas(d.nfs_sem_medicao.length)).map((n, i) => (
                  <tr key={n.id} className={`linha${i % 2 === 1 ? " par" : ""}`}>
                    <td className="num">{n.numero}{n.serie ? `/${n.serie}` : ""}</td><td className="col-num num">{n.coligada}</td>
                    <td className="num">{n.emissao ? fmtDataPura(n.emissao) : "sem data"}</td>
                    <td className="col-num dinheiro num">{brl(n.valor_centavos)}</td><td>{n.campo_livre1 ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Rolagem>
        </Grupo>
      )}

      {mostra("medicoes") && (
        <Grupo id="medicoes" titulo="Medições sem NF do RM" conta={conta("medicoes")} carregadas={d.medicoes_sem_nf.length}
          mostrando={quantas(d.medicoes_sem_nf.length)} verTodas={verTodas("medicoes")} mais={null}>
          <Rolagem rotulo="Medições sem NF do RM">
            <table className="tabela">
              <caption className="sr-only">Medições com NF ou recebimento na dashboard e sem nota do RM alocada</caption>
              <thead><tr><th scope="col">Obra</th><th scope="col">Medição</th><th scope="col">Competência</th>
                <th scope="col">Situação</th><th scope="col" className="col-num">Valor</th></tr></thead>
              <tbody>
                {d.medicoes_sem_nf.slice(0, quantas(d.medicoes_sem_nf.length)).map((m, i) => (
                  <tr key={m.medicao_id} className={`linha${i % 2 === 1 ? " par" : ""}`}>
                    <td>{nomeObra(m.contrato_id, m.numero_instrumento)}</td>
                    <td><Link para={{ tela: "medicao", obra: m.contrato_id, id: m.medicao_id }} secao="notas">{tituloMedicao(m)}</Link></td>
                    <td className="num">{fmtCompetencia(m.competencia)}</td>
                    <td><EstadoMedicao estado={m.estado} /></td>
                    <td className="col-num dinheiro num">{m.valor_centavos === null ? "—" : brl(m.valor_centavos)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Rolagem>
        </Grupo>
      )}

      {mostra("divergencias") && (
        <Grupo id="divergencias" titulo="Divergências de valor" conta={conta("divergencias")} carregadas={d.divergencias.length}
          mostrando={quantas(d.divergencias.length)} verTodas={verTodas("divergencias")} mais={null}>
          <Rolagem rotulo="Divergências de valor">
            <table className="tabela">
              <caption className="sr-only">Medições cujo valor difere da soma das NFs alocadas a elas</caption>
              <thead><tr><th scope="col">Obra</th><th scope="col">Medição</th><th scope="col">Competência</th>
                <th scope="col" className="col-num">Valor da medição</th><th scope="col" className="col-num">NFs alocadas</th></tr></thead>
              <tbody>
                {d.divergencias.slice(0, quantas(d.divergencias.length)).map((x, i) => (
                  <tr key={x.medicao_id} className={`linha${i % 2 === 1 ? " par" : ""}`}>
                    <td>{nomeObra(x.contrato_id, x.numero_instrumento)}</td>
                    <td><Link para={{ tela: "medicao", obra: x.contrato_id, id: x.medicao_id }} secao="notas">{tituloMedicao(x)}</Link></td>
                    <td className="num">{x.competencia ? fmtCompetencia(x.competencia) : "—"}</td>
                    <td className="col-num dinheiro num">{brl(x.valor_centavos)}</td><td className="col-num dinheiro num">{brl(x.alocado_centavos)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Rolagem>
        </Grupo>
      )}

      {mostra("desfeitas") && (
        <Grupo id="desfeitas" titulo="Alocações desfeitas" conta={conta("desfeitas")} carregadas={d.alocacoes_desfeitas.length}
          mostrando={quantas(d.alocacoes_desfeitas.length)} verTodas={verTodas("desfeitas")} mais={mais("desfeitas")}>
          <Rolagem rotulo="Alocações desfeitas">
            <table className="tabela">
              <caption className="sr-only">NFs cuja alocação a uma medição foi desfeita, da mais recente à mais antiga</caption>
              <thead><tr><th scope="col">Obra</th><th scope="col">Medição</th><th scope="col">NF</th><th scope="col">Desfeita em</th>
                <th scope="col">Motivo</th><th scope="col">Situação da medição</th></tr></thead>
              <tbody>
                {d.alocacoes_desfeitas.slice(0, quantas(d.alocacoes_desfeitas.length)).map((x, i) => {
                  const o = porInstrumento.get(x.numero_instrumento);
                  return (
                    <tr key={x.id} className={`linha${i % 2 === 1 ? " par" : ""}`}>
                      <td>{o ? <Link className="nome-link" para={{ tela: "obra", id: o.id, aba: "medicoes" }}>{nomeDaObra(o)}</Link> : x.numero_instrumento}</td>
                      <td>{o ? <Link para={{ tela: "medicao", obra: o.id, id: x.medicao_id }} secao="notas">{x.numero_medicao}ª Medição</Link> : `${x.numero_medicao}ª Medição`}</td>
                      <td className="num">{x.numero}{x.serie ? `/${x.serie}` : ""}</td>
                      <td className="num">{fmtDataHora(x.desfeita_em)}</td>
                      <td>{x.motivo_desfazer}</td>
                      <td><EstadoMedicao estado={x.estado} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Rolagem>
        </Grupo>
      )}

      {mostra("recebidas") && (
        <Grupo id="recebidas" titulo="Notas de recebimentos à mão sem baixa no RM" conta={conta("recebidas")} carregadas={d.recebidas_sem_baixa.length}
          mostrando={quantas(d.recebidas_sem_baixa.length)} verTodas={verTodas("recebidas")} mais={null}>
          <Rolagem rotulo="Notas de recebimentos à mão sem baixa no RM">
            <table className="tabela">
              <caption className="sr-only">NFs de medições com recebimento registrado à mão cujo título ainda está aberto no RM, uma linha por NF</caption>
              <thead><tr><th scope="col">Obra</th><th scope="col">Medição</th><th scope="col">Recebida em</th><th scope="col">NF</th>
                <th scope="col" className="col-num">Em aberto no RM</th></tr></thead>
              <tbody>
                {d.recebidas_sem_baixa.slice(0, quantas(d.recebidas_sem_baixa.length)).map((x, i) => (
                  <tr key={`${x.medicao_id}-${x.nota_id}`} className={`linha${i % 2 === 1 ? " par" : ""}`}>
                    <td>{nomeObra(x.contrato_id, x.numero_instrumento)}</td>
                    <td><Link para={{ tela: "medicao", obra: x.contrato_id, id: x.medicao_id }} secao="notas">{tituloMedicao(x)}</Link></td>
                    <td className="num">{x.recebida_em ? fmtDataPura(x.recebida_em) : "sem data"}</td>
                    <td className="num">{x.numero_nf}{x.serie ? `/${x.serie}` : ""}</td>
                    <td className="col-num dinheiro num">{brl(x.falta_centavos)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Rolagem>
        </Grupo>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ usuarios */

// `eu`: quem esta' logado. A propria linha nao tem Desativar (a API tambem recusa: trancaria o unico admin fora),
// nem perfil editavel, nem Redefinir senha (derrubaria a propria sessao; a propria senha se troca em Minha conta).
function Usuarios({ eu }: { eu?: number }) {
  const [usuarios, setUsuarios] = useState<Usr[] | null>(null);
  // undefined = carregando; null = nao deu para ler as contas Microsoft
  const [contas, setContas] = useState<Map<number, Conta> | null | undefined>(undefined);
  const [novo, setNovo] = useState({ nome: "", email: "", senha: "", perfil: "engenharia" });
  const [erro, setErro] = useState("");
  // o formulario tem o proprio erro e o proprio aviso, junto dele
  const [erroNovo, setErroNovo] = useState("");
  // desativar tira o acesso: pede confirmacao na propria linha
  const [confirmar, setConfirmar] = useState<number | null>(null);
  const [criado, setCriado] = useState("");
  const [enviando, setEnviando] = useState(false);
  // A-05/B-10 (10/10/2026): a linha com o campo de senha nova aberto, a senha digitada e o aviso de feito
  const [redefinir, setRedefinir] = useState<number | null>(null);
  const [senhaNova, setSenhaNova] = useState("");
  const [aviso, setAviso] = useState("");
  // o campo a que o erro da API se refere: fica com aria-invalid e aponta para a mensagem (N05-09)
  const campoErro = erroNovo ? campoDoErroDeUsuario(erroNovo) : null;
  const apontaErro = (campo: string) => campoErro === campo ? { "aria-invalid": true, "aria-describedby": "erro-novo-usuario" } : {};

  const carregar = () => api<Usr[]>("/api/admin/usuarios").then(setUsuarios).catch(e => setErro(falhaDeCarga(e)));
  useEffect(() => {
    carregar();
    api<Conta[]>("/api/admin/contas-microsoft").then(l => setContas(new Map(l.map(c => [c.usuario_id, c]))))
      .catch(() => setContas(null));
  }, []);

  async function criar(e: React.FormEvent) {
    e.preventDefault();
    setErroNovo(""); setCriado(""); setEnviando(true);
    try {
      await api("/api/admin/usuarios", { method: "POST", body: JSON.stringify(novo) });
      setCriado(`Usuário ${novo.nome || novo.email} criado.`);
      setNovo({ nome: "", email: "", senha: "", perfil: "engenharia" });
      carregar();
    } catch (err) {
      setErroNovo(mensagem(err));
    } finally { setEnviando(false); }
  }

  async function alternar(u: Usr) {
    try {
      await api(`/api/admin/usuarios/${u.id}`, { method: "PUT", body: JSON.stringify({ ativo: !u.ativo }) });
      setErro(""); carregar();
    } catch (err) { setErro(mensagem(err)); }
  }

  // A-05/B-10: as acoes novas seguem o `alternar` (erro do servidor no topo do cartao, recarrega a lista)
  async function agir(caminho: string, opts: RequestInit, feito: string) {
    setAviso("");
    try {
      await api(caminho, opts);
      setErro(""); setAviso(feito); carregar();
      return true;
    } catch (err) { setErro(mensagem(err)); return false; }
  }

  async function confirmarSenha(e: React.FormEvent, u: Usr) {
    e.preventDefault();
    if (await agir(`/api/admin/usuarios/${u.id}/senha`, { method: "POST", body: JSON.stringify({ senha: senhaNova }) },
                   `Senha de ${u.nome} redefinida; as sessões abertas dessa pessoa foram encerradas.`)) {
      setRedefinir(null); setSenhaNova("");
    }
  }

  return (
    <>
      <section className="cartao" aria-labelledby="titulo-usuarios">
        <div className="cartao__cabeca">
          <h2 className="cartao__titulo" id="titulo-usuarios">Usuários</h2>
        </div>
        {erro && <Erro texto={erro} />}
        {!usuarios && !erro && <div className="vazio"><p>Carregando…</p></div>}
        {usuarios && (
          <Rolagem rotulo="Usuários">
            <table className="tabela">
              <caption className="sr-only">Usuários, com o perfil, a situação e a conta Microsoft usada para enviar e-mail</caption>
              <thead>
                <tr>
                  <th scope="col">Nome</th><th scope="col">E-mail</th><th scope="col">Perfil</th><th scope="col">Situação</th>
                  <th scope="col">Bloqueio</th>
                  <th scope="col">Conta Microsoft</th><th scope="col"><span className="sr-only">Senha, ativar ou desativar</span></th>
                </tr>
              </thead>
              <tbody>
                {usuarios.map((u, i) => {
                  const c = contas?.get(u.id);
                  return (
                    <tr key={u.id} className={`linha${i % 2 === 1 ? " par" : ""}`}>
                      <td>{u.nome}</td>
                      <td>{u.email}</td>
                      <td>{u.id === eu ? rotuloPerfil(u.perfil) : (
                        <select aria-label={`Perfil de ${u.nome}`} value={u.perfil}
                                onChange={e => agir(`/api/admin/usuarios/${u.id}`, { method: "PUT", body: JSON.stringify({ perfil: e.target.value }) },
                                                    `Perfil de ${u.nome} alterado.`)}>
                          <option value="engenharia">Engenharia</option>
                          <option value="diretoria">Diretoria</option>
                          <option value="admin">Administrador</option>
                        </select>
                      )}</td>
                      {/* o comum (ativo) em ponto e palavra; a excecao (inativo) no selo, para destacar da coluna (D15) */}
                      <td>{u.ativo ? <span className="estado"><span className="estado__ponto" aria-hidden="true" />Ativo</span>
                        : <Selo>inativo</Selo>}</td>
                      <td>{u.bloqueado_ate ? (
                        <span className="form-inline">
                          <span className="num">até {fmtHora(u.bloqueado_ate)}</span>
                          <button type="button" className="btn btn--pequeno"
                                  onClick={() => agir(`/api/admin/usuarios/${u.id}/desbloquear`, { method: "POST" }, `${u.nome} desbloqueado.`)}>
                            Desbloquear<span className="sr-only"> {u.nome}</span>
                          </button>
                        </span>
                      ) : "—"}</td>
                      <td>{!u.ativo || contas === null ? "—" : c?.conectada ? (
                        <Selo classe="selo--ok">conectada</Selo>
                      ) : contas === undefined ? "…" : <Selo classe="">não conectada</Selo>}</td>
                      <td>
                        {u.id === eu ? null
                          : redefinir === u.id ? (
                            <form className="form-inline" onSubmit={e => confirmarSenha(e, u)}>
                              <label className="sr-only" htmlFor={`senha-${u.id}`}>Senha nova de {u.nome} (mínimo de 10 caracteres)</label>
                              <input id={`senha-${u.id}`} type="password" required minLength={10} autoComplete="new-password" autoFocus
                                     placeholder="Senha nova (mín. 10)…" value={senhaNova} onChange={e => setSenhaNova(e.target.value)} />
                              <button type="submit" className="btn btn--pequeno btn--primario">Confirmar a senha nova</button>
                              <button type="button" className="btn btn--pequeno" onClick={() => { setRedefinir(null); setSenhaNova(""); }}>Cancelar</button>
                            </form>
                          ) : !u.ativo ? (
                            <button type="button" className="btn btn--pequeno" onClick={() => alternar(u)}>
                              Reativar<span className="sr-only"> {u.nome}</span>
                            </button>
                          ) : confirmar === u.id ? (
                            <span className="form-inline">
                              <button type="button" className="btn btn--pequeno btn--destrutivo" onClick={() => { setConfirmar(null); alternar(u); }}>
                                Confirmar a desativação<span className="sr-only"> de {u.nome}</span>
                              </button>
                              <button type="button" className="btn btn--pequeno" autoFocus onClick={() => setConfirmar(null)}>Cancelar</button>
                            </span>
                          ) : (
                            <span className="form-inline">
                              <button type="button" className="btn btn--pequeno" onClick={() => { setRedefinir(u.id); setSenhaNova(""); }}>
                                Redefinir senha<span className="sr-only"> de {u.nome}</span>
                              </button>
                              <button type="button" className="btn btn--pequeno" onClick={() => setConfirmar(u.id)}>
                                Desativar<span className="sr-only"> {u.nome}</span>
                              </button>
                            </span>
                          )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Rolagem>
        )}
        {contas === null && <div className="cartao__corpo"><p className="campo__nota">Não foi possível ler as contas Microsoft; recarregue a página para tentar de novo.</p></div>}
        <p className="sr-only" role="status">{aviso}</p>
        {aviso && <div className="cartao__corpo"><p className="campo__nota">{aviso}</p></div>}
      </section>

      <section className="cartao" aria-labelledby="titulo-novo-usuario">
        <div className="cartao__cabeca"><h2 className="cartao__titulo" id="titulo-novo-usuario">Novo usuário</h2></div>
        <form className="cartao__corpo form-inline" onSubmit={criar}>
          <div className="campo">
            <label className="campo__rotulo" htmlFor="novo-nome">Nome</label>
            <input id="novo-nome" required autoComplete="off" value={novo.nome} onChange={e => setNovo({ ...novo, nome: e.target.value })}
              {...apontaErro("nome")} />
          </div>
          <div className="campo">
            <label className="campo__rotulo" htmlFor="novo-email">E-mail</label>
            <input id="novo-email" type="email" required autoComplete="off" spellCheck={false} value={novo.email}
              onChange={e => setNovo({ ...novo, email: e.target.value })} {...apontaErro("email")} />
          </div>
          <div className="campo">
            <label className="campo__rotulo" htmlFor="novo-senha">Senha (mínimo de 10 caracteres)</label>
            <input id="novo-senha" type="password" required minLength={10} autoComplete="new-password" value={novo.senha}
              onChange={e => setNovo({ ...novo, senha: e.target.value })} {...apontaErro("senha")} />
          </div>
          <div className="campo">
            <label className="campo__rotulo" htmlFor="novo-perfil">Perfil</label>
            <select id="novo-perfil" value={novo.perfil} onChange={e => setNovo({ ...novo, perfil: e.target.value })} {...apontaErro("perfil")}>
              <option value="engenharia">Engenharia</option>
              <option value="diretoria">Diretoria</option>
              <option value="admin">Administrador</option>
            </select>
          </div>
          <button type="submit" className="btn btn--primario" disabled={enviando}>{enviando ? "Criando…" : "Criar usuário"}</button>
        </form>
        {erroNovo && <Erro texto={erroNovo} id="erro-novo-usuario" />}
        <p className="sr-only" role="status">{criado}</p>
        {criado && <div className="cartao__corpo"><p className="campo__nota">{criado}</p></div>}
      </section>
    </>
  );
}

/* ----------------------------------------------------------------- auditoria */

function Auditoria({ busca }: { busca: Busca }) {
  const [audit, setAudit] = useState<PaginaAuditoria | null>(null);
  // null = nao deu para ler os nomes (a coluna Quem mostra o numero do usuario, e uma nota diz por que)
  const [nomes, setNomes] = useState<Map<number, string> | null>(new Map());
  const [erro, setErro] = useState("");
  const [carregandoMais, setCarregandoMais] = useState(false);
  const [erroMais, setErroMais] = useState("");
  useEffect(() => {
    api<PaginaAuditoria>(`/api/admin/auditoria?limite=${LIMITE_AUDITORIA}`)
      .then(setAudit).catch(e => setErro(falhaDeCarga(e)));
    // o nome de quem fez; sem ele, a coluna mostra o numero do usuario
    api<Usr[]>("/api/admin/usuarios").then(l => setNomes(new Map(l.map(u => [u.id, u.nome])))).catch(() => setNomes(null));
  }, []);

  // a pagina seguinte e' a dos eventos antes do ultimo que ja' chegou (cursor = id dele)
  function carregarMais() {
    if (!audit || carregandoMais) return;
    const cursor = audit.eventos[audit.eventos.length - 1].id;
    setCarregandoMais(true); setErroMais("");
    api<PaginaAuditoria>(`/api/admin/auditoria?limite=${LIMITE_AUDITORIA}&antes_de=${cursor}`)
      // a cadeia so' e' verificada na primeira pagina; as seguintes chegam sem esse campo
      .then(p => setAudit(a => a && { cadeia_integra: a.cadeia_integra, ha_mais: p.ha_mais, eventos: [...a.eventos, ...p.eventos] }))
      .catch(e => setErroMais(mensagem(e)))
      .finally(() => setCarregandoMais(false));
  }

  const f = { acao: busca.acao ?? null, pessoa: busca.pessoa ?? null, desde: busca.desde ?? null };
  const quem = (p: string) => (p === "sistema" ? "sistema" : nomes?.get(Number(p)) ?? `usuário ${p}`);
  const eventos = audit ? filtrarEventos(audit.eventos, f) : [];
  // o objeto e' link para a tela dele; sem tela, fica o texto
  const objeto = (ev: Evento) => {
    const rota = rotaDoObjeto(ev);
    return rota ? <Link para={rota}>{rotuloObjeto(ev.entidade, ev.entidade_id)}</Link> : rotuloObjeto(ev.entidade, ev.entidade_id);
  };
  // as opcoes do filtro em ordem alfabetica do rotulo em portugues (o valor segue sendo o codigo da acao)
  const acoes = audit ? [...new Set(audit.eventos.map(e => e.acao))].sort((a, b) => rotuloAcao(a).localeCompare(rotuloAcao(b), "pt-BR")) : [];
  const pessoas = audit ? [...new Set(audit.eventos.map(pessoaDoEvento))] : [];
  // enquanto houver anteriores no banco, a tela mostra so' os ultimos que ja' chegaram ("Carregar mais" traz o resto)
  const haMais = audit?.ha_mais ?? false;

  return (
    <section className="cartao" aria-labelledby="titulo-auditoria">
      <div className="cartao__cabeca">
        <h2 className="cartao__titulo" id="titulo-auditoria">Auditoria</h2>
        {audit && <Selo classe={audit.cadeia_integra ? "selo--ok" : "selo--acao"}>{audit.cadeia_integra ? "cadeia íntegra" : "cadeia violada"}</Selo>}
      </div>
      {erro && <Erro texto={erro} />}
      {!audit && !erro && <div className="vazio"><p>Carregando…</p></div>}
      {audit && (
        <>
          <div className="cartao__corpo form-inline">
            <div className="campo">
              <label className="campo__rotulo" htmlFor="aud-acao">Ação</label>
              <select id="aud-acao" value={f.acao ?? ""} onChange={e => trocarBusca({ acao: e.target.value || null })}>
                <option value="">Todas</option>
                {f.acao && !acoes.includes(f.acao) && <option value={f.acao}>{rotuloAcao(f.acao)}</option>}
                {acoes.map(a => <option key={a} value={a}>{rotuloAcao(a)}</option>)}
              </select>
            </div>
            <div className="campo">
              <label className="campo__rotulo" htmlFor="aud-pessoa">Pessoa</label>
              <select id="aud-pessoa" value={f.pessoa ?? ""} onChange={e => trocarBusca({ pessoa: e.target.value || null })}>
                <option value="">Todas</option>
                {f.pessoa && !pessoas.includes(f.pessoa) && <option value={f.pessoa}>{quem(f.pessoa)}</option>}
                {pessoas.map(p => <option key={p} value={p}>{quem(p)}</option>)}
              </select>
            </div>
            <div className="campo">
              <label className="campo__rotulo" htmlFor="aud-desde">Desde</label>
              <input id="aud-desde" type="date" value={f.desde ?? ""} onChange={e => trocarBusca({ desde: e.target.value || null })} />
            </div>
          </div>
          {/* so' a contagem do recorte na regiao viva: trocar os filtros refaz a tabela */}
          <span className="sr-only" role="status">{contar(eventos.length, "evento", "eventos")}</span>
          {nomes === null && (
            <p className="cartao__corpo campo__nota">Não foi possível ler os nomes: a coluna Quem mostra o número de cada usuário. Recarregue a página para tentar de novo.</p>
          )}
          {audit.eventos.length === 0 ? (
            <div className="vazio vazio--curto"><p className="vazio__titulo">Nenhum evento registrado.</p></div>
          ) : eventos.length === 0 ? (
            <div className="vazio vazio--curto">
              <p className="vazio__titulo">Nenhum evento com esses filtros.</p>
              <p><Link para={{ tela: "admin", aba: "auditoria" }}>Limpar os filtros</Link></p>
            </div>
          ) : (
            <Rolagem rotulo="Eventos de auditoria" alta>
              <table className="tabela">
                {/* criado_em vem de datetime('now') do SQLite, sempre UTC: `fmtDataHora` converte para Cuiaba, o
                    mesmo fuso das rodadas do RM na Saude (antes a coluna ficava em UTC e quem cruzava os dois
                    horarios errava por 4 h). */}
                <caption className="sr-only">Eventos de auditoria, do mais recente ao mais antigo</caption>
                <thead>
                  <tr><th scope="col">Data e hora</th><th scope="col">Quem</th><th scope="col">Ação</th><th scope="col">Objeto</th></tr>
                </thead>
                <tbody>
                  {eventos.map((ev, i) => (
                    <tr key={ev.id} className={`linha${i % 2 === 1 ? " par" : ""}`}>
                      <td className="num">{fmtDataHora(ev.criado_em)}</td>
                      <td>{quem(pessoaDoEvento(ev))}</td>
                      <td>{rotuloAcao(ev.acao)}</td>
                      <td>{objeto(ev)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Rolagem>
          )}
          {haMais && (
            <div className="cartao__corpo">
              {erroMais && <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erroMais}</p>}
              <button type="button" className="btn btn--pequeno" onClick={carregarMais} disabled={carregandoMais}>
                {carregandoMais ? "Carregando…" : "Carregar mais"}
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}

export default function Admin({ aba = "saude", busca = {}, eu }: { aba?: AbaAdmin; busca?: Busca; eu?: number }) {
  return (
    <div className="pilha">
      <Abas rotulo="Seções da Administração" atual={aba}
        itens={ABAS_ADMIN.map(a => ({ ...a, para: { tela: "admin" as const, aba: a.id } }))} />
      {aba === "saude" && <Saude />}
      {aba === "reconciliacao" && <ReconciliacaoAba busca={busca} />}
      {aba === "usuarios" && <Usuarios eu={eu} />}
      {aba === "auditoria" && <Auditoria busca={busca} />}
    </div>
  );
}
