// Respostas ficticias da API para os estados que o cadastro de exemplo nao alcanca (acabamento do redesenho, #717):
// o SIGA com processos, as listas vazias e as falhas de leitura. `telas.mjs` poe cada uma no `simular` da tela.
// Tudo inventado: orgao, pessoa, numero e obra daqui nao existem.

const mov = (data, evento, tipo, extra = {}) => ({
  data, evento, tipo, cad_lotacao: "PROTOC/ORGAO", cad_pessoa: "Beltrano", at_lotacao: "COFIN/ORGAO", at_pessoa: "Fulano", ...extra,
});

// a leitura do tempo no setor, como o servidor a manda (`siga.situacao_do_tempo`): o encerrado nao tem
const tempoDe = p => (p.encerrado ? null : p.hoje > 0 ? "feito" : p.dias_uteis === null ? null
  : p.dias_uteis >= 10 ? "critico" : p.dias_uteis >= 5 ? "breve" : "andamento");

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
    medicao_titulo: "24ª Medição", categoria: "medicoes", o_que_e: "24ª Medição", dias_uteis: 25, setor: "NUCLEO-ADM", com_quem: "Sicrana",
    desde: "2026-09-22T10:00:00-04:00", ultima: mov("2026-10-13T11:00:00-04:00", "Juntada | despacho", "juntada"),
    protocolado_em: "2026-09-08T08:00:00-04:00" }),
  processo({ id: 7, nome: "Processo Eta", numero: "ORGAO-PRO-2026/00032", contrato_id: 9012, obra: "Ponte Mi", ...sinfra, protocolo_id: 6,
    medicao_titulo: "7ª Medição e Reajuste da 7ª Medição", categoria: "medicoes", o_que_e: "7ª Medição e Reajuste da 7ª Medição",
    dias_uteis: 17, setor: "CCONT", com_quem: "Beltrano", desde: "2026-10-02T10:00:00-04:00", protocolado_em: "2026-09-25T08:00:00-04:00" }),
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
  linhas: [{ competencia: "2025-04", custo_centavos: 35120044 }, { competencia: "2025-05", custo_centavos: 41877310 },
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
    medido: { ...painel.medido, valor_centavos: 2428000007, quantidade: 9,
      anterior: { competencia: mesAntes(competencia, 1), valor_centavos: 2642000005 },
      ano_anterior: { competencia: mesAntes(competencia, 12), valor_centavos: 2410000003 } } };
};

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
  ["Consórcio Intermunicipal de Desenvolvimento do Vale do Rio Cuiabá", null, 70]];
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
// O protocolado tem a referencia da mesma altura e o recebido vem sem lastro (sem variacao). `contratante` recorta
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
    linha(9001, "Avenida Alfa", "SINFRA", "29ª Medição", "em_analise", 553_000, 12, 9),
    linha(9010, "Hospital Capa", "SES-MT", "5ª Medição", "em_analise", 169_000, 16, 11),
    linha(9005, "Bairros Épsilon", "SINFRA", "12ª Medição", "boletim", 412_000, 0, 0, comPedido(414_000, 2_000)),
    linha(9002, "Corredor Beta", "SINFRA", "16ª Medição", "nota", 3_270_000, 1, 1, comPedido(3_270_000)),
    linha(9009, "Orla Iota", "Pref. Cuiabá", "30ª Medição", "nota", 828_000, 8, 6, comPedido(820_000, 0, 8_000)),
    { ...linha(9007, "Trevo Eta", "MTPAR", "25ª Medição + Reajuste", "protocolado", 1_904_000, 6, 4, comPedido(1_904_000)), medicao_ids: [9690, 9691] },
    linha(9008, "Anel Teta", "MTPAR", "8ª Medição", "protocolado", 592_000, 11, 8),
    // protocoladas com o prazo do orgao: dentro dele (a data esperada vai escrita) e alem dele (critico). O prazo curto
    // da segunda e' para o estado caber no mes da prova
    linha(9004, "Quartel Delta", "SINFRA", "35ª Medição", "protocolado", 209_000, 12, 8, { prazo: [47, 35] }),
    linha(9015, "Viaduto Ômicron", "SES-MT", "3ª Medição", "protocolado", 240_000, 16, 11, { prazo: [14, -2] }),
    linha(9003, "Estações Gama", "SINFRA", "8ª Medição", "recebido", 14_629_000, 5, null, { ...comPedido(14_629_000), dias_da_nota_ao_recebimento: 4 }),
    linha(9001, "Avenida Alfa", "SINFRA", "Reajuste da 28ª Medição", "recebido", 1_607_000, 9, null,
      { tipo: "reajuste", ...comPedido(1_977_000, 370_000), dias_da_nota_ao_recebimento: 31 }),
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
    ...deAntes(7, linha(9009, "Orla Iota", "Pref. Cuiabá", "23ª Medição", "protocolado", 905_000, 190, 128)),
    ...deAntes(2, linha(9002, "Corredor Beta", "SINFRA", "14ª Medição", "protocolado", 2_790_000, 48, 33, comPedido(2_800_000, 10_000)),
      linha(9007, "Trevo Eta", "MTPAR", "23ª Medição", "protocolado", 4_000_000, 51, 35)),
    ...deAntes(1, linha(9001, "Avenida Alfa", "SINFRA", "28ª Medição", "protocolado", 1_760_000, 20, 14),
      linha(9003, "Estações Gama", "SINFRA", "7ª Medição", "nota", 9_600_000, 15, 10),
      linha(9008, "Anel Teta", "MTPAR", "7ª Medição", "em_analise", 610_000, 40, 28)),
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
  // o mesmo dia de hoje, um mes antes (o dia 29 em diante fica no 28, para caber em qualquer mes)
  const d = new Date(hoje), ate = dataEm(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() - 1, Math.min(28, d.getUTCDate())));
  return { ...resposta, contratante, contratantes, etapas: porEtapa(linhasDoMes),
    // o medido subiu contra o mes anterior e ficou estavel contra o mesmo mes do ano anterior
    medido: { valor_centavos: medido, mes_anterior: medido ? { competencia: mesAntes(mes, 1), valor_centavos: Math.round(medido / 1.068) } : null,
      ano_anterior: medido ? { competencia: mesAntes(mes, 12), valor_centavos: Math.round(medido / 0.99) } : null },
    // o protocolado caiu contra a mesma altura do mes anterior; o recebido nao tem lastro (sem variacao)
    mesma_altura: medido ? { competencia: mesAntes(mes, 1), ate, protocolado_centavos: 3_780_000 * REAIS, recebido_centavos: null } : null,
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
    andamento: { ritmo_centavos: x.ritmo == null ? null : x.ritmo * REAIS, necessario_centavos: x.necessario == null ? null : x.necessario * REAIS },
    medido_mes: { competencia: competenciaHa(1), valor_centavos: (x.mes ?? 0) * REAIS, referencia_competencia: competenciaHa(2),
      referencia_centavos: (x.antes ?? 0) * REAIS },
  };
};
const CARTEIRA = () => [
  // SINFRA: devagar (27% e 18% do necessario), adiantada, em atencao, em encerramento e uma encerrada
  daCarteira(9001, "Avenida Alfa", "SINFRA", "sinfra", { orgao: "SINFRA - SUEF II", sub: "SUEF II", vigente: 120_000_000, medido: 44_400_000,
    ritmo: 2_400_000, necessario: 8_800_000, mes: 1_600_000, antes: 1_760_000 }),
  daCarteira(9002, "Corredor Beta", "SINFRA", "sinfra", { orgao: "SINFRA - SUPU", sub: "SUPU", bp: 4900, vigente: 210_000_000, medido: 178_500_000,
    ritmo: 4_100_000, necessario: 3_600_000, mes: 3_300_000, antes: 2_790_000, receber: 3_900_000, dias: 96 }),
  daCarteira(9003, "Estações Gama", "SINFRA", "sinfra", { orgao: "SINFRA - SUPU", sub: "SUPU", vigente: 180_000_000, medido: 63_000_000,
    ritmo: 7_000_000, necessario: 38_700_000, mes: 14_600_000, antes: 9_600_000, dias: 40 }),
  daCarteira(9004, "Quartel Delta", "SINFRA", "sinfra", { orgao: "SINFRA - SUEF II", sub: "SUEF II", vigente: 12_000_000, medido: 5_640_000,
    ritmo: 500_000, necessario: 600_000, mes: 600_000, antes: 600_000, receber: 600_000, dias: 250 }),
  daCarteira(9005, "Bairros Épsilon", "SINFRA", "sinfra", { orgao: "SINFRA - SUPU", sub: "SUPU", vigente: 8_000_000, medido: 7_960_000,
    ritmo: 300_000, necessario: null, mes: 200_000, antes: 510_000, dias: 4, encerramento: dataEm(hojeDaProva(), -20) }),
  daCarteira(9006, "Travessia Zeta", "SINFRA", "sinfra", { orgao: "SINFRA - SUEF II", sub: "SUEF II", vigente: 30_000_000, medido: 30_000_000,
    estado: "encerrado", ritmo: null, necessario: null, dias: -400 }),
  // MTPAR, sem prazo de pagamento no sistema: uma com a execucao vencida e uma em atencao
  daCarteira(9007, "Trevo Eta", "MTPAR", "mtpar", { vigente: 90_000_000, medido: 74_700_000, ritmo: 900_000, necessario: null,
    mes: 3_100_000, antes: 4_000_000, receber: 7_100_000, dias: -24 }),
  daCarteira(9008, "Anel Teta", "MTPAR", "mtpar", { vigente: 124_600_000, medido: 49_840_000, ritmo: 2_000_000, necessario: 2_500_000, dias: 900 }),
  // Pref. Cuiaba: uma obra paralisada
  daCarteira(9009, "Orla Iota", "Pref. Cuiabá", "pref-cuiaba", { vigente: 66_500_000, medido: 37_240_000, estado: "suspenso",
    paralisada: dataEm(hojeDaProva(), -100), ritmo: 300_000, necessario: null, mes: 900_000, antes: 905_000, receber: 900_000 }),
  // SES-MT: uma obra adiantada, sem nada pendente e sem medicao no mes (o contratante fica "Em dia")
  daCarteira(9010, "Hospital Capa", "SES-MT", "ses-mt", { vigente: 168_300_000, medido: 156_519_000, ritmo: 5_000_000, necessario: 4_000_000, dias: 75 }),
];
export const carteiraSimulada = () => CARTEIRA();

