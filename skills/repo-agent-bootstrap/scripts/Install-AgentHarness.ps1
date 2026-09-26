<#
.SYNOPSIS
   調査済みリポジトリへ共通ハーネスを導入する。
.DESCRIPTION
   使用例: & ./scripts/Install-AgentHarness.ps1 -RepoRoot D:/work/repository -Check
   -Check は事前検査のみで書き込まない。通常実行は不足分を作成する。
   衝突は書き込み前に例外（CLI 終了コード 1）。既存の別実装を強制置換するオプションはない。
#>
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$RepoRoot, [switch]$Check)
$assets = Join-Path (Split-Path -Parent $PSScriptRoot) 'assets'
. (Join-Path $assets 'Tools/AgentHarness.Common.ps1')
$repo = Get-HarnessRoot $RepoRoot
$pending = @{}
$utf8 = New-Object System.Text.UTF8Encoding($false)
function Add-HarnessWrite {
   param([string]$RelativePath, [byte[]]$Bytes, [switch]$AllowUpdate)
   $path = Get-HarnessPath $repo $RelativePath
   if (Test-Path -LiteralPath $path) {
      if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "ファイルとディレクトリが衝突しています: $path" }
      if (Test-HarnessBytes $path $Bytes) { return }
      if (-not $AllowUpdate) { throw "同名・異内容のファイルがあります。内容を確認して統合してください: $path" }
   }
   # 親にファイルがあるケースも書き込み前に拒否する。
   $parent = Split-Path -Parent $path
   while ($parent -ne $repo) {
      if ((Test-Path -LiteralPath $parent) -and -not (Test-Path -LiteralPath $parent -PathType Container)) { throw "親がディレクトリではありません: $parent" }
      $parent = Split-Path -Parent $parent
   }
   $pending[$path] = $Bytes
}
# リンクは対象ファイル・スキルツリー・親階層のすべてで拒否する。
$source = Get-HarnessPath $repo '.agents/skills'
$target = Get-HarnessPath $repo '.claude/skills'
$null = @(Get-HarnessFiles $source)
$legacy = @(Get-HarnessFiles $target)
foreach ($file in $legacy) {
   $relative = $file.FullName.Substring($target.Length + 1)
   if ($relative -eq '.gitkeep') { continue }
   Add-HarnessWrite ('.agents/skills/' + $relative) ([IO.File]::ReadAllBytes($file.FullName))
}
$agentsPath = Get-HarnessPath $repo 'AGENTS.md'
$entryPath = Get-HarnessPath $repo 'CLAUDE.md'
$agentsText = if (Test-Path -LiteralPath $agentsPath -PathType Leaf) { [IO.File]::ReadAllText($agentsPath) } else { '' }
$entryText = if (Test-Path -LiteralPath $entryPath -PathType Leaf) { [IO.File]::ReadAllText($entryPath) } else { '' }
$newEntry = [IO.File]::ReadAllBytes((Join-Path $assets 'CLAUDE.md'))
if ($entryText -and -not (Test-HarnessEntry $entryText)) {
   if ($agentsText) { throw "両方に独自指示があります。AGENTS.md と CLAUDE.md を内容確認・統合してから再実行してください: $repo" }
   # 事前にエージェントが読んで共通指示だけと判断した場合に使用する。
   $agentsText = $entryText
   Add-HarnessWrite 'CLAUDE.md' $newEntry -AllowUpdate
} elseif (-not $entryText) {
   Add-HarnessWrite 'CLAUDE.md' $newEntry -AllowUpdate
} else {
   foreach ($line in ($entryText -split '\r?\n')) {
      if ($line -match '^@(\.claude/.+?)\s*$') {
         $reference = Get-HarnessPath $repo $Matches[1]
         if (-not (Test-Path -LiteralPath $reference -PathType Leaf)) { throw "参照先がありません: $reference" }
      }
   }
}
$section = [IO.File]::ReadAllText((Join-Path $assets 'AGENTS.section.md'))
if ($agentsText.Contains('<!-- repo-agent-bootstrap:begin -->')) {
   if (-not $agentsText.Contains('<!-- repo-agent-bootstrap:end -->')) { throw "共通運用節の終了マーカーがありません: $agentsPath" }
} else {
   if (-not $agentsText) { $agentsText = "# プロジェクト共通指示" }
   $agentsText = $agentsText.TrimEnd() + [Environment]::NewLine + [Environment]::NewLine + $section
}
Add-HarnessWrite 'AGENTS.md' ($utf8.GetBytes($agentsText)) -AllowUpdate
foreach ($file in Get-HarnessFiles (Join-Path $assets 'Tools')) {
   Add-HarnessWrite ('Tools/' + $file.Name) ([IO.File]::ReadAllBytes($file.FullName))
}
# clone 後にも空のスキル置き場を残す。
foreach ($relative in @('.agents/skills/.gitkeep','.claude/skills/.gitkeep')) {
   $path = Get-HarnessPath $repo $relative
   if (-not (Test-Path -LiteralPath $path)) { Add-HarnessWrite $relative ([byte[]]@()) }
}
# 正本だけにあるファイルも配布予定へ追加。双方向衝突は上記で検出済み。
foreach ($file in @(Get-HarnessFiles $source)) {
   $relative = $file.FullName.Substring($source.Length + 1)
   if ($relative -eq '.gitkeep') { continue }
   Add-HarnessWrite ('.claude/skills/' + $relative) ([IO.File]::ReadAllBytes($file.FullName))
}
Write-Host ("[PLAN] 導入差分 {0} 件" -f $pending.Count)
foreach ($path in @($pending.Keys | Sort-Object)) { Write-Host $path }
if ($Check) { return }
foreach ($path in @($pending.Keys | Sort-Object)) {
   Assert-HarnessNoLink $path
   [void][IO.Directory]::CreateDirectory((Split-Path -Parent $path))
   [IO.File]::WriteAllBytes($path, $pending[$path])
}
& (Join-Path $repo 'Tools/Test-AgentHarness.ps1') -RepoRoot $repo
