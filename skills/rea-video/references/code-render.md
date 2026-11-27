# 写代码重做

代码渲染、MG 动效、插画动画这类镜头本来就是写代码做出来的，复刻也照这样做：让编程能力强的模型（如 Claude Opus 5.5 及以上、Gemini 4 系列）按拆解结果直接写动画代码，渲染成 MP4，得到一个可改的工程，比 rea-video 自带的 `code-remake` 草稿更接近原片。

可以直接写 HTML / CSS / Canvas 动画，也可以参考现成的开源框架，用哪个由用户定：

| 框架 | 是什么 | 费用和条件 |
|---|---|---|
| [HyperFrames](https://github.com/heygen-com/hyperframes) | HTML 视频框架，写 HTML / CSS 动画渲染成 MP4 | 免费（Apache-2.0），本地渲染，需要 Node.js 22 以上；它的 Studio 应用另有付费套餐，只重做代码类镜头用不到 |
| [Remotion](https://www.remotion.dev) | 用 React 组件写视频，逐帧渲染成 MP4 | 个人和小团队免费，公司使用要买许可；需要 Node.js |

## 怎么装

HyperFrames，Claude Code 里：

```bash
claude plugin marketplace add heygen-com/hyperframes
claude plugin install hyperframes@hyperframes
```

其他编程助手（Codex、Cursor 等）运行一次 `npx hyperframes skills update`。装完以后按它的 skill 让助手写视频。

Remotion：`npx create-video@latest` 建一个工程，让助手在里面写。

## 给它什么

把这些交给写代码的模型，说明「照这个节奏和画面重做，不要用原片像素」：

1. `video/rhythm.md`：每个切点和转场的时间、转场类型和时长、每镜关键帧（时间 + 是哪一种：动作开始 / 到位、转折、元素出入、构图变化……）。每个时间后面的 @数字 是原片帧号，按帧号排（工程用同样的帧率），不要按四舍五入的秒数；动画的关键帧就按这里排，中间交给缓动。
2. 每镜关键帧图 `shots/shot_XXX.jpg`，和报告「代码合成」一节：版式、配色（色值）、元素是什么、怎么入场。
3. 声音：`stems/music.wav` 当配乐，或按 `video/sound.md` 的 BPM 和情绪换一首；音效时间点在 `video/sound.md`。
4. 字幕和花字：`packaging/timeline.json`（时间、位置、样式）。

只想重做其中几镜时，说清楚镜头号和时间范围；其余镜头可以原片占位，做好的片段写进 `remake/mine.json`，用 `rea-video remake out/ref` 拼回原时间线（见 `diy.md`）。
