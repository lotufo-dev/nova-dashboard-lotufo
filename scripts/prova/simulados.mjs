// Respostas ficticias da API para os estados que o cadastro de exemplo nao alcanca (acabamento do redesenho, #717):
// o SIGA com processos, as listas vazias e as falhas de leitura. `telas.mjs` poe cada uma no `simular` da tela.
// Tudo inventado: orgao, pessoa, numero e obra daqui nao existem.

const mov = (data, evento, tipo, extra = {}) => ({
  data, evento, tipo, cad_lotacao: "PROTOC/ORGAO", cad_pessoa: "Beltrano", at_lotacao: "COFIN/ORGAO", at_pessoa: "Fulano", ...extra,
});

// a leitura de "parado", como o servidor a manda (`siga.parado`, #840: sobre os dias sem movimentacao): o encerrado
// nao tem
const tempoDe = p => (p.encerrado ? null : p.hoje > 0 ? "feito" : p.dias_sem_movimentacao === null ? null
  : p.dias_sem_movimentacao >= 10 ? "critico" : p.dias_sem_movimentacao >= 5 ? "breve" : "andamento");

const processo = extra => {
  const p = {
    id: 1, codigo: null, link: null, numero: null, nome: null, contrato_id: null, obra: null, contratante: null, orgao_sub: null,
    medicao_id: null, categoria: "outros", categoria_sugerida: false, categoria_a_conferir: null, complemento: null, o_que_e: "Outro",
    medicao_titulo: null, protocolo_id: null,
    situacao: "1º Volume - Aguardando Andamento [COFIN, [X]]", encerrado: null, setor: "COFIN", caixa_entrada: false,
    com_quem: "Fulano", desde: "2026-10-20T10:00:00-04:00", dias_uteis: 6, hoje: 0,
    ultima: mov("2026-10-20T10:00:00-04:00", "Recebimento", "recebimento"), protocolado_em: "2026-10-01T08:00:00-04:00",
    movimentacoes: [mov("2026-10-20T10:00:00-04:00", "Recebimento", "recebimento")], ...extra,
  };
  // #840: sem dizer, os dias sem movimentacao sao os do setor (o processo nao andou desde que entrou)
  if (!("dias_sem_movimentacao" in extra)) p.dias_sem_movimentacao = p.ultima === null ? null : p.dias_uteis;
  return { ...p, situacao_tempo: tempoDe(p) };
};

// a resposta de GET /api/siga com a faixa de numeros contada como o servidor conta (so' os vivos; parado = critico)
const painelDoSiga = (processos, avisos = []) => {
  const vivos = processos.filter(p => !p.encerrado);
  const naoLidos = new Set(avisos.filter(a => a.tipo === "nao_lido").map(a => a.processo_id));
  return {
    lido_em: "2026-10-28T15:00:00+00:00", atrasado: false, pode_atualizar: true,
    robo: { estado: "parado", rodada: null, pedidos: [], avisos },
    processos,
    numeros: { acompanhados: vivos.length, parados: vivos.filter(p => p.situacao_tempo === "critico").length,
      andaram_hoje: vivos.filter(p => p.hoje > 0).length, nao_lidos: vivos.filter(p => naoLidos.has(p.id)).length },
    limites: { dias_atencao: 5, dias_critico: 10 },
  };
};

