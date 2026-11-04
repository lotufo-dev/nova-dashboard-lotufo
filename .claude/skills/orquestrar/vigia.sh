#!/usr/bin/env bash
# Vigia de uma PR com auto-merge ligado (skill orquestrar, passo 9).
# Uso: vigia.sh <numero da PR> [intervalo em segundos (120)] [limite sem mudanca em minutos (60)] [hora de referencia UTC, AAAA-MM-DDTHH:MM:SSZ]
# Hora de referencia: so contam execucoes da fila (merge_group) criadas a partir dela. A orquestradora grava a hora
# (date -u +%Y-%m-%dT%H:%M:%SZ) ANTES do `gh pr merge --auto` e passa aqui: com a CI ja verde a PR entra direto na
# fila e a execucao nasce ~20 s depois, antes de o vigia subir. Sem o argumento vale agora menos 10 minutos.
# Roda em segundo plano e termina na primeira destas situacoes, imprimindo o motivo na primeira palavra:
#   MERGED                PR mergeada
#   FECHADA               PR fechada sem merge
#   COMENTARIO            ha comentario ou review na PR (e do Leo; o passo 8 exige zero)
#   CI_VERMELHA           algum check da branch da PR terminou em falha (nao espera a fila)
#   FILA_VERMELHA         a PR saiu da fila e um grupo da fila (merge_group) criado a partir da hora de referencia falhou
#   AUTO_MERGE_DESLIGADO  nem auto-merge armado nem PR na fila (o GitHub desliga quando a fila falha; o Leo pode desligar)
#   SEM_MUDANCA           nada mudou nos checks por N minutos (a orquestradora reconsulta e relanca)
# Saida 0 em qualquer um dos motivos acima; 2 (ERRO) se a PR nao existe ou o gh falha de forma repetida.
# Custo: uma chamada GraphQL por volta; `gh run list` so quando a PR nao esta na fila.
set -u

PR="${1:-}"
INTERVALO="${2:-120}"
LIMITE_MIN="${3:-60}"
REPO_DONO="${VIGIA_DONO:-lotufo-dev}"
REPO_NOME="${VIGIA_REPO:-nova-dashboard-lotufo}"
case "$PR" in
  ''|*[!0-9]*) echo "ERRO uso: vigia.sh <numero da PR> [intervalo] [limite em minutos] [hora de referencia UTC]" >&2; exit 2 ;;
esac

REFERENCIA="${4:-}"
if [ -n "$REFERENCIA" ]; then
  case "$REFERENCIA" in
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z) inicio_iso="$REFERENCIA" ;;
    *) echo "ERRO hora de referencia deve ser AAAA-MM-DDTHH:MM:SSZ (UTC)" >&2; exit 2 ;;
  esac
else
  # date do Linux e do Windows (GNU) ou do Mac (BSD)
  inicio_iso=$(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v-10M +%Y-%m-%dT%H:%M:%SZ)
fi

CONSULTA='query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r){pullRequest(number:$n){
  state isInMergeQueue mergeStateStatus autoMergeRequest{enabledAt} comments{totalCount} reviews{totalCount}
  commits(last:1){nodes{commit{statusCheckRollup{contexts(first:100){nodes{__typename
    ... on CheckRun{name status conclusion} ... on StatusContext{context state}}}}}}}}}}'

# state, naFila, armado, comentarios, falhos, assinatura (campos vazios viram "-")
FILTRO='.data.repository.pullRequest
  | ([.commits.nodes[0].commit.statusCheckRollup.contexts.nodes[]?]) as $c
  | [ .state, (.isInMergeQueue|tostring), ((.autoMergeRequest != null)|tostring),
      ((.comments.totalCount + .reviews.totalCount)|tostring),
      ([$c[] | select((.conclusion // "") as $x | ($x=="FAILURE" or $x=="TIMED_OUT" or $x=="STARTUP_FAILURE") or ((.state // "") as $s | ($s=="FAILURE" or $s=="ERROR"))) | (.name // .context)] | join(",") | if .=="" then "-" else . end),
      ([$c[] | "\(.name // .context)=\(.conclusion // .state // .status)"] | join("|") | if .=="" then "-" else . end) ]
  | @tsv'

consulta() {
  gh api graphql -f query="$CONSULTA" -f o="$REPO_DONO" -f r="$REPO_NOME" -F n="$PR" -q "$FILTRO" 2>/dev/null
}

linha=$(consulta) || linha=""
if [ -z "$linha" ]; then
  echo "ERRO PR #$PR nao encontrada (ou gh sem acesso)" >&2
  exit 2
fi

ultima_assinatura=""
ultima_mudanca=$(date +%s)
falhas=0

while true; do
  linha=$(consulta) || linha=""
  if [ -z "$linha" ]; then
    falhas=$((falhas + 1))
    if [ "$falhas" -ge 5 ]; then
      echo "ERRO gh falhou 5 vezes seguidas na PR #$PR" >&2
      exit 2
    fi
    sleep "$INTERVALO"
    continue
  fi
  falhas=0
  IFS=$'\t' read -r estado na_fila armado coment falhos assin <<<"$linha"

  if [ "$estado" = "MERGED" ]; then echo "MERGED PR #$PR mergeada"; exit 0; fi
  if [ "$estado" = "CLOSED" ]; then echo "FECHADA PR #$PR fechada sem merge"; exit 0; fi
  if [ "$coment" -gt 0 ]; then
    echo "COMENTARIO PR #$PR tem comentario ou review (do Leo): desarmar e seguir o passo 9"
    exit 0
  fi
  if [ "$falhos" != "-" ]; then
    echo "CI_VERMELHA PR #$PR: $falhos"
    exit 0
  fi

  if [ "$na_fila" = "false" ]; then
    # So acusa fila vermelha quem saiu da fila, e so execucao criada a partir da hora de referencia.
    grupo=$(gh run list --event merge_group --limit 20 --json headBranch,conclusion,databaseId,createdAt \
      -q ".[] | select((.headBranch | test(\"/pr-$PR-\")) and .createdAt >= \"$inicio_iso\" and (.conclusion==\"failure\" or .conclusion==\"timed_out\")) | .databaseId" 2>/dev/null | head -1 || true)
    if [ -n "$grupo" ]; then
      echo "FILA_VERMELHA PR #$PR: execucao $grupo (gh run view $grupo --log-failed)"
      exit 0
    fi
    if [ "$armado" = "false" ]; then
      echo "AUTO_MERGE_DESLIGADO PR #$PR sem auto-merge e fora da fila"
      exit 0
    fi
  fi

  assinatura=$(printf '%s|%s|%s' "$assin" "$na_fila" "$armado" | cksum)
  agora=$(date +%s)
  if [ "$assinatura" != "$ultima_assinatura" ]; then
    ultima_assinatura="$assinatura"
    ultima_mudanca=$agora
  elif [ $((agora - ultima_mudanca)) -ge $((LIMITE_MIN * 60)) ]; then
    echo "SEM_MUDANCA PR #$PR sem mudanca ha ${LIMITE_MIN} min: reconsultar e relancar o vigia"
    exit 0
  fi
  sleep "$INTERVALO"
done
