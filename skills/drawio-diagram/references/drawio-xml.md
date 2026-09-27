# .drawio の書き方

D1 で XML を書くときに読む。draw.io は非圧縮の XML をそのまま開けるので、圧縮しない。

## 骨格

```xml
<mxfile>
  <diagram id="page1" name="全体構成">
    <mxGraphModel dx="1200" dy="800" grid="1" gridSize="10" guides="1" page="1" pageWidth="1169" pageHeight="827">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <!-- ここに vertex と edge を並べる。parent は通常 "1" -->
      </root>
    </mxGraphModel>
  </diagram>
  <!-- ページを増やすときは diagram を並べる -->
</mxfile>
```

- `id="0"` と `id="1"` の2セルは必須。消さない
- id は意味のある英数字にする（`ecu`、`can_bus`、`e_ecu_can`）。直すときに探しやすい
- pageWidth / pageHeight は A4 横（1169×827）を既定にする

## 図形（vertex）

```xml
<mxCell id="ecu" value="ECU" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1">
  <mxGeometry x="240" y="120" width="140" height="60" as="geometry"/>
</mxCell>
```

| 用途 | style |
|---|---|
| 処理・ブロック | `rounded=1;whiteSpace=wrap;html=1;` |
| 外部システム | `rounded=0;whiteSpace=wrap;html=1;dashed=1;` |
| データベース・記憶域 | `shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;size=12;` |
| 判断（フロー図） | `rhombus;whiteSpace=wrap;html=1;` |
| 開始・終了 | `ellipse;whiteSpace=wrap;html=1;` |
| 人・アクター | `shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;html=1;` |
| 文書 | `shape=document;whiteSpace=wrap;html=1;boundedLbl=1;` |
| 注記 | `shape=note;whiteSpace=wrap;html=1;size=14;fillColor=#fff2cc;strokeColor=#d6b656;` |
| 見出し文字だけ | `text;html=1;align=left;verticalAlign=middle;fontSize=16;fontStyle=1;` |

色は意味で使い分け、1枚で3系統までにする。

| 意味 | fillColor / strokeColor |
|---|---|
| 通常 | `#dae8fc` / `#6c8ebf` |
| 対象範囲・強調 | `#d5e8d4` / `#82b366` |
| 外部・対象外 | `#f5f5f5` / `#666666` |
| 注意・変更点 | `#f8cecc` / `#b85450` |

## まとまり（コンテナ・スイムレーン）

中の図形は `parent` をコンテナの id にし、**座標はコンテナ左上からの相対値**で書く。

```xml
<mxCell id="grp_ecu" value="ECU 内部" style="swimlane;html=1;startSize=26;horizontal=1;" vertex="1" parent="1">
  <mxGeometry x="200" y="80" width="360" height="220" as="geometry"/>
</mxCell>
<mxCell id="app" value="アプリ層" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="grp_ecu">
  <mxGeometry x="20" y="46" width="140" height="50" as="geometry"/>
</mxCell>
```

業務フローのスイムレーンは、レーンごとに `swimlane;horizontal=0;startSize=40;` のコンテナを**縦に積む**（y をずらし、x と幅はそろえる。ラベルが左に縦書きで出る）。「上から A・B・C」と言われたら、この向きにする。レーン間の線は上下に渡し、見出し帯（左端の帯）を横切らせない

- 作業の箱は、**その作業をする人のレーン**の子にする（`parent` をレーンの id に）。レーンをまたぐ箱は作らない
- レーンの中の座標は、左の見出し帯（`startSize` の幅）より右から始める。`x` は `startSize + 20` 以上（`check_drawio.py` が見出し帯へのかぶりを ERROR にする）
- 横向きの枠（`horizontal=1`、見出しが上）では、中の箱の `y` を `startSize + 20` 以上にする

層構造（アプリ層・RTE・BSW など）は、層ごとの横長の枠を縦に積み、中の箱は層の子にする。層を飛ばす線（アプリ層から MCAL へ直接など）は、依頼に無ければ引かない。

