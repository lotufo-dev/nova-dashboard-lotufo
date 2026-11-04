# Vigia de uma PR com auto-merge ligado (skill orquestrar, passo 9), versao Windows de vigia.sh.
# Uso: powershell -NoProfile -ExecutionPolicy Bypass -File vigia.ps1 <PR> [intervalo (60)] [limite em minutos (60)]
# Termina imprimindo MERGED | FECHADA | CI_VERMELHA | FILA_VERMELHA | AUTO_MERGE_DESLIGADO | COMENTARIO | SEM_MUDANCA
# (exit 0), ou ERRO (exit 2) se a PR nao existe ou o gh falha repetidas vezes.
param([Parameter(Mandatory = $true)][string]$Pr, [int]$Intervalo = 60, [int]$LimiteMin = 60)
if ($Pr -notmatch '^\d+$') { [Console]::Error.WriteLine('ERRO uso: vigia.ps1 <numero da PR>'); exit 2 }

function Consultar {
  $j = gh pr view $Pr --json state,autoMergeRequest,comments,reviews 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $j) { return $null }
  $o = $j | ConvertFrom-Json
  return [pscustomobject]@{ Estado = $o.state; Armado = ($null -ne $o.autoMergeRequest); Coment = (@($o.comments).Count + @($o.reviews).Count) }
}

$c = Consultar
if (-not $c) { [Console]::Error.WriteLine("ERRO PR #$Pr nao encontrada (ou gh sem acesso)"); exit 2 }
$inicial = $c.Coment
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
  if ($c.Coment -gt $inicial) { "COMENTARIO PR #$Pr tem comentario ou review novo (do Leo): desarmar e seguir o passo 9"; exit 0 }

  $checks = @(gh pr checks $Pr --json name,bucket 2>$null | ConvertFrom-Json)
  $falhos = @($checks | Where-Object { $_.bucket -eq 'fail' })
  if ($falhos.Count -gt 0) { "CI_VERMELHA PR #${Pr}: " + (($falhos | ForEach-Object { $_.name }) -join ','); exit 0 }

  $runs = @(gh run list --event merge_group --limit 20 --json headBranch,conclusion,databaseId 2>$null | ConvertFrom-Json |
    Where-Object { $_.headBranch -match "/pr-$Pr-" })
  $ruins = @($runs | Where-Object { $_.conclusion -in 'failure', 'cancelled', 'timed_out' })
  if ($ruins.Count -gt 0) { "FILA_VERMELHA PR #${Pr}: execucao $($ruins[0].databaseId) (gh run view $($ruins[0].databaseId) --log-failed)"; exit 0 }

  if (-not $c.Armado) { "AUTO_MERGE_DESLIGADO PR #$Pr sem auto-merge (o GitHub desliga quando a fila falha)"; exit 0 }

  $assin = ($checks | ForEach-Object { "$($_.name)=$($_.bucket)" }) -join '|'
  $assin += '|' + (($runs | ForEach-Object { "$($_.databaseId)=$($_.conclusion)" }) -join '|')
  if ($assin -ne $ultima) { $ultima = $assin; $ultimaMudanca = Get-Date }
  elseif (((Get-Date) - $ultimaMudanca).TotalMinutes -ge $LimiteMin) { "SEM_MUDANCA PR #$Pr sem mudanca ha $LimiteMin min: reconsultar e relancar o vigia"; exit 0 }
  Start-Sleep -Seconds $Intervalo
}
