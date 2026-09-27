// ナレーション付き動画の雛形。voicevox_tts.py が書いた narration.json を読み、
// シーンごとに「音声の長さ + 余白」の尺で並べ、最後にクレジット画面を付ける。
// 使い方: src/ にコピーし、SCENE_VISUALS にシーン id ごとの画面を書き足す。
// Root.tsx で <NarratedComposition /> を登録する。
import { Audio } from "@remotion/media";
import React from "react";
import {
  AbsoluteFill,
  Composition,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
} from "remotion";
import narration from "./narration.json";

const FPS = 30;
const WIDTH = 1920;
const HEIGHT = 1080;
const TAIL_FRAMES = 6; // シーン末尾の余白（音声が切れて見えないように）。scene_frames.py の --tail と合わせる
const CREDIT_FRAMES = 2 * FPS; // クレジット画面の長さ。scene_frames.py の --credit と合わせる

type SceneRow = { id: string; text: string; subtitle: string; file: string; seconds: number };
const scenes = narration.scenes as SceneRow[];

const sceneFrames = scenes.map((s) => Math.ceil(s.seconds * FPS) + TAIL_FRAMES);
const starts = sceneFrames.map((_, i) =>
  sceneFrames.slice(0, i).reduce((a, b) => a + b, 0),
);
const TOTAL_FRAMES = sceneFrames.reduce((a, b) => a + b, 0) + CREDIT_FRAMES;

// シーン id ごとの画面。無い id は DefaultScene（字幕だけ）で描く。
const SCENE_VISUALS: Record<string, React.FC<{ text: string }>> = {
  // s01: ({ text }) => <TitleScene title="..." />,
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
  <AbsoluteFill style={{ backgroundColor: "#0f172a" }} />
);

const Scene: React.FC<{ row: SceneRow }> = ({ row }) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 8], [0, 1], { extrapolateRight: "clamp" });
  const Visual = SCENE_VISUALS[row.id] ?? DefaultScene;
  return (
    <AbsoluteFill style={{ opacity }}>
      <Visual text={row.subtitle} />
      <Subtitle text={row.subtitle} />
      <Audio src={staticFile(row.file)} />
    </AbsoluteFill>
  );
};

const Credit: React.FC = () => (
  <AbsoluteFill
    style={{
      backgroundColor: "#0f172a",
      justifyContent: "center",
      alignItems: "center",
      color: "#cbd5e1",
      fontSize: 40,
    }}
  >
    {narration.credit}
  </AbsoluteFill>
);

export const NarratedVideo: React.FC = () => (
  <AbsoluteFill
    style={{ fontFamily: "'Yu Gothic UI', 'Meiryo', 'Hiragino Sans', sans-serif" }}
  >
    {scenes.map((row, i) => (
      <Sequence key={row.id} from={starts[i]} durationInFrames={sceneFrames[i]} name={row.id}>
        <Scene row={row} />
      </Sequence>
    ))}
    <Sequence from={TOTAL_FRAMES - CREDIT_FRAMES} durationInFrames={CREDIT_FRAMES} name="credit">
      <Credit />
    </Sequence>
  </AbsoluteFill>
);

export const NarratedComposition: React.FC = () => (
  <Composition
    id="Narrated"
    component={NarratedVideo}
    durationInFrames={TOTAL_FRAMES}
    fps={FPS}
    width={WIDTH}
    height={HEIGHT}
  />
);
