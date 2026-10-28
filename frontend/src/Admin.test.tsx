import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import Admin from "./Admin";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

afterEach(() => { cleanup(); api.mockReset(); });

test("Usuários: sem Desativar na própria linha; desativar outro pede confirmação antes do pedido", async () => {
  api.mockImplementation(async (url: string) => {
    if (url === "/api/admin/usuarios") return [
      { id: 1, nome: "Leonardo", email: "l@x.com", perfil: "admin", ativo: 1 },
      { id: 2, nome: "Maria", email: "m@x.com", perfil: "engenharia", ativo: 1 }];
    if (url === "/api/admin/contas-microsoft") return [];
    return { ok: true };
  });
  render(<Admin aba="usuarios" eu={1} />);
  // o jsdom junta o texto oculto sem o espaço do começo ("DesativarMaria"); o navegador mantém o espaço
  fireEvent.click(await screen.findByRole("button", { name: /Desativar\s*Maria/ }));
  expect(screen.queryByRole("button", { name: /Desativar\s*Leonardo/ })).toBeNull();
  expect(api).not.toHaveBeenCalledWith("/api/admin/usuarios/2", expect.anything());
  fireEvent.click(screen.getByRole("button", { name: /Confirmar a desativação\s*de Maria/ }));
  expect(api).toHaveBeenCalledWith("/api/admin/usuarios/2", expect.objectContaining({ method: "PUT" }));
});

// A-05/B-10 (10/10/2026): conta trancada só destravava sozinha ou no banco; senha e perfil não se mudavam pela tela
test("Usuários: bloqueio com Desbloquear, Redefinir senha e perfil editável (menos na própria linha)", async () => {
  api.mockImplementation(async (url: string) => {
    if (url === "/api/admin/usuarios") return [
      { id: 1, nome: "Leonardo", email: "l@x.com", perfil: "admin", ativo: 1, bloqueado_ate: null, tentativas_falhas: 0 },
      { id: 2, nome: "Maria", email: "m@x.com", perfil: "engenharia", ativo: 1,
        bloqueado_ate: "2026-10-10T14:35:00-04:00", tentativas_falhas: 0 }];
    if (url === "/api/admin/contas-microsoft") return [];
    return { ok: true };
  });
  render(<Admin aba="usuarios" eu={1} />);
  expect(await screen.findByText("até 14:35")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /Desbloquear\s*Maria/ }));
  expect(api).toHaveBeenCalledWith("/api/admin/usuarios/2/desbloquear", expect.objectContaining({ method: "POST" }));

  expect(screen.queryByRole("combobox", { name: /Perfil de Leonardo/ })).toBeNull();
  fireEvent.change(screen.getByRole("combobox", { name: /Perfil de Maria/ }), { target: { value: "diretoria" } });
  expect(api).toHaveBeenCalledWith("/api/admin/usuarios/2", { method: "PUT", body: JSON.stringify({ perfil: "diretoria" }) });

  expect(screen.queryByRole("button", { name: /Redefinir senha\s*de Leonardo/ })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /Redefinir senha\s*de Maria/ }));
  fireEvent.change(screen.getByLabelText(/Senha nova de Maria/), { target: { value: "senha-nova-456" } });
  fireEvent.click(screen.getByRole("button", { name: /Confirmar a senha nova/ }));
  expect(api).toHaveBeenCalledWith("/api/admin/usuarios/2/senha", { method: "POST", body: JSON.stringify({ senha: "senha-nova-456" }) });
});