## 線（edge）

```xml
<mxCell id="e_sensor_ecu" value="CAN" style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;labelBackgroundColor=#ffffff;" edge="1" parent="1" source="sensor" target="ecu">
  <mxGeometry relative="1" as="geometry"/>
</mxCell>
```

- **ラベル付きの線には必ず `labelBackgroundColor=#ffffff;` を付ける。** 付けないと線とラベルが重なる（`check_drawio.py` が WARN にする）
- source / target は必ず指定する。座標だけで線を引くと、人が箱を動かしたときに線が付いてこない
- **出口と入口を明示する。** 省くと自動の経路が同じ列の箱を縦に突き抜けることがある。1つの箱から右側の複数の箱へ分岐するなら全部に `exitX=1;exitY=0.5;entryX=0;entryY=0.5;` を付ける（左端から出て分岐点でそろい、各箱の左辺に入る）。下へ出すなら `exitX=0.5;exitY=1;`
- 向き: 片方向は既定のまま、双方向は `startArrow=classic;`、矢印なしは `endArrow=none;`
- 非同期・任意の流れは `dashed=1;`
- 線が箱を横切るときは、箱の並びを直す。`waypoints` での迂回は最後の手段

## 突き抜け・重なりの直し方

`check_layout.py` が THROUGH（線が箱を突き抜ける）や OVERLAP（別々の線が重なる）を出したら、次の順に試す。上ほど効きやすく、壊しにくい。

1. **出口と入口を明示する**（上の「線」の節）。自動の経路が箱の間を縫うのをやめさせる
2. **箱の並びを変える**。つながる箱どうしを同じ行か同じ列に置く。間に無関係の箱があれば、行か列をずらす
3. **戻りの線（ループ）は図の外周を回す**。戻り先の上辺か下辺に入るよう `entryY=0` か `entryY=1` を指定し、`exitY` も同じ側にする。こうすると経路が他の箱の外側を通る
4. **分岐した線どうしが重なるなら、出口の位置をずらす**（`exitY=0.25` と `exitY=0.75` など）
5. **ラベルが別の線に乗る（LABEL）なら、ラベルの無い側に寄せるか、ラベルを減らす。** 同じ意味のラベルが何本もの線に付く（「ログ」×6 など）なら、ラベルは付けず、受け側の箱の名前で意味を伝える。往復の2本（注文と約定など）は出口・入口を上下にずらして平行に離す（`exitY=0.3` と `exitY=0.7`）
6. それでも直らないときだけ waypoint（`<Array as="points"><mxPoint x=".." y=".."/></Array>`）で経由点を置く。経由点は箱の無い通路（箱と箱の間隔の中央）に置く

## 配置の規則

- 座標はすべて 10 の倍数（グリッドに乗せる）
- 標準サイズは 140×60。同じ役割の箱は同じサイズにそろえる
- 箱と箱の間隔は横 80、縦 60 以上。ラベル付きの線が通る間は 120 以上
- 流れは左→右、または上→下の一方向にそろえる。戻りの線だけが逆向きになるようにする
- 1ページの箱は 20 個までを目安にする。超えたらページを分ける（全体図＋詳細図）

## 日本語

- **ファイルは UTF-8 で保存する。** PowerShell の `Set-Content` や `>` は既定で UTF-8 以外になり、日本語が `?` に化ける。ファイル書き込み用のツールがあればそれで書き、シェルで書くなら `Out-File -Encoding utf8` か Python の `open(..., encoding="utf-8")` を使う（`check_drawio.py` が文字化けを ERROR にする）

- ラベルに日本語をそのまま書いてよい。XML の特殊文字（`&` `<` `>` `"`）だけ `&amp;` `&lt;` `&gt;` `&quot;` にする
- 改行は `html=1` のもとで `&lt;br&gt;` と書く
- 長いラベルは箱の幅に合わせて改行し、箱を広げすぎない
