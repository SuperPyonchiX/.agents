# Blender で 3D 素材を作る

N0 で 3D を使うと決めたとき、N2c で素材を作る前に読む。

## 導入

| OS | 入れ方 |
|---|---|
| Windows | `winget install --id BlenderFoundation.Blender -e` |
| macOS | `brew install --cask blender` |
| Linux | `sudo snap install blender --classic` |

`python scripts/blender_render.py --find` が場所を出せば使える。入れた場所が見つからなければ `--blender <blender.exe のパス>` か環境変数 `BLENDER` で渡す。

**導入はユーザーの承認を得てから行う**（数百 MB ある）。承認が無ければ 3D は Three.js で作る（下の「Three.js に切り替える」）。

## 作り方

1. `assets/blender/scene_template.py` を作業先の `blender/<シーンid>.py` にコピーし、`build_scene()` を書き換える。引数の受け取り（`parse_args`）とレンダリング設定（`setup_render`）は変えない
2. 枚数はシーンの尺（`timeline.json` の `duration`）以下にする。最後の1枚で止まるので、動きの部分だけ作ればよい（30fps で 1.5〜2 秒＝45〜60 枚が目安）
3. まず小さく試す。`--width 480 --height 270 --frames 10` で書き出し、1枚目と最後の1枚を開いて形・色・カメラを確かめてから本番の解像度で回す
4. 本番:

   ```
   python scripts/blender_render.py blender/s01.py --out public/3d/s01 --frames 45 --set text=告知 --set color=#f97316
   ```

5. 雛形の `SCENE_VISUALS` に `s01: () => <BlenderClip dir="3d/s01" frames={45} />` を書く。背景は透過なので、後ろに 2D の背景や図形を重ねられる（2D と 3D をつなげる演出はここでやる）

## 雛形に無いものを作るときの勘所

- 背景透過（`film_transparent`）と PNG の RGBA を外さない。外すと 2D と重ねられない
- 日本語の文字は Blender の既定フォントで豆腐になる。雛形の `japanese_font()` が Windows の游ゴシック・メイリオを探す。見つからなければ `--set font=<.ttc のパス>`
- レンダリングエンジンは EEVEE（速い）。Cycles は1枚に数十秒かかるので使わない
- 色は雛形の `hex_rgba()` で渡す（sRGB をリニアに変換する）。`view_transform` は `Standard` のままにする。既定の AgX に戻すと指定した色より白っぽく抜ける。World（環境光）を消すと逆に暗く沈む
- 所要時間の目安は 1920×1080・45枚で約1分半（Blender の起動に十数秒かかる）
- モデルを外部からダウンロードしない。形は Blender のプリミティブ（立方体・球・円柱・テキスト）と修飾子で作る

## 失敗したとき（最大2回で打ち切る）

`blender_render.py` の終了コード 3 は、末尾25行のログが出る。

| ログ | 直し方 |
|---|---|
| `Traceback` と bpy の属性エラー | Blender の版で API 名が違う。`--find` の版数を見て、該当の行を書き直す |
| 枚数が足りない | `frame_end` や `filepath` を書き換えていないか確かめる |
| 時間切れ | 解像度・枚数を下げる。ライトを減らす |

**2回直しても終了コード 0 にならない、または出来上がった絵が意図とずれているなら、Blender をやめて Three.js に切り替える。** 3回目を試さない。

## Three.js に切り替える

Remotion の中で 3D を描く。Blender が無い環境でも動く。

```
npx remotion add @remotion/three
```

```tsx
import { ThreeCanvas } from "@remotion/three";
import { useCurrentFrame, useVideoConfig } from "remotion";

const Spin3D: React.FC = () => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  return (
    <ThreeCanvas width={width} height={height} camera={{ position: [0, 0, 6] }}>
      <ambientLight intensity={0.6} />
      <directionalLight position={[3, 4, 5]} intensity={1.2} />
      <mesh rotation={[0.4, frame * 0.05, 0]}>
        <torusKnotGeometry args={[1.2, 0.35, 160, 24]} />
        <meshStandardMaterial color="#38bdf8" metalness={0.6} roughness={0.25} />
      </mesh>
    </ThreeCanvas>
  );
};
```

- 回転・移動は必ず `useCurrentFrame()` から計算する。`useFrame` や `requestAnimationFrame` で動かすと、レンダリング結果がフレームごとにばらつく
- 詳しい書き方は `remotion-best-practices` の `remotion-markup/3d.md` に従う
