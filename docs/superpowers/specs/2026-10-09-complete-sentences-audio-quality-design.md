# 完整切句与练习音频提质 设计说明

- 日期：2026-10-09
- 范围：`apps/api`（识别、切句、媒体处理）；README 配置表；不改 API 契约与前端
- 触发问题：
  1. 一句完整的话经常被切成两句；用户不在意单句时长，只要求整句完整。
  2. 练习页播放的音频不如原视频清楚，部分流畅对话被截断后听起来像噪音。

## 1. 实测证据

素材：本机任务 `40B6B687AFE9916D`（B 站英文 vlog，12.4 分钟，带背景音乐），模型 `small.en`，切句用当前默认参数。

| 识别方式 | 非句末标点结尾的句子 | 零停顿处强制拆分 | 词数 | 耗时 |
|---|---|---|---|---|
| 当前：批量（batch 8） | 34 / 80 | 15 | 1178 | 约 45s |
| 非批量 | 38 / 74 | 17 | 1175 | 43s |
| 非批量 + `condition_on_previous_text` | 57 / 59 | 25 | 1165 | 84s |
| 批量 + 标点提示词 | 7 / 112 | 0 | 1105（漏识别约 6%） | 48s |
| **非批量 + 上下文 + 标点提示词** | **8 / 111** | **0** | **1190** | 102s |

结论：

1. **切句不完整的根因是识别结果缺标点**。当前输出大段无标点（如 "good morning today is Thursday I'm getting ready for work and I just took a shower…"），切句只能退回停顿和 14 秒上限，于是在零停顿处硬切（"…I've actually been wanting to ‖ vlog for such a long time"）。
2. 批量模式加提示词会整段漏识别（300–340s、540s 附近），不可用；非批量 + 上下文 + 提示词无漏词、无重复 6-gram。
3. **VAD 拼接造成词时间戳错位**：跨拼接点的词被标到另一侧（"Good" 标在 0.00s，实际在 12.7s；"So I ‖ just realized" 显示 2.3s 停顿）。这些假停顿触发 `hard_pause` 硬切，产生 "I'm" 这类单词孤岛，并让句首或句尾音节落到相邻句。
4. **音质**：96k 单声道 AAC 与原音频相比信噪比 31 dB、各频段能量一致，转码本身损失有限；但原音频左右声道相关仅 0.64、side 能量 −6.5 dB，混成单声道后背景音乐与人声叠在一起，削弱可懂度。
5. **切点**：零停顿处硬切加上时间戳误差，切点落在词中间；留白又被限制在句间空隙的中点（`segmentation.py` `_sentences`），连读处几乎没有余量。

## 2. 已确认的决策

| 问题 | 决定 |
|---|---|
| 识别方式 | 本地 faster-whisper 改非批量 + `condition_on_previous_text=True` + 带标点的英文 `initial_prompt`；接受识别耗时约翻倍 |
| 批量开关 | 删除 `asr_batch_size` 配置项，不保留快速模式 |
| mlx 后端 | 同步传入相同两个参数 |
| 切句策略 | 有标点时完整句优先；无标点时维持按停顿兜底 |
| 单句上限 | `max_duration` 默认 14s → 30s，仅作兜底 |
| 无标点字幕 | `auto` 模式视为没有可用字幕，改走 ASR；`existing` 模式照用 |
| 练习音频 | 原音轨为 AAC 时直接拷贝；否则 AAC 160k，保留立体声（多于 2 声道降到 2） |
| 句首留白 | 默认 0.2s → 0.3s；首尾留白上限从「空隙中点」放宽到「相邻句语音边界」 |

非目标：云端后端（`whisper-1` 的词数组本身无标点，另议）、VAD 参数调整、前端改动、浏览器慢速播放的音质。

## 3. 识别

### 3.1 faster-whisper（`infrastructure/asr/local_backend.py`）

- 只构建 `WhisperModel`，不再包 `BatchedInferencePipeline`；删除构造参数 `batch_size`。
- `transcribe` 参数：
  - `condition_on_previous_text=True`
  - `initial_prompt=PUNCTUATED_PROMPT`，仅当 `language` 为 `None` 或以 `en` 开头时传入；其他语言不传，避免把识别带偏成英文。
  - `word_timestamps`、`vad_filter`、`vad_parameters` 不变。
- 防幻觉沿用 faster-whisper 默认的压缩比阈值、温度回退和 `prompt_reset_on_temperature`。
- `PUNCTUATED_PROMPT` 为模块级常量，取实测用的那句：`"Hello, everyone. Welcome back! Today, I'm going to show you my routine. Are you ready? Let's go."`

### 3.2 mlx（`infrastructure/asr/mlx_backend.py`）

`mlx_whisper.transcribe` 改为 `condition_on_previous_text=True`，按同样的语言规则传 `initial_prompt`。提示词与语言判断放在两个后端共用的位置（`timeline.py` 或新的小模块），不重复定义。

### 3.3 配置（`config.py`、`registry.py`、README、`.env.example`）

删除 `asr_batch_size` 及其 README 中英文配置表行、`.env.example` 行。`Settings` 是 `extra="ignore"`，旧 `.env` 中残留的 `LOOPLISH_ASR_BATCH_SIZE` 不会报错。

## 4. 切句（`domain/segmentation.py`）

### 4.1 是否有标点

