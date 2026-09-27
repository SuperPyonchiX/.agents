#!/usr/bin/env python3
"""Codex CLI に質問を1ターン投げ、回答をファイルへ、thread_id を標準出力へ出す。

使い方:
    python ask_codex.py --prompt-file q.md --out a.md [--cd DIR] [--resume THREAD_ID]
                        [--model MODEL] [--timeout SEC]

- 常に read-only サンドボックスで実行する（相手に書き込みをさせない）
- プロンプトは stdin に UTF-8 で渡す（Windows の引数クォートと文字化けを避ける）
- --resume を付けると同じスレッドで会話を続ける。--last は使わない（並行セッションで取り違える）

終了コード:
    0  成功。標準出力の1行目が thread_id
    1  codex の実行失敗・タイムアウト・空回答
    2  codex コマンドが見つからない / 引数・入力ファイルの不備
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def build_command(codex, args):
    common = ["--skip-git-repo-check", "--json", "-o", str(args.out)]
    if args.model:
        common += ["-m", args.model]
    if args.resume:
        # resume は -s を受け付けないので設定で read-only を明示する
        return [codex, "exec", "resume", args.resume, "-c", 'sandbox_mode="read-only"'] + common + ["-"]
    return [codex, "exec", "-s", "read-only"] + common + ["-"]


def main():
    p = argparse.ArgumentParser(description="Codex CLI に read-only で1ターン質問する")
    p.add_argument("--prompt-file", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--cd", type=Path, default=Path.cwd(), help="Codex に読ませる作業ディレクトリ")
    p.add_argument("--resume", help="継続するスレッドの thread_id")
    p.add_argument("--model")
    p.add_argument("--timeout", type=int, default=600)
    args = p.parse_args()
    # 相対パスのままだと codex が --cd 側で解決してしまう
    args.prompt_file = args.prompt_file.resolve()
    args.out = args.out.resolve()
    args.cd = args.cd.resolve()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")

    codex = shutil.which("codex")
    if codex is None:
        print("codex が見つからない。`npm install -g @openai/codex` で導入し、`codex login` を済ませる。"
              "導入できない環境ではブラウザ経路（references/browser-route.md）を使う。", file=sys.stderr)
        return 2
    if not args.prompt_file.is_file():
        print(f"プロンプトファイルが無い: {args.prompt_file}", file=sys.stderr)
        return 2
    if not args.cd.is_dir():
        print(f"作業ディレクトリが無い: {args.cd}", file=sys.stderr)
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        args.out.unlink()
    prompt = args.prompt_file.read_text(encoding="utf-8")

    try:
        proc = subprocess.run(
            build_command(codex, args), input=prompt.encode("utf-8"),
            capture_output=True, cwd=str(args.cd), timeout=args.timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"タイムアウト（{args.timeout} 秒）", file=sys.stderr)
        return 1

    thread_id = None
    errors = []
    for line in proc.stdout.decode("utf-8", errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "thread.started":
            thread_id = ev.get("thread_id")
        elif ev.get("type") in ("error", "turn.failed"):
            errors.append(json.dumps(ev, ensure_ascii=False))

    answer = args.out.read_text(encoding="utf-8").strip() if args.out.exists() else ""
    if proc.returncode != 0 or errors or not answer:
        print(f"codex 実行失敗（終了コード {proc.returncode}）", file=sys.stderr)
        for e in errors:
            print(e, file=sys.stderr)
        tail = proc.stderr.decode("utf-8", errors="replace").strip().splitlines()[-10:]
        print("\n".join(tail), file=sys.stderr)
        if not answer:
            print("回答が空。未ログインなら `codex login` を案内する。", file=sys.stderr)
        return 1

    print(thread_id or args.resume or "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
