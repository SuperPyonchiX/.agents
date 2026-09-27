#!/usr/bin/env python3
"""VOICEVOX エンジンでシーンごとのナレーション音声（wav）を作り、尺を計ってマニフェストに書く。

使い方:
  python voicevox_tts.py --list-speakers [--host URL]
  python voicevox_tts.py <scenes.json> --out <public/narration> --manifest <src/narration.json>
                         [--only s01,s03] [--host URL]

scenes.json の形:
  {
    "speaker": 3,               # VOICEVOX の style id（--list-speakers で調べる）
    "speedScale": 1.1,          # 任意。話速（既定 1.0）
    "pauseAfter": 0.4,          # 任意。各シーンの後ろに足す無音の秒数（既定 0.4）
    "scenes": [ {"id": "s01", "text": "読み上げる文（英単語はカタカナで）",
                 "subtitle": "字幕に出す文（任意。省略時は text）"}, ... ]
  }

出力:
  <out>/<id>.wav              シーンごとの音声
  <manifest>                  {"fps": null, "credit": "VOICEVOX:<キャラ名>", "speaker": ..,
                               "scenes": [{"id", "text", "subtitle", "file", "seconds"}], "total_seconds": ..}
                              file は Remotion の staticFile() に渡す public/ からの相対パス

--only を付けると、指定したシーンだけ作り直してマニフェストの該当行を差し替える。

終了コード: 0 = 作った / 1 = エンジンに接続できない / 2 = 引数・入力の誤り / 3 = 合成に失敗
依存: 標準ライブラリのみ（VOICEVOX エンジンを別途起動しておく。既定 http://127.0.0.1:50021）
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import wave

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


class EngineError(Exception):
    pass


def call(host, path, params=None, body=None, timeout=120):
    url = host.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST" if data is not None or params else "GET",
                                 headers={"Content-Type": "application/json"})
    if path in ("/speakers", "/version"):
        req.method = "GET"
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.URLError as e:
        raise EngineError(str(e))


def speakers(host):
    return json.loads(call(host, "/speakers", timeout=10))


def style_name(host, style_id):
    for sp in speakers(host):
        for st in sp.get("styles", []):
            if st.get("id") == style_id:
                return sp["name"], st.get("name", "")
    return None, None


def synth(host, text, style_id, speed, pause):
    query = json.loads(call(host, "/audio_query", {"text": text, "speaker": style_id}))
    query["speedScale"] = speed
    query["postPhonemeLength"] = pause
    return call(host, "/synthesis", {"speaker": style_id}, query)


def wav_seconds(path):
    with wave.open(path, "rb") as w:
        return w.getnframes() / float(w.getframerate())


def rel_to_public(path):
    norm = os.path.abspath(path).replace("\\", "/")
    marker = "/public/"
    i = norm.rfind(marker)
    return norm[i + len(marker):] if i >= 0 else os.path.basename(norm)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("scenes", nargs="?")
    p.add_argument("--out")
    p.add_argument("--manifest")
    p.add_argument("--only")
    p.add_argument("--host", default="http://127.0.0.1:50021")
    p.add_argument("--list-speakers", action="store_true")
    try:
        a = p.parse_args()
    except SystemExit:
        return 2

    try:
        call(a.host, "/version", timeout=5)
    except EngineError as e:
        print(f"ERROR  VOICEVOX エンジンに接続できない（{a.host}）: {e}\n"
              "       VOICEVOX アプリを起動するか、vv-engine/run.exe を起動してから再実行する")
        return 1

    if a.list_speakers:
        for sp in speakers(a.host):
            styles = ", ".join(f"{st['id']}:{st['name']}" for st in sp.get("styles", []))
            print(f"{sp['name']}  [{styles}]")
        return 0

    if not (a.scenes and a.out and a.manifest):
        print("ERROR  scenes.json・--out・--manifest を指定する（または --list-speakers）")
        return 2
    try:
        cfg = json.load(open(a.scenes, encoding="utf-8"))
        style_id = int(cfg["speaker"])
        scenes = cfg["scenes"]
        ids = [s["id"] for s in scenes]
        assert all(str(s.get("text", "")).strip() for s in scenes), "text が空のシーンがある"
        assert len(ids) == len(set(ids)), "id が重複している"
    except (OSError, ValueError, KeyError, TypeError, AssertionError) as e:
        print(f"ERROR  scenes.json が読めない: {e}")
        return 2
    speed = float(cfg.get("speedScale", 1.0))
    pause = float(cfg.get("pauseAfter", 0.4))
    name, style = style_name(a.host, style_id)
    if name is None:
        print(f"ERROR  speaker {style_id} がエンジンに無い。--list-speakers で調べる")
        return 2

    only = set(a.only.split(",")) if a.only else None
    if only and not only <= set(ids):
        print(f"ERROR  --only に scenes.json に無い id がある: {sorted(only - set(ids))}")
        return 2
    old = {}
    if only and os.path.isfile(a.manifest):
        old = {s["id"]: s for s in json.load(open(a.manifest, encoding="utf-8")).get("scenes", [])}

    os.makedirs(a.out, exist_ok=True)
    rows = []
    for s in scenes:
        wav_path = os.path.join(a.out, f"{s['id']}.wav")
        if only is not None and s["id"] not in only and s["id"] in old and os.path.isfile(wav_path):
            rows.append(dict(old[s["id"]], subtitle=s.get("subtitle") or s["text"]))
            continue
        try:
            data = synth(a.host, s["text"], style_id, speed, pause)
        except EngineError as e:
            print(f"ERROR  {s['id']} の合成に失敗: {e}")
            return 3
        with open(wav_path, "wb") as f:
            f.write(data)
        sec = round(wav_seconds(wav_path), 3)
        rows.append({"id": s["id"], "text": s["text"], "subtitle": s.get("subtitle") or s["text"],
                     "file": rel_to_public(wav_path), "seconds": sec})
        print(f"OK     {s['id']}  {sec:6.2f} 秒  {s['text'][:30]}")

    manifest = {
        "credit": f"VOICEVOX:{name}",
        "speaker": {"id": style_id, "name": name, "style": style},
        "scenes": rows,
        "total_seconds": round(sum(r["seconds"] for r in rows), 3),
    }
    os.makedirs(os.path.dirname(os.path.abspath(a.manifest)), exist_ok=True)
    with open(a.manifest, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"合計 {manifest['total_seconds']:.2f} 秒 / {len(rows)} シーン / クレジット表記「{manifest['credit']}」")
    return 0


if __name__ == "__main__":
    sys.exit(main())
