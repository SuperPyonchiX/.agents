"""render.py — .pptx をスライドごとの PNG にする（目視チェック用）。

使い方:
    python render.py out/deck.pptx --out render/ [--dpi 80] [--sheet]

出力:
    render/slide-01.png ...   スライドごとの画像
    render/sheet.png          --sheet 指定時、全スライドの一覧（縮小）
    render/render.json        使った方式・解像度・入力 pptx の sha256・画像の一覧
                              （納品前に out/deck.pptx の sha256 と一致することを確かめる）
    標準出力の 1 行目          「method: powerpoint」か「method: libreoffice」

開始時に render/ の slide-*.png・sheet.png・render.json を消す。失敗したときに古い画像が残って
見間違えることはない。

終了コード:
    0 = 成功
    1 = 変換手段はあったが、すべて失敗した（stderr に方式ごとの理由）
    2 = 変換手段が無い、または必要なパッケージが無い（--sheet 指定時の Pillow を含む）。
        見た目は未確認のまま。納品時に「見た目未確認」と明記する

変換手段（Windows は 1 → 2、それ以外は 2 だけ。失敗したら次を試す）:
    1. PowerPoint（COM）で PNG を書き出す。納品先と同じアプリで描く。
       自分で起動した PowerPoint だけを終了する（ユーザーが開いている PowerPoint は閉じない）。
    2. LibreOffice (soffice) で PDF → pdftoppm か PyMuPDF で PNG。
       Linux では theme のフォント（BIZ UDPGothic）が無い環境が多いので、fontconfig の別名で
       Noto Sans CJK JP / IPAexGothic に置き換えて描く（render.json の font_substitution に記録）。
どちらの方式でも、theme のフォントが無い PC では代替フォントで描かれる。フォントの有無は調べないので、
render.json の font_substitution が "unknown" のときは「代替の有無は未確認」と扱う。
"""
import argparse
import glob
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

SW_IN, SH_IN = 13.333, 7.5
FONT_ALIASES = {
    "BIZ UDPGothic": ["Noto Sans CJK JP", "IPAexGothic", "IPAPGothic"],
    "BIZ UDPゴシック": ["Noto Sans CJK JP", "IPAexGothic", "IPAPGothic"],
    "Meiryo UI": ["Noto Sans CJK JP", "IPAexGothic"],
    "メイリオ": ["Noto Sans CJK JP", "IPAexGothic"],
    "Yu Gothic UI": ["Noto Sans CJK JP", "IPAexGothic"],
}


class Unavailable(Exception):
    """この方式は使えない（実行ファイルや依存が無い）。"""


