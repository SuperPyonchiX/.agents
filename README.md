# ~/.agents — Agent Skills 置き場

個人用 Agent Skills（`SKILL.md`）の**実体を1箇所に集めたリポジトリ**。
Claude Code / GitHub Copilot / Codex / Gemini CLI のどれを使っても、同じスキルが効くようにするための置き場所である。

## これは何か

Agent Skills は、AIエージェントに「作業手順」を渡すためのオープン標準。実体は `SKILL.md` を1つ置いたフォルダにすぎず、書式はただのMarkdownである。

問題は**探索パスがツールごとに違う**こと。

| ツール | 見に行く場所 |
| --- | --- |
| GitHub Copilot | `.github/skills/`, `.claude/skills/`, `.agents/skills/` |
| Codex | `.agents/skills/` |
| Gemini CLI | `.agents/skills/` |
| Claude Code | `.claude/skills/` のみ |

そこで **`~/.agents/skills/` を実体とし、`~/.claude/skills` からシンボリックリンクを張る**。これで4ツールすべてが同じファイルを読む。二重管理は発生しない。

```mermaid
graph LR
    A["~/.agents/skills/<br/>（実体・Git管理対象）"] --> B[Codex]
    A --> C[Gemini CLI]
    A --> D[GitHub Copilot]
    A --> E["~/.claude/skills<br/>（シンボリックリンク・Git管理外）"]
    E --> F[Claude Code]
```

リンクは環境ごとに1回張るだけ。リポジトリには含めない（後述）。

## ディレクトリ構成

```
~/.agents/
├── README.md                  ← このファイル（人間向け運用手順）
├── AGENTS.md                  ← エージェント向け規約（実体）
├── CLAUDE.md                  ← AGENTS.md への参照のみ
├── tools/
│   └── pack_skill.py          ← claude.ai（WEB版）へアップロードする zip を作る
├── vendor/
│   └── NOTICE.md              ← 外部から取り込んだスキルの出典・ライセンス・改変の記録
└── skills/
    └── <skill-name>/
        ├── SKILL.md           ← 必須。frontmatter + 手順本文
        ├── references/        ← 大部の資料。索引経由で必要な分だけ読ませる
        ├── scripts/           ← 決定論的な処理。毎回同じ結果が必要なもの
        ├── assets/            ← 出力テンプレート
        ├── templates/         ← 同上（assets の別名として使っているスキルあり）
        ├── examples/          ← 出力例
        └── LICENSE            ← 外部から取り込んだスキルのみ。元のライセンス全文
```

`SKILL.md` 以外はすべて任意。ただし **SKILL.md から参照されないファイルは置かない**（検証スクリプトが孤児ファイルとして警告する）。

### 収録スキル

