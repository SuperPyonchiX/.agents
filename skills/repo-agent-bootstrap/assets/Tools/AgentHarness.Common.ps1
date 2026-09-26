# 共通ハーネスのパス検証。Sync/Test/Install からドットソースする。
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
function Assert-HarnessNoLink {
   param([string]$Path)
   $cursor = [IO.Path]::GetFullPath($Path)
   while ($cursor) {
      $item = Get-Item -LiteralPath $cursor -Force -ErrorAction SilentlyContinue
      if ($item -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
         throw "リンクを検出しました。移行方針を確認してください: $cursor"
      }
      $cursor = Split-Path -Parent $cursor
   }
}
function Get-HarnessRoot {
   param([string]$RepoRoot)
   if (-not [IO.Path]::IsPathRooted($RepoRoot)) { throw "RepoRoot は絶対パスで指定してください: $RepoRoot" }
   $resolved = [IO.Path]::GetFullPath($RepoRoot).TrimEnd('\','/')
   if (-not (Test-Path -LiteralPath $resolved -PathType Container)) { throw "対象ディレクトリがありません: $RepoRoot" }
   Assert-HarnessNoLink $resolved
   return $resolved
}
function Get-HarnessPath {
   param([string]$Root, [string]$RelativePath)
   if (-not $RelativePath -or [IO.Path]::IsPathRooted($RelativePath) -or
       $RelativePath -match '(^|[\\/])\.\.?([\\/]|$)|[:*?]' -or
       $RelativePath -match '(^|[\\/])[^\\/]*[. ]([\\/]|$)') {
      throw "不正な相対パス: $RelativePath"
   }
   $result = [IO.Path]::GetFullPath((Join-Path $Root $RelativePath))
   if (-not $result.StartsWith($Root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
      throw "対象範囲外: $result"
   }
   Assert-HarnessNoLink $result
   $parent = Split-Path -Parent $result
   while ($parent -and $parent -ne $Root) {
      if ((Test-Path -LiteralPath $parent) -and -not (Test-Path -LiteralPath $parent -PathType Container)) { throw "親がディレクトリではありません: $parent" }
      $parent = Split-Path -Parent $parent
   }
   return $result
}
function Get-HarnessFiles {
   param([string]$Directory)
   Assert-HarnessNoLink $Directory
   if (-not (Test-Path -LiteralPath $Directory)) { return }
   if (-not (Test-Path -LiteralPath $Directory -PathType Container)) { throw "ディレクトリではありません: $Directory" }
   foreach ($item in Get-ChildItem -LiteralPath $Directory -Force) {
      Assert-HarnessNoLink $item.FullName
      if ($item.PSIsContainer) { Get-HarnessFiles $item.FullName } else { $item }
   }
}
function Test-HarnessBytes {
   param([string]$Path, [byte[]]$Bytes)
   if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
   $actual = [IO.File]::ReadAllBytes($Path)
   return [Convert]::ToBase64String($actual) -ceq [Convert]::ToBase64String($Bytes)
}
function Test-HarnessEntry {
   param([string]$Text)
   if ($Text -notmatch '(?m)^@AGENTS\.md\s*$') { return $false }
   foreach ($line in ($Text -split '\r?\n')) {
      if ($line -match '^\s*$|^# |^@AGENTS\.md\s*$|^@\.claude/[a-zA-Z0-9_/-]+\.md\s*$') { continue }
      return $false
   }
   return $true
}