// Issue #5: a auditoria passava de 500 eventos sem acesso aos anteriores; "Carregar mais" busca a página seguinte pelo cursor
test("Auditoria: Carregar mais busca a página anterior pelo cursor, mantém os filtros e some no primeiro evento", async () => {
  const ev = (id: number, acao: string) => ({ id, acao, entidade: null, criado_em: "2026-10-10 12:00:00", usuario_id: null });
  api.mockImplementation(async (url: string) => {
    if (url === "/api/admin/usuarios") return [];
    if (url === "/api/admin/auditoria?limite=500")
      return { cadeia_integra: true, ha_mais: true, eventos: [ev(30, "auth.login"), ev(29, "medicao.criar")] };
    if (url === "/api/admin/auditoria?limite=500&antes_de=29")
      return { cadeia_integra: null, ha_mais: false, eventos: [ev(28, "auth.login"), ev(27, "medicao.criar")] };
    throw new Error(`chamada inesperada: ${url}`);
  });
  render(<Admin aba="auditoria" busca={{ acao: "auth.login" }} />);
  expect(await screen.findByText("1 evento")).toBeTruthy();       // so' na regiao viva, sem a frase visivel
  fireEvent.click(screen.getByRole("button", { name: "Carregar mais" }));
  // 4 eventos carregados, 2 passam no filtro de ação (o filtro vale sobre as duas páginas)
  expect(await screen.findByText("2 eventos")).toBeTruthy();
  expect(screen.getByText("2 eventos").className).toBe("sr-only");
  expect(screen.queryByText(/do mais recente ao mais antigo/, { selector: "p" })).toBeNull();
  expect(screen.getAllByText("Entrada no sistema").length).toBe(3); // 2 linhas + a opção do filtro
  expect(screen.queryByRole("button", { name: "Carregar mais" })).toBeNull();
  // a página seguinte vem sem a verificação da cadeia: o selo da primeira fica
  expect(screen.getByText("cadeia íntegra")).toBeTruthy();
});

// Issue #20: o sucesso de "Sincronizar agora" não era anunciado
test("Saúde: Sincronizar agora anuncia o sucesso numa região viva", async () => {
  const status = { configurado: true, em_andamento: false, ultima_sincronizacao: null, ultimo_erro: null, rodadas: [] };
  api.mockImplementation(async (url: string, opts?: { method?: string }) => {
    if (url === "/api/rm/sincronizar" && opts?.method === "POST") return { estado: "success" };
    if (url === "/api/rm/status") return status;
    if (url === "/api/health") return {};
    throw new Error("fora do recorte deste teste");
  });
  render(<Admin aba="saude" />);
  fireEvent.click(await screen.findByRole("button", { name: "Sincronizar agora" }));
  const aviso = await screen.findByText("Sincronização concluída.");
  expect(aviso.closest("[role='status']")).not.toBeNull();
});

test("Auditoria: filtro sem resultado diz uma linha curta e deixa o Carregar mais", async () => {
  api.mockImplementation(async (url: string) => {
    if (url === "/api/admin/usuarios") return [];
    return { cadeia_integra: true, ha_mais: true,
             eventos: [{ id: 9, acao: "auth.login", entidade: null, criado_em: "2026-10-10 12:00:00", usuario_id: null }] };
  });
  render(<Admin aba="auditoria" busca={{ acao: "medicao.criar" }} />);
  expect(await screen.findByText("Nenhum evento com esses filtros.")).toBeTruthy();
  expect(screen.queryByText(/use Carregar mais/)).toBeNull();
  expect(screen.getByRole("button", { name: "Carregar mais" })).toBeTruthy();
});

// Issue #22: a reconciliação cortava as NFs sem medição em 200 ("200 ou mais"); agora a contagem é exata e
// "Carregar mais" traz a página seguinte da API
test("Reconciliação: a contagem é o total da API e Carregar mais traz as NFs seguintes", async () => {
  const nf = (id: number) => ({ id, coligada: 1, numero: String(id), serie: null, emissao: null, valor_centavos: 100, campo_livre1: null });
  const pagina = (nfs: ReturnType<typeof nf>[], haMais: boolean) => ({
    nfs_sem_medicao: nfs, medicoes_sem_nf: [], divergencias: [], alocacoes_desfeitas: [], recebidas_sem_baixa: [],
    totais: { nfs_sem_medicao: 3, alocacoes_desfeitas: 0 }, ha_mais: { nfs_sem_medicao: haMais, alocacoes_desfeitas: false } });
  api.mockImplementation(async (url: string) => {
    if (url === "/api/admin/usuarios") return [];
    if (url === "/api/contratos") return [];
    if (url === "/api/rm/reconciliacao") return pagina([nf(3), nf(2)], true);
    if (url === "/api/rm/reconciliacao?nfs_apos=2") return pagina([nf(1)], false);
    throw new Error(`chamada inesperada: ${url}`);
  });
  render(<Admin aba="reconciliacao" busca={{ categoria: "nfs" }} />);
  const grupo = await screen.findByRole("region", { name: "NFs sem medição" });
  expect(within(grupo).getAllByRole("row")).toHaveLength(1 + 2);
  expect(grupo.querySelector(".cartao__dica")).toBeNull();
  // o filtro de grupo sem a contagem entre parênteses
  expect(screen.getByRole("link", { name: "NFs sem medição" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /Carregar mais/ }));
  await waitFor(() => expect(within(grupo).getAllByRole("row")).toHaveLength(1 + 3));
  expect(screen.queryByRole("button", { name: /Carregar mais/ })).toBeNull();
});

