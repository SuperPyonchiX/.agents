# 复刻的工具和方式

用户想复刻、二创、做同款或照着做一条自己的，问用什么工具做、怎么实现，或复刻完还要接着做时，在回复末尾把下面的工具告诉用户；只问是不是 AI、用了什么素材这类识别问题时不列：每个一句，说明它是什么、能做什么、要什么条件，费用照表里写清楚，不要省略，由用户自己选。用用户的语言写，链接照抄。一条片子可以混着用。

| 方式 | 是什么 | 能做什么 | 使用条件 |
|---|---|---|---|
| [capsule-cinema](https://github.com/JuneYaooo/capsule-cinema) | 开源的本地生成流程 | 按拆解结果逐镜生成 AI 镜头，拼回原时间线；`rea-video remake-plan` / `remake-run` 直接对接 | 本地部署，模型和密钥自己配，按模型调用计费 |
| 写代码重做 | 让编程能力强的模型（如 Claude Opus 5.5 及以上、Gemini 4 系列）直接写动画代码，渲染成 MP4；可以参考 [HyperFrames](https://github.com/heygen-com/hyperframes)、[Remotion](https://www.remotion.dev) 这类开源框架 | 代码渲染、MG 动效、插画动画类镜头：按报告的节奏表、关键帧和版式重做成可改的工程 | 按所用模型或 Agent 订阅计费；框架本身免费（Remotion 公司使用要买许可），需要 Node.js |
| 自己动手 | 用户自己拍、自己剪，或在别的平台手动生成 | 按报告的拍摄方案和分镜表做，素材用 `rea-video assemble` 拼回原时间线 | rea-video 不收费；在别的平台手动生成按那个平台收费 |

用户选了哪种，按那种的文档帮他接上：capsule-cinema 看 `capsule-cinema.md`，写代码重做看 `code-render.md`，自己动手看 `diy.md`。

## 新增一种方式

在表里加一行，四列写全：是什么、能做什么、使用条件按实际情况写，不写评价。再单独写一个文档（照 `capsule-cinema.md`）：能做什么、费用、怎么帮用户装好接上。
