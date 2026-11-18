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
// as tres leituras da diferenca entre o aprovado e o pedido (critica, pequena e igual). Outubro tem uma medicao em
// analise, que nao e' diferenca; novembro e' o mes em curso, sem variacao. Valores de centenas de milhoes, para a
// tabela ser provada com o numero largo. Tudo inventado; a obra e a medicao dos links sao as da prova.
const fchLinha = (aprovado, pedido, recebido, emAnalise = 0) => ({
  medido_centavos: aprovado + emAnalise, aprovado_centavos: aprovado, protocolado_centavos: aprovado, recebido_centavos: recebido,
  em_aberto_centavos: aprovado - recebido, em_aberto_notas_centavos: aprovado - recebido, em_aberto_repasse_centavos: 0,
  sem_nota_centavos: 0, aprovado_com_pedido_centavos: aprovado, pedido_do_aprovado_centavos: pedido });
const FCH_MESES = [
  ["2025-07", fchLinha(3391300001, 3391300001, 3391300001)], ["2025-08", fchLinha(2644600003, 2644600003, 2644600003)],
  ["2025-09", fchLinha(2341800005, 2341800005, 2341800005)], ["2025-10", fchLinha(2273400007, 2273400007, 2273400007)],
  ["2026-07", fchLinha(2305000001, 2340000001, 2287000001)],                 // aprovado 1,5% abaixo do pedido
  ["2026-08", fchLinha(3094000003, 3106400003, 3094000003)],                 // 0,4% abaixo
  ["2026-09", fchLinha(2368000005, 2368000005, 1442000005)],                 // igual ao pedido
  ["2026-10", fchLinha(1873000007, 1873000007, 1624000007, 555000000)],      // parte ainda em analise
  ["2026-11", fchLinha(0, 0, 0, 310000009)],                                 // o mes em curso
];
const fchSoma = linhas => Object.fromEntries(Object.keys(fchLinha(0, 0, 0)).map(k => [k, linhas.reduce((t, x) => t + x[k], 0)]));
export const fechamentoComValores = reg => {
  const medido = Object.fromEntries(FCH_MESES.map(([comp, x]) => [comp, x.medido_centavos]));
  const meses = FCH_MESES.map(([comp, x], i) => {
    const aberto = x.em_aberto_centavos > 0;
    const medicao = { ...x, medicao_id: reg.medicao, contrato_id: reg.obra, obra: "Obra Exemplo", numero: i + 1, tipo: "execucao",
      competencia: comp, protocolo_em: x.protocolado_centavos ? `${mesAntes(comp, -1)}-20` : null, notas_fora_da_conta: [], sem_nota: false,
      notas: x.protocolado_centavos ? [{ nota_id: 9400 + i, numero: String(900 + i), valor_centavos: x.protocolado_centavos,
        recebido_centavos: x.recebido_centavos, em_aberto_centavos: x.em_aberto_centavos, recebida: !aberto, paga_em_parte: aberto,
        aguarda_repasse: false }] : [] };
    const anterior = medido[mesAntes(comp, 12)];
    return { competencia: comp, ...x, medido_ano_anterior_centavos: anterior && comp < "2026-11" ? anterior : null,
      obras: [{ contrato_id: reg.obra, obra: "Obra Exemplo", ...x, medicoes: [medicao] }] };
  });
  const doAno = ano => meses.filter(m => m.competencia.startsWith(ano));
  const cobertura = ano => { const t = fchSoma(doAno(ano)); return { aprovado_centavos: t.aprovado_centavos,
    com_nota_centavos: t.aprovado_centavos, sem_nota_centavos: 0, medicoes_sem_nota: 0, percentual: 100 }; };
  return {
    anos: ["2025", "2026"], meses,
    por_ano: { 2025: { ...fchSoma(doAno("2025")), meses: 4 }, 2026: { ...fchSoma(doAno("2026")), meses: 5 } },
    acumulado: { ate_mes: "11", 2025: fchSoma(doAno("2025")), 2026: fchSoma(doAno("2026")) },
    em_aberto: meses.filter(m => m.em_aberto_centavos > 0).map(m => {
      const md = m.obras[0].medicoes[0];
      return { tipo_aberto: "nota", nota_id: md.notas[0].nota_id, numero: md.notas[0].numero, contrato_id: reg.obra, obra: "Obra Exemplo",
        medicao_id: reg.medicao, medicao_numero: md.numero, tipo: "execucao", competencia: m.competencia, protocolo_em: md.protocolo_em,
        emitida_em: null, valor_centavos: m.em_aberto_centavos, paga_em_parte: true };
    }),
    em_aberto_anteriores: { quantidade: 0, valor_centavos: 0 },
    notas_sem_medicao: { em_aberto: [], em_aberto_centavos: 0, pagas: { quantidade: 0, valor_centavos: 0 } },
    cobertura: { 2025: cobertura("2025"), 2026: cobertura("2026") }, notas_diferem: [], pares_mistos: [],
    diferenca_critica_por_mil: 5, total_a_receber_liberado: true,
  };
};

export const obrasComAParte = obras => obras.map((o, i) => ({ ...o, posicao: { ...o.posicao, a_receber_ano_inicial: "2025",
  a_receber_anterior_centavos: i === 0 ? 70003 : 0, a_receber_sem_atualizacao_centavos: i === 0 ? 40001 : 0 } }));

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

// Uma resposta que a tela nao sabe desenhar: o Inicio cai e a ultima rede ("A tela parou de responder") aparece.
export const RESPOSTA_QUE_QUEBRA = { medido: null };
