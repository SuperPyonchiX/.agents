<#
.SYNOPSIS
   正本 .agents/skills を .claude/skills へ配布する。
.DESCRIPTION
   使用例: & ./Tools/Sync-AgentSkills.ps1 -Check
   -Check は読み取り専用。不整合やパスエラーは例外（CLI 終了コード 1）。
   同期先は生成物専用。初回は Install-AgentHarness.ps1 で既存スキルを統合する。
#>
[CmdletBinding()]
param([switch]$Check, [string]$RelativePath = '', [string]$RepoRoot = '')
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
. (Join-Path $PSScriptRoot 'AgentHarness.Common.ps1')
$repo = Get-HarnessRoot $RepoRoot
$source = Get-HarnessPath $repo '.agents/skills'
$target = Get-HarnessPath $repo '.claude/skills'
$sourceFiles = @(Get-HarnessFiles $source | Where-Object { $_.FullName -ne (Join-Path $source '.gitkeep') })
$targetFiles = @(Get-HarnessFiles $target | Where-Object { $_.FullName -ne (Join-Path $target '.gitkeep') })
if ($sourceFiles.Count -eq 0 -and $targetFiles.Count -gt 0) {
   throw "正本が空ですが配布物があります。自動削除しません: $target"
}
$wanted = @{}
foreach ($file in $sourceFiles) { $wanted[$file.FullName.Substring($source.Length + 1)] = $file.FullName }
if ($RelativePath) {
   $null = Get-HarnessPath $source $RelativePath
   $RelativePath = $RelativePath.Replace('/', '\')
   if (-not $wanted.ContainsKey($RelativePath)) { throw "正本にありません: $RelativePath" }
}
# 全件を事前検証してから変更する。
$copies = @{}
$extras = @()
foreach ($relative in @($wanted.Keys | Sort-Object)) {
   if ($RelativePath -and $relative -ne $RelativePath) { continue }
   $destination = Get-HarnessPath $target $relative
   if ((Test-Path -LiteralPath $destination) -and -not (Test-Path -LiteralPath $destination -PathType Leaf)) {
      throw "ファイルとディレクトリが衝突しています: $destination"
   }
   $bytes = [IO.File]::ReadAllBytes($wanted[$relative])
   if (-not (Test-HarnessBytes $destination $bytes)) { $copies[$destination] = $bytes }
}
if (-not $RelativePath) {
   $extras = @($targetFiles | Where-Object { -not $wanted.ContainsKey($_.FullName.Substring($target.Length + 1)) })
}
if ($Check -and ($copies.Count -or $extras.Count)) {
   throw ("正本と配布物が不一致です。同期を実行してください: " + ((@($copies.Keys) + @($extras | ForEach-Object { $_.FullName })) -join ', '))
}
if (-not $Check) {
   foreach ($destination in $copies.Keys) {
      Assert-HarnessNoLink $destination
      [void][IO.Directory]::CreateDirectory((Split-Path -Parent $destination))
      [IO.File]::WriteAllBytes($destination, $copies[$destination])
   }
   foreach ($extra in $extras) {
      $safe = Get-HarnessPath $target $extra.FullName.Substring($target.Length + 1)
      [IO.File]::Delete($safe)
   }
}
Write-Host ("[OK] スキル同期{0}: 更新 {1}、余剰 {2}" -f $(if ($Check) { '検査' } else { '' }), $copies.Count, $extras.Count)
