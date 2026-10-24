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
import zipfile
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
agy = load('ask_antigravity', 'second-opinion/scripts/ask_antigravity.py')
sys.path.insert(0, str(ROOT / 'skills/notion-api/scripts'))
import notion_page as notion
recalc = load('recalc_check', 'operate-excel/scripts/recalc_check.py')
EXCEL = ROOT/'skills/operate-excel'
HAS_OPENPYXL = importlib.util.find_spec('openpyxl') is not None
PPT = ROOT/'skills/operate-powerpoint'
HAS_PPTX = importlib.util.find_spec('pptx') is not None


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


class AntigravityTests(TemporaryCase):
    def test_command_is_headless_without_skip_permissions(self):
        cmd = agy.build_command('agy', 600)
        self.assertEqual(cmd[1], '-p')
        self.assertIn('--disable-slash-commands', cmd)
        self.assertEqual(cmd[cmd.index('--output-format')+1], 'json')
        self.assertNotIn('--dangerously-skip-permissions', cmd)
        self.assertIn('別の生成AIへの相談', cmd[2])

    def test_runs_on_copy_and_keeps_original(self):
        src = self.folder/'src'
        self.file('src/a.txt', '元の内容')
        self.file('src/.git/HEAD', 'ref')
        q = self.file('q.md', '根拠を示して検討してください。')
        out = self.folder/'answer.md'
        for status in ['SUCCESS', 'ERROR']:
            with self.subTest(status=status):
                def fake_run(cmd, **kwargs):
                    ws = Path(kwargs['cwd'])
                    self.assertNotEqual(ws, src)
                    self.assertFalse((ws/'.git').exists())
                    self.assertIn('根拠を示して', (ws/agy.QUESTION_NAME).read_text(encoding='utf-8'))
                    (ws/'a.txt').write_text('書き換え', encoding='utf-8')
                    return subprocess.CompletedProcess(cmd, 0, json.dumps({'status': status, 'response': '独立した回答'}), '')
                with patch.object(agy.shutil, 'which', return_value='agy'), \
                        patch.object(agy.subprocess, 'run', side_effect=fake_run), \
                        contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    code = agy.main(['--prompt-file', str(q), '--out', str(out), '--cd', str(src)])
                self.assertEqual(code, 0 if status == 'SUCCESS' else 1)
                self.assertEqual((src/'a.txt').read_text(encoding='utf-8'), '元の内容')
                self.assertEqual(out.exists(), status == 'SUCCESS')

    def test_missing_cli(self):
        q = self.file('q.md', '質問')
        with patch.object(agy.shutil, 'which', return_value=None), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(agy.main(['--prompt-file', str(q), '--out', str(self.folder/'a.md')]), 2)


