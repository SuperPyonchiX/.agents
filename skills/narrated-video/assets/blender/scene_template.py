# Blender シーンの雛形。blender_render.py から `blender -b -P scene.py -- ...` で呼ばれる。
# 立体文字が回り込みながら現れるカットを、背景透過の連番 PNG（<out>/0001.png〜）で書き出す。
# コピーして build_scene() を書き換える。引数の受け取りとレンダリング設定はそのまま使う。
#
# --set で渡せる値: text=表示する文字 / color=#RRGGBB / font=フォントファイルのパス
import argparse
import math
import os
import sys

import bpy


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--frames", type=int, required=True)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--set", action="append", default=[])
    a = p.parse_args(argv)
    a.opts = dict(kv.split("=", 1) for kv in a.set)
    return a


def hex_rgba(h):
    # Base Color はリニア値で受け取る。画面の色（sRGB）をそのまま渡すと白っぽく抜ける
    h = h.lstrip("#")
    srgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb) + (1.0,)


def japanese_font(path):
    cands = [path] if path else []
    cands += [r"C:\Windows\Fonts\YuGothB.ttc", r"C:\Windows\Fonts\meiryob.ttc",
              "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"]
    for c in cands:
        if c and os.path.isfile(c):
            return bpy.data.fonts.load(c)
    return None  # 既定フォントは日本語を持たない。豆腐になったら font= で渡す


def setup_render(a):
    sc = bpy.context.scene
    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):  # 版によって名前が違う
        try:
            sc.render.engine = engine
            break
        except TypeError:
            continue
    sc.render.resolution_x, sc.render.resolution_y = a.width, a.height
    sc.render.resolution_percentage = 100
    sc.render.fps = a.fps
    sc.render.film_transparent = True
    sc.view_settings.view_transform = "Standard"  # 既定の AgX は彩度を落とし、指定した色からずれる
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    sc.render.filepath = os.path.join(a.out, "")  # <out>/0001.png から連番
    sc.frame_start, sc.frame_end = 1, a.frames
    # 環境光。背景は透過で写らないが、無いと影側が真っ黒になり色が沈む
    sc.world = bpy.data.worlds.new("World")
    sc.world.use_nodes = True
    bg = sc.world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (1, 1, 1, 1)
    bg.inputs["Strength"].default_value = 0.6


def build_scene(a):
    o = a.opts
    bpy.ops.object.text_add(location=(0, 0, 0))
    txt = bpy.context.object
    txt.data.body = o.get("text", "SAMPLE")
    font = japanese_font(o.get("font"))
    if font:
        txt.data.font = font
    txt.data.align_x, txt.data.align_y = "CENTER", "CENTER"
    txt.data.extrude = 0.12
    txt.data.bevel_depth = 0.02
    mat = bpy.data.materials.new("TextMat")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = hex_rgba(o.get("color", "#38bdf8"))
    bsdf.inputs["Metallic"].default_value = 0.2  # 上げると環境光を映すだけになり、指定色より暗く見える
    bsdf.inputs["Roughness"].default_value = 0.3
    txt.data.materials.append(mat)

    # 文字が奥から回り込んで正面で止まる
    end = max(2, int(a.frames * 0.6))
    txt.rotation_euler = (math.radians(90), 0, math.radians(-60))
    txt.scale = (0.2, 0.2, 0.2)
    txt.keyframe_insert("rotation_euler", frame=1)
    txt.keyframe_insert("scale", frame=1)
    txt.rotation_euler = (math.radians(90), 0, 0)
    txt.scale = (1, 1, 1)
    txt.keyframe_insert("rotation_euler", frame=end)
    txt.keyframe_insert("scale", frame=end)

    bpy.ops.object.camera_add(location=(0, -7, 0), rotation=(math.radians(90), 0, 0))
    bpy.context.scene.camera = bpy.context.object
    bpy.ops.object.light_add(type="AREA", location=(3, -4, 4))
    bpy.context.object.data.energy = 800
    bpy.ops.object.light_add(type="AREA", location=(-4, -2, -1))
    bpy.context.object.data.energy = 300


def main():
    a = parse_args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    setup_render(a)
    build_scene(a)
    bpy.ops.render.render(animation=True)


main()
