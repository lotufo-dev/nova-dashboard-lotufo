// Respostas ficticias da API para os estados que o cadastro de exemplo nao alcanca (acabamento do redesenho, #717):
// o SIGA com processos, as listas vazias e as falhas de leitura. `telas.mjs` poe cada uma no `simular` da tela.
// Tudo inventado: orgao, pessoa, numero e obra daqui nao existem.

const mov = (data, evento, tipo, extra = {}) => ({
  data, evento, tipo, cad_lotacao: "PROTOC/ORGAO", cad_pessoa: "Beltrano", at_lotacao: "COFIN/ORGAO", at_pessoa: "Fulano", ...extra,
});

const processo = extra => ({
  id: 1, codigo: null, link: null, numero: null, nome: null, contrato_id: null, obra: null, medicao_id: null,
  categoria: "outros", complemento: null, o_que_e: "Outro", medicao_titulo: null, protocolo_id: null,
  situacao: "1º Volume - Aguardando Andamento [COFIN, [X]]", encerrado: null, setor: "COFIN", caixa_entrada: false,
  com_quem: "Fulano", desde: "2026-10-20T10:00:00-04:00", dias_uteis: 6, hoje: 0,
  ultima: mov("2026-10-20T10:00:00-04:00", "Recebimento", "recebimento"), protocolado_em: "2026-10-01T08:00:00-04:00",
  movimentacoes: [mov("2026-10-20T10:00:00-04:00", "Recebimento", "recebimento")], ...extra,
});

// Um processo de cada situacao da coluna de tempo (hoje, em andamento, vence em breve, critico), um na caixa de
// entrada, um encerrado e um com o historico longo.
export const SIGA_COM_PROCESSOS = {
  lido_em: "2026-10-28T15:00:00+00:00", atrasado: false, pode_atualizar: true,
  robo: { estado: "parado", rodada: null, pedidos: [], avisos: [] },
  processos: [
    processo({
      id: 1, codigo: "ABC123", link: "https://siga.exemplo.com.br/acompanhar?n=ABC123", numero: "ORGAO-PRO-2026/00001",
      nome: "Processo Alfa", contrato_id: 2, obra: "Obra Própria", medicao_id: 1, medicao_titulo: "1ª Medição",
      categoria: "medicoes", o_que_e: "1ª Medição", protocolo_id: 5, desde: "2026-10-28T08:00:00-04:00", dias_uteis: 0, hoje: 1,
      ultima: mov("2026-10-28T09:30:00-04:00", "Recebimento | texto escrito pelo órgão ao receber o processo no setor", "recebimento"),
      movimentacoes: [
        mov("2026-10-20T10:00:00-04:00", "Cadastro", "outras", { at_pessoa: "Beltrano", at_lotacao: "PROTOC/ORGAO" }),
        mov("2026-10-25T08:00:00-04:00", "Transferência", "transferencia", { cad_pessoa: "Sicrana", at_lotacao: "GABIN/ORGAO", at_pessoa: "" }),
        mov("2026-10-26T14:10:00-04:00", "Juntada | documento ORGAO-DIC-2026/96012-A", "juntada", { cad_lotacao: "COFIN/ORGAO", cad_pessoa: "Bruna", at_lotacao: "", at_pessoa: "" }),
        mov("2026-10-27T09:00:00-04:00", "Marcação", "marcacao", { cad_lotacao: "COFIN/ORGAO", cad_pessoa: "Camila", at_lotacao: "GSAGPM/ORGAO", at_pessoa: "Helia" }),
        mov("2026-10-28T08:00:00-04:00", "Recebimento", "recebimento", { cad_lotacao: "COFIN/ORGAO", cad_pessoa: "Fulano" }),
      ],
    }),
    processo({ id: 2, nome: "Processo Delta", numero: "ORGAO-PRO-2026/00007", contrato_id: 1, obra: "Obra Consórcio", categoria: "aditivos",
      complemento: "de prazo", o_que_e: "Aditivo de prazo", dias_uteis: 3 }),
    processo({ id: 3, nome: "Processo Beta", numero: "ORGAO-PRO-2026/00011", situacao: "2º Volume - Caixa de Entrada [GABIN, [X]]",
      setor: "GABIN", caixa_entrada: true, com_quem: "", dias_uteis: 6 }),
    processo({ id: 4, nome: "Processo Gama de nome comprido, como o órgão costuma escrever o assunto do processo", contrato_id: 2,
      obra: "Obra Própria", categoria: "indenizatorios", o_que_e: "Indenizatório", dias_uteis: 12, setor: "CCONT" }),
    processo({ id: 5, nome: "Processo Ômega", numero: "ORGAO-PRO-2025/00090", contrato_id: 2, obra: "Obra Própria", medicao_id: 2,
      medicao_titulo: "2ª Medição", categoria: "medicoes", o_que_e: "2ª Medição", encerrado: "recebida", dias_uteis: 40 }),
  ],
};