| スキル | 用途 | SKILL.md |
| --- | --- | --- |
| `markdown-doc` | 業務用 Markdown 文書を4種別の定型で作る。説明資料・ナレッジベース記事、業務手順書、生成AI活用のノウハウ記録、不具合報告書。種別を決めてから references/ の該当1本だけを読む | 85行 |
| `japanese-prose-polish` | AIくさい日本語を人間の文章に直す。20パターンを検出して書き換え、文書種別に応じて業務文書モード／個人発信モードを使い分ける。文書系スキルの最終工程から呼ばれる | 338行 |
| `notion-api` | NotionをREST API（`NOTION_TOKEN`）経由で操作する基盤。DBスキーマ取得・クエリ・ページ作成・アーカイブ・Markdown→ブロック変換を標準ライブラリのみのスクリプトで行う。他のNotion系スキルの書き込み基盤 | 86行 |
| `notion-knowhow-page` | Notionの「DB_ノウハウまとめ」へノウハウ記事ページを投稿する。会話の知見の整理と既存Markdownの変換の両方に対応し、承認を得てから notion-api 経由で書き込む | 130行 |
| `notebooklm` | 重い読み込み仕事をNotebookLMに外注してトークンを節約する。資料が3件以上、または合計1万字を超えそうなときに使う | 136行 |
| `nextdesign-cpp14-implementation` | Next Design の詳細設計から組込みC++14の関数設計と実装を構築。Doxygenコメント（retval の成立条件・sideeffect）を関数仕様の正本として書き切ってから実装し、レビューゲートと設計⇔宣言の機械突合で漏れを防ぐ。DEBUG/INFO/ERROR のログ出力方針を含む。単体テストは別スキルの担当 | 198行 |
| `nextdesign-script-extension` | Next Design の拡張機能を C# スクリプト（manifest.json + main.cs）で作る。最初に必ずバージョンを尋ねて参照ドキュメントを確定させ、配置前に manifest を機械検査してから実機で動作確認する | 277行 |
| `cpp14-code-review` | 組込みC++14の既存コード・git差分のレビュー。規約違反をスキャナで機械抽出し、判断が要る観点に集中させる。指摘は台帳化し未クローズ残ゼロを機械判定する | 219行 |
| `cpp14-defect-analysis` | 動いているコードが期待どおり動かないときの原因究明。現象の確定をゲートにし、仮説を確度と切り分けコストで並べて1件ずつ検証、根本原因の確定・再発防止テストのRED確認・同種パターンの水平展開まで行う | 287行 |
| `static-analysis-triage` | CodeSonar / Helix QAC の大量指摘を修正・逸脱・誤検知に仕分ける。同種の指摘をフィンガープリントで束ねて代表1件で判断し、過去の判定を判定DBから再適用する。申請書Excelへの書き戻しと逸脱記録書の生成まで行う | 254行 |
| `workflow-skill-architect` | スキルそのものの設計。ループ設計・DAG分解・状態管理・データ受け渡し契約まで含む | 198行 |
| `skill-portfolio-audit` | スキル置き場の横断検査。web-description欠落・発火競合・READMEとの乖離を機械検査し、競合候補を1組ずつ判定する | 209行 |
| `show-me` | 会話の流れの中でその場に図を出す。簡潔な図・コードの形のスケッチ・小さなHTMLから、いちばん小さく伝わるものを選ぶ（外部取り込み・MIT） | 132行 |
| `second-opinion` | 意見が割れそうなテーマで ChatGPT にも同じ質問を投げ、Claude 自身の見解と突き合わせる。機密チェックとリトライ上限を手順に組み込み、結果をリサーチフォルダに残す | 98行 |
| `youtube-member-summary` | YouTube動画（メンバー限定を含む）を要約してNotionの「DB_YouTube要約」に保存する。公開動画はNotebookLMにURL直接登録、メンバー限定はClaude in Chromeで字幕を抜いてから登録し、notion-api 経由で書き込む | 249行 |
| `implementation-plan-grill` | 実装計画・設計案を着工前に問い詰めて穴を潰す。論点を台帳化し、推奨回答つきの質問で1件ずつ確定させ、確定事項・保留事項を計画書にまとめる。組込みC/C++向けの追加観点を references に同梱 | 101行 |
| `session-handoff` | 作業セッションの状態をリポジトリ直下の HANDOFF.md 1枚に圧縮して次セッションへ引き継ぐ。再開時は実際のリポジトリ状態と突き合わせ、ズレていたら報告してから続行する | 62行 |
| `cpp14-rule-reference` | AUTOSAR C++14 / CERT C++ の規約をルール番号や違反内容から引き、番号・要旨・根拠・出典箇所を返す基盤。規約資料は git 管理外の local/ に置く（vendor/NOTICE.md 参照） | 71行 |
| `agents-md-advisor` | AGENTS.md / CLAUDE.md を整える。未整備なら導入診断して AGENTS.md 草案・スキル候補・運用ルールの提案書に、整備済みなら監査して台帳化し1件ずつ判定を得てから適用する | 126行 |

**表の行数は実測値。** `skill-portfolio-audit` が実体と突き合わせるので、スキルを直したらここも直す。

`skills/obsidian/` はこの表に載っていない。ライセンスが付与されていない配布物で、リポジトリには含めていない（後述の「外部から取り込んだスキル」を参照）。

## セットアップ（新しい環境で）

### 1. クローン

```bash
git clone <このリポジトリ> ~/.agents
```

### 2. リンクを張る

**Windows（コマンドプロンプト）**

```bat
mkdir "%USERPROFILE%\.claude"
mklink /D "%USERPROFILE%\.claude\skills" "%USERPROFILE%\.agents\skills"
```

