"""共通ハーネスの回帰検査。使用法: python test_bootstrap.py --shell powershell
Python 3 標準ライブラリのみ。合格 0 / 不合格 1。実リポジトリを変更しない。
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1]
SHELL = "powershell"
SPEC = "---\nname: example\ndescription: テスト用のスキル\n---\n\n既存の手順。\n"


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="repo-agent-bootstrap-")).resolve()
        self.repo = self.base / "repo with spaces"
        self.repo.mkdir()
        self.junctions = []

    def tearDown(self):
        # 実測した一時ルート内だけを削除。ジャンクションは先にリンク本体を除去する。
        temp = Path(tempfile.gettempdir()).resolve()
        self.assertEqual(self.base.parent, temp)
        self.assertTrue(self.base.name.startswith("repo-agent-bootstrap-"))
        for junction in self.junctions:
            self.assertTrue(junction.is_relative_to(self.base))
            if junction.exists():
                os.rmdir(junction)
        shutil.rmtree(self.base)

    def write(self, rel, data):
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
        return path

    def run_ps(self, script, *args, ok=True):
        result = subprocess.run(
            [SHELL, "-NoProfile", "-NonInteractive", "-File", str(script), *map(str, args)],
            capture_output=True, timeout=40,
        )
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace"))
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def install(self, *args, ok=True):
        return self.run_ps(SKILL / "scripts/Install-AgentHarness.ps1", "-RepoRoot", self.repo, *args, ok=ok)

    def check(self, ok=True):
        return self.run_ps(self.repo / "Tools/Test-AgentHarness.ps1", ok=ok)

    def sync(self, *args, ok=True):
        return self.run_ps(self.repo / "Tools/Sync-AgentSkills.ps1", *args, ok=ok)

    def snapshot(self):
        return {str(p.relative_to(self.repo)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
                for p in self.repo.rglob("*") if p.is_file()}

    def test_empty_and_idempotent(self):
        self.install("-Check")
        self.assertEqual(list(self.repo.iterdir()), [])
        self.install()
        self.check()
        initial = self.snapshot()
        self.install()
        self.sync()
        self.assertEqual(initial, self.snapshot())
        self.assertFalse(list((self.repo / ".agents/skills").glob("*/SKILL.md")))

    def test_claude_only_migration_preserves_bytes(self):
        original = "# 独自規約\n\n既存仕様を保持する。\n"
        self.write("CLAUDE.md", original)
        self.write(".claude/skills/example/SKILL.md", SPEC)
        binary = bytes(range(256))
        self.write(".claude/skills/example/assets/data.bin", binary)
        self.install()
        self.assertTrue((self.repo / "AGENTS.md").read_text("utf-8").startswith(original.rstrip()))
        self.assertEqual((self.repo / ".agents/skills/example/assets/data.bin").read_bytes(), binary)
        self.assertEqual((self.repo / ".agents/skills/example/SKILL.md").read_text("utf-8"), SPEC)
        self.check()

    def test_conflicting_skills_fail_before_writes(self):
        self.write(".agents/skills/example/SKILL.md", SPEC)
        self.write(".claude/skills/example/SKILL.md", SPEC + "独自変更\n")
        initial = self.snapshot()
        self.install(ok=False)
        self.assertEqual(initial, self.snapshot())

    def test_conflicting_instructions_fail_before_writes(self):
        self.write("AGENTS.md", "# 共通\n既存指示\n")
        self.write("CLAUDE.md", "# Claude\n別の指示\n")
        initial = self.snapshot()
        self.install(ok=False)
        self.assertEqual(initial, self.snapshot())

    def test_claude_specific_reference(self):
        self.write("AGENTS.md", "# 共通\n独自規約\n")
        self.write("CLAUDE.md", "# Claude\n\n@AGENTS.md\n@.claude/project-notes.md\n")
        specific = self.write(".claude/project-notes.md", "# Claude 専用\n設定メモ\n").read_bytes()
        self.install()
        self.check()
        self.assertEqual((self.repo / ".claude/project-notes.md").read_bytes(), specific)
        (self.repo / ".claude/project-notes.md").unlink()
        self.check(ok=False)

    def test_existing_tool_collision_is_nonmutating(self):
        self.write("Tools/Sync-AgentSkills.ps1", "# 独自実装\n")
        initial = self.snapshot()
        self.install(ok=False)
        self.assertEqual(initial, self.snapshot())

    def test_missing_modified_extra_distribution_readonly(self):
        self.write(".agents/skills/example/SKILL.md", SPEC)
        self.install()
        for change in ("missing", "modified", "extra"):
            with self.subTest(change=change):
                target = self.repo / ".claude/skills/example/SKILL.md"
                if change == "missing":
                    target.unlink()
                elif change == "modified":
                    target.write_text("改変", encoding="utf-8")
                else:
                    self.write(".claude/skills/extra.txt", "余剰")
                before = self.snapshot()
                self.sync("-Check", ok=False)
                self.check(ok=False)
                self.assertEqual(before, self.snapshot())
                self.sync()
                self.check()

    def test_empty_source_does_not_delete_distribution(self):
        self.write(".agents/skills/example/SKILL.md", SPEC)
        self.install()
        (self.repo / ".agents/skills/example/SKILL.md").unlink()
        before = self.snapshot()
        self.sync(ok=False)
        self.assertEqual(before, self.snapshot())

    def test_relative_path_rejects_escape_and_missing(self):
        self.write(".agents/skills/example/SKILL.md", SPEC)
        self.install()
        before = self.snapshot()
        for bad in ("../outside", r"..\outside", "C:/outside", "example/missing", "example/SKILL.md:stream"):
            self.sync("-RelativePath", bad, ok=False)
        self.assertEqual(before, self.snapshot())

    def test_relative_sync_leaves_other_file_unchanged(self):
        self.write(".agents/skills/example/SKILL.md", SPEC)
        self.write(".agents/skills/example/LESSONS.md", "before")
        self.install()
        self.write(".agents/skills/example/LESSONS.md", "after")
        target = self.write(".claude/skills/example/SKILL.md", "manual")
        self.sync("-RelativePath", "example/LESSONS.md")
        self.assertEqual(target.read_text("utf-8"), "manual")
        self.assertEqual((self.repo / ".claude/skills/example/LESSONS.md").read_text("utf-8"), "after")

    def test_skill_structure_errors(self):
        self.write(".agents/skills/example/SKILL.md", SPEC)
        self.install()
        for invalid in ("no frontmatter", SPEC.replace("name: example", "name: other"), SPEC.replace("description: テスト用のスキル", 'description: ""')):
            self.write(".agents/skills/example/SKILL.md", invalid)
            self.sync()
            self.check(ok=False)

    def test_portable_copy(self):
        self.write(".agents/skills/example/SKILL.md", SPEC)
        self.install()
        clone = self.base / "clone"
        shutil.copytree(self.repo, clone)
        shutil.rmtree(self.repo)
        self.run_ps(clone / "Tools/Test-AgentHarness.ps1")

    def test_file_directory_collision_preflight(self):
        self.install()
        self.write(".agents/skills/example/SKILL.md", SPEC)
        self.write(".claude/skills/example", "not a directory")
        before = self.snapshot()
        self.sync(ok=False)
        self.assertEqual(before, self.snapshot())

    def test_junction_rejected(self):
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "sentinel.txt").write_text("keep", encoding="utf-8")
        parent = self.repo / ".agents"
        parent.mkdir()
        link = parent / "skills"
        # 一時領域内の固定した2パスのみ。作成後は実体を辿る前に拒否されることを検証する。
        command = "New-Item -ItemType Junction -Path '" + str(link).replace("'", "''") + "' -Target '" + str(outside).replace("'", "''") + "' | Out-Null"
        result = subprocess.run([SHELL, "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.junctions.append(link)
        self.install(ok=False)
        self.assertEqual((outside / "sentinel.txt").read_text("utf-8"), "keep")
        self.assertFalse((self.repo / "AGENTS.md").exists())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--shell", default="powershell")
    args, rest = parser.parse_known_args()
    SHELL = args.shell
    if not shutil.which(SHELL):
        parser.error("PowerShell が見つかりません: " + SHELL)
    unittest.main(argv=[__file__, *rest], verbosity=2)