class ExcelTests(TemporaryCase):
    WORKBOOK = ('<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<sheets><sheet name="表" sheetId="1" r:id="rId1"/></sheets></workbook>')
    RELS = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/></Relationships>')

    def book(self, cells):
        p = self.folder/'calc.xlsx'
        with zipfile.ZipFile(p, 'w') as z:
            z.writestr('xl/workbook.xml', self.WORKBOOK)
            z.writestr('xl/_rels/workbook.xml.rels', self.RELS)
            z.writestr('xl/worksheets/sheet1.xml',
                       '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                       '<sheetData><row r="1">%s</row></sheetData></worksheet>' % cells)
        return p

    def run_script(self, script, *args):
        return subprocess.run([sys.executable, str(EXCEL/'scripts'/script), *map(str, args)],
                              capture_output=True, text=True, encoding='utf-8',
                              env=dict(os.environ, PYTHONIOENCODING='utf-8'))

    def test_recalc_scan_counts_blank_result_and_array_and_shared(self):
        p = self.book('<c r="A1" t="str"><f>IF(B1&gt;0,B1,"")</f><v></v></c>'
                      '<c r="B1"><f t="array" ref="B1">SUM(C1:C2*2)</f><v>4</v></c>'
                      '<c r="C1" t="e"><f t="shared" ref="C1:D1" si="0">1/0</f><v>#DIV/0!</v></c>'
                      '<c r="D1" t="e"><f t="shared" si="0"/><v>#DIV/0!</v></c>'
                      '<c r="E1"><f>F1*2</f></c>'
                      '<c r="F1" t="inlineStr"><is><t>#N/A</t></is></c>')
        formulas, uncalculated, errors, summary = recalc.scan(p)
        self.assertEqual(formulas, 5)
        self.assertEqual(uncalculated, 1)  # E1 だけ。空文字を返す A1 は計算済み
        self.assertEqual(summary, {'#DIV/0!': 2})  # 文字列の "#N/A" はエラーではない
        self.assertEqual([e['formula'] for e in errors], ['=1/0', '（C1 の共有数式）'])

    def test_strip_cached_values_keeps_constants(self):
        src = self.book('<c r="A1"><v>5</v></c><c r="B1"><f>A1*2</f><v>999</v></c>'
                        '<c r="C1"><f t="shared" si="0"/><v>1</v></c>')
        dst = self.folder/'stripped.xlsx'
        recalc.strip_cached_values(src, dst)
        with zipfile.ZipFile(dst) as z:
            xml = z.read('xl/worksheets/sheet1.xml').decode()
        self.assertIn('<c r="A1"><v>5</v></c>', xml)
        self.assertIn('<c r="B1"><f>A1*2</f></c>', xml)
        self.assertIn('<c r="C1"><f t="shared" si="0"/></c>', xml)

    @unittest.skipUnless(recalc.find_soffice(), 'LibreOffice が無い')
    def test_recalc_ignores_stale_cached_value(self):
        src = EXCEL/'evals/files/stale_cache.xlsx'
        before = src.read_bytes()
        result = self.run_script('recalc_check.py', src)
        self.assertEqual(result.returncode, 1, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual([(e['cell'], e['error']) for e in out['errors']], [('D4', '#DIV/0!')])
        self.assertEqual(src.read_bytes(), before)

    @unittest.skipUnless(HAS_OPENPYXL, 'openpyxl が無い')
    def test_inspect_unknown_sheet_is_usage_error(self):
        result = self.run_script('inspect_xlsx.py', EXCEL/'evals/files/stale_cache.xlsx', '--sheet', '無い')
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('Traceback', result.stderr)

    @unittest.skipUnless(HAS_OPENPYXL, 'openpyxl が無い')
    def test_inspect_and_diff_on_bloated_sheet(self):
        import openpyxl
        src = EXCEL/'evals/files/bloated_blank_if.xlsx'
        result = self.run_script('inspect_xlsx.py', src)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('A1:C4（4 行 × 3 列）', result.stdout)
        self.assertIn('使用範囲は A1:GR100000', result.stdout)
        after = self.folder/'after.xlsx'
        wb = openpyxl.load_workbook(src)
        wb.active['B3'] = 65
        wb.save(after)
        result = self.run_script('diff_xlsx.py', src, after)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('変わったセル: 1 件（範囲 B3:B3）', result.stdout)
        self.assertIn('| B3 | 値 | （空） | 65 |', result.stdout)


@unittest.skipUnless(HAS_PPTX, 'python-pptx が無い')
class PowerPointTests(TemporaryCase):
    DECK = PPT/'evals/files/q3_report.pptx'

    def run_script(self, *args):
        return subprocess.run([sys.executable, str(PPT/'scripts/inspect_pptx.py'), *map(str, args)],
                              capture_output=True, text=True, encoding='utf-8',
                              env=dict(os.environ, PYTHONIOENCODING='utf-8'))

    def helpers(self):
        import re
        md = (PPT/'references/python-pptx-helpers.md').read_text(encoding='utf-8')
        blocks = re.findall(r"```python\n(.*?)```", md, re.S)
        g = {}
        exec(blocks[0], g)
        return g

    def test_check_finds_empty_placeholder_table_overlap_and_hidden_slide(self):
        result = self.run_script(self.DECK, '--check')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('スライド 1（画像 p1）: 「Subtitle 2」が空のプレースホルダ', result.stdout)
        self.assertIn('スライド 4（画像 p3）: 「Table 2」と「TextBox 3」が重なっている', result.stdout)
        self.assertIn('スライド 5（画像 p4）: 「Content Placeholder 2」の文字があふれている疑い', result.stdout)
        self.assertIn('非表示スライド: 3', result.stdout)
        self.assertNotIn('スライド 2', result.stdout)  # 収まっているスライドは何も出さない
        self.assertNotIn('ph[', result.stdout)  # --check だけなら図形一覧は出さない

    def test_full_shows_table_cells(self):
        result = self.run_script(self.DECK, '--slides', '4', '--full')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('3 | ログが重複する | 11/19', result.stdout)

    def test_bad_slide_range_is_usage_error(self):
        for spec in ('a', '9', '3-1', ',', '1-', '1,,2'):
            result = self.run_script(self.DECK, '--slides', spec)
            self.assertEqual(result.returncode, 2, spec)
            self.assertNotIn('Traceback', result.stderr)

    def test_delete_then_add_keeps_every_slide(self):
        g = self.helpers()
        prs = g['Presentation'](str(self.DECK))
        g['delete_slide'](prs, 2)
        prs.slides.add_slide(prs.slide_layouts[5]).shapes.title.text = '次回の報告は12月'
        out = self.folder/'out.pptx'
        prs.save(str(out))
        with zipfile.ZipFile(out) as z:
            names = z.namelist()
        self.assertEqual(len(names), len(set(names)))
        titles = [s.shapes.title.text for s in g['Presentation'](str(out)).slides]
        self.assertEqual(titles, ['第3四半期の不具合報告', '不具合は 3 件に減った', '残課題の一覧',
                                  '再発防止の取り組み', '次回の報告は12月'])

    def check(self, prs):
        out = self.folder/'case.pptx'
        prs.save(str(out))
        result = self.run_script(out, '--check')
        self.assertNotIn('Traceback', result.stderr)
        return result

    def test_check_edge_cases(self):
        from pptx import Presentation
        from pptx.chart.data import CategoryChartData
        from pptx.enum.chart import XL_CHART_TYPE
        from pptx.util import Mm, Pt
        prs = Presentation()
        blank = prs.slide_layouts[6]
        # 1: 段落に指定した 10pt（run には指定なし）と、空段落だけが 10pt の枠
        s = prs.slides.add_slide(blank)
        tb = s.shapes.add_textbox(Mm(10), Mm(10), Mm(100), Mm(20))
        tb.text_frame.text = '段落で小さくした'
        tb.text_frame.paragraphs[0].font.size = Pt(10)
        tb2 = s.shapes.add_textbox(Mm(10), Mm(60), Mm(100), Mm(30))
        tb2.text_frame.text = '本文'
        tb2.text_frame.add_paragraph().font.size = Pt(10)
        # 2: 表のセルの 8pt
        s = prs.slides.add_slide(blank)
        cell = s.shapes.add_table(1, 1, Mm(10), Mm(10), Mm(60), Mm(20)).table.cell(0, 0)
        cell.text = '細かい表'
        cell.text_frame.paragraphs[0].runs[0].font.size = Pt(8)
        # 3: 折り返さない枠に4段落（縦にあふれる）
        s = prs.slides.add_slide(blank)
        tb = s.shapes.add_textbox(Mm(10), Mm(10), Mm(100), Mm(10))
        tb.text_frame.text = '一'
        for _ in range(3):
            tb.text_frame.add_paragraph().text = '二'
        # 4: グラフと画像の重なり
        s = prs.slides.add_slide(blank)
        data = CategoryChartData()
        data.categories = ['a', 'b']
        data.add_series('x', (1, 2))
        s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Mm(10), Mm(10), Mm(80), Mm(60), data).name = 'グラフ'
        png = self.folder/'dot.png'
        import base64
        png.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=='))
        s.shapes.add_picture(str(png), Mm(50), Mm(30), Mm(60), Mm(40)).name = '写真'
        # 5: 同じグループの中の重なりは見ない／90度回転したグループの子はスライド外へ出る
        s = prs.slides.add_slide(blank)
        g = s.shapes.add_group_shape()
        card = g.shapes.add_textbox(Mm(150), Mm(20), Mm(80), Mm(40))
        card.text_frame.text = 'カードの見出し'
        inner = g.shapes.add_textbox(Mm(160), Mm(30), Mm(60), Mm(20))
        inner.text_frame.text = 'カードの本文'
        g2 = s.shapes.add_group_shape()
        long = g2.shapes.add_textbox(Mm(10), Mm(170), Mm(200), Mm(10))
        long.text_frame.text = '横長の帯'
        long.name = '帯'
        g2._element.grpSpPr.find('{http://schemas.openxmlformats.org/drawingml/2006/main}xfrm').set('rot', str(90 * 60000))
        out = self.check(prs).stdout
        self.assertIn('スライド 1: 「TextBox 1」に 10pt の文字がある', out)
        self.assertNotIn('「TextBox 2」に', out)  # 空段落の 10pt は数えない
        self.assertIn('スライド 2: 「Table 1」に 8pt の文字がある', out)
        self.assertIn('スライド 3: 「TextBox 1」の文字があふれている疑い（推定: 必要な高さ', out)
        self.assertIn('「グラフ」と「写真」が重なっている', out)
        self.assertNotIn('カード', out)
        self.assertIn('スライド 5: 「帯」がスライドの外にはみ出している', out)

    def test_delete_linked_slide_removes_link(self):
        g = self.helpers()
        prs = g['Presentation']()
        slides = [prs.slides.add_slide(prs.slide_layouts[5]) for _ in range(3)]
        for i, s in enumerate(slides):
            s.shapes.title.text = 's%d' % i
        slides[0].shapes.title.click_action.target_slide = slides[1]
        g['delete_slide'](prs, 1)
        out = self.folder/'link.pptx'
        prs.save(str(out))
        with zipfile.ZipFile(out) as z:
            names = z.namelist()
            first = z.read('ppt/slides/slide1.xml').decode()
        self.assertEqual(len(names), len(set(names)))
        self.assertNotIn('hlinkClick', first)
        self.assertEqual([s.shapes.title.text for s in g['Presentation'](str(out)).slides], ['s0', 's2'])

    def test_potx_opens(self):
        potx = self.folder/'t.potx'
        with zipfile.ZipFile(self.DECK) as src, zipfile.ZipFile(potx, 'w') as dst:
            for item in src.infolist():
                data = src.read(item.filename)
                if item.filename == '[Content_Types].xml':
                    data = data.replace(b'presentationml.presentation.main+xml', b'presentationml.template.main+xml')
                dst.writestr(item, data)
        self.assertEqual(len(self.helpers()['open_template'](str(potx)).slides), 5)
        result = self.run_script(potx, '--outline')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('スライド 4（Title Only・画像 p3）: 残課題の一覧', result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