`.claude` が既にある場合、1行目は「既に存在します」と出るが無視してよい。
`mklink` は**開発者モードが有効なら一般ユーザーで実行できる**。有効にしていない場合は、コマンドプロンプトを管理者として実行する。

**Linux / macOS / WSL**

```bash
ln -s ~/.agents/skills ~/.claude/skills
```

> VirtualBox 上の Ubuntu と Windows ホストの両方で作業する場合、ホームディレクトリは互いに独立しているため**両方で実行する**。

### 3. 確認

```bash
ls -la ~/.claude/skills     # → skills -> .../.agents/skills と出れば成功
```

Claude Code を起動し、上の「収録スキル」の一覧が出ることを確認する。すでに起動していた場合は再起動が必要。

## WEB版 Claude（claude.ai）へ反映する

claude.ai はローカルのファイルを読まない。**スキルフォルダを zip にしてアップロードする**のが唯一の経路である。シンボリックリンクによる自動反映は効かないので、スキルを直したら手作業で上げ直す。

```
skills/<name>/            ← 実体（長い description）。CLI 系はここを直接読む
      │
      │ python tools/pack_skill.py --all
      ▼
dist/<name>.zip           ← description を短縮版に差し替えた複製
      │
      │ 手動アップロード
      ▼
claude.ai > Customize > Skills
```

### 初回だけやること

**Settings > Capabilities で「Code execution and file creation」を ON にする。** これが無いと Skills 機能自体が使えない。Free / Pro / Max はここ、Team / Enterprise は Organization settings 側で Owner が有効化する。

### 反映手順

```bash
python tools/pack_skill.py --all          # dist/*.zip が出る
python tools/pack_skill.py skills/<name>  # 1件だけならこちら
```

`dist/` の zip を claude.ai の **Customize > Skills > 「+」> Upload a skill** から上げる。

**更新するときは、旧スキルを削除してから再アップロードする。** 同名を上げ直したときの挙動が保証されていない。

### 制約

- **`description` は 200 文字以内。** Agent Skills 仕様の 1024 文字より厳しい。このリポジトリの description は発火文言を含めるため 200〜340 文字あり、そのままでは通らない。そこで **各 SKILL.md の frontmatter に `metadata.web-description`（200文字以内）を置き、`pack_skill.py` が zip 内の `description:` をそれに差し替える**。実体側は書き換えないので、CLI 系の発火精度は落ちない。

  ```yaml
  ---
  name: markdown-doc
  description: 業務用の Markdown 文書を種別ごとの定型で作るスキル。…（CLI 用。長いまま）
  metadata:
    web-description: 業務用 Markdown 文書を種別ごとの定型で作る。…（200文字以内）
  ---
  ```

  `metadata.web-description` が無いスキルは**パッケージ時に終了コード1で止まる**。長い description のまま上げてしまう事故を防ぐため。
- **`scripts/` は claude.ai のサンドボックスでも動く。** ただし `static-analysis-triage` の `openpyxl` のような外部依存は実行時にインストールが必要になるため、WEB では動かないことがある。標準ライブラリだけのスクリプトはそのまま動く。
- **アップロードしたスキルは個人アカウント内でのみ有効。** チーム全体へ配るには Team / Enterprise で Owner が組織向けに配置する必要がある。

### 出力先

`dist/` は生成物なので `.gitignore` 済み。zip をコミットしない。

## スキルを追加する

1. **設計する** — `workflow-skill-architect` スキルを使う。「〇〇するスキルを作りたい」と言えば発火する。ループの終了条件、フェーズの依存関係、状態管理、データ受け渡しを最初に決めるのがこのスキルの仕事。
2. **`skills/<name>/SKILL.md` を作る** — ハマりどころは次の2つだけ。
   - **`name` はディレクトリ名と完全一致させる。** ずれるとエラーも出ずに読み込まれない。
   - **`description` には「何をするか」と「いつ使うか」の両方を書く。** これがエージェントがスキルを使うか判断する唯一の材料。「レビューの手順」だけでは発火せず、「レビュー依頼のときに使用する」まで書いてはじめて拾われる。
   - **`metadata.web-description` に200文字以内の短縮版を添える。** claude.ai 用。無いと `pack_skill.py` が止まる（前節参照）。
