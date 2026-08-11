# スキャンルールとスクリプトの使い方

R1（機械スキャン）と R5（是正確認）で読む。**毎回読むこと。**

- [確度の意味](#確度の意味)
- [ルール一覧](#ルール一覧)
- [誤検知の典型パターン](#誤検知の典型パターン)
- [スクリプトの使い方](#スクリプトの使い方)
- [出力形式](#出力形式)

## 確度の意味

スキャナが出すのは**指摘ではなく候補**。確度3段階で、後工程での扱いが違う。

| 確度 | 意味 | R2 でやること |
|---|---|---|
| `high` | 構文上ほぼ確実に違反。誤検知は稀 | 原則そのまま採用する。落とすなら理由を書く |
| `medium` | 違反の可能性がある。文脈次第で正当 | **1件ずつ採否を判定する。** 判定しないまま残さない |
| `policy` | プロジェクト方針次第で違反にも正当にもなる | `work/review-scope.json` の方針3点に照らして判定する |

`--scope` を渡すと `policy` ルールは方針に従って有効化・無効化され、`policy` 確度の候補は出なくなる。渡さない場合はすべて `policy` として出るので、R2 で全件を判定することになる。**R0 で方針を確定させてから R1 を実行するほうが手戻りが少ない。**

## ルール一覧

### high — 構文で確定する

| ルールID | 検出する内容 | 根拠 |
|---|---|---|
| `CAST-001` | C スタイルキャスト `(T)expr` | `static_cast` 等を使い分ける。`reinterpret_cast` は原則禁止 |
| `BAN-001` | `NULL` の使用 | `nullptr` を使う |
| `BAN-002` | ヘッダ内の `using namespace` | インクルードした側の名前空間を汚染する |
| `BAN-003` | `malloc` / `calloc` / `realloc` / `free` | C のメモリ API を使わない |
| `BAN-004` | `system` / `getenv` / `exit` / `abort` / `atexit` | 環境依存 API を使わない |
| `BAN-005` | 関数形式マクロ `#define F(x) ...` | `constexpr` 関数か `inline` 関数にする |
| `BAN-006` | 可変長引数 `...`（関数宣言・定義） | 型安全でない |
| `CTRL-001` | `goto` | — |
| `CTRL-002` | `default` の無い `switch` | 全列挙子を書いた場合も置く |
| `CTRL-003` | `if` / `for` / `while` の本体でブレースを省略 | 1文でも省略しない |
| `MNT-001` | `TODO` / `FIXME` / `XXX` / `HACK` の残存 | 出荷コードに未完了の印を残さない |

### medium — 文脈で判定する

| ルールID | 検出する内容 | 判定のしかた |
|---|---|---|
| `TYPE-001` | 可変幅の整数型宣言（`int` / `long` / `short` / 数値用途の `char` / `unsigned`） | `<cstdint>` の固定幅型にすべきか。ループカウンタや標準 API の戻り値受けは正当な場合がある |
| `TYPE-002` | 浮動小数点の `==` / `!=` 比較 | 許容誤差との比較にすべきか。`0.0` との比較でも意図が要る |
| `CLS-001` | 単一引数コンストラクタに `explicit` が無い | 暗黙変換を意図しているか。コピー / ムーブコンストラクタは対象外 |
| `CLS-002` | `virtual` を持つクラスのデストラクタが非 `virtual`、または未宣言 | 多態的に `delete` されるか。されないなら `protected` 非 virtual が正解 |
| `CLS-003` | Rule of Five / Zero 違反（デストラクタ・コピー・ムーブの一部だけ宣言） | 残りを `= default` / `= delete` で明示する |
| `CLS-004` | 派生クラスの `virtual` 再宣言に `override` / `final` が無い | 基底に同名の仮想関数があるか。新規の仮想関数なら正当 |
| `FUNC-001` | 直接再帰（関数が自身を呼ぶ） | スタック使用量が静的に見積もれるか。深さ上限が `@note` にあるか |
| `MNT-002` | マジックナンバー（`0` / `1` / `-1` / `2` と定数定義行を除く数値リテラル） | 意味のある値なら定数化する。配列サイズやビット位置は特に |
| `MNT-003` | 関数が既定 60 行を超える | 責務が1つか。分割してテストが壊れないか |
| `CTRL-004` | `case` のフォールスルー（`break` / `return` / `throw` / `[[fallthrough]]` 相当のコメントが無い） | 意図的か。意図的ならコメントで明示させる |

### policy — 方針次第

| ルールID | 検出する内容 | 有効になる方針 |
|---|---|---|
| `POL-001` | `throw` / `try` / `catch` | 例外禁止（`exceptions: "forbidden"`） |
| `POL-002` | 生の `new` / `delete` | 動的メモリ禁止（`dynamic_memory: "forbidden"`）。`init_only` の場合は候補として残し、初期化時のみか R2 で判定する |
| `POL-003` | `dynamic_cast` / `typeid` | RTTI 禁止（`virtual_rtti: "forbidden"`） |

## 誤検知の典型パターン

**そのまま採用すると信用を落とす。** 次のパターンは R2 で必ず確認する。

| ルールID | 誤検知するケース | 見分け方 |
|---|---|---|
| `CAST-001` | `(void)x;` による未使用引数の抑止、関数ポインタ型の宣言、マクロ内の型名 | `(void)` は別扱い。組込みでは正当なことが多い |
| `TYPE-001` | `int main()`、標準 API のシグネチャに合わせた宣言、`std::size_t` を含む行の並び | 外部インタフェースに合わせている箇所は正当 |
| `CTRL-003` | 1行に収まる `if (x) { return; }`、マクロ展開を挟む行、`else if` の連鎖 | ブレースが同一行にある場合は違反でない |
| `CTRL-002` | `switch` が複数行にまたがりネストした `switch` を含む場合、内側の `default` を外側のものと誤認する | 対応するブロックを目視で確認する |
| `MNT-002` | ビット演算のシフト量、配列の次元、`constexpr` 定義行の右辺 | 定義側は正当。使用側にリテラルが散っているかを見る |
| `CLS-004` | 基底クラスが同一ファイルに無い場合、判定できない | 基底が範囲外なら「判定不能」として `rejected` にし、理由に書く |
| `FUNC-001` | 同名の別関数（オーバーロード、別クラスの同名メンバ）の呼び出し | 呼び出し先が本当に自分自身か確認する |

スキャナは**文字列リテラルとコメントを除去してから**判定するので、それらの中の該当語は検出されない。ただしマクロ展開後のコードは見ないので、マクロを多用したコードでは取りこぼす。マクロの中身は目視で当てる。

## スクリプトの使い方

### `scripts/scan_cpp_rules.py`

```
python scripts/scan_cpp_rules.py --scope work/review-scope.json -o work/scan-report.json
python scripts/scan_cpp_rules.py src/ include/ -o work/scan-report.json
python scripts/scan_cpp_rules.py --scope work/review-scope.json --tidy-log build/tidy.log -o work/scan-report.json
```

| 引数 | 意味 |
|---|---|
| 位置引数 | 対象のファイルまたはディレクトリ。`--scope` を使う場合は省略できる |
| `--scope <path>` | `work/review-scope.json` を読み、対象ファイルと方針3点を取得する |
| `--tidy-log <path>` | clang-tidy / PC-lint 形式のログを取り込む。複数回指定できる |
| `--max-function-lines <n>` | `MNT-003` の閾値。既定 60 |
| `-o <path>` | JSON の出力先。省略時は標準出力に JSON を出さず、要約のみ表示する |

| 終了コード | 意味 |
|---|---|
| 0 | 実行成功。**検出件数の多寡によらず 0**（検出はレビューの入力であってゲートではない） |
| 1 | 実行エラー（対象が存在しない、scope が読めない、出力先に書けない） |
| 2 | 引数の指定ミス |

標準出力には確度別・ルール別の要約を出す。詳細は `-o` で指定した JSON を読む。

**取り込める外部ツールのログ形式**（1行1件）:

```
src/motor.cpp:42:11: warning: do not use C-style cast [google-readability-casting]
```

`path:line:col: severity: message [check-name]` に一致する行を取り込む。`severity` が `error` なら確度 `high`、それ以外は `medium` として登録する。一致しない行は無視する。取り込み件数は要約に出るので、**0 件だった場合は形式が違う。** その旨を R4 の報告に書く。

### `scripts/check_review_log.py`

```
python scripts/check_review_log.py work/review-log.md
```

`work/review-log.md` の「指摘一覧」表を読み、状態列を集計する。

| 終了コード | 意味 |
|---|---|
| 0 | `open` の指摘なし |
| 1 | `open` が残っている、または台帳の形式が不正（表が見つからない、状態列が既知の値でない） |
| 2 | 引数の指定ミス |

状態として認めるのは `open` / `fixed` / `accepted` / `rejected` の4つ。`open` と `未対応` / `対応中` は未クローズとして扱う。

## 出力形式

`work/scan-report.json`:

```json
{
  "generated_at": "2026-08-11T14:32:10+09:00",
  "mode": "diff",
  "diff_base": "main",
  "policy": { "exceptions": "forbidden", "dynamic_memory": "init_only", "virtual_rtti": "allowed" },
  "files_scanned": 6,
  "summary": { "high": 4, "medium": 11, "policy": 0, "external": 7 },
  "findings": [
    {
      "seq": 1,
      "rule": "CAST-001",
      "confidence": "high",
      "file": "src/motor_controller.cpp",
      "line": 42,
      "in_diff": true,
      "code": "  std::int32_t v = (int)raw;",
      "message": "C スタイルキャスト",
      "source": "scanner"
    }
  ]
}
```

- `in_diff` は `mode` が `diff` のときのみ意味を持つ。`false` は「対象ファイルだが変更行ではない」＝ **差分外の既存問題**。R3 で `区分` を `差分外` にする。
- `source` は `scanner` または取り込み元のログ名。
- `seq` は連番。台帳の `RV-` 番号とは別物なので、混同しない。
