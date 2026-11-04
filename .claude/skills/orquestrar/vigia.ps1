# Vigia de uma PR com auto-merge ligado (skill orquestrar, passo 9), versao Windows de vigia.sh.
# Uso: powershell -NoProfile -ExecutionPolicy Bypass -File vigia.ps1 <PR> [intervalo (120)] [limite em minutos (60)] [hora de referencia UTC AAAA-MM-DDTHH:MM:SSZ]
# Hora de referencia: so contam execucoes da fila (merge_group) criadas a partir dela. A orquestradora grava a hora
# antes do `gh pr merge --auto` e passa aqui (com a CI verde a PR entra direto na fila e a execucao nasce ~20 s depois,
# antes de o vigia subir). Sem o argumento vale agora menos 10 minutos.
# Termina imprimindo MERGED | FECHADA | COMENTARIO | CI_VERMELHA | FILA_VERMELHA | AUTO_MERGE_DESLIGADO | SEM_MUDANCA
# (exit 0), ou ERRO (exit 2) se a PR nao existe ou o gh falha repetidas vezes. Mesmas regras do vigia.sh.
param([Parameter(Mandatory = $true)][string]$Pr, [int]$Intervalo = 120, [int]$LimiteMin = 60, [string]$Referencia = '')
if ($Pr -notmatch '^\d+$') { [Console]::Error.WriteLine('ERRO uso: vigia.ps1 <numero da PR>'); exit 2 }
$dono = if ($env:VIGIA_DONO) { $env:VIGIA_DONO } else { 'lotufo-dev' }
$repo = if ($env:VIGIA_REPO) { $env:VIGIA_REPO } else { 'nova-dashboard-lotufo' }

$consultaGql = 'query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r){pullRequest(number:$n){state isInMergeQueue autoMergeRequest{enabledAt} comments{totalCount} reviews{totalCount} commits(last:1){nodes{commit{statusCheckRollup{contexts(first:100){nodes{__typename ... on CheckRun{name status conclusion} ... on StatusContext{context state}}}}}}}}}}'

function Consultar {
  $j = gh api graphql -f query=$consultaGql -f o=$dono -f r=$repo -F n=$Pr 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $j) { return $null }
  $p = ($j | ConvertFrom-Json).data.repository.pullRequest
  if (-not $p) { return $null }
  $ctx = @($p.commits.nodes[0].commit.statusCheckRollup.contexts.nodes)
  $falhos = @($ctx | Where-Object { $_.conclusion -in 'FAILURE', 'TIMED_OUT', 'STARTUP_FAILURE' -or $_.state -in 'FAILURE', 'ERROR' } |
    ForEach-Object { if ($_.name) { $_.name } else { $_.context } })
  $assin = ($ctx | ForEach-Object { $n = if ($_.name) { $_.name } else { $_.context }; $s = if ($_.conclusion) { $_.conclusion } elseif ($_.state) { $_.state } else { $_.status }; "$n=$s" }) -join '|'
  return [pscustomobject]@{
    Estado = $p.state; NaFila = [bool]$p.isInMergeQueue; Armado = ($null -ne $p.autoMergeRequest)
    Coment = ([int]$p.comments.totalCount + [int]$p.reviews.totalCount); Falhos = $falhos; Assin = $assin
  }
}

$c = Consultar
if (-not $c) { [Console]::Error.WriteLine("ERRO PR #$Pr nao encontrada (ou gh sem acesso)"); exit 2 }
if ($Referencia) {
  if ($Referencia -notmatch '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$') { [Console]::Error.WriteLine('ERRO hora de referencia deve ser AAAA-MM-DDTHH:MM:SSZ (UTC)'); exit 2 }
  $inicio = $Referencia
} else {
  $inicio = (Get-Date).ToUniversalTime().AddMinutes(-10).ToString('yyyy-MM-ddTHH:mm:ssZ')
}
$ultima = ''; $ultimaMudanca = Get-Date; $falhas = 0

while ($true) {
  $c = Consultar
  if (-not $c) {
    $falhas++
    if ($falhas -ge 5) { [Console]::Error.WriteLine("ERRO gh falhou 5 vezes seguidas na PR #$Pr"); exit 2 }
    Start-Sleep -Seconds $Intervalo; continue
  }
  $falhas = 0
  if ($c.Estado -eq 'MERGED') { "MERGED PR #$Pr mergeada"; exit 0 }
  if ($c.Estado -eq 'CLOSED') { "FECHADA PR #$Pr fechada sem merge"; exit 0 }
  if ($c.Coment -gt 0) { "COMENTARIO PR #$Pr tem comentario ou review (do Leo): desarmar e seguir o passo 9"; exit 0 }
  if ($c.Falhos.Count -gt 0) { "CI_VERMELHA PR #${Pr}: " + ($c.Falhos -join ','); exit 0 }

  if (-not $c.NaFila) {
    $ruins = @(gh run list --event merge_group --limit 20 --json headBranch,conclusion,databaseId,createdAt 2>$null | ConvertFrom-Json |
      Where-Object { $_.headBranch -match "/pr-$Pr-" -and $_.createdAt -ge $inicio -and $_.conclusion -in 'failure', 'timed_out' })
    if ($ruins.Count -gt 0) { "FILA_VERMELHA PR #${Pr}: execucao $($ruins[0].databaseId) (gh run view $($ruins[0].databaseId) --log-failed)"; exit 0 }
    if (-not $c.Armado) { "AUTO_MERGE_DESLIGADO PR #$Pr sem auto-merge e fora da fila"; exit 0 }
  }

  $assin = "$($c.Assin)|$($c.NaFila)|$($c.Armado)"
  if ($assin -ne $ultima) { $ultima = $assin; $ultimaMudanca = Get-Date }
  elseif (((Get-Date) - $ultimaMudanca).TotalMinutes -ge $LimiteMin) { "SEM_MUDANCA PR #$Pr sem mudanca ha $LimiteMin min: reconsultar e relancar o vigia"; exit 0 }
  Start-Sleep -Seconds $Intervalo
}