// #805, um painel por categoria: processo em cada categoria (Medicoes, Aditivos, Indenizatorios, Outros) e em cada
// faixa do tempo parado (andou hoje, em andamento, vence em breve, critico, sem data de entrada), um na caixa de
// entrada, um com a categoria a conferir, um sem obra (so' o nome do robo), dois encerrados e um com o historico longo.
const sinfra = { contratante: "SINFRA", orgao_sub: "SUEF II" };
const mtpar = { contratante: "MTPAR", orgao_sub: null };
const PROCESSOS_DO_SIGA = [
  processo({
    id: 1, codigo: "ABC123", link: "https://siga.exemplo.com.br/acompanhar?n=ABC123", numero: "ORGAO-PRO-2026/00001",
    nome: "Processo Alfa", contrato_id: 2, obra: "Obra Própria", ...sinfra, medicao_id: 1, medicao_titulo: "1ª Medição",
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
  processo({ id: 2, nome: "Processo Delta", numero: "ORGAO-PRO-2026/00007", contrato_id: 1, obra: "Obra Consórcio", ...sinfra,
    categoria: "aditivos", complemento: "de prazo", o_que_e: "Aditivo de prazo", dias_uteis: 3 }),
  processo({ id: 3, nome: "Processo Beta", numero: "ORGAO-PRO-2026/00011", situacao: "2º Volume - Caixa de Entrada [GABIN, [X]]",
    setor: "GABIN", caixa_entrada: true, com_quem: "", dias_uteis: 6 }),
  processo({ id: 4, nome: "Processo Gama de nome comprido, como o órgão costuma escrever o assunto do processo", contrato_id: 2,
    obra: "Obra Própria", ...sinfra, categoria: "indenizatorios", o_que_e: "Indenizatório", dias_uteis: 28, setor: "CCONT",
    desde: "2026-09-17T10:00:00-04:00", protocolado_em: "2026-09-02T08:00:00-04:00" }),
  processo({ id: 5, nome: "Processo Ômega", numero: "ORGAO-PRO-2025/00090", contrato_id: 2, obra: "Obra Própria", ...sinfra, medicao_id: 2,
    medicao_titulo: "2ª Medição", categoria: "medicoes", o_que_e: "2ª Medição", encerrado: "recebida", dias_uteis: 40 }),
  processo({ id: 6, nome: "Processo Zeta", numero: "ORGAO-PRO-2026/00031", contrato_id: 9011, obra: "Complexo Lambda", ...mtpar, medicao_id: 9701,
    medicao_titulo: "24ª Medição", categoria: "medicoes", o_que_e: "24ª Medição", dias_uteis: 25, dias_sem_movimentacao: 11, setor: "NUCLEO-ADM", com_quem: "Sicrana",
    desde: "2026-09-22T10:00:00-04:00", ultima: mov("2026-10-13T11:00:00-04:00", "Juntada | despacho", "juntada"),
    protocolado_em: "2026-09-08T08:00:00-04:00" }),
  processo({ id: 7, nome: "Processo Eta", numero: "ORGAO-PRO-2026/00032", contrato_id: 9012, obra: "Ponte Mi", ...sinfra, protocolo_id: 6,
    medicao_titulo: "7ª Medição e Reajuste da 7ª Medição", categoria: "medicoes", o_que_e: "7ª Medição e Reajuste da 7ª Medição",
    dias_uteis: 17, setor: "CCONT", com_quem: "Beltrano", desde: "2026-10-02T10:00:00-04:00", protocolado_em: "2026-09-25T08:00:00-04:00",
    dias_sem_movimentacao: 1, ultima: mov("2026-10-27T16:20:00-04:00", "Recebimento", "recebimento", { at_lotacao: "CCONT/ORGAO", at_pessoa: "Beltrano" }) }),
  processo({ id: 8, nome: "Processo Teta", numero: "ORGAO-PRO-2026/00033", contrato_id: 1, obra: "Obra Consórcio", ...sinfra, medicao_id: 3,
    medicao_titulo: "7ª Medição", categoria: "medicoes", o_que_e: "7ª Medição", dias_uteis: 7, setor: "CCONT",
    desde: "2026-10-19T10:00:00-04:00" }),
  processo({ id: 9, nome: "Processo Iota", numero: "ORGAO-PRO-2026/00034", contrato_id: 9014, obra: "Rodovia Csi lote 2", ...mtpar, medicao_id: 9704,
    medicao_titulo: "3ª Medição", categoria: "medicoes", o_que_e: "3ª Medição", dias_uteis: 2, setor: "NUCLEO-ADM", com_quem: "Sicrana",
    desde: "2026-10-26T10:00:00-04:00" }),
  processo({ id: 10, nome: "Processo Capa", numero: "ORGAO-PRO-2026/00040", contrato_id: 9012, obra: "Ponte Mi", ...sinfra,
    categoria: "aditivos", complemento: "de valor", o_que_e: "Aditivo de valor", desde: "2026-10-28T09:00:00-04:00", dias_uteis: 0, hoje: 3,
    setor: "GEFOR", ultima: mov("2026-10-28T10:40:00-04:00", "Sobrestar", "outras") }),
  // a pessoa escolheu Outros e escreveu o que e' um aditivo: a linha avisa "categoria a conferir" e nada muda sozinho
  processo({ id: 11, nome: "Obra Consórcio · Aditivo de prazo de dezembro", numero: "ORGAO-PRO-2026/00041", contrato_id: 1,
    obra: "Obra Consórcio", ...sinfra, complemento: "Aditivo de prazo de dezembro", o_que_e: "Aditivo de prazo de dezembro",
    categoria_a_conferir: "aditivos", dias_uteis: 12, setor: "GSAGPM", desde: "2026-10-09T10:00:00-04:00" }),
  // o robo mandou so' o nome e a situacao ainda nao diz o setor: sem data de entrada, sem leitura de tempo
  processo({ id: 12, nome: "Terminais de exemplo - IC 044/2026 (ORGAO-PRO-2026/00042)", numero: "ORGAO-PRO-2026/00042",
    situacao: null, setor: "", com_quem: "", desde: null, dias_uteis: null, ultima: null, protocolado_em: null, movimentacoes: [] }),
  processo({ id: 13, nome: "Processo Lambda", numero: "ORGAO-PRO-2025/00077", contrato_id: 9013, obra: "Praça Ni", contratante: "Pref. Cuiabá",
    categoria: "aditivos", complemento: "de prazo", o_que_e: "Aditivo de prazo", encerrado: "arquivado", setor: "ARQUIVO", dias_uteis: 60 }),
];

export const SIGA_COM_PROCESSOS = painelDoSiga(PROCESSOS_DO_SIGA);

// #805: dois processos que o robo nao conseguiu ler na ultima rodada: a etiqueta "Nao lido" na linha de cada um, com a
// hora e o motivo, o numero da faixa e o resumo no alto
export const SIGA_COM_NAO_LIDOS = painelDoSiga(PROCESSOS_DO_SIGA, [
  { tipo: "nao_lido", processo_id: 8, texto: "não lido às 11:02: A página do processo não abriu" },
  { tipo: "nao_lido", processo_id: 2, texto: "não lido às 11:02: Processo sem código de acompanhamento" },
  { tipo: "nao_lidos", processo_id: null, texto: "2 de 11 processos não foram lidos" },
]);

// #805: a categoria escolhida sem processo em andamento (so' ha' medicoes): as escolhas continuam, com zero
export const SIGA_SO_MEDICOES = painelDoSiga(PROCESSOS_DO_SIGA.filter(p => p.categoria === "medicoes"));

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

// ---- Segunda passada do acabamento (#717): o que a primeira deixou sem estado na prova.

// O espelho gerado e ainda nao enviado ao faturamento: o passo "Espelhos" com o botao de enviar, e o e-mail aberto.
// A regra e' a verdadeira da obra de exemplo; so' o espelho e' posto.
export const medicaoComEspelhoGerado = (medicoes, reg) => medicoes.map(m => (m.id === reg.medicao
  ? { ...m, estado: "espelho_gerado", protocolos: [], congelada: 0 } : m));

export const ESPELHO_ID = 9101;
export const espelhoGerado = (resposta, reg) => ({
  ...resposta,
  espelhos: [{
    id: ESPELHO_ID, numero: 1, competencia: "2025-04", versao: 1, situacao: "vigente",
    entradas: Object.fromEntries((resposta.regra?.entradas ?? []).map(e => [e.chave, 41234567])),
    periodo_inicio: "2025-04-01", periodo_fim: "2025-04-30", criado_em: "2025-05-20 10:00:00", criado_por_nome: "Engenharia",
    motivo: null,
    saidas: [{ chave: "nf", natureza: "execucao", rotulo: "Nota de execução", emissor: "Construtora Alfa Ltda", municipio: "Cidade de Exemplo",
      valor: 41234567, mo: 16493827, material: 24740740, inss: 1814321, iss: 824691, irrf: 494815, ibs: null, cbs: null,
      liquido: 38100740, nome_arquivo: "Espelho NF 1ª medição - Obra Própria.docx" }],
    medicoes: [{ id: reg.medicao, tipo: "execucao", estado: "espelho_gerado" }],
    arquivos: [{ documento_id: 9111, saida: "nf", nome: "Espelho NF 1ª medição - Obra Própria.docx", tamanho: 48211 }],
    envio: null,
  }],
});

// Issue #798: o mesmo espelho com o envio ao faturamento registrado como feito por fora. A medicao passa a "espelho
// enviado" e a linha do tempo ganha o registro, com quem fez.
export const medicaoComEspelhoEnviadoPorFora = (medicoes, reg) => medicoes.map(m => (m.id === reg.medicao ? {
  ...m, estado: "espelho_enviado", protocolos: [], congelada: 0,
  edicoes_valor: [...(m.edicoes_valor ?? []), { data: "2025-05-21",
    texto: "Espelho enviado ao faturamento por fora em 21/05/2025 (pelo Outlook), registrado por Engenharia" }],
} : m));

export const espelhoEnviadoPorFora = (resposta, reg) => {
  const gerado = espelhoGerado(resposta, reg);
  return { ...gerado, espelhos: gerado.espelhos.map(e => ({
    ...e, medicoes: [{ id: reg.medicao, tipo: "execucao", estado: "espelho_enviado" }],
    envio_externo: { enviado_em: "2025-05-21", observacao: "pelo Outlook", registrado_em: "2025-05-23 14:00:00",
      registrado_por_nome: "Engenharia" },
  })) };
};

// A previa do e-mail ao faturamento. O assunto e' comprido de proposito: o campo cresce para a segunda linha.
export const PREVIA_DO_ESPELHO = {
  para: ["faturamento@exemplo.com.br"], copia: ["controladoria@exemplo.com.br", "engenharia@exemplo.com.br"],
  assunto: "Espelho para emissão de nota fiscal: 1ª medição da Obra Própria, competência 04/2025, contrato 001/2025/00/00-EXEMPLO da Secretaria de Exemplo",
  corpo: "Bom dia,\n\nSegue o espelho da 1ª medição da Obra Própria para a emissão da nota fiscal.\n\nAtenciosamente,",
  anexos: [{ nome: "Espelho NF 1ª medição - Obra Própria.docx", tamanho: 48211 }], total: 48211, limite: 26214400,
  avisos: ["O boletim do órgão ainda não foi anexado a esta medição."],
};

// O envio da nota ao orgao ja' comecado (tem protocolo): a linha do envio abre o e-mail montado. `divergente` poe uma
// nota que diverge do espelho, e o envio passa a pedir o motivo escrito (a caixa de justificativa acima do e-mail).
export const PROTOCOLO_ID = 9201;
const DIVERGENCIA = reg => ({ medicao_id: reg.medicao, nota_id: 9001, numero: "2322", campo: "iss", espelho: 824691, nota: 804691, grau: "divergente" });

const envioAberto = (reg, divergente) => ({
  ...notasAEnviar("sinfra")(reg).envios[0], protocolo_id: PROTOCOLO_ID,
  itens: [{ chave: `nf:${reg.medicao}`, rotulo: "Nota fiscal 2322", estado: "ok" },
    { chave: `frc:${reg.medicao}`, rotulo: "FRC assinada", estado: "falta", acao: "anexar_frc", medicao_id: reg.medicao }],
  ...(divergente ? { divergencias: [DIVERGENCIA(reg)] } : {}),
});

export const notasComEnvioAberto = (divergente = false) => reg => ({ contadores: { Todas: 1 }, envios: [envioAberto(reg, divergente)] });

export const detalheDoEnvio = (divergente = false) => reg => ({
  envio: envioAberto(reg, divergente), familia: "sinfra", etapa: "nota", situacao_protocolo: "rascunho", carta: null,
  previa: {
    para: ["protocolo@exemplo.com.br"], copia: ["fiscal.do.contrato@exemplo.com.br"],
    assunto: "Nota fiscal 2322 da 1ª medição da Obra Própria, contrato 001/2025/00/00-EXEMPLO, com a FRC e as certidões de regularidade",
    corpo: "Prezados,\n\nEncaminhamos a nota fiscal 2322, referente à 1ª medição da Obra Própria, com os documentos de regularidade.\n\nAtenciosamente,",
    anexos: [{ nome: "NF 2322.pdf", origem: "nota", tamanho: 182044 }, { nome: "Certidão federal.pdf", origem: "certidao", tamanho: 95120 }],
    links: [],
  },
  bloqueio: null, pendencias: ["FRC assinada não anexada"], exige_justificativa: divergente, extras: [],
});

// A medicao com a nota emitida que diverge do espelho no ISS: o passo "Notas" destaca a celula e diz a diferenca, e o
// resumo da pagina aponta a nota.
const DIFERENCA_NO_ISS = [{ campo: "iss", espelho: 824691, nota: 804691, grau: "divergente" }];
export const medicaoComNotaDivergente = (medicoes, reg) => medicaoComNotaEmitida(medicoes, reg).map(m => (m.id === reg.medicao ? {
  ...m,
  notas: [{ nota_id: 9001, coligada: 1, numero: "2322", serie: null, emissao: "2025-05-22", valor_centavos: 41234567,
    recebido_centavos: 0, devido_centavos: 38120740, falta_centavos: 38120740, da_lotufo: true, da_cota: true,
    recebido_em: null, origem: "pdf", regra: null, conferencia: DIFERENCA_NO_ISS, justificativa: null }],
} : m));

export const NOTAS_COM_DIVERGENCIA = {
  esperadas: [{ chave: "nf", natureza: "execucao", rotulo: "Nota de execução", emissor: "lotufo", municipio: "Cidade de Exemplo",
    valor: 41234567, iss: 824691, inss: 1814321, irrf: 494815, ibs: null, cbs: null, liquido: 38100740, nota_id: 9001 }],
  notas: [{ alocacao_id: 9301, nota_id: 9001, coligada: 1, numero: "2322", serie: null, emissao: "2025-05-22",
    valor_centavos: 41234567, valor_pdf_centavos: 41234567, origem_nota: "pdf", confirmacao: "aguardando_rm", documento_id: 9311,
    conferencia: DIFERENCA_NO_ISS, justificativa: null, leitura: null, municipio: "Cidade de Exemplo", regra: null,
    recebido_centavos: 0 }],
  faltam: 0, documentos_sem_nota: [], pode_declarar: false,
};

// A obra com cadastro de custo: a aba Medicoes ganha a coluna do custo lancado no RM por competencia.
export const CUSTO_DA_OBRA = {
  linhas: [{ competencia: "2025-04", custo_centavos: 35000000 }, { competencia: "2025-05", custo_centavos: 40000000 },
    { competencia: "2025-06", custo_centavos: 0 }],
};

// O a receber que fica a' parte (docs/adr/0006): o cadastro de exemplo nao tem pendencia anterior a 2025 nem nota fora da
// janela do RM. No Inicio, a linha sob o ciclo; na lista de Obras, sob os totais (a primeira obra leva os dois valores).
export const inicioComAParte = painel => ({ ...painel, a_receber: { ...painel.a_receber, liberado: true,
  a_parte: { ano_inicial: "2025", valor_centavos: 110004, anterior_centavos: 70003, sem_atualizacao_centavos: 40001,
    sem_atualizacao_desde: "2026-10-02" } } });
// As familias de valor na Inicio (#805): o cadastro de exemplo so' tem medicoes de 2025, entao os dois numeros do alto
// nao tem com o que comparar. Aqui eles ganham as referencias, com as tres leituras da variacao: subiu (bom), caiu
// (ruim) e estavel. Os meses saem do `hoje` da resposta verdadeira; os valores sao inventados.
const mesAntes = (mes, n) => {
  const [ano, m] = mes.split("-").map(Number), total = ano * 12 + m - 1 - n;
  return `${Math.floor(total / 12)}-${String(total % 12 + 1).padStart(2, "0")}`;
};
export const inicioComVariacoes = painel => {
  const mesDeHoje = painel.hoje.slice(0, 7), competencia = painel.medido.competencia;
  return { ...painel,
    notas_mes: { ...painel.notas_mes, valor_centavos: 1124000001, notas: 6, obras: 4,
      anterior: { mes: mesAntes(mesDeHoje, 1), ate_dia: Number(painel.hoje.slice(8, 10)), valor_centavos: 1000000001 } },
    medido: { ...painel.medido, valor_centavos: 400000007,
      anterior: { competencia: mesAntes(competencia, 1), valor_centavos: 500000005 },
      ano_anterior: { competencia: mesAntes(competencia, 12), valor_centavos: 400000003 } } };
};

// O que faltava apresentar a' diretoria na Inicio (#817): o cadastro de exemplo tem um orgao so' e poucas medicoes, e a
// tela foi desenhada para varios contratantes com valores de dezenas de milhoes. Aqui o ciclo abre em cinco
// contratantes ficticios (um de nome longo e um sem orgao no cadastro, que nao tem pagina), a faixa do ciclo e o a
// receber saem da soma das linhas (como no servidor: a tela mostra os dois e eles tem de fechar), e o medido das 12
// competencias ganha uma serie regular, com um mes sem medicao. Valores de tabela, em milhoes de reais: cada
// contratante tem as cinco colunas em degraus de um milhao; o de nome longo tem duas colunas vazias ("—").
const MI = 100000000;   // R$ 1.000.000,00 em centavos
//                         contratante, chave, em analise, boletim, nota, protocolado, a receber (em milhoes)
const INI_CONTRATANTES = [
  ["Contratante Alfa", "contratante-alfa", 1, 2, 3, 4, 5],
  ["Contratante Beta", "contratante-beta", 2, 3, 4, 5, 6],
  ["Contratante Gama", "contratante-gama", 3, 4, 5, 6, 7],
  ["Consórcio Intermunicipal de Desenvolvimento do Vale do Rio Exemplo", "consorcio-exemplo", 1, 0, 2, 0, 3],
  ["sem órgão", null, 1, 1, 1, 1, 1],
];
const INI_ETAPAS = ["em_analise", "boletim", "nota", "protocolado"];
// o medido de cada competencia, em milhoes: dois a mais por mes, e o setimo mes sem medicao
const INI_MEDIDO = [2, 4, 6, 8, 10, 12, 0, 16, 18, 20, 22, 24];
export const inicioPorContratante = painel => {
  const linhas = INI_CONTRATANTES.map(([contratante, chave, ...valores]) => ({ contratante, chave,
    ...Object.fromEntries(INI_ETAPAS.map((e, i) => [`${e}_centavos`, valores[i] * MI])), a_receber_centavos: valores[4] * MI }));
  const soma = campo => linhas.reduce((s, l) => s + l[campo], 0);
  return { ...painel,
    ciclo: painel.ciclo.map(e => INI_ETAPAS.includes(e.etapa)
      ? { ...e, valor_centavos: soma(`${e.etapa}_centavos`), quantidade: 2 * (INI_ETAPAS.indexOf(e.etapa) + 1),
        mais_antigo_dias: 10 * (INI_ETAPAS.indexOf(e.etapa) + 1) }
      : e),
    a_receber: { liberado: true, valor_centavos: soma("a_receber_centavos"), mais_60_centavos: 2 * MI,
      a_parte: painel.a_receber.a_parte ?? { ano_inicial: "2025", valor_centavos: 0, anterior_centavos: 0, sem_atualizacao_centavos: 0,
        sem_atualizacao_desde: null } },
    ciclo_por_contratante: linhas,
    medido_12m: painel.medido_12m.map((m, i) => ({ ...m, valor_centavos: (INI_MEDIDO[i] ?? 0) * MI })) };
};
// Nada no ciclo nem a receber, e nenhuma competencia com medido: a linha curta no lugar da tabela e o grafico sem coluna.
export const inicioSemCiclo = painel => ({ ...painel,
  ciclo: painel.ciclo.map(e => ({ ...e, valor_centavos: 0, quantidade: 0, mais_antigo_dias: null })),
  ciclo_por_contratante: [], medido_12m: painel.medido_12m.map(m => ({ ...m, valor_centavos: 0 })) });

// As familias de valor no Fechamento (#805): dois anos, para o medido de cada mes ter o mesmo mes do ano anterior, e
// as leituras da diferenca entre o aprovado e o pedido. Julho: um corte critico. Agosto: um corte que, no mes, fica
// pequeno, ao lado de uma medicao dentro da tolerancia de arredondamento (R$ 0,03). Setembro: uma medicao com o pedido
// gravado dez vezes menor (aprovado acima do pedido: so' aparece na linha dela) e outra igual; o mes sai "igual ao
// pedido". Outubro: so' arredondamento, mais uma medicao em analise, que nao e' diferenca. Novembro e' o mes em curso,
// sem variacao. Valores de centenas de milhoes, para a tabela ser provada com o numero largo. Tudo inventado; a obra
// e a primeira medicao de cada mes sao as da prova.
const FCH_TOLERANCIA = 5;      // o que o servidor conta como arredondamento do orgao, em centavos
const fchMedicao = (aprovado, pedido, recebido, emAnalise = 0) => {
  const falta = pedido - aprovado;
  return { medido_centavos: aprovado + emAnalise, aprovado_centavos: aprovado, protocolado_centavos: aprovado, recebido_centavos: recebido,
    em_aberto_centavos: aprovado - recebido, em_aberto_notas_centavos: aprovado - recebido, em_aberto_repasse_centavos: 0,
    sem_nota_centavos: 0, aprovado_com_pedido_centavos: aprovado, pedido_do_aprovado_centavos: pedido,
    abaixo_do_pedido_centavos: falta > FCH_TOLERANCIA ? falta : 0, acima_do_pedido_centavos: -falta > FCH_TOLERANCIA ? -falta : 0 };
};
const igual = v => [fchMedicao(v, v, v)];
const FCH_MESES = [
  ["2025-07", igual(3391300001)], ["2025-08", igual(2644600003)], ["2025-09", igual(2341800005)], ["2025-10", igual(2273400007)],
  ["2026-07", [fchMedicao(2305000001, 2340000001, 2287000001)]],                                              // corte de 1,5%
  ["2026-08", [fchMedicao(1894000003, 1906400003, 1894000003), fchMedicao(1200000000, 1200000003, 1200000000)]],   // corte e arredondamento
  ["2026-09", [fchMedicao(1768000005, 1768000005, 842000005), fchMedicao(600000000, 60000000, 600000000)]],         // igual e acima
  ["2026-10", [fchMedicao(1873000007, 1873000009, 1624000007), fchMedicao(0, 0, 0, 555000000)]],                    // arredondamento e analise
  ["2026-11", [fchMedicao(0, 0, 0, 310000009)]],                                                              // o mes em curso
];
// o acima do pedido e' so' da medicao: nao soma
const FCH_SOMAVEIS = Object.keys(fchMedicao(0, 0, 0)).filter(k => k !== "acima_do_pedido_centavos");
const fchSoma = linhas => Object.fromEntries(FCH_SOMAVEIS.map(k => [k, linhas.reduce((t, x) => t + x[k], 0)]));
export const fechamentoComValores = reg => {
  let numero = 0;
  const meses = FCH_MESES.map(([comp, linhas]) => {
    const medicoes = linhas.map((x, j) => {
      numero += 1;
      const aberto = x.em_aberto_centavos > 0;
      return { ...x, medicao_id: j === 0 ? reg.medicao : 9500 + numero, contrato_id: reg.obra, obra: "Obra Exemplo", numero, tipo: "execucao",
        competencia: comp, protocolo_em: x.protocolado_centavos ? `${mesAntes(comp, -1)}-20` : null, notas_fora_da_conta: [], sem_nota: false,
        notas: x.protocolado_centavos ? [{ nota_id: 9400 + numero, numero: String(900 + numero), valor_centavos: x.protocolado_centavos,
          recebido_centavos: x.recebido_centavos, em_aberto_centavos: x.em_aberto_centavos, recebida: !aberto, paga_em_parte: aberto,
          aguarda_repasse: false }] : [] };
    });
    const soma = fchSoma(medicoes);
    return { competencia: comp, ...soma, obras: [{ contrato_id: reg.obra, obra: "Obra Exemplo", ...soma, medicoes }] };
  });
  const medido = Object.fromEntries(meses.map(m => [m.competencia, m.medido_centavos]));
  for (const m of meses) {
    const anterior = medido[mesAntes(m.competencia, 12)];
    m.medido_ano_anterior_centavos = anterior && m.competencia < "2026-11" ? anterior : null;
  }
  const doAno = ano => meses.filter(m => m.competencia.startsWith(ano));
  const cobertura = ano => { const t = fchSoma(doAno(ano)); return { aprovado_centavos: t.aprovado_centavos,
    com_nota_centavos: t.aprovado_centavos, sem_nota_centavos: 0, medicoes_sem_nota: 0, percentual: 100 }; };
  return {
    anos: ["2025", "2026"], meses,
    por_ano: { 2025: { ...fchSoma(doAno("2025")), meses: 4 }, 2026: { ...fchSoma(doAno("2026")), meses: 5 } },
    acumulado: { ate_mes: "11", 2025: fchSoma(doAno("2025")), 2026: fchSoma(doAno("2026")) },
    em_aberto: meses.flatMap(m => m.obras[0].medicoes.filter(md => md.em_aberto_centavos > 0).map(md => (
      { tipo_aberto: "nota", nota_id: md.notas[0].nota_id, numero: md.notas[0].numero, contrato_id: reg.obra, obra: "Obra Exemplo",
        medicao_id: md.medicao_id, medicao_numero: md.numero, tipo: "execucao", competencia: m.competencia, protocolo_em: md.protocolo_em,
        emitida_em: null, valor_centavos: md.em_aberto_centavos, paga_em_parte: true }))),
    em_aberto_anteriores: { quantidade: 0, valor_centavos: 0 },
    notas_sem_medicao: { em_aberto: [], em_aberto_centavos: 0, pagas: { quantidade: 0, valor_centavos: 0 } },
    cobertura: { 2025: cobertura("2025"), 2026: cobertura("2026") }, notas_diferem: [], pares_mistos: [],
    diferenca_critica_por_mil: 5, total_a_receber_liberado: true,
  };
};

// #815, Fechamento em abas: a aba Por contratante com o que o cadastro de exemplo nao tem (ele tem um orgao so'). O
// total de cada ano de `fechamentoComValores` repartido entre quatro contratantes, o ultimo de nome comprido e sem
// pagina (sem orgao no cadastro); cada coluna das linhas soma o total do ano, como no servidor, com o resto no
// primeiro. `vazio` e' a pagina sem lancamento nenhum, nas tres abas. Valores inventados.
const FCH_CONTRATANTES = [["SINFRA", "sinfra", 560], ["MTPAR", "mtpar", 250], ["Pref. Várzea Grande", "pref-vg", 120],
  ["Secretaria Municipal de Infraestrutura e Obras de Exemplo do Norte", null, 70]];
const fchPorContratante = total => {
  const linhas = FCH_CONTRATANTES.map(([contratante, chave, porMil]) => ({ contratante, contratante_chave: chave,
    ...Object.fromEntries(FCH_SOMAVEIS.map(k => [k, Math.floor(total[k] * porMil / 1000)])), participacao_medido_por_mil: porMil }));
  for (const k of FCH_SOMAVEIS) linhas[0][k] += total[k] - linhas.reduce((t, x) => t + x[k], 0);
  return linhas;
};
export const fechamentoEmAbas = ({ vazio = false } = {}) => reg => {
  const f = fechamentoComValores(reg);
  if (!vazio) return { ...f, por_contratante: { 2025: fchPorContratante(f.por_ano[2025]), 2026: fchPorContratante(f.por_ano[2026]) } };
  const zero = fchSoma([]);
  const semCobertura = { aprovado_centavos: 0, com_nota_centavos: 0, sem_nota_centavos: 0, medicoes_sem_nota: 0, percentual: null };
  return { ...f, meses: [], por_ano: { 2025: { ...zero, meses: 0 }, 2026: { ...zero, meses: 0 } },
    acumulado: { ate_mes: null, 2025: zero, 2026: zero }, por_contratante: { 2025: [], 2026: [] }, em_aberto: [],
    cobertura: { 2025: semCobertura, 2026: semCobertura } };
};

export const obrasComAParte = obras => obras.map((o, i) => ({ ...o, posicao: { ...o.posicao, a_receber_ano_inicial: "2025",
  a_receber_anterior_centavos: i === 0 ? 70003 : 0, a_receber_sem_atualizacao_centavos: i === 0 ? 40001 : 0 } }));

// #805, Resumo das medicoes em quadro por etapa: o mes que o cadastro de exemplo nao tem (ele tem uma obra com
// medicao). As obras e os contratantes sao os da carteira simulada acima; os valores sao inventados. Medicao em cada
// etapa; cartao com o tempo parado em cada situacao (chegou hoje, em andamento, vence em breve, critico), que e' o
// `parada` da fila de trabalho: no protocolado, sem prazo do orgao (a MTPAR), dentro do prazo e alem dele; aprovado
// abaixo do pedido (pequeno e critico) e acima dele; recebida com os dias da nota ao recebimento; planilha/carta
// ainda nao enviada; obras sem medicao (uma que nunca mediu) e meses anteriores em aberto de tres competencias.
// O protocolado tem a variacao do acumulado contra a mesma altura e o recebido vem sem lastro (sem variacao). `contratante` recorta
// como o servidor (a MTPAR fica com quatro etapas vazias); `vazio` e' o mes sem medicao nenhuma.
// A resposta verdadeira da' o dia, a competencia e de quando e' o dado; o resto e' trocado.
const ETAPAS_DO_RESUMO = ["em_analise", "boletim", "nota", "protocolado", "recebido"];
const porNome = (a, b) => a.localeCompare(b, "pt-BR");
export const resumoEmQuadro = ({ contratante = null, vazio = false } = {}) => resposta => {
  const hoje = Date.parse(`${resposta.hoje}T00:00:00Z`), mes = resposta.mes;
  let id = 9600;
  // a linha de uma medicao: a etapa da vez e, de cada etapa alcancada, a data (ha' quantos dias). O `parada` e' o da
  // fila de trabalho: os limites do SIGA fora do protocolado; nele, `prazo: [dias do orgao, a data esperada em dias a
  // partir de hoje]` (negativa = ja' passou, critico); sem prazo, em andamento
  const linha = (contrato_id, obra, quem, titulo, etapa, valor, dias, uteis, { prazo = null, ...extra } = {}) => {
    id += 1;
    const pos = ETAPAS_DO_RESUMO.indexOf(etapa), recebida = etapa === "recebido", alem = prazo !== null && prazo[1] < 0;
    const etapas = ETAPAS_DO_RESUMO.map((e, i) => ({ etapa: e,
      situacao: i > pos ? "futuro" : i < pos || recebida ? "feito" : "atual",
      data: i > pos || dias === null ? null : dataEm(hoje, -(dias + (pos - i) * 6)) }));
    const situacao = dias === null ? null : alem ? "critico" : dias === 0 ? "feito"
      : etapa === "protocolado" || uteis < 5 ? "andamento" : uteis < 10 ? "breve" : "critico";
    const parada = recebida ? null : { desde: dias === null ? null : dataEm(hoje, -dias), dias_uteis: dias === null ? null : uteis,
      hoje: dias === 0, situacao, prazo_orgao_dias: prazo ? prazo[0] : null, esperada: prazo ? dataEm(hoje, prazo[1]) : null, alem_do_prazo: alem };
    return { contrato_id, obra, contratante: quem, medicao_id: id, medicao_ids: [id], titulo, numero: parseInt(titulo, 10) || 1, tipo: "execucao",
      competencia: mes, etapa, etapas, valor_centavos: valor * REAIS, parada, recebida_em: recebida ? dataEm(hoje, -dias) : null,
      dias_da_nota_ao_recebimento: null,
      pedido_do_aprovado_centavos: null, abaixo_do_pedido_centavos: null, acima_do_pedido_centavos: null, ...extra };
  };
  const comPedido = (pedido, abaixo = 0, acima = 0) => ({ pedido_do_aprovado_centavos: pedido * REAIS,
    abaixo_do_pedido_centavos: abaixo * REAIS, acima_do_pedido_centavos: acima * REAIS });
  const doMes = vazio ? [] : [
    linha(9001, "Avenida Alfa", "SINFRA", "29ª Medição", "em_analise", 500_000, 12, 9),
    linha(9010, "Hospital Capa", "SES-MT", "5ª Medição", "em_analise", 200_000, 16, 11),
    linha(9005, "Bairros Épsilon", "SINFRA", "11ª Medição", "boletim", 400_000, 0, 0, comPedido(401_000, 1_000)),
    linha(9002, "Corredor Beta", "SINFRA", "6ª Medição", "nota", 3_000_000, 1, 1, comPedido(3_000_000)),
    linha(9009, "Orla Iota", "Pref. Cuiabá", "30ª Medição", "nota", 800_000, 8, 6, comPedido(790_000, 0, 10_000)),
    { ...linha(9007, "Trevo Eta", "MTPAR", "25ª Medição + Reajuste", "protocolado", 2_000_000, 6, 4, comPedido(2_000_000)), medicao_ids: [9690, 9691] },
    linha(9008, "Anel Teta", "MTPAR", "8ª Medição", "protocolado", 600_000, 11, 8),
    // protocoladas com o prazo do orgao: dentro dele (a data esperada vai escrita) e alem dele (critico). O prazo curto
    // da segunda e' para o estado caber no mes da prova
    linha(9004, "Quartel Delta", "SINFRA", "14ª Medição", "protocolado", 200_000, 12, 8, { prazo: [45, 35] }),
    linha(9015, "Viaduto Ômicron", "SES-MT", "3ª Medição", "protocolado", 250_000, 16, 11, { prazo: [14, -2] }),
    linha(9003, "Estações Gama", "SINFRA", "8ª Medição", "recebido", 15_000_000, 5, null, { ...comPedido(15_000_000), dias_da_nota_ao_recebimento: 4 }),
    linha(9001, "Avenida Alfa", "SINFRA", "Reajuste da 28ª Medição", "recebido", 2_000_000, 9, null,
      { tipo: "reajuste", ...comPedido(2_500_000, 500_000), dias_da_nota_ao_recebimento: 31 }),
    // a planilha/carta gerada e ainda nao enviada: existe, sem valor e sem etapa
    { ...linha(9004, "Quartel Delta", "SINFRA", "1ª de Projeto", "antes", 0, 4, 3), tipo: "projeto", valor_centavos: null,
      etapas: ETAPAS_DO_RESUMO.map(e => ({ etapa: e, situacao: "futuro", data: null })) },
  ];
  const semMedicao = vazio ? [] : [
    { contrato_id: 9011, obra: "Complexo Lambda", contratante: "SINFRA", ultima: { medicao_id: 9701, titulo: "7ª Medição", competencia: mesAntes(mes, 3), etapa: "recebido" } },
    { contrato_id: 9012, obra: "Ponte Mi", contratante: "SINFRA", ultima: { medicao_id: 9702, titulo: "3ª Medição", competencia: mesAntes(mes, 1), etapa: "protocolado" } },
    { contrato_id: 9013, obra: "Praça Ni", contratante: "Pref. Cuiabá", ultima: { medicao_id: 9703, titulo: "14ª Medição", competencia: mesAntes(mes, 11), etapa: "recebido" } },
    { contrato_id: 9014, obra: "Rodovia Csi lote 2", contratante: "MTPAR", ultima: null },
  ];
  const deAntes = (meses, ...linhas) => linhas.map(l => ({ ...l, competencia: mesAntes(mes, meses) }));
  const anteriores = vazio ? [] : [
    ...deAntes(7, linha(9009, "Orla Iota", "Pref. Cuiabá", "23ª Medição", "protocolado", 900_000, 190, 128)),
    ...deAntes(2, linha(9002, "Corredor Beta", "SINFRA", "14ª Medição", "protocolado", 3_000_000, 48, 33, comPedido(3_010_000, 10_000)),
      linha(9007, "Trevo Eta", "MTPAR", "23ª Medição", "protocolado", 4_000_000, 51, 35)),
    ...deAntes(1, linha(9001, "Avenida Alfa", "SINFRA", "28ª Medição", "protocolado", 5_000_000, 20, 14),
      linha(9003, "Estações Gama", "SINFRA", "7ª Medição", "nota", 10_000_000, 15, 10),
      linha(9008, "Anel Teta", "MTPAR", "7ª Medição", "em_analise", 600_000, 40, 28)),
  ];
  const quantas = ls => ls.reduce((n, l) => n + l.medicao_ids.length, 0);
  const soma = ls => ls.reduce((n, l) => n + (l.valor_centavos ?? 0), 0);
  const porEtapa = ls => ["antes", ...ETAPAS_DO_RESUMO].map(e => {
    const daEtapa = ls.filter(l => l.etapa === e);
    return { etapa: e, medicoes: quantas(daEtapa), valor_centavos: soma(daEtapa) };
  });
  const contratantes = [...new Set([...doMes, ...anteriores].map(l => l.contratante))].sort(porNome).map(n => ({ contratante: n,
    medicoes: quantas(doMes.filter(l => l.contratante === n)), anteriores: quantas(anteriores.filter(l => l.contratante === n)) }));
  const recorte = ls => (contratante ? ls.filter(l => l.contratante === contratante) : ls);
  const linhasDoMes = recorte(doMes), linhasDeAntes = recorte(anteriores);
  const grupos = [...new Set(linhasDoMes.map(l => l.contratante))].sort(porNome).map(n => {
    const ls = linhasDoMes.filter(l => l.contratante === n).sort((a, b) => porNome(a.obra, b.obra));
    return { contratante: n, medicoes: quantas(ls), valor_centavos: soma(ls), linhas: ls };
  });
  const medido = soma(linhasDoMes);
  const acumulado = soma(linhasDoMes.filter(l => l.etapa === "protocolado" || l.etapa === "recebido"));
  // o mesmo dia de hoje, um mes antes (o dia 29 em diante fica no 28, para caber em qualquer mes)
  const d = new Date(hoje), ate = dataEm(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() - 1, Math.min(28, d.getUTCDate())));
  return { ...resposta, contratante, contratantes, etapas: porEtapa(linhasDoMes),
    // o medido subiu contra o mes anterior e ficou estavel contra o mesmo mes do ano anterior
    medido: { valor_centavos: medido, mes_anterior: medido ? { competencia: mesAntes(mes, 1), valor_centavos: Math.round(medido / 1.068) } : null,
      ano_anterior: medido ? { competencia: mesAntes(mes, 12), valor_centavos: Math.round(medido / 0.99) } : null },
    // o protocolado compara o acumulado (o que esta' na etapa e o que ja' foi recebido), que subiu contra o da
    // competencia anterior na mesma altura, embora o valor da etapa seja bem menor: o orgao pagou cedo. O recebido
    // nao tem lastro (sem variacao)
    protocolado_acumulado_centavos: acumulado,
    mesma_altura: medido ? { competencia: mesAntes(mes, 1), ate, protocolado_acumulado_centavos: Math.round(acumulado / 1.09), recebido_centavos: null } : null,
    diferenca_critica_por_mil: 5, grupos, sem_medicao: recorte(semMedicao), anteriores_etapas: porEtapa(linhasDeAntes),
    anteriores: [...new Set(linhasDeAntes.map(l => l.competencia))].sort().map(c => {
      const ls = linhasDeAntes.filter(l => l.competencia === c);
      return { competencia: c, medicoes: quantas(ls), valor_centavos: soma(ls), linhas: ls };
    }) };
};

// #805, Obras por contratante: a carteira que o cadastro de exemplo nao tem (ele tem um orgao so', duas obras em
// andamento e nenhuma medicao no mes fechado). Quatro contratantes (as siglas sao as que o codigo conhece; as obras e
// os valores sao inventados): obra devagar, em atencao e adiantada; obra paralisada, com a execucao vencida, em
// encerramento e encerrada; contratante com e sem prazo de pagamento; medido do mes subindo, caindo, estavel e sem
// medicao. `carteiraSimulada` troca o /api/contratos e `painelDaCarteira` ajusta o /api/diretoria com o farol, os
// motivos, os avisos criticos e o prazo de pagamento dessas obras. As competencias andam com o dia da prova.
const competenciaHa = meses => { const h = new Date(); return new Date(Date.UTC(h.getFullYear(), h.getMonth() - meses, 1)).toISOString().slice(0, 7); };
const REAIS = 100;
const daCarteira = (id, nome, contratante, chave, x) => {
  const vigente = x.vigente * REAIS, medido = x.medido * REAIS, fim = hojeDaProva() + (x.dias ?? 200) * DIA;
  return {
    id, orgao: x.orgao ?? contratante, contratante, contratante_chave: chave, orgao_sub: x.sub ?? null, numero_instrumento: `00${id - 9000}/2025/00/00-EXEMPLO`,
    nome_curto: nome, estado: x.estado ?? "ativo", encerramento_iniciado_em: x.encerramento ?? null, entidade_id: 1, percentual_direito_bp: x.bp ?? 10000,
    valor_vigente_centavos: vigente, valor_vigente_execucao_centavos: vigente, medido_centavos: medido, saldo_centavos: vigente - medido,
    execucao_fim_vigente: dataEm(fim), vigencia_fim_vigente: dataEm(fim, 90), dias_execucao: x.dias ?? 200, dias_vigencia: (x.dias ?? 200) + 90,
    vigencia_automatica: false, paralisada_desde: x.paralisada ?? null, pedido_prorrogacao: null,
    posicao: { vigente_centavos: vigente, medido_centavos: medido, saldo_centavos: vigente - medido, a_receber_centavos: (x.receber ?? 0) * REAIS,
      a_receber_ano_inicial: "2025", a_receber_anterior_centavos: 0, a_receber_sem_atualizacao_centavos: 0 },
    andamento: { ritmo_centavos: x.ritmo == null ? null : x.ritmo * REAIS, necessario_centavos: x.necessario == null ? null : x.necessario * REAIS,
      leitura: leituraSimulada(x.ritmo, x.necessario, x.fora) },
    medido_mes: { competencia: competenciaHa(1), valor_centavos: (x.mes ?? 0) * REAIS, referencia_competencia: competenciaHa(2),
      referencia_centavos: (x.antes ?? 0) * REAIS },
  };
};
const CARTEIRA = () => [
  // SINFRA: devagar (40% e 17% do necessario), adiantada, em atencao, em encerramento e uma encerrada
  daCarteira(9001, "Avenida Alfa", "SINFRA", "sinfra", { orgao: "SINFRA - SUEF II", sub: "SUEF II", vigente: 120_000_000, medido: 60_000_000,
    ritmo: 3_000_000, necessario: 7_500_000, mes: 4_000_000, antes: 5_000_000 }),
  daCarteira(9002, "Corredor Beta", "SINFRA", "sinfra", { orgao: "SINFRA - SUPU", sub: "SUPU", bp: 4900, vigente: 210_000_000, medido: 180_000_000,
    ritmo: 4_100_000, necessario: 3_600_000, mes: 3_300_000, antes: 2_800_000, receber: 3_900_000, dias: 90 }),
  daCarteira(9003, "Estações Gama", "SINFRA", "sinfra", { orgao: "SINFRA - SUPU", sub: "SUPU", vigente: 180_000_000, medido: 63_000_000,
    ritmo: 7_000_000, necessario: 39_000_000, mes: 15_000_000, antes: 10_000_000, dias: 40 }),
  daCarteira(9004, "Quartel Delta", "SINFRA", "sinfra", { orgao: "SINFRA - SUEF II", sub: "SUEF II", vigente: 12_000_000, medido: 5_600_000,
    ritmo: 500_000, necessario: 600_000, mes: 600_000, antes: 600_000, receber: 600_000, dias: 250 }),
  daCarteira(9005, "Bairros Épsilon", "SINFRA", "sinfra", { orgao: "SINFRA - SUPU", sub: "SUPU", vigente: 8_000_000, medido: 7_900_000,
    ritmo: 300_000, necessario: null, mes: 200_000, antes: 500_000, dias: 4, encerramento: dataEm(hojeDaProva(), -20) }),
  daCarteira(9006, "Travessia Zeta", "SINFRA", "sinfra", { orgao: "SINFRA - SUEF II", sub: "SUEF II", vigente: 30_000_000, medido: 30_000_000,
    estado: "encerrado", ritmo: null, necessario: null, dias: -400 }),
  // MTPAR, sem prazo de pagamento no sistema: uma com a execucao vencida e uma em atencao
  daCarteira(9007, "Trevo Eta", "MTPAR", "mtpar", { vigente: 90_000_000, medido: 75_000_000, ritmo: 900_000, necessario: null,
    mes: 3_100_000, antes: 4_000_000, receber: 7_100_000, dias: -25 }),
  daCarteira(9008, "Anel Teta", "MTPAR", "mtpar", { vigente: 125_000_000, medido: 50_000_000, ritmo: 2_000_000, necessario: 2_500_000, dias: 900 }),
  // Pref. Cuiaba: uma obra paralisada
  daCarteira(9009, "Orla Iota", "Pref. Cuiabá", "pref-cuiaba", { vigente: 65_000_000, medido: 37_000_000, estado: "suspenso",
    paralisada: dataEm(hojeDaProva(), -100), ritmo: 300_000, necessario: null, mes: 900_000, antes: 900_000, receber: 900_000 }),
  // SES-MT: uma obra adiantada, sem nada pendente e sem medicao no mes (o contratante fica "Em dia")
  daCarteira(9010, "Hospital Capa", "SES-MT", "ses-mt", { vigente: 170_000_000, medido: 160_000_000, ritmo: 5_000_000, necessario: 4_000_000, dias: 75 }),
  // SINFRA, decisao do dono de 18/11/2026: devagar (40% do necessario) e sem aviso nenhum. Na pagina do contratante a
  // Situacao diz o motivo do andamento, e nao "Em dia"
  daCarteira(9016, "Ponte Pi", "SINFRA", "sinfra", { orgao: "SINFRA - SUEF II", sub: "SUEF II", vigente: 54_000_000, medido: 16_200_000,
    ritmo: 3_000_000, necessario: 7_500_000, mes: 1_100_000, antes: 1_000_000, dias: 400 }),
];
export const carteiraSimulada = () => CARTEIRA_INTEIRA();

const farolDaCarteira = (o, farol, motivos = []) => ({
  contrato_id: o.id, seq: o.id - 9000, obra: o.nome_curto, contratante: o.contratante, empreita: o.percentual_direito_bp === 10000 ? "PRÓPRIA" : "CONSÓRCIO",
  direito: o.percentual_direito_bp / 10000, pi_va: o.posicao.vigente_centavos, faturados: o.posicao.medido_centavos, saldo: o.posicao.saldo_centavos,
  status: "EM ANDAMENTO", termino: o.execucao_fim_vigente, vigencia: o.vigencia_fim_vigente, farol,
  motivo: motivos.map(m => m[1]).join("; "),
  motivos: motivos.map(([nivel, texto]) => ({ tipo: "simulado", nivel, dias: null, valor_centavos: null, texto })) });
const MOTIVOS = {
  9001: ["vermelho", [["critico", "14ª Medição: aprovado 20% abaixo do pedido"], ["atencao", "garantia vence em 30 dias"]]],
  9002: ["atencao", [["atencao", "prorrogação pedida há 10 dias"]]],
  9003: ["vermelho", [["critico", "garantia não cobre o fim da execução"], ["acao", "execução termina em 40 dias"], ["atencao", "reajuste esperando apostilamento"]]],
  9005: ["acao", [["acao", "execução termina em 5 dias"]]],
  9007: ["vermelho", [["critico", "execução venceu há 25 dias"]]],
  9009: ["atencao", [["atencao", "obra paralisada há 100 dias"]]],
};
export const painelDaCarteira = painel => {
  const emAndamento = CARTEIRA_INTEIRA().filter(o => o.estado !== "encerrado");
  const obras = emAndamento.map(o => farolDaCarteira(o, ...(MOTIVOS[o.id] ?? ["verde", []])));
  return { ...painel, obras, prazo_pagamento: { SINFRA: 45, "Pref. Cuiabá": 60, "SES-MT": 40 },
    reajustes_apostilamento: { competencias: 3, valor_centavos: 40_000_000, obras: [
      { contrato_id: 9003, obra: "Estações Gama", competencias: 2, valor_centavos: 30_000_000 },
      { contrato_id: 9004, obra: "Quartel Delta", competencias: 1, valor_centavos: 10_000_000 }] },
    avisos: obras.flatMap(o => o.motivos.map(m => ({ tipo: m.tipo, nivel: m.nivel, publico: ["diretoria"], contrato_id: o.contrato_id, obra: o.obra,
      dias: null, valor_centavos: null, mensagem: `${o.obra}: ${m.texto}`, destino: { tela: "contrato", id: o.contrato_id, aba: "prazos" } }))) };
};

// A reconciliacao com o grupo "Títulos baixados no RM por valor menor" (docs/adr/0006): o banco da prova nao tem titulo
// baixado com diferenca. Uma linha com medicao e outra de nota sem medicao, na primeira obra da prova.
export const reconciliacaoComBaixados = (rec, reg) => ({ ...rec, baixados_com_diferenca: [
  { titulo_id: 9301, nota_id: 9311, contrato_id: reg.obra, numero_instrumento: "001/2025/00/00-EXEMPLO", medicao_id: reg.medicao, numero: 1,
    tipo: "execucao", competencia: "2025-04", numero_nf: "101", serie: "1", valor_original_centavos: 38000001,
    valor_baixado_centavos: 37800000, diferenca_centavos: 200001, data_baixa: "2025-07-10" },
  { titulo_id: 9302, nota_id: 9312, contrato_id: reg.obra, numero_instrumento: "001/2025/00/00-EXEMPLO", medicao_id: null, numero: null,
    tipo: null, competencia: null, numero_nf: "115", serie: null, valor_original_centavos: 50001, valor_baixado_centavos: 40000,
    diferenca_centavos: 10001, data_baixa: null }] });

// A obra paralisada e a obra em encerramento: o cabecalho muda o selo do estado e a aba Prazos mostra a paralisacao
// (sem o selo dos dias da execucao) ou o cartao do encerramento.
// `extra`: desde quando a obra esta' assim (`status_desde`) e a ordem de paralisacao (`paralisada_desde`), que o
// painel "Prazo" mostra no lugar dos dias do prazo.
export const cabecalhoCom = (status, extra = {}) => cabecalho => ({ ...cabecalho, status, ...extra });
export const prazosParalisada = prazos => ({
  ...prazos, situacao: { ...prazos.situacao, paralisacao: { desde: "2026-08-03", numero: "OP-01/2026" }, encerramento: null },
});
export const prazosEmEncerramento = prazos => ({
  ...prazos, situacao: { ...prazos.situacao, paralisacao: null,
    encerramento: { desde: "2026-10-01", marcos: { recebimento_provisorio: "2026-10-15" }, conclusao_comunicada: false } },
});

// #803: a obra com a execucao em dia, que a de exemplo nao tem (a dela venceu e nao ha' medicao na janela do ritmo:
// o painel "Prazo" mostra "—" no ritmo, no necessario e na conclusao). O fim da execucao vai para o ultimo dia do mes
// daqui a 4 meses, entao restam 5 competencias, e o necessario e' o saldo do topo dividido por elas. `noRitmo`: o
// ritmo acima do necessario (selo "No ritmo do prazo"); senao abaixo, com os dias da conclusao alem do fim. As datas
// andam com o dia da prova, para a linha do tempo nao mostrar vencida a execucao que o painel diz em dia.
const DIA = 86_400_000;
const hojeDaProva = () => { const h = new Date(); return Date.UTC(h.getFullYear(), h.getMonth(), h.getDate()); };
const fimEmDia = () => { const h = new Date(); return Date.UTC(h.getFullYear(), h.getMonth() + 5, 0); };
const dataEm = (ms, dias = 0) => new Date(ms + dias * DIA).toISOString().slice(0, 10);
const diasAte = ms => Math.round((ms - hojeDaProva()) / DIA);
export const cabecalhoEmDia = cabecalho => ({
  ...cabecalho, execucao_fim: dataEm(fimEmDia()), dias_execucao: diasAte(fimEmDia()), execucao_sem_prazo: false,
  nivel_execucao: "normal", vigencia_fim: dataEm(fimEmDia(), 90), dias_vigencia: diasAte(fimEmDia()) + 90, nivel_vigencia: "normal" });
export const fichaComNecessario = noRitmo => ficha => {
  const fim = fimEmDia(), necessario = Math.round(ficha.topo.saldo_centavos / 5);
  return { ...ficha,
    vencimentos: ficha.vencimentos.map(v => (v.chave === "execucao" ? { ...v, data: dataEm(fim), dias: diasAte(fim), nivel: "normal" } : v)),
    ritmo: { ritmo_centavos: Math.round(necessario * (noRitmo ? 5 : 3) / 4), necessario_centavos: necessario, competencias_restantes: 5,
      conclusao: dataEm(fim, noRitmo ? -13 : 70), situacao: noRitmo ? "no_prazo" : "atrasa", dias_alem: noRitmo ? null : 70,
      leitura: leituraSimulada(noRitmo ? 5 : 3, 4) } };
};

// #822: a leitura do andamento como o servidor a manda (`prazos.leitura_do_andamento`): a palavra e o percentual pelo
// corte dele (70% e 100%, por piso) ou, com `fora`, o motivo de a obra ficar fora da regua. A tela so' escreve o que
// vem aqui. `FORA_DA_REGUA`: as obras que a carteira simulada nao tinha, uma de cada motivo (prazo no fim, com e sem
// pedido de prorrogacao; prorrogacao pedida com prazo pela frente; sem medicao ha' tres competencias), com o aviso de
// prazo que elas teriam. `fichaForaDaRegua`: a pagina da obra nesses estados (o selo da conclusao continua, 19/11).
const SEM_LEITURA = { situacao: null, pct: null, motivo: null, prorrogacao_pedida: false, sem_medicao_desde: null,
  atencao_desde_pct: 70, adiantada_desde_pct: 100 };
const leituraSimulada = (ritmo, necessario, fora) => {
  if (fora || ritmo == null || necessario == null || necessario <= 0) return { ...SEM_LEITURA, ...fora };
  const pct = Math.floor(ritmo * 100 / necessario);
  return { ...SEM_LEITURA, pct, situacao: pct >= 100 ? "adiantada" : pct >= 70 ? "atencao" : "devagar" };
};
const FORA_DA_REGUA = () => [
  daCarteira(9011, "Viaduto Lambda", "SINFRA", "sinfra", { orgao: "SINFRA - SUPU", sub: "SUPU", vigente: 64_000_000, medido: 55_000_000,
    ritmo: 1_900_000, necessario: 9_000_000, mes: 2_100_000, antes: 1_700_000, dias: 10,
    fora: { motivo: "prazo_no_fim", prorrogacao_pedida: true, execucao_fim: dataEm(hojeDaProva(), 10) } }),
  daCarteira(9012, "Maternidade Mi", "SINFRA", "sinfra", { orgao: "SINFRA - SUEF II", sub: "SUEF II", vigente: 240_000_000, medido: 5_000_000,
    ritmo: 800_000, necessario: 17_000_000, mes: 900_000, antes: 800_000, dias: 400, fora: { motivo: "prorrogacao_pedida", prorrogacao_pedida: true } }),
  daCarteira(9013, "Complexo Ni", "MTPAR", "mtpar", { vigente: 52_000_000, medido: 47_000_000, ritmo: 750_000, necessario: 1_100_000,
    dias: 100, fora: { motivo: "sem_medicao", sem_medicao_desde: competenciaHa(5) } }),
  daCarteira(9014, "Praça Xi", "Pref. Cuiabá", "pref-cuiaba", { vigente: 9_500_000, medido: 6_500_000, ritmo: 400_000, necessario: 1_500_000,
    mes: 400_000, antes: 400_000, dias: 45, fora: { motivo: "prazo_no_fim", execucao_fim: dataEm(hojeDaProva(), 45) } }),
];
// a carteira que as telas recebem: a de sempre e as obras fora da regua
const CARTEIRA_INTEIRA = () => [...CARTEIRA(), ...FORA_DA_REGUA()];
Object.assign(MOTIVOS, {
  9011: ["vermelho", [["critico", "execução termina em 12 dias"], ["atencao", "prorrogação pedida há 14 dias"]]],
  9012: ["atencao", [["atencao", "prorrogação pedida há 218 dias"]]],
  // 9014 (prazo no fim) fica verde: o aviso de execucao terminando e' so' da operacao, e o farol e' o da diretoria.
  // A Situacao dela diz "Prazo no fim · execução até dd/mm" no lugar de "Em dia" (decisao do dono de 19/11/2026)
});
// a pagina da obra fora da regua. `noFim`: a execucao termina no ultimo dia do mes que vem (duas competencias, a de
// hoje e a seguinte); senao, daqui a 4 meses (cinco), como em `fichaComNecessario`
const fimNoFim = () => { const h = new Date(); return Date.UTC(h.getFullYear(), h.getMonth() + 2, 0); };
const nivelDosDias = dias => (dias <= 30 ? "critico" : dias <= 60 ? "atencao" : "normal");
export const cabecalhoNoFim = cabecalho => {
  const fim = fimNoFim(), dias = diasAte(fim);
  return { ...cabecalho, execucao_fim: dataEm(fim), dias_execucao: dias, execucao_sem_prazo: false, nivel_execucao: nivelDosDias(dias),
    vigencia_fim: dataEm(fim, 90), dias_vigencia: dias + 90, nivel_vigencia: "normal" };
};
export const fichaForaDaRegua = (fora, noFim = false) => ficha => {
  const fim = noFim ? fimNoFim() : fimEmDia(), competencias = noFim ? 2 : 5, dias = diasAte(fim);
  const necessario = Math.round(ficha.topo.saldo_centavos / competencias);
  return { ...ficha,
    vencimentos: ficha.vencimentos.map(v => (v.chave === "execucao" ? { ...v, data: dataEm(fim), dias, nivel: nivelDosDias(dias) } : v)),
    ritmo: { ritmo_centavos: Math.round(necessario / 4), necessario_centavos: necessario, competencias_restantes: competencias,
      // o selo da conclusao continua fora da regua (decisao do dono de 19/11/2026)
      conclusao: dataEm(fim, 190), situacao: "atrasa", dias_alem: 190,
      leitura: leituraSimulada(null, null, fora?.motivo === "prazo_no_fim" ? { ...fora, execucao_fim: dataEm(fim) } : fora) } };
};
export const semAvisoDePrazo = inicio => ({
  ...inicio, avisos: inicio.avisos.filter(a => !["instrumento_pendente", "execucao_vencendo"].includes(a.tipo)) });

// #805: a fila de avisos com o volume que o cadastro de exemplo nao tem: dezenas de vencidos em varias obras (e numa
// empresa), alguns de mais de dois anos, e a agenda dos proximos 90 dias, com pelo menos um aviso de cada assunto da
// pagina (Prazos, Reajustes, Garantias, Certidoes, Medicoes e SIGA). Os tipos sao os do servidor. `publico` e' o
// recorte que o servidor faz para o perfil ("operacao" ou "diretoria"): a diretoria nao recebe certidao, prazo a
// vencer, nota nem SIGA. A primeira obra e' a da prova (`reg.obra`), para o filtro `?obra=` ter o que mostrar; as
// outras nao existem no banco. As datas andam com o dia da prova.
const OBRAS_DOS_AVISOS = ["Obra Própria", "Ponte do Exemplo", "Escola Modelo", "Rodovia Alfa", "Hospital Beta", "Terminal Gama",
  "Praça Delta", "Viaduto Ômega", "Creche Sigma", "Ginásio Lambda", "Avenida Kappa", "Canal Teta", "Parque Zeta",
  "Complexo Esportivo e Cultural do Bairro de Exemplo, 2ª Etapa"];
const dataBR = iso => `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`;
const TODOS_VEEM = ["operacao", "diretoria"], SO_OPERACAO = ["operacao"];
export const avisosEmVolume = publico => (inicio, reg) => {
  const hoje = hojeDaProva();
  const id = i => (i === 0 ? reg.obra : 9000 + i);
  // `dias` com sinal no prazo (negativo = venceu); no fato parado "desde", os dias que ja' passaram
  const base = (i, tipo, nivel, dias, sentido, fato, aba, quem = TODOS_VEEM) => {
    const data = dataEm(hoje, sentido === "desde" ? -dias : dias);
    return { tipo, nivel, natureza: "fato", publico: quem, contrato_id: id(i), obra: OBRAS_DOS_AVISOS[i], dias, valor_centavos: null,
      mensagem: `${OBRAS_DOS_AVISOS[i]}: ${fato(dataBR(data))}`, destino: { tela: "contrato", id: id(i), aba }, data, sentido };
  };
  const daMedicao = (i, aviso) => ({ ...aviso, medicao_id: i === 0 ? reg.medicao : 9100 + i });
  const emDocumentos = aviso => ({ ...aviso, destino: { tela: "documentos" }, entidade_id: reg.empresa });
  // Reajustes
  const semResposta = (i, dias) => base(i, "reajuste_sem_resposta", "acao", dias, "desde", d => `pleito de reajuste sem resposta do órgão desde ${d}`, "reajuste");
  const apostilamento = (i, dias) => base(i, "reajuste_apostilamento", "atencao", dias, "desde", d => `apostilamento do reajuste pendente desde ${d}`, "reajuste");
  // Prazos
  const execucao = (i, dias) => (dias < 0
    ? base(i, "instrumento_pendente", "critico", dias, "prazo", d => `execução vencida em ${d}, sem pedido de prorrogação`, "prazos")
    : base(i, "execucao_vencendo", "atencao", dias, "prazo", d => `execução termina em ${d}`, "prazos", SO_OPERACAO));
  const vigencia = (i, dias) => base(i, "vigencia_vencendo", dias < 0 ? "critico" : "atencao", dias, "prazo",
    d => (dias < 0 ? `vigência vencida em ${d}` : `vigência termina em ${d}`), "prazos", SO_OPERACAO);
  // Garantias: as tres abrem lugares diferentes (Documentos e a aba Prazos da obra) e sao do mesmo assunto
  const garantiaAquem = (i, dias) => emDocumentos(base(i, "garantia_aquem_execucao", dias < 0 ? "critico" : "acao", dias, "prazo",
    d => (dias < 0 ? `garantia venceu em ${d}, antes do fim da execução` : `garantia vence em ${d}, antes do fim da execução`), "prazos"));
  const garantia = (i, dias) => emDocumentos(base(i, "garantia_vencendo", "atencao", dias, "prazo", d => `garantia vence em ${d}`, "prazos"));
  const endosso = (i, dias) => base(i, "endosso_garantia", "atencao", dias, "prazo", d => `endosso do seguro-garantia do 2º aditivo vence em ${d}`,
    "prazos", SO_OPERACAO);
  // Medicoes: o pedido sem boletim, o aprovado abaixo do pedido (os dois com o destino padrao, a aba Medicoes) e a nota
  const medicao = (i, dias) => daMedicao(i, [
    base(i, "pedido_sem_boletim", "acao", dias, "desde", d => `3ª Medição: pedido enviado em ${d} sem boletim do órgão`, "medicoes"),
    base(i, "aprovado_abaixo_do_pedido", "acao", dias, "desde", d => `2ª Medição: aprovado abaixo do pedido desde ${d}`, "medicoes"),
    base(i, "nota_ausente_rm", "atencao", dias, "desde", d => `1ª Medição: nota ainda não confirmada no RM desde ${d}`, "notas", SO_OPERACAO),
  ][i % 3]);
  // Certidoes: da empresa, sem obra
  const certidao = (dias, qual) => {
    const data = dataEm(hoje, dias);
    return { tipo: "documentos_empresa", nivel: dias < 0 ? "critico" : "atencao", natureza: "fato", publico: SO_OPERACAO, contrato_id: null,
      obra: null, dias, valor_centavos: null, entidade_id: reg.empresa, entidade: "Construtora Alfa",
      mensagem: `Construtora Alfa: ${qual} ${dias < 0 ? "vencida" : "vence"} em ${dataBR(data)}`, destino: { tela: "documentos" }, data, sentido: "prazo" };
  };
  // SIGA: o processo parado no orgao
  const siga = (i, dias) => ({ ...base(i, "siga_parado", "acao", dias, "desde", d => `processo ORGAO-PRO-2026/00007 em COFIN sem movimentação desde ${d}`,
    "medicoes", SO_OPERACAO), destino: { tela: "siga", processo: 2 } });
  // os vencidos: de 2 a 6 por obra, o mais antigo de cada uma cada vez mais novo (890, 758, 641... dias)
  const vencidos = OBRAS_DOS_AVISOS.flatMap((_, i) => {
    const maisAntigo = Math.max(12, 890 - i * 66 - (i % 3) * 51);
    return [semResposta(i, maisAntigo),
      ...(i % 2 === 0 ? [execucao(i, -Math.round(maisAntigo / 2))] : [garantiaAquem(i, -Math.round(maisAntigo / 3))]),
      ...(i < 9 ? [apostilamento(i, Math.round(maisAntigo / 4))] : []),
      ...(i < 6 ? [medicao(i, 30 + i * 11)] : []),
      ...(i < 3 ? [vigencia(i, -(8 + i * 5)), semResposta(i, 61 + i * 30)] : [])];
  });
  const agenda = [certidao(0, "certidão estadual"), execucao(3, 0), execucao(5, 4), certidao(5, "certidão do FGTS"), vigencia(0, 7),
    garantia(7, 8), endosso(9, 12), garantia(0, 19), certidao(23, "certidão federal"), vigencia(11, 27), garantiaAquem(12, 30),
    garantia(13, 34), vigencia(6, 45), execucao(8, 60), certidao(72, "certidão trabalhista"), vigencia(10, 88)];
  const fila = [...vencidos, certidao(-18, "certidão municipal"), certidao(-3, "certidão trabalhista"), siga(2, 17), ...agenda];
  return { ...inicio, avisos: fila.filter(a => a.publico.includes(publico)) };
};
export const semAvisos = inicio => ({ ...inicio, avisos: [] });

// Uma resposta que a tela nao sabe desenhar: o Inicio cai e a ultima rede ("A tela parou de responder") aparece.
export const RESPOSTA_QUE_QUEBRA = { medido: null };

// #805, Medicoes como fila de trabalho: o mes cheio que o cadastro de exemplo nao tem (as medicoes dele sao de 2025).
// Medicao com cada um (a Lotufo, o faturamento, o orgao), parada ha' pouco e ha' muito, alem do prazo do orgao e
// dentro dele, com o aprovado abaixo (pouco e muito), acima e igual ao pedido, obra de cinco e de tres passos, medicao
// com o reajuste, concluida e obra sem medicao; nos meses anteriores, o que pede acao e o que so' espera pagamento.
// Obras, medicoes e valores inventados (os links das linhas nao abrem nada no banco da prova). As obras sem medicao e a
// lista de obras da janela "Iniciar" sao as verdadeiras, com mais tres inventadas.
const NOMES_DOS_PASSOS = ["Planilha e carta", "Análise do órgão", "Espelhos", "Notas", "Envio da nota", "Pagamento"];
const paradaDaFila = (dias, situacao, x = {}) => ({
  desde: dias === null ? null : dataEm(hojeDaProva(), -Math.round(dias * 1.4)), dias_uteis: dias, hoje: dias === 0, situacao,
  prazo_orgao_dias: x.prazo ?? null, esperada: x.esperada === undefined ? null : dataEm(hojeDaProva(), x.esperada), alem_do_prazo: (x.esperada ?? 1) < 0,
});
const comparadosDaFila = (pedido, aprovado) => {
  const p = pedido === null ? null : pedido * REAIS, a = aprovado === null ? null : aprovado * REAIS, ha = p !== null && a !== null;
  return { pedido_centavos: p, aprovado_centavos: a, aprovado_com_pedido_centavos: ha ? a : null, pedido_do_aprovado_centavos: ha ? p : null,
    abaixo_do_pedido_centavos: ha ? Math.max(0, p - a) : null, acima_do_pedido_centavos: ha ? Math.max(0, a - p) : null };
};
const linhaDaFila = (reg, n, obra, titulo, quem, tem, atual, parada, pedido, aprovado, x = {}) => ({
  contrato_id: 9100 + n, obra, contratante: x.contratante ?? "SINFRA", orgao_sub: x.sub === undefined ? "SUEF II" : x.sub,
  medicao_id: reg.medicao + n * 1000, medicao_ids: [reg.medicao + n * 1000], titulo, competencia: x.competencia ?? competenciaHa(1), com_quem: quem,
  passo: { numero: atual, nome: NOMES_DOS_PASSOS[atual - 1], posicao: tem.indexOf(atual) + 1, total: tem.length },
  passos: tem.map(p => ({ numero: p, nome: NOMES_DOS_PASSOS[p - 1], situacao: p < atual ? "feito" : p === atual ? "atual" : "futuro" })),
  parada, ...comparadosDaFila(pedido, aprovado), acao: x.acao ?? null,
});
const SEIS = [1, 2, 3, 4, 5, 6], CINCO = [2, 3, 4, 5, 6], TRES = [3, 4, 6];
const somaDaFila = linhas => {
  const soma = k => { const v = linhas.map(l => l[k]).filter(x => x !== null); return v.length ? v.reduce((a, b) => a + b, 0) : null; };
  return { pedido_centavos: soma("pedido_centavos"), aprovado_centavos: soma("aprovado_centavos"),
    aprovado_com_pedido_centavos: soma("aprovado_com_pedido_centavos"), pedido_do_aprovado_centavos: soma("pedido_do_aprovado_centavos"),
    abaixo_do_pedido_centavos: soma("abaixo_do_pedido_centavos") };
};
export const filaSimulada = (resposta, reg) => {
  const mtpar = { contratante: "MTPAR", sub: null };
  const lotufo = [
    linhaDaFila(reg, 1, "Maternidade Alfa", "5ª Medição", "lotufo", CINCO, 3, paradaDaFila(12, "critico"), 170_000, 170_000,
      { acao: "gerar_espelho", contratante: "Pref. Várzea Grande", sub: null }),
    linhaDaFila(reg, 2, "Corredor Beta", "12ª Medição + Reajuste", "lotufo", SEIS, 5, paradaDaFila(6, "breve"), 1_700_000, 1_600_000, { acao: "enviar_nota", sub: "SUPU" }),
    linhaDaFila(reg, 3, "Estações Gama", "6ª Medição", "lotufo", SEIS, 3, paradaDaFila(4, "andamento"), 8_000_000, 7_990_000, { acao: "enviar_espelho", sub: "SUPU" }),
    linhaDaFila(reg, 4, "Terminais Delta", "3ª Medição de Projeto", "lotufo", SEIS, 1, paradaDaFila(0, "feito"), 1_000_000, null, { acao: "enviar_planilha" }),
    linhaDaFila(reg, 5, "Trevo Eta", "9ª Medição", "lotufo", CINCO, 2, paradaDaFila(null, null), 300_000, null, { acao: "registrar_boletim", ...mtpar }),
  ];
  const faturamento = [
    linhaDaFila(reg, 6, "Quartel Delta", "8ª Medição", "faturamento", SEIS, 4, paradaDaFila(7, "breve"), 600_000, 600_100),
    linhaDaFila(reg, 7, "Anel Teta", "11ª Medição", "faturamento", CINCO, 4, paradaDaFila(1, "andamento"), 2_000_000, 2_000_000, mtpar),
  ];
  const orgao = [
    linhaDaFila(reg, 8, "Bairros Épsilon", "14ª Medição", "orgao", SEIS, 6, paradaDaFila(41, "critico", { prazo: 45, esperada: -9 }), 200_000, 200_000, { sub: "SUPU" }),
    linhaDaFila(reg, 9, "Rodovia Capa", "29ª Medição", "orgao", SEIS, 2, paradaDaFila(11, "critico"), 800_000, null),
    linhaDaFila(reg, 10, "Avenida Alfa", "11ª Medição", "orgao", SEIS, 2, paradaDaFila(5, "breve"), 4_000_000, null),
    linhaDaFila(reg, 11, "Complexo Lambda", "10ª Medição + Reajuste", "orgao", CINCO, 6, paradaDaFila(4, "andamento", { prazo: 45, esperada: 39 }), 2_000_000, 2_000_000, mtpar),
    linhaDaFila(reg, 12, "Praça Mi", "2ª Medição", "orgao", TRES, 6, paradaDaFila(3, "andamento"), 80_000, 80_000, { contratante: "Pref. Cuiabá", sub: null }),
  ];
  const doMes = [...lotufo, ...faturamento, ...orgao];
  const contar = ls => ({ quantidade: ls.length, criticas: ls.filter(l => l.parada.situacao === "critico").length,
    breves: ls.filter(l => l.parada.situacao === "breve").length, alem_do_prazo: ls.filter(l => l.parada.alem_do_prazo).length });
  const concluidas = [
    { contrato_id: reg.obra, obra: "Ponte Ni", medicao_id: reg.medicao, titulo: "8ª Medição", recebida_em: dataEm(hojeDaProva(), -8) },
    { contrato_id: reg.obra, obra: "Rodovia Csi", medicao_id: reg.medicao + 500, titulo: "15ª Medição", recebida_em: dataEm(hojeDaProva(), -2) },
  ];
  const semMedicao = [...resposta.sem_medicao,
    ...["Orla Iota", "Hospital Ômicron", "Travessia Zeta"].map((obra, i) => ({ contrato_id: 9900 + i, obra, contratante: "SINFRA" }))];
  // o quadro: as mesmas medicoes, uma linha por obra, agrupadas pelo contratante
  const noQuadro = l => ({
    contrato_id: l.contrato_id, obra: l.obra, contratante: l.contratante, orgao_sub: l.orgao_sub, medicoes: [{ id: l.medicao_id, titulo: l.titulo }],
    iniciar: false, pedido_centavos: l.pedido_centavos, aprovado_centavos: l.aprovado_centavos,
    aprovado_com_pedido_centavos: l.aprovado_com_pedido_centavos, pedido_do_aprovado_centavos: l.pedido_do_aprovado_centavos,
    abaixo_do_pedido_centavos: l.abaixo_do_pedido_centavos, acima_do_pedido_centavos: l.acima_do_pedido_centavos,
    passos: l.passos.map(p => ({ ...p, data: p.situacao === "feito" ? dataEm(hojeDaProva(), -30 + p.numero * 3) : null,
      medicao_id: p.situacao === "atual" ? l.medicao_id : null, parada: p.situacao === "atual" ? l.parada : null,
      siga: p.situacao === "atual" && p.numero === 2 && l.parada.dias_uteis === 11
        ? { processo_id: 1, setor: "SUPE", dias_uteis: 6, desde: "2026-10-20T10:00:00-04:00", hoje: 0,
          dias_sem_movimentacao: 6, ultima_em: "2026-10-20T10:00:00-04:00", situacao_tempo: "breve" } : null })),
  });
  const contratantes = [...new Set(doMes.map(l => l.contratante))];
  const quadro = contratantes.map(c => { const ls = doMes.filter(l => l.contratante === c); return { contratante: c, ...somaDaFila(ls), linhas: ls.map(noQuadro) }; })
    .sort((a, b) => b.linhas.length - a.linhas.length);
  const anteriores = [
    linhaDaFila(reg, 13, "Corredor Beta", "9ª Medição", "lotufo", SEIS, 5, paradaDaFila(19, "critico"), 1_500_000, 1_450_000,
      { acao: "enviar_nota", sub: "SUPU", competencia: competenciaHa(2) }),
    linhaDaFila(reg, 14, "Trevo Eta", "8ª Medição", "faturamento", CINCO, 4, paradaDaFila(8, "breve"), 300_000, 300_000, { ...mtpar, competencia: competenciaHa(2) }),
    linhaDaFila(reg, 15, "Rodovia Capa", "27ª Medição", "orgao", SEIS, 2, paradaDaFila(33, "critico"), 600_000, null, { competencia: competenciaHa(3) }),
  ];
  return {
    ...resposta,
    numeros: { com: { lotufo: contar(lotufo), faturamento: contar(faturamento), orgao: contar(orgao) }, concluidas: concluidas.length,
      sem_medicao: semMedicao.length, ...somaDaFila(doMes) },
    grupos: [{ com_quem: "lotufo", linhas: lotufo }, { com_quem: "faturamento", linhas: faturamento }, { com_quem: "orgao", linhas: orgao }],
    concluidas, sem_medicao: semMedicao, quadro,
    anteriores: { linhas: anteriores, esperam_pagamento: 17, antes_do_ano_inicial: 4, ano_inicial: "2025" },
  };
};

// ------------------------------------------------------------------ caminho no alto (#814)
// O cabecalho da obra com nomes compridos, como os da producao: o contratante escrito por extenso e a obra com o
// trecho e o lote no nome. O caminho do topo ("Obras › contratante › obra › Medições › 15ª Medição") tem de quebrar
// em linhas a 390 px em vez de cortar ou de alargar a pagina. Nomes inventados.
export const cabecalhoDeNomeLongo = cabecalho => ({
  ...cabecalho,
  contratante: "Secretaria de Estado de Infraestrutura e Logística",
  obra: "Rodovia Exemplo, trecho do entroncamento ao distrito, lote 2",
});

// ---- Tela de login (#821): o que o servidor responde a quem tenta entrar. Simuladas porque a recusa de verdade
// conta no limite de tentativas por computador, e a prova ja' entra uma vez por perfil e largura.
export const LOGIN_RECUSADO = { detail: "E-mail ou senha inválidos, ou usuário bloqueado" };
export const LOGIN_NO_LIMITE = { detail: "Muitas tentativas de entrar a partir deste computador. Tente de novo em alguns minutos." };

// ---- A receber (#816): o em aberto nota a nota com o que o cadastro de exemplo nao tem. Quatro contratantes com
// linhas (um de nome comprido e sem pagina, sem orgao no cadastro) e um sem nada em aberto, que fica na fileira com
// zero; valores de nove e dez digitos; tempo parado em cada leitura (alem do prazo do orgao, dentro dele, sem prazo,
// protocolo de hoje), o repasse sem baixa, a paga em parte, a medicao sem nota e a nota sem protocolo; a' parte, duas
// notas sem medicao e o em aberto antigo. O subtotal, o total e o de cada ano sao somados aqui como o servidor soma,
// para a tela receber numeros que fecham. `vazio`: nada em aberto (a fileira so' com zeros); `trava`: o total a
// receber nao liberado. Tudo inventado.
const AR_ANOS = ["2025", "2026"];
const arParada = (desde, dias, situacao, esperada = null, prazo = null) => ({
  desde, dias_uteis: dias, hoje: dias === 0, situacao, prazo_orgao_dias: prazo, esperada, alem_do_prazo: situacao === "critico" });
const arGrupo = (contratante, chave, prazo, linhas = [], extra = {}) => {
  const por_ano = Object.fromEntries(AR_ANOS.map(a => [a, linhas.filter(l => l.competencia.startsWith(a)).reduce((t, l) => t + l.valor_centavos, 0)]));
  const soltas = extra.notas_sem_medicao ?? [];
  return { contratante, chave, prazo_orgao_dias: prazo, quantidade: linhas.length, em_aberto_centavos: linhas.reduce((t, l) => t + l.valor_centavos, 0),
    por_ano, alem_do_prazo: linhas.filter(l => l.parada?.alem_do_prazo).length, linhas, notas_sem_medicao: soltas,
    notas_sem_medicao_centavos: soltas.reduce((t, n) => t + n.valor_centavos, 0), anteriores: { quantidade: 0, valor_centavos: 0 }, ...extra };
};
export const aReceberComNotas = ({ vazio = false, trava = false } = {}) => reg => {
  if (trava) return { anos: AR_ANOS, total_a_receber_liberado: false };
  let id = 9800;
  const l = (obra, competencia, protocolo, valor, parada, extra = {}) => {
    id += 1;
    return { tipo_aberto: "nota", nota_id: id, numero: String(41000 + id), valor_centavos: valor, paga_em_parte: false, contrato_id: reg.obra,
      obra, medicao_id: id === 9801 ? reg.medicao : id, medicao_numero: 3 + (id % 20), tipo: "execucao", competencia, protocolo_em: protocolo,
      emitida_em: null, parada, orgao_pagou_em: null, ...extra };
  };
  const hoje = dataEm(hojeDaProva());
  const grupos = vazio ? [arGrupo("SINFRA", "sinfra", 52), arGrupo("SES-MT", "ses-mt", null)] : [
    arGrupo("SINFRA", "sinfra", 52, [
      l("Rodovia Alfa", "2026-05", "2026-06-10", 412_345_678_90, arParada("2026-06-10", 112, "critico", "2026-08-01", 52)),
      l("Avenida Beta", "2026-07", "2026-08-04", 98_765_432_10, arParada("2026-08-04", 74, "critico", "2026-09-25", 52), { paga_em_parte: true }),
      l("Rodovia Alfa", "2026-08", "2026-09-15", 205_000_000_00, arParada("2026-09-15", 46, "andamento", "2026-11-06", 52), { tipo: "reajuste" }),
      l("Ponte Gama", "2026-09", "2026-10-06", 31_250_000_01, arParada("2026-10-06", 31, "andamento", "2026-11-27", 52)),
      l("Corredor Delta", "2026-09", "2026-10-20", 7_000_000_03, arParada("2026-10-20", 21, "andamento", "2026-12-11", 52),
        { tipo_aberto: "sem_nota", nota_id: null, numero: null }),
      l("Avenida Beta", "2026-10", hoje, 64_800_000_00, arParada(hoje, 0, "feito", null, 52)),
    ]),
    arGrupo("MTPAR", "mtpar", 38, [
      l("Trevo Épsilon", "2025-11", "2025-12-15", 150_000_000_00, arParada("2025-12-15", 230, "critico", "2026-01-22", 38)),
      l("Trevo Épsilon", "2026-08", "2026-09-01", 55_555_555_55, arParada("2026-09-01", 55, "andamento", "2026-10-09", 38)),
      l("Viaduto Zeta", "2026-09", "2026-10-02", 12_000_000_00, null, { tipo_aberto: "repasse", orgao_pagou_em: "2026-11-03" }),
    ]),
    arGrupo("Pref. Várzea Grande", "pref-vg", null, [
      l("Escola Eta", "2026-09", null, 3_333_333_33, arParada("2026-10-14", 25, "andamento"), { emitida_em: "2026-10-14" }),
    ], { notas_sem_medicao: [{ nota_id: 9890, numero: "41990", contrato_id: reg.obra, obra: "Escola Eta", emissao: "2026-07-01",
      valor_centavos: 1_777_777_77, paga_em_parte: false, ligada_a_medicao_nao_enviada: false }], anteriores: { quantidade: 2, valor_centavos: 4_000_000_00 } }),
    arGrupo("Secretaria Municipal de Infraestrutura e Obras de Exemplo do Norte", null, null, [
      l("Requalificação urbana do corredor central, trecho do terminal ao distrito industrial, lote 3", "2026-06", "2026-07-08", 23_456_789_01,
        arParada("2026-07-08", 94, "andamento")),
    ], { notas_sem_medicao: [{ nota_id: 9891, numero: "41991", contrato_id: reg.obra, obra: "Requalificação urbana do corredor central",
      emissao: null, valor_centavos: 890_000_00, paga_em_parte: true, ligada_a_medicao_nao_enviada: true }] }),
    arGrupo("SES-MT", "ses-mt", null),
  ];
  const lista = grupos.sort((a, b) => b.em_aberto_centavos - a.em_aberto_centavos || porNome(a.contratante, b.contratante));
  const soma = k => lista.reduce((t, g) => t + g[k], 0);
  return { anos: AR_ANOS, total_a_receber_liberado: true, em_aberto_centavos: soma("em_aberto_centavos"),
    por_ano: Object.fromEntries(AR_ANOS.map(a => [a, lista.reduce((t, g) => t + g.por_ano[a], 0)])), quantidade: soma("quantidade"),
    alem_do_prazo: soma("alem_do_prazo"), notas_sem_medicao_centavos: soma("notas_sem_medicao_centavos"),
    notas_sem_medicao: lista.flatMap(g => g.notas_sem_medicao).sort((a, b) => (a.emissao ?? "9999").localeCompare(b.emissao ?? "9999")),
    anteriores: { quantidade: lista.reduce((t, g) => t + g.anteriores.quantidade, 0),
      valor_centavos: lista.reduce((t, g) => t + g.anteriores.valor_centavos, 0) },
    contratantes: lista };
};

// ---- Documentos em tres paginas (#820): o painel sem empresa, sem obra e sem nada a renovar (cada pagina mostra o
// estado vazio dela)
export const DOCUMENTOS_VAZIO = { hoje: "2026-09-23", empresas: [], contratos: [], renovar_agora: [] };

// ---- Busca unica do topo (#819): GET /api/busca com os tres grupos, nomes compridos e o grupo de medicoes cortado
// (8 de 23), e a resposta sem nada. Obras, orgaos e numeros inventados. O perfil sem SIGA nao recebe `processos`: a
// prova da diretoria usa o servidor de verdade (o recorte e' dele), nao esta resposta.
const medicaoAchada = (id, contrato_id, titulo, competencia, obra, contratante) => ({ id, contrato_id, titulo, competencia, obra, contratante });
const OBRA_LONGA = "Rodovia Exemplo, trecho do entroncamento ao distrito, lote 2";
export const BUSCA_CHEIA = {
  obras: { total: 2, itens: [
    { id: 1, nome: OBRA_LONGA, contratante: "SINFRA", orgao_sub: "SUEF II" },
    { id: 2, nome: "Corredor Beta", contratante: "Pref. Cuiabá", orgao_sub: null },
  ] },
  medicoes: { total: 23, itens: [
    medicaoAchada(11, 1, "15ª Medição", "2026-10", OBRA_LONGA, "SINFRA"),
    medicaoAchada(12, 1, "Reajuste da 15ª Medição", "2026-10", OBRA_LONGA, "SINFRA"),
    medicaoAchada(13, 2, "15ª Medição", "2026-09", "Corredor Beta", "Pref. Cuiabá"),
    medicaoAchada(14, 3, "15ª Medição de Projeto", "2026-07", "Trevo Eta", "MTPAR"),
    medicaoAchada(15, 4, "15ª Medição", "2026-05", "Rodovia Capa", "SINFRA"),
    medicaoAchada(16, 5, "15ª Medição", "2026-02", "Ponte Gama", "SES-MT"),
    { ...medicaoAchada(17, 6, "15ª Medição", "2025-12", "Escola Delta", "MTPAR"), estado: "cancelada" },
    { ...medicaoAchada(18, 7, "15ª Medição", "2025-09", "Anel Viário Zeta", "SINFRA"), estado: "prevista" },
  ] },
  processos: { total: 2, itens: [
    { id: 1, numero: "ORGAO-PRO-2026/00015", assunto: `${OBRA_LONGA} · 15ª Medição` },
    { id: 2, numero: null, assunto: "Corredor Beta · Pedido de paralisação" },
  ] },
};
export const BUSCA_VAZIA = { obras: { itens: [], total: 0 }, medicoes: { itens: [], total: 0 }, processos: { itens: [], total: 0 } };

// ---- As abas da pagina do contratante (#818): o recorte da SINFRA que o servidor manda de cada tela
// (`app/contratante.py`), tirado das respostas simuladas das telas de onde ele vem, para a aba ter o volume que o
// cadastro de exemplo nao tem. Obras, notas, processos e valores inventados, como os de la'.

/** As abas dos contratantes da carteira simulada que o cadastro de exemplo nao tem (o servidor responde 404 a' chave
 *  que nenhuma obra tem): vazias, como o servidor manda ao contratante sem nada na aba. A SINFRA e' do cadastro de
 *  exemplo e fica com o servidor de verdade. */
const OUTROS_DA_CARTEIRA = "(mtpar|pref-cuiaba|ses-mt)";
export const ABAS_DA_CARTEIRA = [
  { caminho: new RegExp(`^/api/contratantes/${OUTROS_DA_CARTEIRA}/medicoes$`), corpo: () => ({ hoje: dataEm(hojeDaProva()), mes: competenciaHa(1),
    limites: { dias_atencao: 5, dias_critico: 10, diferenca_critica_por_mil: 5 }, grupos: [], concluidas: [], sem_medicao: [], quantidade: 0 }) },
  { caminho: new RegExp(`^/api/contratantes/${OUTROS_DA_CARTEIRA}/a-receber$`),
    corpo: { anos: AR_ANOS, total_a_receber_liberado: true, contratante: null, quantidade: 0 } },
  { caminho: new RegExp(`^/api/contratantes/${OUTROS_DA_CARTEIRA}/siga$`), corpo: { lido_em: null, limites: { dias_atencao: 5, dias_critico: 10 },
    robo: { estado: "parado", rodada: null, pedidos: [], avisos: [] }, processos: [], quantidade: 0, sem_obra: 0 } },
];

/** Medicoes: as linhas da SINFRA na fila simulada (`filaSimulada`), as concluidas no mes e as obras sem medicao. */
export const medicoesDoContratante = (resposta, reg) => {
  const f = filaSimulada({ ...resposta, sem_medicao: resposta.sem_medicao ?? [] }, reg);
  const daSinfra = l => l.contratante === "SINFRA";
  const grupos = f.grupos.map(g => ({ ...g, linhas: g.linhas.filter(daSinfra) })).filter(g => g.linhas.length > 0);
  const sem_medicao = f.sem_medicao.filter(daSinfra);
  return { hoje: resposta.hoje, mes: resposta.mes, limites: resposta.limites, grupos, concluidas: f.concluidas, sem_medicao,
    quantidade: grupos.reduce((t, g) => t + g.linhas.length, 0) + f.concluidas.length };
};

/** Em aberto: o grupo de um contratante na pagina Em aberto simulada (`aReceberComNotas`). `de`: a chave do grupo
 *  tirado de la'; `como`: o nome e a chave com que ele vem (o contratante da carteira simulada que a pagina abre). */
export const aReceberDoContratante = ({ trava = false, de = "sinfra", como = null } = {}) => reg => {
  const r = aReceberComNotas({ trava })(reg);
  if (trava) return r;
  const g = r.contratantes.find(x => x.chave === de);
  const grupo = como ? { ...g, contratante: como[0], chave: como[1] } : g;
  return { anos: r.anos, total_a_receber_liberado: true, contratante: grupo, quantidade: grupo.quantidade };
};

/** Processos no SIGA: os vivos da SINFRA no SIGA simulado, do mais parado para o menos, com o "nao lido" deles. */
const doMaisParado = (a, b) => (b.dias_sem_movimentacao ?? -1) - (a.dias_sem_movimentacao ?? -1)
  || (a.ultima?.data ?? "9").localeCompare(b.ultima?.data ?? "9") || a.id - b.id;
const PROCESSOS_DA_SINFRA = SIGA_COM_NAO_LIDOS.processos.filter(p => p.contratante === "SINFRA" && !p.encerrado).sort(doMaisParado);
export const SIGA_DO_CONTRATANTE = {
  lido_em: SIGA_COM_NAO_LIDOS.lido_em, limites: SIGA_COM_NAO_LIDOS.limites,
  robo: { ...SIGA_COM_NAO_LIDOS.robo, avisos: SIGA_COM_NAO_LIDOS.robo.avisos.filter(a => PROCESSOS_DA_SINFRA.some(p => p.id === a.processo_id)) },
  processos: PROCESSOS_DA_SINFRA, quantidade: PROCESSOS_DA_SINFRA.length,
  // #845: os vivos do SIGA simulado sem obra ligada, o total da tela SIGA (de nenhum contratante)
  sem_obra: SIGA_COM_NAO_LIDOS.processos.filter(p => p.contrato_id == null && !p.encerrado).length,
};

// ---- Peca "inicio" da reestrutura (19/11/2026, decisao do dono na #805): a matriz obra por competencia (#659) saiu
// da Inicio para a aba "Últimos 12 meses" do Resumo das medicoes (GET /api/resumo-medicoes/matriz). O cadastro de
// exemplo tem poucas obras e quase nenhuma medicao; aqui a matriz ganha o volume da carteira: cinco contratantes
// ficticios (um de nome longo), cinco obras cada (uma de nome longo), e as etapas em rodizio fixo, com meses vazios.
// Nao tem valor: so' a etapa de cada mes. As competencias sao as da resposta do servidor (as 12 ultimas fechadas).
const MATRIZ_CONTRATANTES = ["Autarquia Beta", "MTPAR", "Prefeitura Alfa", "SINFRA",
  "Secretaria de Estado de Infraestrutura e Logística de Exemplo"];
const MATRIZ_RODIZIO = ["recebida", "recebida", "protocolado", "atrasado", null, "nota", "boletim", "em_analise"];
export const matrizEmVolume = resposta => ({
  competencias: resposta.competencias,
  grupos: MATRIZ_CONTRATANTES.map((contratante, g) => ({ contratante, obras: [0, 1, 2, 3, 4].map(o => {
    const id = 9500 + g * 10 + o;
    return { contrato_id: id,
      obra: o === 4 ? `Restauração e Pavimentação da Rodovia de Exemplo, Trecho ${g + 1}` : `Obra ${String.fromCharCode(65 + g)}${o + 1}`,
      celulas: resposta.competencias.map((_, i) => {
        // as obras mais novas comecam no meio da janela; a ultima competencia fica mais atras no ciclo
        if (i < o * 2) return null;
        const etapa = i === 11 ? ["em_analise", "boletim", "nota", null, "protocolado"][o] : MATRIZ_RODIZIO[(i + g + o) % MATRIZ_RODIZIO.length];
        return etapa && { etapa, medicao_id: id * 100 + i };
      }) };
  }) })),
});
export const matrizVazia = resposta => ({ competencias: resposta.competencias, grupos: [] });

// ---- Criterio de encerramento do SIGA (#841): o processo sobrestado (a palavra no lugar dos dias, sem cor), o de
// Medicoes sem medicao com a proposta do servidor ("medição a ligar"), e nos Encerrados o juntado e o encerrado a' mao
// (motivo, quem e quando, com "Reabrir"). Obras, numeros e pessoa inventados.
const PROCESSOS_DO_ENCERRAMENTO = [
  ...PROCESSOS_DO_SIGA,
  { ...processo({ id: 20, nome: "Processo Sobrestado", numero: "ORGAO-PRO-2026/00050", contrato_id: 2, obra: "Obra Própria", ...sinfra,
    categoria: "aditivos", complemento: "de valor", o_que_e: "Aditivo de valor", dias_uteis: 30, dias_sem_movimentacao: 30,
    situacao: "1º Volume - Aguardando Andamento [PROTOC, [Y]] | 2º Volume - Sobrestado [GEFOR, [X]]", setor: "GEFOR" }),
  situacao_tempo: "sobrestado" },
  processo({ id: 21, nome: "9ª Medição - Obra Consórcio - IC 001/2026 (ORGAO-PRO-2026/00051)", numero: "ORGAO-PRO-2026/00051",
    categoria: "medicoes", categoria_sugerida: true, o_que_e: "Medição", dias_uteis: 4,
    medicao_proposta: { id: 3, contrato_id: 1, titulo: "9ª Medição", obra: "Obra Consórcio", estado: "recebida" } }),
  processo({ id: 22, nome: "Processo Juntado", numero: "ORGAO-PRO-2026/00052", contrato_id: 1, obra: "Obra Consórcio", ...sinfra,
    categoria: "aditivos", complemento: "de prazo", o_que_e: "Aditivo de prazo", encerrado: "juntado", dias_uteis: 9,
    situacao: "1º Volume - Juntado [PROTOC, [X]]", setor: "PROTOC" }),
  processo({ id: 23, nome: "Processo Encerrado à Mão", numero: "ORGAO-PRO-2026/00053", contrato_id: 9012, obra: "Ponte Mi", ...sinfra,
    categoria: "indenizatorios", o_que_e: "Indenizatório", encerrado: "manual", dias_uteis: 15,
    encerramento: { motivo: "indenizatório pago", por: "Pessoa de teste", em: "2026-10-27T14:00:00+00:00" } }),
];
export const SIGA_ENCERRAMENTO = painelDoSiga(PROCESSOS_DO_ENCERRAMENTO);

// a medicao da prova com o processo do SIGA arquivado (o pleito): a pendencia do protocolo novo no alto da pagina
export const medicaoComProtocoloNovo = (medicoes, reg) => medicoes.map(m => (m.id === reg.medicao
  ? { ...m, siga_protocolo_novo: true } : m));

// ---- Licitacoes (#908): a Triagem e as Favoritas com o que o cadastro de exemplo nao tem (o banco da prova nunca
// recebeu leitura do radar). Orgaos, editais, objetos, valores e pastas inventados; o CNPJ das chaves e' o ficticio de
// digito valido. As datas saem do dia da prova, e os dias uteis e a situacao de cada prazo vem escritos, como o
// servidor os manda: a tela so' desenha.
const licDia = dias => dataEm(hojeDaProva(), dias);
// `passado` e' do servidor, pela data (nunca pelo sinal dos dias uteis): aqui, o prazo de antes do dia da prova
const licPrazo = (codigo, rotulo, dias, diasUteis, situacao, extra = {}) => ({
  codigo, rotulo, data: licDia(dias), hora: null, aviso: "", dias_uteis: diasUteis, passado: dias < 0, hoje: dias === 0, situacao, ...extra });
const licFavorita = (etapa, etapaRotulo, prazos, extra = {}) => ({
  desde: licDia(-12), etapa, etapa_rotulo: etapaRotulo, etapa_do_dossie: false, dossie: null, selos: [], prazos,
  proximo_prazo: prazos.find(p => !p.passado) ?? null, mudancas: [],
  mudancas_novas: (extra.mudancas ?? []).filter(m => !m.vista).length, ...extra });
// `chave`: a identidade que o servidor da' a' mudanca; `vista`: alguem ja' a marcou como vista (so' depois do corte)
const licMudanca = (dias, rotulo, texto, vista = false) => ({ chave: `${licDia(dias)}-${rotulo}`, data: licDia(dias), texto, rotulo, vista });
const licRecomendada = (nota, motivo, cidade, km) => ({ nota, pontos: { valor: 3, distancia: 2, acervo: nota - 5 }, motivo, km, cidade });
const licitacao = (n, extra = {}) => comSessaoHoje({
  id: n, chave: `11444777000161-1-${String(n).padStart(6, "0")}/2026`, orgao: "Prefeitura Municipal de Vila Exemplo", sigla_orgao: "",
  grupo_orgao: "Outros órgãos", orgao_de_interesse: false, esfera: "Municipal", municipio: "Vila Exemplo", uf: "MT", cidade: "Vila Exemplo",
  km: 120, edital: `CE ${String(n).padStart(3, "0")}/2026`, modalidade: "Concorrência", objeto: "Pavimentação asfáltica e drenagem de vias urbanas",
  tipo_obra: "Pavimentação", valor_centavos: 1234567890, valor_rotulo: "", situacao: "Divulgada no PNCP", data_publicacao: licDia(-14),
  data_sessao: licDia(16), hora_sessao: "09:00", primeira_vez: licDia(-13), link: `https://exemplo.com.br/editais/${n}`, portal: "Site do órgão",
  fontes: ["PNCP"], recomendada: null, dias_uteis: 12, prazo: "breve", encerrada: false, favorita: null, ...extra });
// `sessao_hoje` e' do servidor, pela data: aqui, a sessao no dia da prova
const comSessaoHoje = l => ({ ...l, sessao_hoje: l.data_sessao === licDia(0) });
const SEOBRAS = { orgao: "Secretaria de Obras de Exemplo", sigla_orgao: "SEOBRAS-EX", grupo_orgao: "SEOBRAS-EX", orgao_de_interesse: true, esfera: "Estadual" };
const DER = { orgao: "Departamento de Estradas de Exemplo", sigla_orgao: "DER-EX", grupo_orgao: "DER-EX", orgao_de_interesse: true, esfera: "Estadual" };

// as favoritas, na ordem do servidor: as em aberto pela sessao mais proxima (sem data, no fim); as encerradas depois.
// De tudo um pouco: a etapa do dossie com os selos dele, tres prazos (um com o aviso de data diferente no dossie),
// quatro mudancas (a tela mostra tres e conta o resto), a sessao de hoje, a sem data e sem link, o valor sigiloso e o
// valor com o rotulo de onde veio; encerradas, uma vencida e uma perdida com o dossie descartado.
const licFavoritas = () => [
  licitacao(3, { objeto: "Construção de unidade escolar com doze salas de aula, quadra coberta e urbanização do entorno, no distrito de Serra Alfa",
    tipo_obra: "Edificação", valor_centavos: 234567890, valor_rotulo: "valor do lote 2", data_sessao: licDia(0), hora_sessao: "14:30", dias_uteis: 0,
    prazo: "critico", favorita: licFavorita("acompanhando", "Acompanhando", [licPrazo("sessao", "Sessão", 0, 0, "critico", { hora: "14:30" })],
      { mudancas: [licMudanca(-1, "Esclarecimento publicado", "publicou resposta a pedido de esclarecimento")] }) }),
  licitacao(12, { ...SEOBRAS, objeto: "Duplicação de rodovia estadual, trecho do entroncamento ao distrito industrial", tipo_obra: "Rodovia",
    valor_centavos: 4875000000, favorita: licFavorita("em_analise", "Em análise", [
        licPrazo("esclarecimento", "Esclarecimento", 3, 3, "critico"), licPrazo("impugnacao", "Impugnação", 8, 6, "breve"),
        licPrazo("sessao", "Sessão", 16, 12, "breve", { hora: "09:00", aviso: `dossiê diz ${dataBR(licDia(17))}, conferir` })],
      { etapa_do_dossie: true, dossie: "2026-CE-012-exemplo-duplicacao", selos: ["Diretoria: interesse"], mudancas: [
        licMudanca(-4, "Sessão adiada", "publicou adiamento"), licMudanca(-6, "Novo anexo", "anexou a planilha orçamentária"),
        licMudanca(-7, "Esclarecimento publicado", "publicou resposta a pedido de esclarecimento", true),
        licMudanca(-10, "Edital retificado", "publicou errata", true)] }) }),
  licitacao(7, { ...DER, objeto: "Restauração de pavimento em rodovia estadual", valor_centavos: null, valor_rotulo: "sigiloso",
    data_sessao: licDia(97), hora_sessao: null, dias_uteis: 65, prazo: null,
    favorita: licFavorita("proposta_enviada", "Proposta enviada", [licPrazo("sessao", "Sessão", 97, 65, null)]) }),
  licitacao(21, { edital: "", modalidade: "Concorrência", link: "", objeto: "Reforma e ampliação do terminal rodoviário", tipo_obra: "Edificação",
    valor_centavos: null, valor_rotulo: "sem valor", data_sessao: null, hora_sessao: null, dias_uteis: null, prazo: null,
    favorita: licFavorita("acompanhando", "Acompanhando", [], { etapa_do_dossie: true, dossie: "2026-CE-021-exemplo-terminal",
      selos: ["Suspensa", "Diretoria: interesse"], mudancas: [licMudanca(-2, "Licitação suspensa", "publicou a suspensão")] }) }),
  licitacao(2, { ...SEOBRAS, objeto: "Construção de ponte de concreto sobre o Rio Modelo", tipo_obra: "Obra de arte especial",
    valor_centavos: 987654321, data_sessao: licDia(-19), dias_uteis: -13, prazo: null, encerrada: true, situacao: "Homologada",
    favorita: licFavorita("vencida", "Vencida", [licPrazo("sessao", "Sessão", -19, -13, null, { hora: "09:00" })],
      { mudancas: [licMudanca(-5, "Resultado publicado", "publicou a homologação")] }) }),
  licitacao(5, { ...DER, objeto: "Implantação e pavimentação de rodovia, lote 3", valor_centavos: 15600000000, data_sessao: licDia(-33),
    dias_uteis: -22, prazo: null, encerrada: true, situacao: "Homologada",
    favorita: licFavorita("perdida", "Perdida", [licPrazo("sessao", "Sessão", -33, -22, null, { hora: "10:00" })],
      { etapa_do_dossie: true, dossie: "2026-CE-005-exemplo-rodovia", selos: ["Diretoria: descartada"] }) }),
];

// as recomendadas, da nota maior para a menor: com e sem valor, com e sem sessao, sem link, sem distancia e sem local,
// e o objeto e o motivo compridos
const licRecomendadas = () => [
  licitacao(31, { ...SEOBRAS, objeto: "Pavimentação de rodovia estadual, com obras de arte correntes", tipo_obra: "Rodovia", valor_centavos: 12340000000,
    data_sessao: licDia(4), dias_uteis: 3, prazo: "critico",
    recomendada: licRecomendada(9, "concorrência · R$ 123,4 mi · Porto Modelo · 85 km · 3 atestados", "Porto Modelo", 85) }),
  licitacao(32, { objeto: "Construção de hospital municipal com cento e vinte leitos, centro cirúrgico, unidade de terapia intensiva e central de material esterilizado",
    tipo_obra: "Edificação", valor_centavos: 8765432100, recomendada: licRecomendada(8,
      "concorrência · R$ 87,7 mi · Vila Exemplo · 120 km · 2 atestados de edificação hospitalar e 1 de instalações especiais", "Vila Exemplo", 120) }),
  licitacao(33, { ...DER, link: "", objeto: "Recuperação de pontes de madeira", tipo_obra: "Obra de arte especial", valor_centavos: null,
    valor_rotulo: "sigiloso", data_sessao: licDia(41), hora_sessao: null, dias_uteis: 28, prazo: null,
    recomendada: licRecomendada(7, "concorrência · valor sigiloso · Serra Alfa · 310 km · 1 atestado", "Serra Alfa", 310) }),
  licitacao(34, { objeto: "Urbanização de praça e ciclovia", tipo_obra: "Urbanização", valor_centavos: 456789000, data_sessao: null, hora_sessao: null,
    dias_uteis: null, prazo: null, recomendada: licRecomendada(7, "concorrência · R$ 4,6 mi · Vila Exemplo · 1 atestado", "Vila Exemplo", null) }),
  licitacao(35, { ...SEOBRAS, objeto: "Drenagem e contenção de encostas", tipo_obra: "", valor_centavos: 2100000000, recomendada:
    licRecomendada(5, "concorrência · R$ 21,0 mi · 1 atestado", "", null) }),
];

const licLeitura = ({ atrasada = false, problemas = 2 } = {}) => ({
  lido_em: `${licDia(atrasada ? -4 : 0)}T13:05:00+00:00`, atrasada, fontes_com_problema: problemas });

// fatia 2 da #906: de que lado estao as decisoes. `decide`: depois do corte, para quem decide (a tela acende os botoes);
// sem ele, as decisoes ainda sao espelho do radar, como no banco da prova. As etapas e os motivos vem do servidor.
const licPoder = decide => ({ decisoes: decide ? "dashboard" : "radar", pode_decidir: decide });
const LIC_ETAPAS = [["acompanhando", "Acompanhando"], ["em_analise", "Em análise"], ["proposta_enviada", "Proposta enviada"],
  ["vencida", "Vencida"], ["perdida", "Perdida"], ["desistida", "Desistida"], ["encerrada", "Encerrada"]].map(([etapa, rotulo]) => ({ etapa, rotulo }));
const LIC_MOTIVOS = [["tipo de obra", "Tipo de obra"], ["local", "Local"], ["valor", "Valor"], ["órgão", "Órgão"], ["outro", "Outro"]]
  .map(([motivo, rotulo]) => ({ motivo, rotulo }));

/** GET /api/licitacoes/triagem. `vazia`: a leitura chegou e nada pede decisao; `atrasada`: o radar nao le ha' dias;
 *  `decide`: depois do corte, com os botoes. */
export const licitacoesTriagem = ({ vazia = false, atrasada = false, decide = false } = {}) => () => {
  if (vazia) {
    return { leitura: licLeitura({ problemas: 0 }), ...licPoder(decide), motivos_descarte: LIC_MOTIVOS, favoritas: [], recomendadas: [],
      contagens: { recomendadas: 0, favoritas: 0, novas: 0, novas_desde: null, por_orgao: [] } };
  }
  const favoritas = licFavoritas(), recomendadas = licRecomendadas();
  return { leitura: licLeitura({ atrasada }), ...licPoder(decide), motivos_descarte: LIC_MOTIVOS, recomendadas,
    // as que pedem atencao: prazo em ate' 15 dias uteis ou mudanca recente; a de prazo mais proximo primeiro
    favoritas: favoritas.filter(l => !l.encerrada && l.favorita.etapa !== "proposta_enviada"),
    contagens: { recomendadas: recomendadas.length, favoritas: favoritas.length, novas: 506,
      novas_desde: { desde: licDia(-1), quantas: 12 }, por_orgao: [{ orgao: "DER-EX", novas: 2 }, { orgao: "SEOBRAS-EX", novas: 4 }] } };
};

/** GET /api/licitacoes/favoritas, com os mesmos estados (a lista e o quadro leem daqui). */
export const licitacoesFavoritas = ({ vazia = false, atrasada = false, decide = false } = {}) => () => (vazia
  ? { leitura: licLeitura({ problemas: 0 }), ...licPoder(decide), etapas: LIC_ETAPAS, favoritas: [] }
  : { leitura: licLeitura({ atrasada }), ...licPoder(decide), etapas: LIC_ETAPAS, favoritas: licFavoritas() });

/** GET /api/licitacoes/calendario: o mes da prova em semanas de domingo a sabado, com os prazos das favoritas acima no
 *  dia de cada um, como o servidor monta. `vazio`: o mes sem prazo nenhum. */
export const licitacoesCalendario = ({ vazio = false } = {}) => () => {
  const hoje = dataEm(hojeDaProva()), mes = hoje.slice(0, 7);
  const outroMes = n => new Date(Date.UTC(Number(mes.slice(0, 4)), Number(mes.slice(5, 7)) - 1 + n, 1)).toISOString().slice(0, 7);
  const porDia = {};
  for (const l of vazio ? [] : licFavoritas()) {
    for (const p of l.favorita.prazos.filter(p => p.data.startsWith(mes))) {
      (porDia[p.data] ??= []).push({ ...p, licitacao: { id: l.id, chave: l.chave, orgao: l.orgao, sigla_orgao: l.sigla_orgao, edital: l.edital,
        modalidade: l.modalidade, objeto: l.objeto, link: l.link, encerrada: l.encerrada } });
    }
  }
  const primeiro = Date.parse(`${mes}-01T00:00:00Z`);
  const semanas = [];
  for (let dia = primeiro - new Date(primeiro).getUTCDay() * DIA; dataEm(dia).slice(0, 7) <= mes;) {
    const semana = [];
    for (let i = 0; i < 7; i += 1, dia += DIA) {
      const data = dataEm(dia);
      semana.push({ data, do_mes: data.startsWith(mes), hoje: data === hoje, prazos: porDia[data] ?? [] });
    }
    semanas.push(semana);
  }
  return { leitura: licLeitura({ problemas: 0 }), ...licPoder(false), mes, anterior: outroMes(-1), proximo: outroMes(1), mes_atual: true,
    prazos: Object.values(porDia).flat().length, semanas };
};

/** POST /api/licitacoes/{id}/analise: o comando que o servidor devolve; `semLink`: sem o link do edital, com o aviso. */
export const licitacaoAnalisada = ({ semLink = false } = {}) => ({
  id: 31, favoritou: true, comando: semLink ? "/analisar-edital" : "/analisar-edital https://exemplo.com.br/editais/31",
  aviso: semLink ? "Esta licitação não tem link de edital: baixe o edital e passe o arquivo ao comando" : null });

/** GET /api/licitacoes/resumo: a linha das licitacoes na Inicio (os numeros da Triagem acima). `atrasada`: o radar
 *  nao le ha' dias. */
export const resumoDasLicitacoes = ({ atrasada = false } = {}) => () => ({
  leitura: licLeitura({ atrasada }), recomendadas: licRecomendadas().length, favoritas: 3 });