// A medicao com a nota emitida e ainda nao enviada ao orgao: o passo "Envio da nota" aberto, com a lista de envios.
// O cadastro de exemplo so' tem medicao ja' protocolada, entao a resposta verdadeira e' ajustada (o estado volta um
// passo e os protocolos saem) e a lista de notas a enviar ganha o envio desta medicao. `familia` fora da SINFRA pede o
// numero do oficio antes do e-mail.
export const medicaoComNotaEmitida = (medicoes, reg) => medicoes.map(m => (m.id === reg.medicao
  ? { ...m, estado: "nota_emitida", protocolos: [], nota_emitida_em: "2025-05-22", congelada: 0 } : m));

export const notasAEnviar = familia => reg => ({
  contadores: { Todas: 1 },
  envios: [{
    chave: `c${reg.obra}:m${reg.medicao}`, contrato_id: reg.obra, obra: "Obra Própria", orgao: "Secretaria de Exemplo", orgao_sub: null,
    familia, grupo: "Secretaria de Exemplo", a_pedido: false, medicao_ids: [reg.medicao], descricao: "1ª medição",
    notas: [{ numero: "2322", natureza: "execucao", valor_centavos: 41234567 }], valor_centavos: 41234567,
    emitida_em: "2025-05-22", dias: 2, situacao: "pronto", aviso: null, protocolo_id: null,
    itens: [{ chave: `frc:${reg.medicao}`, rotulo: "FRC assinada", estado: "falta", acao: "anexar_frc" }],
  }],
});

export const FALHA = { detail: "O servidor não respondeu a tempo." };

/** Uma leitura (GET) que falha com 500: a tela tem de mostrar o aviso de erro na forma de critico. */
export const falha = caminho => [{ caminho, status: 500, corpo: FALHA }];

/** O PDF que o sistema nao conseguiu ler: a fila do "Anexar PDF" abre a digitacao. */
export const PDF_ILEGIVEL = { ok: false, digitavel: true, mensagem: "Não deu para ler este PDF. Digite os dados da certidão." };

// ---- O que veio da master em 17/11/2026 e o cadastro de exemplo nao alcanca (a obra de exemplo e' da SINFRA e a prova
// nao fala com o RM): o passo do boletim da MT-PAR (#753) e o que o RM deixou de devolver (#755).

// A medicao como numa obra da MT-PAR: "Análise do órgão" sem "Planilha e carta" e' o passo do boletim assinado. Sem
// `boletim`, a medicao seguiu sem ele (a pendencia aparece na pagina e o passo abre o formulario); com ele, o passo
// mostra o boletim anexado, com a diferenca para o pedido.
export const medicaoDaMtpar = (boletim = false) => (medicoes, reg) => medicoes.map(m => (m.id === reg.medicao ? {
  ...m, boletim_modelo: "mtpar", passos: [2, 3, 4, 5, 6], estado: "espelho_gerado", protocolos: [], congelada: 0,
  boletim_pendente: !boletim, diferenca_aceita: false,
  valor_protocolado_centavos: 41234567, valor_atestado_centavos: boletim ? 41000001 : null,
  boletins: boletim ? [{ id: 1, tem_arquivo: true, valor_centavos: 41000001, atestado_em: "2025-05-20" }] : [],
} : m));

// O passo Pagamento com uma nota que perdeu um titulo no RM e outra que o RM deixou de devolver inteira.
export const medicaoComExcluidosNoRm = (medicoes, reg) => medicoes.map(m => (m.id === reg.medicao ? {
  ...m,
  notas: [{ nota_id: 9001, coligada: 1, numero: "2322", serie: null, emissao: "2025-05-22", valor_centavos: 41234567,
    recebido_centavos: 0, devido_centavos: 38000001, falta_centavos: 38000001, da_lotufo: true, da_cota: true,
    recebido_em: null, origem: "rm", regra: null,
    titulos_excluidos_rm: [{ valor_original_centavos: 38000001, valor_baixado_centavos: 0, excluida_rm_em: "2025-06-02 12:00:00" }] }],
  notas_excluidas_rm: [{ nota_id: 9002, coligada: 1, numero: "2310", serie: null, emissao: "2025-05-20",
    valor_centavos: 41234567, excluida_rm_em: "2025-06-02 12:00:00" }],
} : m));

// A Saude com a ultima rodada do RM recusando uma exclusao em massa.
export const RM_EXCLUSAO_RECUSADA = {
  configurado: true, ultima_sincronizacao: "2025-06-02T10:40:38-04:00", ultimo_erro: null, em_andamento: false,
  rodadas: [{ id: 2, disparo: "agendada", estado: "success", iniciado_em: "2025-06-02T10:40:00-04:00",
    terminado_em: "2025-06-02T10:40:38-04:00", nfs: 600, baixas: 900, alocacoes: 0, sugestoes: 0, recebimentos: 0, erro: null }],
  custo_aviso: null,
  exclusao_aviso: "Exclusão em massa recusada: 412 notas deixaram de vir do RM, inteiras ou em algum título (teto de 30). "
    + "Nada foi marcado como excluído. Ver docs/runbook.md, TOTVS RM.",
};