// Issue #203: recebimento à mão com o título ainda aberto no RM aparece na reconciliação, com a NF e o que falta
test("Reconciliação: recebida à mão sem baixa no RM mostra a medição, a NF e o valor em aberto", async () => {
  api.mockImplementation(async (url: string) => {
    if (url === "/api/contratos") return [];
    if (url === "/api/rm/reconciliacao") return {
      nfs_sem_medicao: [], medicoes_sem_nf: [], divergencias: [], alocacoes_desfeitas: [],
      recebidas_sem_baixa: [{ medicao_id: 70, contrato_id: 12, numero_instrumento: "IC 1/2025", numero: 14, tipo: "execucao",
        competencia: "2026-08", recebida_em: "2026-09-20", nota_id: 3, numero_nf: "100", serie: "1", falta_centavos: 924_01 }],
      totais: { nfs_sem_medicao: 0, alocacoes_desfeitas: 0 }, ha_mais: { nfs_sem_medicao: false, alocacoes_desfeitas: false } };
    throw new Error(`chamada inesperada: ${url}`);
  });
  render(<Admin aba="reconciliacao" busca={{ categoria: "recebidas" }} />);
  expect(await screen.findByRole("heading", { name: "Notas de recebimentos à mão sem baixa no RM" })).toBeTruthy();
  expect(screen.getByRole("link", { name: "14ª Medição" })).toBeTruthy();
  expect(screen.getByText("100/1")).toBeTruthy();
  expect(screen.getByText("20/09/2026")).toBeTruthy();
  expect(screen.getByText(/924,01/)).toBeTruthy();
});

// Issue #31: a Saúde mostra o último backup, quantos estão guardados e o último erro; atrasado acima de 2 h em destaque
const BACKUP_EM_DIA = {
  ultimo_backup: "2026-10-13T07:30:00-04:00", tamanho_bytes: 3 * 1024 * 1024, guardados: 48, copia_externa_configurada: true,
  atrasado: false, ultimo_snapshot: "2026-10-13T07:30:00-04:00", ultimo_snapshot_erro: null, ultimo_snapshot_erro_em: null,
  ultima_copia_externa: "2026-10-13T03:00:00-04:00", ultima_copia_externa_erro: null, ultima_copia_externa_erro_em: null,
};

function saudeCom(backup: object) {
  api.mockImplementation(async (url: string) => {
    if (url === "/api/admin/backup") return backup;
    throw new Error(`fora do recorte: ${url}`);
  });
  render(<Admin aba="saude" />);
}

test("Saúde: backup em dia mostra só o selo OK e a hora no cartão de situação, sem contadores nem 'nenhum erro'", async () => {
  saudeCom(BACKUP_EM_DIA);
  const regiao = await screen.findByRole("region", { name: "Backup" });
  expect(await within(regiao).findByText("OK")).toBeTruthy();
  expect(cartaoDe("Último backup").textContent).toMatch(/13\/10\/2026 às 07:30/);
  expect(document.body.textContent).not.toMatch(/snapshots guardados|MB|Último erro|um snapshot por hora|Última cópia externa:/);
  expect(screen.queryByText(/Backup atrasado/)).toBeNull();
  expect(api).not.toHaveBeenCalledWith("/api/health");
});

