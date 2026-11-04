#!/usr/bin/env bash
# Vigia de uma PR com auto-merge ligado (skill orquestrar, passo 9).
# Uso: vigia.sh <numero da PR> [intervalo em segundos (60)] [limite sem mudanca em minutos (60)]
# Roda em segundo plano e termina na primeira destas situacoes, imprimindo o motivo na primeira palavra:
#   MERGED                PR mergeada
#   FECHADA               PR fechada sem merge
#   CI_VERMELHA           algum check da branch da PR terminou em falha (nao espera a fila)
#   FILA_VERMELHA         o grupo da fila de merge (evento merge_group) desta PR falhou
#   AUTO_MERGE_DESLIGADO  o auto-merge foi desligado (pelo GitHub ou por alguem)
#   COMENTARIO            apareceu comentario ou review novo na PR (e do Leo)
#   SEM_MUDANCA           nada mudou nos checks por N minutos (a orquestradora reconsulta e relanca)
# Saida 0 em qualquer um dos motivos acima; 2 se a PR nao existe ou o gh falha de forma repetida.
set -u

PR="${1:-}"
INTERVALO="${2:-60}"
LIMITE_MIN="${3:-60}"
case "$PR" in
  ''|*[!0-9]*) echo "ERRO uso: vigia.sh <numero da PR> [intervalo] [limite em minutos]" >&2; exit 2 ;;
esac

consulta() {
  gh pr view "$PR" --json state,autoMergeRequest,comments,reviews \
    -q '[.state, (.autoMergeRequest != null), ((.comments|length) + (.reviews|length))] | @tsv' 2>/dev/null
}

linha=$(consulta) || linha=""
if [ -z "$linha" ]; then
  echo "ERRO PR #$PR nao encontrada (ou gh sem acesso)" >&2
  exit 2
fi
IFS=$'\t' read -r estado armado inicial_coment <<<"$linha"

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
  IFS=$'\t' read -r estado armado coment <<<"$linha"

  if [ "$estado" = "MERGED" ]; then echo "MERGED PR #$PR mergeada"; exit 0; fi
  if [ "$estado" = "CLOSED" ]; then echo "FECHADA PR #$PR fechada sem merge"; exit 0; fi
  if [ "$coment" -gt "$inicial_coment" ]; then
    echo "COMENTARIO PR #$PR tem comentario ou review novo (do Leo): desarmar e seguir o passo 9"
    exit 0
  fi

  checks=$(gh pr checks "$PR" --json name,bucket -q '.[] | "\(.name)=\(.bucket)"' 2>/dev/null || true)
  if printf '%s\n' "$checks" | grep -q '=fail$'; then
    echo "CI_VERMELHA PR #$PR: $(printf '%s\n' "$checks" | grep '=fail$' | sed 's/=fail$//' | paste -sd, -)"
    exit 0
  fi

  grupo=$(gh run list --event merge_group --limit 20 --json headBranch,conclusion,databaseId \
    -q ".[] | select(.headBranch | test(\"/pr-$PR-\")) | \"\(.databaseId)=\(.conclusion)\"" 2>/dev/null || true)
  if printf '%s\n' "$grupo" | grep -Eq '=(failure|cancelled|timed_out)$'; then
    id=$(printf '%s\n' "$grupo" | grep -E '=(failure|cancelled|timed_out)$' | head -1 | cut -d= -f1)
    echo "FILA_VERMELHA PR #$PR: execucao $id (gh run view $id --log-failed)"
    exit 0
  fi

  if [ "$armado" = "false" ]; then
    echo "AUTO_MERGE_DESLIGADO PR #$PR sem auto-merge (o GitHub desliga quando a fila falha)"
    exit 0
  fi

  assinatura=$(printf '%s|%s|%s' "$checks" "$grupo" "$armado" | cksum)
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