3. **検証する** — 後述の `validate_skill.py` を通す。
4. **発火を確認する** — 新規セッションを立て、想定する言い回しで実際に呼ばれるか試す。既存セッションでは読み込まれない。
5. **コミットする** — 1スキル1コミット。

## スキルを改善する

うまく動かないときの切り分け。

| 症状 | 疑うところ | 直し方 |
| --- | --- | --- |
| 発火しない | `description` | 「いつ使うか」を具体的な依頼文言で追記する。やや押しつけがましいくらいでよい |
| 意図しない場面で発火する | `description` | 対象範囲を狭める。競合するスキルがあれば使い分けを明記する |
| 手順を飛ばす | 本文の構造 | フェーズごとに**完了条件**を判定可能な形で書く。「確認する」ではなく「一覧を提示し確認を得たこと」 |
| 想定外時に強引に前進する | 本文の構造 | **戻り条件**を書く。「一覧にないファイルが必要になったらフェーズ1に戻る」 |
| 抜け道を使う | 本文の構造 | **禁止事項**を書く。「テストを削除・スキップして通すことは禁止する」 |
| 結果がぶれる | 処理の置き場所 | 集計・パースなど間違いようがあってはいけない処理は `scripts/` に逃がし、判断だけをエージェントに任せる |
| コンテキストを圧迫する | ファイル構成 | 本文500行を超えたら `references/` に分割し、SKILL.md からは索引として参照する |

> **確実な強制はできない。** スキルは「そう振る舞いやすくする」仕組みであって、従うかどうかは最終的にモデルの判断に委ねられる。コミット前の静的解析のような**例外なく必ず通したいゲートは hooks や CI で実装する**。スキルは品質の底上げには効くが、保証はしない。

## 検証

```bash
python skills/workflow-skill-architect/scripts/validate_skill.py skills/<name>
```

| 終了コード | 意味 |
| --- | --- |
| 0 | 合格（WARN のみの場合も0だが、内容は表示される） |
| 1 | ERROR あり。修正するまでコミットしない |
| 2 | 引数の指定ミス |

検査するのは2系統。

- **仕様適合** — frontmatter の許可キー（`name` / `description` / `license` / `allowed-tools` / `metadata` / `compatibility`）、`name` の kebab-case と64文字以内、`description` の山括弧禁止と1024文字以内
- **構造** — `name` とディレクトリ名の一致、リンク切れ、孤児ファイル、SKILL.md 500行以内、`scripts/` の使い方が文書化されているか

依存は標準ライブラリのみ。Claude Code 以外の環境にそのまま持ち出せる。

> **合格 = 良いスキル、ではない。** 機械判定できない項目（description の押しの強さ、ループに成功条件・上限・諦め条件がそろっているか、並列枝の担当範囲が重複していないか、初見のエージェントが推測を挟まず実行できるか）は対象外。これらは `skills/workflow-skill-architect/references/review-checklist.md` を目視で当てる。

## 命名・粒度の規約

- **命名**: kebab-case。`<動詞>-<対象>`（`review-checklist`）か `<対象>-<成果物>`（`markdown-doc`）。
- **本文の長さ**: SKILL.md は500行以内。超えたら `references/` に分割し、索引として参照する。
- **粒度**: 1スキル1目的。大きなワークフローは役割ごとの小さなスキルに分解し、進行役スキルは「どの順で何を呼ぶか」だけを持つ。個々の判断基準は各スキルに閉じ込める。こうするとレビュー観点を直したいときに `review-checklist` だけを直せばよくなる。
- **記述言語**: 日本語。`description` も含めて英語併記はしない。以前は他ツールでの発火精度のため併記していたが、日本語でしか依頼しないなら重複するだけでコンテキストを食う。英語で依頼する運用に変えるか、description を語句一致で絞り込むツールを使い始めたら見直す。

## Git 運用

- **1スキル1コミット。** レビュー時に差分が1系統で済む。
- コミットメッセージ例
  - `add: <skill-name> スキルを追加`
  - `fix: <skill-name> の description を修正`
  - `docs: README に検証手順を追記`
- **シンボリックリンクはコミットしない。** `~/.claude/skills` は各環境でローカルに張るもので、リポジトリの管理対象外。

