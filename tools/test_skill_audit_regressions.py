"""監査で見つけた誤合格・途中失敗の回帰検査。外部通信は全てモック。

リポジトリ直下で python tools/test_skill_audit_regressions.py を実行する。
標準ライブラリのみ。終了コード0=全件成功、1=テスト失敗。
"""
import argparse
import contextlib
import importlib.util
import http.client
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'skills' / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


trace = load('trace', 'nextdesign-cpp14-implementation/scripts/check_traceability.py')
audit = load('audit', 'skill-portfolio-audit/scripts/audit_skills.py')
claude = load('ask_claude', 'second-opinion/scripts/ask_claude.py')
sys.path.insert(0, str(ROOT / 'skills/notion-api/scripts'))
import notion_page as notion


class TemporaryCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def file(self, name, text):
        p = self.folder / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')
        return p

    def run_ledger(self, skill, script, text, expected, diagnostic=None):
        p = self.file('ledger.md', text)
        result = subprocess.run([sys.executable, str(ROOT/'skills'/skill/'scripts'/script), str(p)],
                                capture_output=True, text=True, encoding='utf-8',
                                env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        if expected == 1:
            self.assertIn('ERROR', result.stdout)
        if diagnostic:
            self.assertIn(diagnostic, result.stdout)
        return result.stdout


class LedgerTests(TemporaryCase):
    def test_review_missing_reason_column(self):
        self.run_ledger('cpp14-code-review', 'check_review_log.py',
                        '| ID | 状態 |\n|---|---|\n| R-01 | accepted |\n', 1, '必須の対応/理由列がない')

    def test_review_valid_and_duplicate(self):
        text = '| ID | 状態 | 対応/理由 |\n|---|---|---|\n| R-01 | accepted | 了承済み |\n'
        self.run_ledger('cpp14-code-review', 'check_review_log.py', text, 0)
        self.run_ledger('cpp14-code-review', 'check_review_log.py', text + '| R-01 | fixed | 修正済み |\n', 1, '重複')

    def test_review_short_row_after_valid(self):
        text = '| ID | 状態 | 対応/理由 |\n|---|---|---|\n| R-01 | fixed | 修正済 |\n| R-02 | open |\n'
        self.run_ledger('cpp14-code-review', 'check_review_log.py', text, 1, '列数が見出しと一致しない')

    def test_defect_missing_columns(self):
        self.run_ledger('cpp14-defect-analysis', 'check_defect_log.py',
                        '| ID | 状態 |\n|---|---|\n| H-01 | confirmed |\n', 1, '必須列がない')

    def test_defect_valid_and_missing_result(self):
        text = '| ID | 状態 | 検証方法 | 検証結果 |\n|---|---|---|---|\n| H-01 | confirmed | ログ観測 | 再現 |\n'
        self.run_ledger('cpp14-defect-analysis', 'check_defect_log.py', text, 0)
        self.run_ledger('cpp14-defect-analysis', 'check_defect_log.py', text.replace('再現', ''), 1, '検証結果が空')

    def test_trace_statuses(self):
        for status, valid in [('fixed', True), ('accepted', True), ('opne', False),
                              ('逸脱承認待ち', False), ('pending', False), ('open', False)]:
            with self.subTest(status=status):
                p = self.file('trace.md', '| ID | 状態 |\n|---|---|\n| R-01 | ' + status + ' |\n')
                rep = trace.Report()
                counts = trace.check_review_log(p, rep)
                self.assertEqual(not rep.errors, valid, rep.errors)
                self.assertEqual(counts['closed'], int(valid))

    def test_trace_empty_or_duplicate(self):
        for rows in ['', '| R-01 | fixed |\n| R-01 | fixed |\n']:
            p = self.file('trace.md', '| ID | 状態 |\n|---|---|\n' + rows)
            rep = trace.Report()
            trace.check_review_log(p, rep)
            self.assertTrue(rep.errors)

    def test_ui_short_row_after_valid(self):
        valid = '| UI-001 | 指摘 | 対象 | 前 | 変更 | 後 | before.png | after.png | 1 | deferred | 利用者が保留 |\n'
        self.run_ledger('ui-visual-verify', 'check_ui_ledger.py', valid, 0)
        self.run_ledger('ui-visual-verify', 'check_ui_ledger.py', valid + '| UI-002 | open |\n', 1, '列数が不正')
        self.run_ledger('ui-visual-verify', 'check_ui_ledger.py', valid + valid, 1, 'IDが重複')

    def test_ui_closed_requires_evidence(self):
        text = '| UI-001 | 指摘 | 対象 | 前 | 変更 | 120px | before.png | after.png | 1 | closed | 確認済 |\n'
        self.run_ledger('ui-visual-verify', 'check_ui_ledger.py', text, 1)
        self.file('after.png', 'fixture')
        self.run_ledger('ui-visual-verify', 'check_ui_ledger.py', text, 0)


class AuditTests(TemporaryCase):
    def test_warning_count_summary_and_full_output(self):
        validator = self.file('validator.py', "print('WARN   first: detail')\n" +
                              "print('\\n'.join('OK detail' for _ in range(10)))\nprint('ERROR 0 件 / WARN 1 件')\n")
        result = audit.run_validator(str(validator), str(self.folder), ['demo'])['demo']
        self.assertEqual((result['errors'], result['warns'], result['exit_code']), (0, 1, 0))
        self.assertTrue(result['output'][0].startswith('WARN'))
        self.assertGreater(len(result['output']), 6)

    def test_warning_is_aggregated_even_exit_zero(self):
        skills = self.folder/'skills'
        self.file('skills/demo/SKILL.md', '---\nname: demo\ndescription: 調査するときに使う。\n---\n')
        validator = self.file('validator.py', "print('WARN   example: missing reference')\nprint('ERROR 0 件 / WARN 1 件')\n")
        output = self.folder/'out.json'
        with contextlib.redirect_stdout(io.StringIO()):
            code = audit.main([str(skills), '--validator', str(validator), '-o', str(output)])
        result = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(code, 0)
        self.assertEqual(len(result['warns']), 1)
        self.assertEqual(result['validation']['demo']['errors'], 0)

    def test_content_hash_and_deletion_resume(self):
        skills = self.folder/'skills'
        self.file('skills/demo/SKILL.md', '---\nname: demo\ndescription: 調査するときに使う。\n---\n')
        doc = self.file('skills/demo/references/info.md', 'before')
        removed = self.file('skills/demo/references/removed.md', 'delete me')
        self.file('skills/demo/local/secret.txt', 'do not hash')
        old = audit.fingerprint(str(skills), ['demo'])
        self.assertFalse(any('/local/' in x for x in old))
        stamp = doc.stat().st_mtime_ns
        doc.write_text('after!', encoding='utf-8')
        os.utime(doc, ns=(stamp, stamp))
        removed.unlink()
        previous = self.file('old.json', json.dumps({'fingerprints': old}))
        output = self.folder/'new.json'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(audit.main([str(skills), '--compare', str(previous), '-o', str(output)]), 0)
        changed = json.loads(output.read_text(encoding='utf-8'))['changed_files']
        self.assertEqual(changed, ['demo/references/info.md', 'demo/references/removed.md'])


class NotionTests(TemporaryCase):
    def args(self, count=201):
        return argparse.Namespace(properties='{}', blocks=json.dumps([{'type': 'paragraph'}]*count),
                                  data_source_id='fake', icon=None, progress=str(self.folder/'progress.json'))

    def invoke(self, method, args, fake):
        stdout, stderr = io.StringIO(), io.StringIO()
        code = 0
        with patch.object(notion, 'request', side_effect=fake) as req, \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                method(args)
            except SystemExit as exc:
                code = exc.code
        raw = stdout.getvalue()
        return code, json.loads(raw) if raw else None, req.call_args_list

    def test_create_three_batches_success(self):
        sizes = []
        def fake(method, path, payload):
            sizes.append(len(payload['children']))
            return {'id': 'page', 'url': 'https://example.invalid/page'}
        code, result, calls = self.invoke(notion.cmd_create, self.args(), fake)
        self.assertEqual((code, result['status'], result['confirmed_blocks']), (0, 'complete', 202))
        self.assertEqual(sizes, [100, 100, 2])
        self.assertEqual(len(calls), 3)

    def test_partial_create_preserves_id_and_confirmed_progress(self):
        counter = 0
        def fake(method, path, payload):
            nonlocal counter
            counter += 1
            if counter == 3:
                raise SystemExit(1)
            return {'id': 'page', 'url': 'https://example.invalid/page'}
        code, result, calls = self.invoke(notion.cmd_create, self.args(), fake)
        self.assertEqual(code, 3)
        self.assertEqual((result['id'], result['confirmed_blocks'], result['pending_blocks']), ('page', 200, 2))
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(json.loads((self.folder/'progress.json').read_text(encoding='utf-8')), result)
        self.assertEqual(len(calls), 3)  # 不明のバッチを自動再送しない

    def test_create_first_patch_failure_preserves_created_id(self):
        def fake(method, path, payload):
            if method == 'PATCH':
                saved = json.loads((self.folder/'progress.json').read_text(encoding='utf-8'))
                self.assertEqual(saved['id'], 'page')
                raise OSError('timeout')
            return {'id': 'page'}
        code, result, _ = self.invoke(notion.cmd_create, self.args(101), fake)
        self.assertEqual((code, result['confirmed_blocks'], result['id']), (3, 100, 'page'))

    def test_post_response_unknown_does_not_retry(self):
        code, result, calls = self.invoke(notion.cmd_create, self.args(0), OSError('timeout'))
        self.assertEqual((code, result['status'], result['id']), (3, 'unknown', None))
        self.assertEqual(len(calls), 1)

    def test_missing_token_keeps_input_error(self):
        code, result, _ = self.invoke(notion.cmd_create, self.args(0), SystemExit(2))
        self.assertEqual((code, result), (2, None))

    def test_unreadable_post_response_is_unknown(self):
        for fake in [ValueError('invalid response JSON'), http.client.IncompleteRead(b'partial'), lambda *a: {}]:
            code, result, calls = self.invoke(notion.cmd_create, self.args(0), fake)
            self.assertEqual((code, result['status']), (3, 'unknown'))
            self.assertEqual(len(calls), 1)

    def test_http_exception_during_patch_preserves_id(self):
        def fake(method, path, payload):
            if method == 'PATCH':
                raise http.client.BadStatusLine('broken HTTP response')
            return {'id': 'page'}
        code, result, calls = self.invoke(notion.cmd_create, self.args(101), fake)
        self.assertEqual((code, result['status'], result['id']), (3, 'partial', 'page'))
        self.assertEqual(len(calls), 2)

    def test_interrupt_leaves_recoverable_progress(self):
        def fake(method, path, payload):
            if method == 'PATCH':
                raise KeyboardInterrupt()
            return {'id': 'page'}
        with self.assertRaises(KeyboardInterrupt):
            self.invoke(notion.cmd_create, self.args(101), fake)
        saved = json.loads((self.folder/'progress.json').read_text(encoding='utf-8'))
        self.assertEqual((saved['status'], saved['id'], saved['confirmed_blocks'], saved['pending_blocks']),
                         ('sending', 'page', 100, 2))

    def test_progress_unwritable_stops_before_post(self):
        args = self.args()
        args.progress = str(self.folder/'missing'/'state.json')
        code, result, calls = self.invoke(notion.cmd_create, args, AssertionError('no request expected'))
        self.assertEqual((code, result, len(calls)), (2, None, 0))

    def test_progress_write_fails_after_post_id_still_returned(self):
        def fake(method, path, payload):
            return {'id': 'page'}
        real_save = notion.save_progress
        def save(args, state):
            if state['id']:
                raise OSError('disk full')
            real_save(args, state)
        with patch.object(notion, 'save_progress', side_effect=save):
            code, result, calls = self.invoke(notion.cmd_create, self.args(0), fake)
        self.assertEqual((code, result['id'], result['confirmed_blocks']), (3, 'page', 1))
        self.assertEqual(len(calls), 1)

    def test_append_mismatch_prevents_write(self):
        args = self.args(2)
        args.page_id, args.expected_count = 'page', 99
        code, result, calls = self.invoke(notion.cmd_append, args, lambda *a: {'results': [1]*100, 'has_more': False})
        self.assertEqual((code, result, len(calls)), (2, None, 1))
        self.assertEqual(calls[0].args[0], 'GET')

    def test_append_reads_all_pages_then_sends_only_missing(self):
        args = self.args(2)
        args.page_id, args.expected_count = 'page', 101
        responses = iter([{'results': [1]*100, 'has_more': True, 'next_cursor': 'next'},
                          {'results': [1], 'has_more': False}, {}])
        code, result, calls = self.invoke(notion.cmd_append, args, lambda *a: next(responses))
        self.assertEqual((code, result['confirmed_blocks']), (0, 103))
        self.assertEqual([call.args[0] for call in calls], ['GET', 'GET', 'PATCH'])
        self.assertEqual(len(calls[-1].args[2]['children']), 2)


class ClaudeTests(TemporaryCase):
    def test_normal_tools_and_no_delegation(self):
        cmd = claude.build_command('claude')
        for option in ['--tools', '--safe-mode', '--strict-mcp-config', '--disable-slash-commands', '--permission-mode', '--system-prompt']:
            self.assertNotIn(option, cmd)
        self.assertEqual(cmd[cmd.index('--disallowedTools')+1], 'Agent,Task')
        self.assertIn('別の生成AIへの相談', cmd[cmd.index('--append-system-prompt')+1])

    def test_success_and_cli_error(self):
        q = self.file('q.md', '根拠を示して検討してください。')
        out = self.folder/'answer.md'
        for success in [True, False]:
            with self.subTest(success=success):
                response = subprocess.CompletedProcess([], 0, json.dumps({'result': '独立した回答', 'is_error': not success}), '')
                with patch.object(claude.shutil, 'which', return_value='claude'), \
                        patch.object(claude.subprocess, 'run', return_value=response) as run, \
                        contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    code = claude.main(['--prompt-file', str(q), '--out', str(out), '--cd', str(self.folder)])
                self.assertEqual(code, 0 if success else 1)
                self.assertEqual(Path(run.call_args.kwargs['cwd']), self.folder)
                if success:
                    self.assertEqual(out.read_text(encoding='utf-8').strip(), '独立した回答')


if __name__ == '__main__':
    unittest.main(verbosity=2)