`_is_punctuated(words)`：句末标点（复用 `_is_terminal`）数量 × 40 ≥ 词数，即平均每 40 词至少一个句末。整份转写的这一判断只用于字幕（见第 5 节）；切句时按局部判断：一个词在 20 词（`PUNCTUATION_WINDOW`，即密度的一半）以内有句末标点，就算处在有标点的区域，下面的规则逐词按所在区域取用，一长段无标点内容不会被前后的标点区域带偏。

### 4.2 有标点时：完整句优先

初分组时，在词 `i` 与 `i+1` 之间：

1. `_is_terminal(i)` → 断开（与现在相同）。
2. 停顿 ≥ `hard_pause`：若 `i` 不是句末，且 `i+1` 以小写字母开头 → **不断开**；否则断开。
3. 其余不断开。

合并阶段：任何不以句末结尾的组（不论时长）与相邻组合并，只要合并后时长 ≤ `max_duration`。选择方向沿用现有规则（停顿更短的一侧，相等时向前）；仍不允许左侧已完整时向后合并跨过句末。

### 4.3 无标点时：维持现状

初分组、合并的行为与现在一致（停顿 ≥ `hard_pause` 断开，短于 `min_duration` 的碎片合并）。云端识别和无标点字幕走这里。

### 4.4 超长兜底拆分

两种模式共用 `_split_long`，候选切点额外要求：停顿 ≥ 0.15s，或左侧以子句标点结尾。没有合格候选时整句保留，允许超过 `max_duration`（与现有「无合法切点可超长」的行为一致）。评分公式不变。

### 4.5 默认值（`models.py`、`config.py`）

| 参数 | 旧 | 新 |
|---|---|---|
| `max_duration` / `LOOPLISH_SEG_MAX_SECONDS` | 14.0 | 30.0 |
| `lead_pad` / `LOOPLISH_SEG_LEAD_PAD_SECONDS` | 0.20 | 0.30 |

校验范围不变（`max_duration` 2–60）。README 配置表同步；前端 `SettingsDrawer.tsx` 注释里写的默认值同步。

### 4.6 留白（`_sentences`）

```
start = max(0, speech_start - lead_pad, 上一句 speech_end)
end   = min(max(media_duration, speech_end), speech_end + tail_pad, 下一句 speech_start)
```

（首句没有「上一句」、末句没有「下一句」时对应项省略；`max(media_duration, speech_end)` 沿用现有的末词容差处理。）

相邻句的播放窗口可以重叠，但任何窗口都不覆盖邻句的语音。前端逐句定位播放，不依赖窗口互不重叠。

### 4.7 旧任务

「重新切句」直接用存储的词重新跑，能用上第 4 节的规则；第 3 节的识别改进需要重新处理任务。

## 5. 字幕选择（`application/processing_pipeline.py`）

`_subtitle` 解析出字幕后，若 `subtitle_source` 为 `auto` 且该字幕判定为无标点（同 4.1 的判断，公开为领域函数 `is_punctuated(words)`），返回 `None`，交给 ASR。`existing` 模式不做此判断；只有 `asr_backend == "local"` 时才丢弃——云端后端（openai/groq）的词数组同样没有标点，丢掉字幕只会白花钱。

## 6. 音频（`infrastructure/media/ffmpeg_processor.py`）

### 6.1 探测音轨

新增 `probe_audio(source) -> AudioStream(codec, channels)`，用 `ffprobe -select_streams a:0 -show_entries stream=codec_name,channels`。没有音轨时与时长探测一样报 `MEDIA_PROCESSING_FAILED`。

### 6.2 `to_web_audio`

- 两条命令都以 `-map 0:a:0` 开头，保证处理的就是探测的那条音轨。
- `codec == "aac"`：`-vn -c:a copy -movflags +faststart`。命令失败（如容器不兼容）时删除半成品，改走重新编码。
- 否则：`-vn -c:a aac -b:a 160k -ar 44100 -movflags +faststart`；`channels > 2` 时加 `-ac 2`，否则保留原声道数。
- `MediaProcessor` 端口签名不变（`to_web_audio(source, target) -> Path`），探测在适配器内部完成。

### 6.3 导出切片

`CLIP_MP3` 去掉 `-ac 1`，保留立体声；码率不变。

## 7. 测试

- `test_segmentation.py`：
  - 新增来自实测的用例：小写续接跨长停顿不断开（"So I ‖ just realized"）；大写开头跨长停顿断开；不完整碎片不论时长都并入邻句；无标点转写维持按停顿切；兜底拆分不在零停顿处下刀；`is_punctuated` 阈值边界。
  - 「切片窗口不重叠」改为「窗口不覆盖邻句语音」；300 组随机时间轴的不变量测试同步更新。
  - 受默认值变化影响的现有用例显式传参，保持原意。
- `test_asr_backends.py`：faster-whisper 不再使用批量管线；英文/未指定语言传 `initial_prompt` 与 `condition_on_previous_text=True`，非英文不传提示词；mlx 同样断言；删除 batch 相关用例。
- `test_media_adapters.py`：AAC 源走 `-c:a copy`；拷贝失败回退重编码；非 AAC 走 160k；多声道加 `-ac 2`；切片命令不含 `-ac 1`。
- `test_pipeline.py`：`auto` 遇无标点字幕改走 ASR；`existing` 照用。
- 端到端复核：用同一 B 站素材跑完整流程，对照第 1 节表格；导出原先被切坏的十几处句子片段供人工试听。