## チーム展開への移行

個人用スキルが「これはチームでも使える」と思えるレベルになったら、プロジェクトリポジトリ側に移す。

1. `~/.agents/skills/<name>/` を `<リポジトリ>/.agents/skills/<name>/` にコピーし、リポジトリにコミットする。
2. リポジトリの `.gitignore` に次を追加する。

   ```gitignore
   .claude/skills
   ```

3. Claude Code を使うメンバーは各自ローカルでリンクを張る（リポジトリルートで実行）。

   **Windows（コマンドプロンプト）**

   ```bat
   mkdir .claude
   mklink /D ".claude\skills" "..\.agents\skills"
   ```

   **Linux / macOS / WSL**

   ```bash
   mkdir -p .claude
   ln -s ../.agents/skills .claude/skills
   ```

**シンボリックリンクをコミットしてはいけない。** Windows でチェックアウトするとリンクが実体化されず、リンク先のパスが書かれただけのテキストファイルになる。`core.symlinks` と開発者モードで回避はできるが、メンバー全員の環境に依存するため運用に乗らない。

リポジトリに含める実体は `.agents/skills/` の1箇所だけにする。OS を問わずチェックアウトでき、差分も1系統で済む。

## トラブルシューティング

| 症状 | 原因 | 対処 |
| --- | --- | --- |
| スキルが一覧に出ない | `name` とディレクトリ名が不一致 | 一致させる。エラーは出ないので気づきにくい |
| 同上 | リンクが切れている | `ls -la ~/.claude/skills` で参照先を確認。壊れていれば張り直す |
| 同上 | セッションを再起動していない | Claude Code を再起動する。スキルは起動時に列挙される |
| 同上 | frontmatter が壊れている | `validate_skill.py` を通す |
| 意図しない場面で発火する | `description` が広すぎる | 対象範囲を絞る |
| 手順を飛ばす | 完了条件がない | 完了条件を判定可能な形で書く。必須ゲートは hooks / CI で担保する |
| Windows でリンクが作れない | 開発者モードが無効 | 設定で開発者モードを有効化するか、コマンドプロンプトを管理者として実行する |
| Ubuntu 側でスキルが見えない | ホームディレクトリが別 | VM とホストは独立しているので、両方でセットアップを実行する |

## 仕組み（なぜ増やしても重くならないか）

段階的情報開示（Progressive Disclosure）により、起動時に読まれるのは `name` と `description` だけ。このリポジトリの description は日本語で 200〜340 文字（1本あたり 200〜300 トークン程度）なので、20本で 5,000 トークン前後になる。description が長くなるほど毎セッションの固定費が増えるので、**300 文字を目安に、名指しの振り分けは取り違えが実際に起きる相手だけに絞る**。本文が読まれるのは実際に使うときだけで、`references/` はさらに参照された瞬間まで読まれない。

だから**資料が何千行あってもコンテキストのコストはかからない**。本文を500行以内に保ち、長い資料を `references/` に逃がすのが推奨されるのはこのため。

### CLAUDE.md / AGENTS.md との使い分け

| | 読み込まれるタイミング | 向いている内容 |
| --- | --- | --- |
| CLAUDE.md / AGENTS.md | 常時 | 前提。使用言語、ディレクトリ構成、守るべき規約 |
| Agent Skills | 必要なときだけ | 作業手順。レビュー、テスト生成、ドキュメント作成 |

常に知っておいてほしい「事実」は AGENTS.md に、特定の場面でだけ従ってほしい「手順」は Skills に置く。**AGENTS.md の一節が説明ではなく手順書に育ってきたら、それはスキルに切り出すタイミング。**

## 参考

- [Agent Skills とは（Notion）](https://rhinestone-bamboo-492.notion.site/Agent-Skills-3b52ccbf51c2802e90eccc959bb27d4c) — この構成の出典
- [Agent Skills 公式サイト](https://agentskills.io/)
- [Agent Skills 仕様書](https://agentskills.io/specification)
- [Claude Code — Extend Claude with skills](https://code.claude.com/docs/en/skills)
- [GitHub Docs — Adding agent skills for GitHub Copilot](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-cloud-agent/add-skills)
- [OpenAI — Codex skills](https://developers.openai.com/codex/skills/)