class Failed(Exception):
    """この方式は使えたが変換に失敗した。"""


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _run(cmd, timeout, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
    except subprocess.TimeoutExpired:
        raise Failed(f"{os.path.basename(cmd[0])} が {timeout} 秒で終わらなかった")
    except OSError as e:
        raise Failed(f"{os.path.basename(cmd[0])} を起動できない: {e}")


def _fontconfig(tmp):
    alias = "".join(
        f"<alias binding=\"same\"><family>{k}</family><prefer>"
        + "".join(f"<family>{f}</family>" for f in v)
        + "</prefer></alias>"
        for k, v in FONT_ALIASES.items())
    path = os.path.join(tmp, "fonts.conf")
    with open(path, "w", encoding="utf-8") as f:
        f.write("<?xml version=\"1.0\"?><!DOCTYPE fontconfig SYSTEM \"fonts.dtd\"><fontconfig>"
                "<include ignore_missing=\"yes\">/etc/fonts/fonts.conf</include>"
                f"{alias}</fontconfig>")
    return path


def via_libreoffice(pptx, tmp, dpi):
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise Unavailable("soffice が見つからない")
    has_pdftoppm = bool(shutil.which("pdftoppm"))
    if not has_pdftoppm:
        try:
            import fitz  # noqa: F401  PyMuPDF
        except ImportError:
            raise Unavailable("PDF を PNG にする pdftoppm も PyMuPDF（pip install pymupdf）も無い")
    env = dict(os.environ)
    subst = "unknown"
    if sys.platform.startswith("linux"):
        env["FONTCONFIG_FILE"] = _fontconfig(tmp)
        subst = "linux-fontconfig-alias"
    profile = pathlib.Path(tmp, "profile").resolve().as_uri()
    r = _run([soffice, f"-env:UserInstallation={profile}", "--headless", "--convert-to", "pdf",
              "--outdir", tmp, pptx], 240, env=env)
    pdf = os.path.join(tmp, os.path.splitext(os.path.basename(pptx))[0] + ".pdf")
    if r.returncode != 0 or not os.path.exists(pdf):
        raise Failed(f"soffice の PDF 変換に失敗: {r.stdout.strip()} {r.stderr.strip()}")
    if has_pdftoppm:
        r = _run(["pdftoppm", "-png", "-r", str(dpi), pdf, os.path.join(tmp, "p")], 240)
        if r.returncode != 0:
            raise Failed(f"pdftoppm が失敗: {r.stderr.strip()}")
        pages = sorted(glob.glob(os.path.join(tmp, "p-*.png")))
    else:
        import fitz
        pages = []
        with fitz.open(pdf) as doc:
            for i, page in enumerate(doc, 1):
                p = os.path.join(tmp, f"p-{i:03d}.png")
                page.get_pixmap(dpi=dpi).save(p)
                pages.append(p)
    if not pages:
        raise Failed("PNG が 1 枚もできなかった")
    return pages, subst


_PS = r"""
$ErrorActionPreference = 'Stop'
$src = $env:RENDER_SRC; $dst = $env:RENDER_DST
$w = [int]$env:RENDER_W; $h = [int]$env:RENDER_H
$owned = -not (Get-Process POWERPNT -ErrorAction SilentlyContinue)
$app = New-Object -ComObject PowerPoint.Application
$p = $null
try {
    $p = $app.Presentations.Open($src, $true, $false, $false)
    $i = 0
    foreach ($s in $p.Slides) {
        $i++
        $s.Export((Join-Path $dst ('p-{0:D3}.png' -f $i)), 'PNG', $w, $h)
    }
} finally {
    if ($p -ne $null) { $p.Close() }
    if ($owned) { $app.Quit() }
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($app)
}
"""


def via_powerpoint(pptx, tmp, dpi):
    if os.name != "nt":
        raise Unavailable("Windows ではない")
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if not ps:
        raise Unavailable("powershell が見つからない")
    env = dict(os.environ, RENDER_SRC=os.path.abspath(pptx), RENDER_DST=tmp,
               RENDER_W=str(round(SW_IN * dpi)), RENDER_H=str(round(SH_IN * dpi)))
    r = _run([ps, "-NoProfile", "-NonInteractive", "-Command", _PS], 300, env=env)
    pages = sorted(glob.glob(os.path.join(tmp, "p-*.png")))
    if r.returncode != 0 or not pages:
        msg = (r.stderr or r.stdout).strip()
        if "80040154" in msg or "ComObject" in msg and "PowerPoint.Application" in msg:
            raise Unavailable(f"PowerPoint が入っていない: {msg[:200]}")
        raise Failed(f"PowerPoint での書き出しに失敗: {msg[:400]}")
    return pages, "unknown"


def contact_sheet(paths, out, cols=4, width=480):
    from PIL import Image
    ims = [Image.open(p) for p in paths]
    h = int(width * ims[0].height / ims[0].width)
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (width + 10) + 10, rows * (h + 10) + 10), "#808080")
    for i, im in enumerate(ims):
        im = im.convert("RGB").resize((width, h))
        sheet.paste(im, (10 + (i % cols) * (width + 10), 10 + (i // cols) * (h + 10)))
    path = os.path.join(out, "sheet.png")
    sheet.save(path)
    return path


def _clean(out):
    os.makedirs(out, exist_ok=True)
    for old in glob.glob(os.path.join(out, "slide-*.png")) + [os.path.join(out, "sheet.png"),
                                                              os.path.join(out, "render.json")]:
        if os.path.exists(old):
            os.remove(old)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pptx")
    ap.add_argument("--out", default="render")
    ap.add_argument("--dpi", type=int, default=80)
    ap.add_argument("--sheet", action="store_true", help="全スライドの一覧画像も作る")
    a = ap.parse_args()
    if not os.path.exists(a.pptx):
        print(f"ファイルが無い: {a.pptx}", file=sys.stderr)
        return 1
    _clean(a.out)
    if a.sheet:
        try:
            import PIL  # noqa: F401
        except ImportError:
            print("--sheet には Pillow が要る。`pip install pillow` で導入してから再実行する。",
                  file=sys.stderr)
            return 2
    methods = ([("powerpoint", via_powerpoint)] if os.name == "nt" else []) + \
        [("libreoffice", via_libreoffice)]
    reasons, failed = [], False
    for name, fn in methods:
        with tempfile.TemporaryDirectory(prefix="render_") as tmp:
            try:
                pages, subst = fn(a.pptx, tmp, a.dpi)
            except Unavailable as e:
                reasons.append(f"{name}: 使えない（{e}）")
                continue
            except Failed as e:
                reasons.append(f"{name}: 失敗（{e}）")
                failed = True
                continue
            dst = []
            for i, p in enumerate(pages, 1):
                d = os.path.join(a.out, f"slide-{i:02d}.png")
                shutil.copy(p, d)
                dst.append(d)
        print(f"method: {name}")
        for r in reasons:
            print(f"  （先に試した方式）{r}", file=sys.stderr)
        for p in dst:
            print(p)
        sheet = contact_sheet(dst, a.out) if a.sheet else None
        if sheet:
            print(sheet)
        with open(os.path.join(a.out, "render.json"), "w", encoding="utf-8") as f:
            json.dump({"status": "ok", "method": name, "dpi": a.dpi,
                       "font_substitution": subst, "pptx": os.path.abspath(a.pptx),
                       "sha256": sha256(a.pptx), "slides": dst, "sheet": sheet},
                      f, ensure_ascii=False, indent=2)
        return 0
    for r in reasons:
        print(r, file=sys.stderr)
    if failed:
        return 1
    print("変換手段が無い（PowerPoint も LibreOffice も使えない）。見た目は未確認のまま進め、"
          "納品時に明記すること。", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