const farolDaCarteira = (o, farol, motivos = []) => ({
  contrato_id: o.id, seq: o.id - 9000, obra: o.nome_curto, contratante: o.contratante, empreita: o.percentual_direito_bp === 10000 ? "PRÓPRIA" : "CONSÓRCIO",
  direito: o.percentual_direito_bp / 10000, pi_va: o.posicao.vigente_centavos, faturados: o.posicao.medido_centavos, saldo: o.posicao.saldo_centavos,
  status: "EM ANDAMENTO", termino: o.execucao_fim_vigente, vigencia: o.vigencia_fim_vigente, farol,
  motivo: motivos.map(m => m[1]).join("; "),
  motivos: motivos.map(([nivel, texto]) => ({ tipo: "simulado", nivel, dias: null, valor_centavos: null, texto })) });
const MOTIVOS = {
  9001: ["vermelho", [["critico", "14ª Medição: aprovado 18,7% abaixo do pedido"], ["atencao", "garantia vence em 28 dias"]]],
  9002: ["atencao", [["atencao", "prorrogação pedida há 9 dias"]]],
  9003: ["vermelho", [["critico", "garantia não cobre o fim da execução"], ["acao", "execução termina em 40 dias"], ["atencao", "reajuste esperando apostilamento"]]],
  9005: ["acao", [["acao", "execução termina em 4 dias"]]],
  9007: ["vermelho", [["critico", "execução venceu há 24 dias"]]],
  9009: ["atencao", [["atencao", "obra paralisada há 100 dias"]]],
};
export const painelDaCarteira = painel => {
  const emAndamento = CARTEIRA().filter(o => o.estado !== "encerrado");
  const obras = emAndamento.map(o => farolDaCarteira(o, ...(MOTIVOS[o.id] ?? ["verde", []])));
  return { ...painel, obras, prazo_pagamento: { SINFRA: 47, "Pref. Cuiabá": 62, "SES-MT": 38 },
    reajustes_apostilamento: { competencias: 3, valor_centavos: 41_250_000, obras: [
      { contrato_id: 9003, obra: "Estações Gama", competencias: 2, valor_centavos: 30_000_000 },
      { contrato_id: 9004, obra: "Quartel Delta", competencias: 1, valor_centavos: 11_250_000 }] },
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
      conclusao: dataEm(fim, noRitmo ? -13 : 70), situacao: noRitmo ? "no_prazo" : "atrasa", dias_alem: noRitmo ? null : 70 } };
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
  const siga = (i, dias) => ({ ...base(i, "siga_parado", "acao", dias, "desde", d => `processo ORGAO-PRO-2026/00007 parado em COFIN desde ${d}`,
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
    linhaDaFila(reg, 1, "Maternidade Alfa", "5ª Medição", "lotufo", CINCO, 3, paradaDaFila(12, "critico"), 172_000, 172_000,
      { acao: "gerar_espelho", contratante: "Pref. Várzea Grande", sub: null }),
    linhaDaFila(reg, 2, "Corredor Beta", "30ª Medição + Reajuste", "lotufo", SEIS, 5, paradaDaFila(6, "breve"), 1_720_000, 1_660_000, { acao: "enviar_nota", sub: "SUPU" }),
    linhaDaFila(reg, 3, "Estações Gama", "16ª Medição", "lotufo", SEIS, 3, paradaDaFila(4, "andamento"), 8_400_000, 8_380_000, { acao: "enviar_espelho", sub: "SUPU" }),
    linhaDaFila(reg, 4, "Terminais Delta", "3ª Medição de Projeto", "lotufo", SEIS, 1, paradaDaFila(0, "feito"), 980_000, null, { acao: "enviar_planilha" }),
    linhaDaFila(reg, 5, "Trevo Eta", "9ª Medição", "lotufo", CINCO, 2, paradaDaFila(null, null), 310_000, null, { acao: "registrar_boletim", ...mtpar }),
  ];
  const faturamento = [
    linhaDaFila(reg, 6, "Quartel Delta", "8ª Medição", "faturamento", SEIS, 4, paradaDaFila(7, "breve"), 593_000, 593_400),
    linhaDaFila(reg, 7, "Anel Teta", "12ª Medição", "faturamento", CINCO, 4, paradaDaFila(1, "andamento"), 2_050_000, 2_050_000, mtpar),
  ];
  const orgao = [
    linhaDaFila(reg, 8, "Bairros Épsilon", "35ª Medição", "orgao", SEIS, 6, paradaDaFila(41, "critico", { prazo: 45, esperada: -9 }), 209_000, 209_000, { sub: "SUPU" }),
    linhaDaFila(reg, 9, "Rodovia Capa", "29ª Medição", "orgao", SEIS, 2, paradaDaFila(11, "critico"), 856_000, null),
    linhaDaFila(reg, 10, "Avenida Alfa", "11ª Medição", "orgao", SEIS, 2, paradaDaFila(5, "breve"), 1_600_000, null),
    linhaDaFila(reg, 11, "Complexo Lambda", "25ª Medição + Reajuste", "orgao", CINCO, 6, paradaDaFila(4, "andamento", { prazo: 45, esperada: 39 }), 1_904_000, 1_904_000, mtpar),
    linhaDaFila(reg, 12, "Praça Mi", "2ª Medição", "orgao", TRES, 6, paradaDaFila(3, "andamento"), 77_000, 77_000, { contratante: "Pref. Cuiabá", sub: null }),
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
        ? { processo_id: 1, setor: "SUPE", dias_uteis: 6, desde: "2026-10-20T10:00:00-04:00", hoje: 0 } : null })),
  });
  const contratantes = [...new Set(doMes.map(l => l.contratante))];
  const quadro = contratantes.map(c => { const ls = doMes.filter(l => l.contratante === c); return { contratante: c, ...somaDaFila(ls), linhas: ls.map(noQuadro) }; })
    .sort((a, b) => b.linhas.length - a.linhas.length);
  const anteriores = [
    linhaDaFila(reg, 13, "Corredor Beta", "29ª Medição", "lotufo", SEIS, 5, paradaDaFila(19, "critico"), 1_510_000, 1_480_000,
      { acao: "enviar_nota", sub: "SUPU", competencia: competenciaHa(2) }),
    linhaDaFila(reg, 14, "Trevo Eta", "8ª Medição", "faturamento", CINCO, 4, paradaDaFila(8, "breve"), 290_000, 290_000, { ...mtpar, competencia: competenciaHa(2) }),
    linhaDaFila(reg, 15, "Rodovia Capa", "27ª Medição", "orgao", SEIS, 2, paradaDaFila(33, "critico"), 640_000, null, { competencia: competenciaHa(3) }),
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
