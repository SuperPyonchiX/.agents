// ナレーション付き動画の雛形。timeline.py が書いた timeline.json だけを見て、
// シーンを from・duration どおりに並べ、BGM と（あれば）クレジット画面を付ける。尺の計算はここでしない。
// 使い方: src/ にコピーし、SCENE_VISUALS にシーン id ごとの画面を書き足す。
// Root.tsx で <NarratedComposition /> を登録する。
import { Audio } from "@remotion/media";
import React, { createContext, useContext } from "react";
import {
  AbsoluteFill,
  Composition,
  Img,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
} from "remotion";
import timeline from "./timeline.json";

const WIDTH = 1920;
const HEIGHT = 1080;
const BGM_VOLUME = 0.22; // ナレーションより十分小さく。試聴で聞き取りにくければ下げる
const BGM_FILE: string | null = timeline.bgm; // 手持ちの曲を使うなら "bgm/曲.mp3" のように書く
const BG_COLOR = "#0f172a"; // シーンの後ろの色。フェード中に透けて見える
const FADE_FRAMES = timeline.bpm ? 0 : 8; // 拍に合わせるときはフェードせず拍の頭で切り替える

type SceneRow = { id: string; subtitle: string; file: string; from: number; duration: number };
type Beat = { frame: number; downbeat: boolean };
const scenes = timeline.scenes as SceneRow[];
const beats = timeline.beats as Beat[];

// シーン内の useCurrentFrame() は 0 始まりなので、拍の計算用に動画全体での開始位置を配る
const SceneStart = createContext(0);

// 直前の拍からの経過で 1→0 に落ちる値。拍に合わせて弾ませる・光らせるのに使う
export const useBeat = (decayFrames = 8) => {
  const abs = useCurrentFrame() + useContext(SceneStart);
  let last: Beat | undefined;
  let index = -1;
  for (let i = 0; i < beats.length && beats[i].frame <= abs; i++) {
    last = beats[i];
    index = i;
  }
  const since = last ? abs - last.frame : Infinity;
  const pulse = interpolate(since, [0, decayFrames], [1, 0], { extrapolateRight: "clamp" });
  return { index, since, pulse, downbeat: last?.downbeat ?? false };
};

// blender_render.py が書いた連番 PNG を、シーン内のフレームに合わせて1枚ずつ出す
export const BlenderClip: React.FC<{ dir: string; frames: number; style?: React.CSSProperties }> = ({
  dir,
  frames,
  style,
}) => {
  const n = Math.min(useCurrentFrame() + 1, frames); // 最後の1枚で止める
  return (
    <Img
      src={staticFile(`${dir}/${String(n).padStart(4, "0")}.png`)}
      style={{ position: "absolute", width: "100%", height: "100%", objectFit: "contain", ...style }}
    />
  );
};

// シーン id ごとの画面。無い id は DefaultScene（字幕だけ）で描く。
const SCENE_VISUALS: Record<string, React.FC<{ text: string }>> = {
  // s01: () => <BlenderClip dir="3d/s01" frames={45} />,
};

const Subtitle: React.FC<{ text: string }> = ({ text }) => (
  <div
    style={{
      position: "absolute",
      left: 120,
      right: 120,
      bottom: 70,
      textAlign: "center",
      fontSize: 44,
      lineHeight: 1.4,
      color: "white",
      textShadow: "0 2px 8px rgba(0,0,0,0.8)",
    }}
  >
    {text}
  </div>
);

const DefaultScene: React.FC<{ text: string }> = () => (
  <AbsoluteFill style={{ backgroundColor: BG_COLOR }} />
);

const Scene: React.FC<{ row: SceneRow }> = ({ row }) => {
  const frame = useCurrentFrame();
  const opacity =
    FADE_FRAMES > 0 ? interpolate(frame, [0, FADE_FRAMES], [0, 1], { extrapolateRight: "clamp" }) : 1;
  const Visual = SCENE_VISUALS[row.id] ?? DefaultScene;
  return (
    <SceneStart.Provider value={row.from}>
      <AbsoluteFill style={{ opacity }}>
        <Visual text={row.subtitle} />
        <Subtitle text={row.subtitle} />
        <Audio src={staticFile(row.file)} />
      </AbsoluteFill>
    </SceneStart.Provider>
  );
};

const Credit: React.FC = () => (
  <AbsoluteFill
    style={{
      backgroundColor: BG_COLOR,
      justifyContent: "center",
      alignItems: "center",
      color: "#cbd5e1",
      fontSize: 40,
    }}
  >
    {timeline.credit}
  </AbsoluteFill>
);

export const NarratedVideo: React.FC = () => (
  <AbsoluteFill
    style={{
      backgroundColor: BG_COLOR,
      fontFamily: "'Yu Gothic UI', 'Meiryo', 'Hiragino Sans', sans-serif",
    }}
  >
    {BGM_FILE ? <Audio src={staticFile(BGM_FILE)} volume={BGM_VOLUME} /> : null}
    {scenes.map((row) => (
      <Sequence key={row.id} from={row.from} durationInFrames={row.duration} name={row.id}>
        <Scene row={row} />
      </Sequence>
    ))}
    {timeline.creditFrames > 0 ? (
      <Sequence
        from={timeline.totalFrames - timeline.creditFrames}
        durationInFrames={timeline.creditFrames}
        name="credit"
      >
        <Credit />
      </Sequence>
    ) : null}
  </AbsoluteFill>
);

export const NarratedComposition: React.FC = () => (
  <Composition
    id="Narrated"
    component={NarratedVideo}
    durationInFrames={timeline.totalFrames}
    fps={timeline.fps}
    width={WIDTH}
    height={HEIGHT}
  />
);
