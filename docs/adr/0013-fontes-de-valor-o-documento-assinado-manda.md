# Fontes de valor: o documento assinado manda; na MT-PAR ele é o boletim assinado pelo fiscal

Uma medição tem o valor escrito em vários lugares: a planilha da medição, o boletim do órgão, o espelho, a nota.
Quando eles discordam, alguém precisa mandar. A regra, que já valia em `.claude/rules/dinheiro.md`, é uma
hierarquia: o documento assinado pelo órgão manda, a nota fiscal desempata e a planilha é insumo. O aprovado da
medição é o do boletim; o que diverge dele (espelho gerado antes, nota de outro valor) vira aviso de divergência,
nunca correção silenciosa.

Na MT-PAR essa regra não tinha onde se apoiar: o órgão não devolve boletim por e-mail, e o motor tratava todos os
passos como "feito por fora". Em 16/11/2026 (#297) os documentos das cinco obras do órgão mostraram o rito: a
empresa preenche o boletim no modelo do órgão, o fiscal do órgão e o engenheiro da empresa assinam, a empresa
emite a nota e manda o ofício com a nota e as certidões. O total da página do "Visto" bateu ao centavo com a nota
nas cinco. O dono decidiu (#753) que na MT-PAR o documento assinado é esse boletim: a medição ganha o passo do
boletim antes do espelho, e o aprovado é o "Valor Total da Nª Medição" do Visto, lido do PDF que a pessoa entrega.
O reajuste vem em PDF próprio, e o aprovado dele é o "TOTAL REAJUSTE".

## Opções consideradas

- Continuar sem boletim na MT-PAR e tomar o valor da nota: a nota passaria de desempate a fonte, e a divergência
  entre o que o fiscal assinou e o que foi faturado não apareceria em lugar nenhum.
- Ler só o rótulo do Visto: na extração de texto o valor sai colado ao rótulo numas obras e num bloco separado
  noutras, em ordem que muda de obra para obra. Uma leitura só proporia, cedo ou tarde, o número do campo vizinho.

## Consequências

- O valor lido só é proposto quando duas leituras independentes dão a mesma quantia: a do rótulo e a da linha da
  medição no quadro "CONTROLE FINANCEIRO". Se não batem, ou se o valor não sai ao lado do rótulo, a pessoa confere
  no PDF e digita, com as duas leituras na tela. Os campos "acumulado das medições anteriores" e "saldo" do Visto
  ficam fora da conferência: vêm errados em parte das obras.
- Uma leitura só nunca vira valor aceito. Quando só a do quadro existe (ou as duas existem e são iguais, mas o
  valor não foi proposto), a pessoa pode usá-la num clique: ela entra como valor digitado. O valor registrado
  diferente de uma leitura avisa na tela antes do registro, não trava, e a diferença fica na auditoria com as
  leituras.
- O número da medição vem da capa ou do campo "N.º da Medição", nunca do rodapé nem do nome do arquivo. O boletim
  de outra medição, de outra obra ou do outro tipo (o da medição no reajuste e o contrário) é recusado. Sem a capa
  e sem o campo, o número do rótulo do Visto só serve para recusar o boletim de outra medição: nada é proposto.
- A obra se confere pelo número do contrato da capa (no reajuste, da carta). O quadro de controle financeiro já
  veio com o ano do contrato trocado: sozinho ele não recusa. Quando só ele foi lido e discorda do cadastro, ou
  quando a capa e ele discordam e só ele traz o contrato da obra, o boletim entra, o valor não é proposto e a
  tela diz que o contrato não pôde ser conferido.
- O passo não trava. Em parte das obras o boletim das medições recentes não estava guardado: a medição sem boletim
  segue até o pagamento, com a pendência "boletim não anexado" na página dela.
- `prazo_boletim_dias` continua sem valer para a MT-PAR: o boletim não é esperado do órgão por e-mail.
- O texto do PDF não prova que a cópia entregue é a assinada (não há certificado de conclusão nele). O sistema lê o
  que a pessoa entregou (`docs/adr/0003`); conferir a assinatura é de quem anexa.
