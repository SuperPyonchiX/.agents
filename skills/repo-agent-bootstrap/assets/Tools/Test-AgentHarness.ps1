<#
.SYNOPSIS
   共通指示・スキル構造・配布状態を読み取り専用で検査する。
.DESCRIPTION
   使用例: & ./Tools/Test-AgentHarness.ps1 -RepoRoot D:/work/repository
   正常終了は 0。不整合はパス付き例外（CLI 終了コード 1）。
#>
[CmdletBinding()]
param([string]$RepoRoot = '')
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
. (Join-Path $PSScriptRoot 'AgentHarness.Common.ps1')
$repo = Get-HarnessRoot $RepoRoot
foreach ($relative in @('AGENTS.md','CLAUDE.md','Tools/Sync-AgentSkills.ps1','Tools/AgentHarness.Common.ps1')) {
   $path = Get-HarnessPath $repo $relative
   if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "必要なファイルがありません: $path" }
}
$agents = Get-HarnessPath $repo 'AGENTS.md'
if ([string]::IsNullOrWhiteSpace([IO.File]::ReadAllText($agents))) { throw "共通指示が空です: $agents" }
$entry = Get-HarnessPath $repo 'CLAUDE.md'
$text = [IO.File]::ReadAllText($entry)
if (-not (Test-HarnessEntry $text)) { throw "CLAUDE.md は見出しと @AGENTS.md、必要な .claude/*.md の参照にしてください: $entry" }
foreach ($line in ($text -split '\r?\n')) {
   if ($line -match '^@(.+?)\s*$') {
      $reference = Get-HarnessPath $repo $Matches[1]
      if (-not (Test-Path -LiteralPath $reference -PathType Leaf)) { throw "入口の参照先がありません: $reference" }
   }
}
foreach ($relative in @('.agents/skills','.claude/skills')) {
   $path = Get-HarnessPath $repo $relative
   # Git は空フォルダを保存しないため、両方とも未作成でもスキルゼロとして扱う。
   $null = @(Get-HarnessFiles $path)
}
$source = Get-HarnessPath $repo '.agents/skills'
if (Test-Path -LiteralPath $source) {
   foreach ($item in Get-ChildItem -LiteralPath $source -Force) {
      if ($item.Name -eq '.gitkeep' -and -not $item.PSIsContainer) { continue }
      if (-not $item.PSIsContainer) { throw "スキル直下にはスキルディレクトリを置いてください: $($item.FullName)" }
      $spec = Get-HarnessPath $item.FullName 'SKILL.md'
      if (-not (Test-Path -LiteralPath $spec -PathType Leaf)) { throw "SKILL.md がありません: $spec" }
      $body = [IO.File]::ReadAllText($spec)
      if ($body -notmatch '\A---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)') { throw "frontmatter がありません: $spec" }
      $front = $Matches[1]
      if ($front -notmatch '(?m)^name:\s*[''"]?([a-z0-9]+(?:-[a-z0-9]+)*)[''"]?\s*$') { throw "name が不正です: $spec" }
      if ($Matches[1] -cne $item.Name -or $item.Name.Length -gt 64) { throw "name とディレクトリ名が一致しません: $spec" }
      if ($front -notmatch '(?m)^description:[ \t]*(\S[^\r\n]*)') { throw "description がありません: $spec" }
      $description = $Matches[1].Trim()
      if ($description -in @('""',"''") -or ($description -match '^[>|][+-]?$' -and $front -notmatch '(?m)^description:[ \t]*[>|][+-]?\r?\n[ \t]+\S')) {
         throw "description が空です: $spec"
      }
   }
}
& (Join-Path $PSScriptRoot 'Sync-AgentSkills.ps1') -RepoRoot $repo -Check
Write-Host '[OK] 共通ハーネス検査'
