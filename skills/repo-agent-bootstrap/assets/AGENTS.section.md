<!-- repo-agent-bootstrap:begin -->
## エージェント共通運用

- 共通指示の正本は `AGENTS.md`。Claude は `CLAUDE.md` から参照する。
- プロジェクト固有スキルは `.agents/skills/` を編集する。`.claude/skills/` は生成物で、直接編集しない。
- 正本を変更したら `powershell -NoProfile -File Tools/Sync-AgentSkills.ps1` を実行し、正本と配布物を同じ変更に含める。
- `powershell -NoProfile -File Tools/Test-AgentHarness.ps1` で指示の入口・スキル構造・配布物を検査する。PowerShell 7 では `powershell` を `pwsh` に置き換える。
- 指示・スキル・配布物・Tools の共通ハーネススクリプトを Git 管理する。個人設定や認証情報は含めない。
<!-- repo-agent-bootstrap:end -->