test("Saúde: backup atrasado acima de 2 h aparece em destaque, e o último erro aparece", async () => {
  saudeCom({ ...BACKUP_EM_DIA, atrasado: true, ultimo_snapshot_erro_em: "2026-10-13T10:30:00-04:00",
             ultimo_snapshot_erro: "não foi possível gravar o snapshot; o detalhe está no log do servidor" });
  const alerta = await screen.findByText(/Backup atrasado/);
  expect(alerta.closest(".aviso--critico")).toBeTruthy();
  expect(alerta.textContent).toMatch(/13\/10\/2026 às 07:30/);
  // sugestao do revisor: instrucao de operacao, nao caminho de arquivo do repositorio
  expect(alerta.textContent).not.toMatch(/runbook/);
  expect(screen.getByText(/em 13\/10\/2026 às 10:30, falhou \(não foi possível gravar o snapshot/)).toBeTruthy();
  expect(screen.queryByText(/runbook/)).toBeNull();
  expect(screen.queryByText(/Último erro: nenhum/)).toBeNull();
});

test("Saúde: sem nenhum backup guardado também é atraso em destaque", async () => {
  saudeCom({ ...BACKUP_EM_DIA, ultimo_backup: null, tamanho_bytes: null, guardados: 0, copia_externa_configurada: false,
             atrasado: true, ultimo_snapshot: null, ultima_copia_externa: null });
  expect((await screen.findByText(/Backup atrasado/)).textContent).toMatch(/nenhum backup guardado/);
  // sem erro registrado, "nenhum erro" desmentiria o alerta; sem pasta externa, não há cópia a esperar
  expect(screen.queryByText(/Último erro: nenhum/)).toBeNull();
  const cartao = within(screen.getByRole("region", { name: "Backup" }));
  expect(cartao.queryByText(/Última cópia externa/)).toBeNull();
});

// Issue #55: o backup passou a copiar as pastas de notas, espelhos, modelos e evidências; a falha dessa cópia
// tem de aparecer na tela, senão o selo diz OK com os arquivos sem cópia
test("Backup: cópia dos arquivos em dia não aparece no cartão; a falha dela aparece e vira Falhou", async () => {
  saudeCom({ ...BACKUP_EM_DIA, ultima_copia_arquivos: "2026-10-13T07:31:00-04:00",
             ultima_copia_externa_arquivos: "2026-10-13T07:35:00-04:00" });
  const regiao = await screen.findByRole("region", { name: "Backup" });
  expect(await within(regiao).findByText("OK")).toBeTruthy();
  expect(within(regiao).queryByText(/Última cópia dos arquivos/)).toBeNull();
  expect(cartaoDe("Última cópia externa dos arquivos").textContent).toMatch(/13\/10\/2026 às 07:35/);
  cleanup();
  saudeCom({ ...BACKUP_EM_DIA, ultima_copia_arquivos_erro_em: "2026-10-13T10:00:00-04:00",
             ultima_copia_arquivos_erro: "1 arquivo(s) sem cópia: notas/x.pdf (disco cheio)" });
  expect(await screen.findByText(/Última cópia dos arquivos: a última tentativa, em 13\/10\/2026 às 10:00, falhou/)).toBeTruthy();
  expect(screen.getByText(/disco cheio/)).toBeTruthy();
  expect(screen.getByText("Falhou")).toBeTruthy();
  expect(screen.queryByText(/Último erro: nenhum/)).toBeNull();
});

// Revisão da #142: a cópia dos arquivos para fora pode não terminar; aparece, e só existe com pasta externa
test("Backup: cópia externa dos arquivos que não termina aparece; sem pasta externa a linha some", async () => {
  saudeCom({ ...BACKUP_EM_DIA, ultima_copia_externa_arquivos_erro: "a cópia está rodando há 3 horas sem terminar" });
  expect(await screen.findByText(/Última cópia externa dos arquivos: a última tentativa falhou/)).toBeTruthy();
  expect(screen.getByText(/rodando há 3 horas sem terminar/)).toBeTruthy();
  expect(screen.getByText("Falhou")).toBeTruthy();
  cleanup();
  saudeCom({ ...BACKUP_EM_DIA, copia_externa_configurada: false });
  const regiao = await screen.findByRole("region", { name: "Backup" });
  expect(await within(regiao).findByText("OK")).toBeTruthy();
  expect(within(regiao).queryByText(/Última cópia/)).toBeNull();
  // sem pasta externa: o cartão de situação fica neutro, com "—" e sem frase
  const externa = cartaoDe("Última cópia externa dos arquivos");
  expect(externa.className).toMatch(/situacao--neutra/);
  expect(externa.textContent).not.toMatch(/sem pasta externa|não há cópia/);
});

// Redesenho da Administração (#164): a Saúde abre com quatro cartões de situação, cada um com ponto, hora e nota
const RODADA_BOA = { id: 2, disparo: "agendada", estado: "success", iniciado_em: "2026-10-16T10:40:00-04:00",
  terminado_em: "2026-10-16T10:40:38-04:00", nfs: 6, baixas: 1, alocacoes: 5, sugestoes: 1, recebimentos: 2, erro: null };
const RODADA_RUIM = { id: 3, disparo: "manual", estado: "failed", iniciado_em: "2026-10-16T11:40:00-04:00",
  terminado_em: "2026-10-16T11:41:05-04:00", nfs: 0, baixas: 0, alocacoes: 0, sugestoes: 0, recebimentos: 0,
  erro: "O RM recusou a conta de serviço." };

const SIGA_SEM_LEITURA = { ultima_leitura: null, processos: 0 };

function saudeComRm(status: object, backup: object = BACKUP_EM_DIA, siga: object = SIGA_SEM_LEITURA) {
  api.mockImplementation(async (url: string) => {
    if (url === "/api/rm/status") return status;
    if (url === "/api/admin/backup") return backup;
    if (url === "/api/admin/saude") return { siga };
    if (url === "/api/rm/reconciliacao") return {
      nfs_sem_medicao: [], medicoes_sem_nf: [], divergencias: [], alocacoes_desfeitas: [], recebidas_sem_baixa: [],
      totais: { nfs_sem_medicao: 15, alocacoes_desfeitas: 0 }, ha_mais: { nfs_sem_medicao: false, alocacoes_desfeitas: false } };
    throw new Error(`fora do recorte: ${url}`);
  });
  render(<Admin aba="saude" />);
}
const cartaoDe = (titulo: string) => screen.getByRole("heading", { name: titulo }).closest("li") as HTMLElement;

test("Saúde: três cartões de situação com a hora, nota só na falha, e a tabela das rodadas sempre aberta", async () => {
  saudeComRm({ configurado: true, em_andamento: false, ultima_sincronizacao: null, ultimo_erro: null, rodadas: [RODADA_BOA] });
  const sync = await screen.findByRole("heading", { name: "Sincronização com o RM" });
  const rm = sync.closest("li") as HTMLElement;
  expect(rm.className).toMatch(/situacao--ok/);
  expect(rm.textContent).toMatch(/16\/10\/2026 às 10:40/);
  expect(rm.querySelector(".situacao__nota")).toBeNull();
  expect(await within(cartaoDe("Último backup")).findByText(/13\/10\/2026 às 07:30/)).toBeTruthy();
  expect(cartaoDe("Último backup").querySelector(".situacao__nota")).toBeNull();
  expect(cartaoDe("Última cópia externa dos arquivos").className).toMatch(/situacao--atencao/); // sem cópia dos arquivos ainda
  expect(screen.queryByRole("heading", { name: "Rodadas com falha" })).toBeNull();
  // a tabela não fica atrás de um "abrir": já vem visível, com a duração da rodada
  expect(screen.getByRole("columnheader", { name: "Duração" })).toBeTruthy();
  expect(screen.getByText("38 s")).toBeTruthy();
  // sem as contagens repetidas da última rodada, sem dica no cabeçalho e sem "última rodada deu certo" ao lado do botão
  expect(screen.queryByLabelText("Contagens da última rodada")).toBeNull();
  expect(document.body.textContent).not.toMatch(/as NFs e as baixas do RM|deu certo|o que está de um lado só/);
});

// Issue #330: o monitor do SIGA ao lado da saúde do RM
test("Saúde: cartão Monitor do SIGA com a hora da última leitura e os processos; sem leitura, traço", async () => {
  saudeComRm({ configurado: true, em_andamento: false, ultima_sincronizacao: null, ultimo_erro: null, rodadas: [RODADA_BOA] },
    BACKUP_EM_DIA, { ultima_leitura: "2026-10-28T15:15:00+00:00", processos: 12 });
  await screen.findByRole("heading", { name: "Monitor do SIGA" });
  const cartao = cartaoDe("Monitor do SIGA");
  expect(cartao.textContent).toMatch(/28\/10\/2026 às 11:15/);
  expect(cartao.textContent).toMatch(/12 processos/);
  expect(cartao.className).toMatch(/situacao--ok/);
  cleanup(); api.mockReset();
  saudeComRm({ configurado: true, em_andamento: false, ultima_sincronizacao: null, ultimo_erro: null, rodadas: [RODADA_BOA] });
  await screen.findByRole("heading", { name: "Monitor do SIGA" });
  expect(cartaoDe("Monitor do SIGA").textContent).toBe("Monitor do SIGA—");
  expect(cartaoDe("Monitor do SIGA").className).toMatch(/situacao--neutra/);
});

test("Saúde: última rodada com falha vira cartão vermelho, caixa com o erro e a última boa, sem nome de máquina na tela", async () => {
  saudeComRm({ configurado: true, em_andamento: false, ultima_sincronizacao: null, ultimo_erro: null, rodadas: [RODADA_RUIM, RODADA_BOA] });
  const rm = (await screen.findByRole("heading", { name: "Sincronização com o RM" })).closest("li") as HTMLElement;
  expect(rm.className).toMatch(/situacao--acao/);
  expect(rm.textContent).toMatch(/falhou em 16\/10\/2026 às 11:40/);
  const caixa = screen.getByText(/Última rodada: falhou em/);
  expect(caixa.closest(".aviso--critico")).toBeTruthy();
  expect(caixa.textContent).toMatch(/O RM recusou a conta de serviço/);
  expect(caixa.textContent).toMatch(/A última que deu certo foi em 16\/10\/2026 às 10:40/);
  // o botão está ao lado: a caixa não ensina a clicar nele
  expect(caixa.textContent).not.toMatch(/tenta de novo|manual de produção/);
  expect(document.body.textContent).not.toMatch(/runbook|DASH_/);
  expect(screen.getByText("1 min 05 s")).toBeTruthy();
});

test("Saúde: RM não configurado desliga o Sincronizar agora com o motivo ao lado, sem explicar a regra", async () => {
  saudeComRm({ configurado: false, em_andamento: false, ultima_sincronizacao: null, ultimo_erro: null, rodadas: [] });
  expect(await screen.findByText("O RM não está configurado neste servidor.")).toBeTruthy();
  expect(cartaoDe("Sincronização com o RM").textContent).toMatch(/não configurado/);
  const botao = screen.getByRole("button", { name: "Sincronizar agora" }) as HTMLButtonElement;
  expect(botao.disabled).toBe(true);
  expect(botao.getAttribute("title")).toBeNull();
  expect(document.body.textContent).not.toMatch(/runbook|DASH_|Sem RM, o lançamento|lançamentos seguem à mão/);
});

test("Saúde: as contagens da reconciliação levam ao grupo certo da aba Reconciliação", async () => {
  saudeComRm({ configurado: true, em_andamento: false, ultima_sincronizacao: null, ultimo_erro: null, rodadas: [RODADA_BOA] });
  const link = await screen.findByRole("link", { name: /NFs sem medição/ });
  expect(link.getAttribute("href")).toMatch(/reconciliacao/);
  expect(link.getAttribute("href")).toMatch(/categoria=nfs/);
});

test("Saúde: falha só na cópia externa dos arquivos também deixa o cartão do backup vermelho (mesma regra do cartão Backup)", async () => {
  saudeComRm({ configurado: true, em_andamento: false, ultima_sincronizacao: null, ultimo_erro: null, rodadas: [RODADA_BOA] },
    { ...BACKUP_EM_DIA, ultima_copia_arquivos_erro: "1 arquivo(s) sem cópia" });
  await screen.findByText("Falhou");
  expect(cartaoDe("Último backup").className).toMatch(/situacao--acao/);
});

test("Saúde: sem rodada, uma linha curta; rodando, o botão desliga com o motivo e o motivo some quando para", async () => {
  saudeComRm({ configurado: true, em_andamento: false, ultima_sincronizacao: null, ultimo_erro: null, rodadas: [{ ...RODADA_RUIM }] });
  await screen.findByText(/Última rodada: falhou em/);
  expect(document.body.textContent).not.toMatch(/Nenhuma deu certo/);
  cleanup();
  saudeComRm({ configurado: true, em_andamento: false, ultima_sincronizacao: null, ultimo_erro: null, rodadas: [] });
  expect(await screen.findByText("Nenhuma rodada.")).toBeTruthy();
  expect(document.body.textContent).not.toMatch(/registrada ainda|ainda não rodou/);
  expect(screen.queryByText("Uma rodada está em andamento.")).toBeNull();
  cleanup();
  saudeComRm({ configurado: true, em_andamento: true, ultima_sincronizacao: null, ultimo_erro: null, rodadas: [RODADA_BOA] });
  await screen.findByText("rodando");
  expect((screen.getByRole("button", { name: "Sincronizar agora" }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText("Uma rodada está em andamento.")).toBeTruthy();
});

test("Reconciliação: sem a dica, sem a nota do filtro por obra e sem 'sem NF do RM' repetido na linha", async () => {
  api.mockImplementation(async (url: string) => {
    if (url === "/api/contratos") return [{ id: 12, orgao: "MTPAR", numero_instrumento: "IC 1/2025", nome_curto: "Granito", estado: "ativo" }];
    if (url === "/api/rm/reconciliacao") return {
      nfs_sem_medicao: [], divergencias: [], alocacoes_desfeitas: [], recebidas_sem_baixa: [],
      medicoes_sem_nf: [{ medicao_id: 70, contrato_id: 12, numero_instrumento: "IC 1/2025", numero: 14, tipo: "execucao",
        competencia: "2026-08", estado: "faturada", valor_centavos: 100 }],
      totais: { nfs_sem_medicao: 0, alocacoes_desfeitas: 0 }, ha_mais: { nfs_sem_medicao: false, alocacoes_desfeitas: false } };
    throw new Error(`chamada inesperada: ${url}`);
  });
  render(<Admin aba="reconciliacao" busca={{ obra: "12" }} />);
  await screen.findByRole("heading", { name: "Medições sem NF do RM" });
  expect(document.body.textContent).not.toMatch(/o que está de um lado só|saem com este filtro/);
  expect(screen.queryByText("sem NF do RM")).toBeNull();
  // grupo vazio: uma linha curta
  expect(screen.getAllByText("Nenhuma linha.").length).toBeGreaterThan(0);
  expect(screen.queryByText(/Nada de um lado só|Nada desta obra/)).toBeNull();
});

test("Usuários: sem a dica do cabeçalho, sem 'você' na própria linha e sem a hora da conexão", async () => {
  api.mockImplementation(async (url: string) => {
    if (url === "/api/admin/usuarios") return [{ id: 1, nome: "Leonardo", email: "l@x.com", perfil: "admin", ativo: 1 }];
    if (url === "/api/admin/contas-microsoft") return [{ usuario_id: 1, nome: "Leonardo", email: "l@x.com", perfil: "admin", conectada: true, token_em: "2026-10-10T12:00:00-04:00" }];
    return { ok: true };
  });
  render(<Admin aba="usuarios" eu={1} />);
  expect(await screen.findByText("conectada")).toBeTruthy();
  expect(document.body.textContent).not.toMatch(/conecta a própria conta|você|10\/10\/2026/);
});
