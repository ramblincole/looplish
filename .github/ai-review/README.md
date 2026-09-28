# Claude Code 自动 PR 评审

工作流：`.github/workflows/ai-pr-review.yml`，评审提示词：`.github/ai-review/prompt.md`，评论渲染：`.github/ai-review/render.py`。
评审 agent 为 [anthropics/claude-code-action](https://github.com/anthropics/claude-code-action)（Claude Code），只开放只读工具（Read / Glob / Grep 和 `git diff/log/show/blame`）：
不能创建或修改任何文件，结论通过 `--json-schema` 约束的 `structured_output` 输出，由工作流发到 PR 评论。

- 超时：Claude Code 评审一步最多 20 分钟、最多 30 轮工具调用（`CLAUDE_REVIEW_MAX_TURNS`），整个任务最多 30 分钟；超时或失败都按「评审失败、不合并」处理。
- 触发方式是 `pull_request_target`：运行的始终是 `main` 上的工作流和提示词模板，PR 改不了自己的评审规则；PR 的代码只作为数据读取，从不执行。
  - 因此修改工作流或提示词的 PR，要**合并进 `main` 之后**才生效；引入本工作流的第一个 PR 不会被自己评审。
- 检出代码时不保存凭据（`persist-credentials: false`），评审报告中出现疑似 token / API key 时整份作废、不发到公开评论。
- 增量评审只采信 GitHub Actions 机器人发的、评审成功的上一次评论，并从它记录的提交开始评审（被取消或失败的评审不算）。

## 行为

| 事件 | 评审方式 |
| --- | --- |
| 指向 `main` 的 PR 新建 / 重新打开 / 从草稿转为 Ready | 全量评审 `merge-base...HEAD` |
| PR 有新提交（`synchronize`） | 增量评审：只看上次成功评审之后的新提交，并逐条跟进上次报告的 Critical / Important |
| 没有成功评审过、force-push、或新提交中含合并提交 | 回退为全量评审 |

- 模型只输出结构化的问题清单（级别、标题、文件和行号、问题、影响、建议、可选的修复代码、是否已核实、是否需人工确认），由 `render.py` 统一排成 PR 评论：
  - 顶部是结论、一两句摘要和各级问题数量；数量由脚本按清单统计，不依赖模型自己计数
  - Critical / Important 逐条展开，位置可点击跳到 PR 最新提交里的对应代码行
  - 增量评审附「上次问题跟进」表；Minor 和「做得好的」默认折叠
  - `render.py` 和提示词一样只取 `main` 上的版本
- **无 Critical 且无 Important** 时：自动 squash 合并、删除 PR 分支，并把报告邮件发给仓库所有者。
- 以下任一情况不合并：有 Critical / Important；问题计数为 0 但结论不是「可以合并」；有锁文件 / 构建产物未送审或 diff 被截断（评审覆盖不完整）；评审失败；评审期间有新推送（`--match-head-commit`）。
- 草稿 PR 和来自 fork 的 PR 不评审、不合并。
- 评审结论写在提交状态 **「AI 评审」** 上，和工作流本身的 ✅（只表示流程跑完了）分开：
  - ⏳ pending：评审进行中
  - ✅ success：没有 Critical / Important；因其他原因不能自动合并时（如改动了评审配置、作者不在白名单），描述里会写「需人工合并」和原因
  - ❌ failure：有 Critical / Important、结论与计数不一致，或评审失败 / 达到次数上限
  - ⚠️ error：本次评审被取消（有新提交或超时）
- 评审说明文字的语言由 `AI_REVIEW_LANGUAGE` 决定（默认简体中文）；代码、路径、报错原文保持原样。

## 需要配置（Settings → Secrets and variables → Actions）

Secrets：
- `ANTHROPIC_API_KEY` 或 `CLAUDE_CODE_OAUTH_TOKEN`（二选一，见下方「使用 Claude 官方模型」）
- （可选，不配置则不发邮件）`SMTP_SERVER`、`SMTP_PORT`（默认 465，走 SSL；587 走 STARTTLS）、`SMTP_USERNAME`、`SMTP_PASSWORD`
  - Gmail 示例：`smtp.gmail.com` / `465` / 你的 Gmail 地址 / 应用专用密码

Variables：
- `REVIEW_REPORT_EMAIL`：报告收件人；未设置时使用仓库所有者 GitHub 资料里公开的邮箱
- `CLAUDE_REVIEW_MODEL`（可选）：评审使用的模型，默认 `claude-opus-5`
- `CLAUDE_REVIEW_MAX_TURNS`（可选）：最多工具调用轮数，默认 `30`
- `CLAUDE_REVIEW_EFFORT`（可选）：推理强度 `low` / `medium` / `high` / `xhigh` / `max`；不设置时用模型自身的默认值（Opus 5.5 为 `medium`，其他多数模型为 `high`）
- `CLAUDE_REVIEW_MAX_BUDGET_USD`（可选）：单次评审的金额上限（美元），默认 `2`；超出即停止，本次按「评审失败、不合并」处理。只对 API Key 计费有意义
- `AI_REVIEW_MAX_PER_DAY`（可选）：同一个 PR 24 小时内最多自动评审几次，默认 `10`；达到上限后不再调用模型，只提醒一次
- `AUTO_MERGE_AUTHORS`（可选）：自动合并白名单，逗号分隔的 GitHub 用户名，默认只有仓库所有者；其他作者的 PR 只评审、不自动合并
- `AI_REVIEW_LANGUAGE`（可选）：评审报告使用的语言，默认 `简体中文`
- `AI_REVIEW_MAX_DIFF_BYTES`（可选）：送给模型的 diff 上限（字节），默认 `60000`，超出部分截断

另外请确认 Settings → Actions → General → Workflow permissions 为 “Read and write permissions”。
若 `main` 开启了分支保护（要求审批或状态检查），`GITHUB_TOKEN` 的自动合并会被拒绝，需要相应放宽规则。

## 安全机制

只有本仓库分支发起的 PR（即有写权限的人）会触发评审；fork 来的 PR 不评审、不消耗额度。在此基础上，针对提示词注入和额度消耗：

| 风险 | 防护 |
| --- | --- |
| 注入让 agent 读取并泄露 Key / token | Claude Code 只能用 Read / Grep / Glob 读取工作区（PR 代码）内的文件（`blockReadsOutsideWorkingDirectories`），不能执行任何命令、不能联网；检出时不保存凭据；结论里出现疑似凭据时整份作废 |
| 借评论外发数据、隐藏内容 | 渲染评论时转义模型输出中的 HTML 标签，并把图片语法改成纯文本（GitHub 会主动请求评论里的图片地址） |
| 注入骗过评审、自动合并 | 自动合并需同时满足：模型结论干净、问题数为 0、整个 PR 全部送审、未改动 CI / 评审规则、**确定性扫描无可疑内容**（隐形 / 双向控制字符、常见注入话术，见 `scan.py`）、**作者在白名单中** |
| 篡改评审规则 | 工作流、提示词、`render.py`、`scan.py` 都取自 `main`；改动它们的 PR 不自动合并 |
| 额度被刷 | 单次评审：最多 30 轮工具调用、20 分钟、金额上限；同一 PR 24 小时内最多评审 `AI_REVIEW_MAX_PER_DAY` 次（每次调用模型前先发「⏳ 评审进行中」占位评论并据此计数，被新推送取消的运行同样计入）；diff 超过上限截断 |

建议另外在 Anthropic Console 给所用 API Key 的 workspace 设置月度花费上限。

## 成本控制

- diff 由工作流预先生成并直接放进提示词，Claude 不用多轮调用工具去拉取改动；只在需要核实上下文时读文件。
- 锁文件、`*.min.*`、`*.map`、`dist/`、`build/`、`vendor/` 不送给模型；diff 超过上限会截断，并附文件列表。
- 有新提交时只做增量评审；同一 PR 的新推送会取消还在运行的旧评审。
- 想再省可以把 `CLAUDE_REVIEW_MODEL` 换成 `claude-sonnet-5`（约为 Opus 5 价格的 40%），或调低 `CLAUDE_REVIEW_MAX_TURNS`（漏报风险会上升）。

## 改用 DeepSeek（或其他兼容 Anthropic 接口的模型）

评审仍由 Claude Code（`claude-code-action`）执行，只把模型请求转到第三方接口：

| 类型 | 名称 | 值 |
| --- | --- | --- |
| Secret | `ANTHROPIC_API_KEY` | DeepSeek 的 API Key |
| Variable | `ANTHROPIC_BASE_URL` | DeepSeek 兼容 Anthropic 的接口地址，以 DeepSeek 官方文档为准 |
| Variable | `CLAUDE_REVIEW_MODEL` | DeepSeek 的模型名，以 DeepSeek 官方文档为准；**必须设置**，否则会用默认的 `claude-opus-5`，第三方接口不认 |

- 三个 `ANTHROPIC_DEFAULT_*_MODEL` 会自动指向 `CLAUDE_REVIEW_MODEL`，Claude Code 的后台请求也走同一个模型。
- 结论依赖模型稳定地调用工具、按 JSON schema 输出；第三方模型做不到时，这一轮按「评审失败、不合并」处理，不会误合并。
- 每次评审前会先用同样的地址、模型和 Key 发一个极小的测试请求（预检）。地址、模型名或 Key 不对时立即失败，PR 评论会写出 HTTP 状态码和接口返回的错误信息。
- 排查问题时把 Variable `AI_REVIEW_DEBUG` 设为 `true`，Actions 日志会显示 Claude Code 的完整输出（含它读到的文件内容），排查完改回来。
- 切回 Anthropic 官方：删掉 `ANTHROPIC_BASE_URL`，把 `CLAUDE_REVIEW_MODEL` 改回 Claude 模型（或删掉，使用默认值），Secret 换回 Anthropic 的 Key。

## 建议的分支保护

仓库已提交 `.github/CODEOWNERS`，把 `.github/workflows/`、`.github/ai-review/` 交给仓库所有者审批。要让它生效，还需要在 Settings → Branches → `main` 的分支保护规则里开启：

- Require a pull request before merging
- Require review from Code Owners

如果希望有阻塞问题的 PR 在合并按钮处就被拦住，可以再开启 Require status checks to pass，并把 **「AI 评审」** 加为必需检查（这个状态至少出现过一次后才能在列表里搜到）。注意：fork 来的 PR 和草稿 PR 不会产生这个状态，开启后它们需要管理员绕过才能合并。

工作流本身也会拒绝自动合并改动这两个目录的 PR；在 `pull_request_target` 下这条规则取自 `main`，PR 删不掉它。

## 使用 Claude 官方模型

两种凭据二选一：

| 方式 | Secret | 怎么获取 | 计费 |
| --- | --- | --- | --- |
| Claude 订阅（Pro / Max） | `CLAUDE_CODE_OAUTH_TOKEN` | 本机装好 Claude Code 并登录订阅账号后，运行 `claude setup-token`，复制输出的 token | 计入订阅额度，与本机使用共享用量上限 |
| API Key | `ANTHROPIC_API_KEY` | 在 https://console.anthropic.com → API Keys 创建（需单独充值） | 按 token 付费，与订阅无关 |

- 只配其中一个。两个都配时，预检按 API Key 进行，Claude Code 实际用哪一个取决于它自身的优先级，容易混淆。
- 删掉 Variable `ANTHROPIC_BASE_URL`；`CLAUDE_REVIEW_MODEL` 删掉（默认 `claude-opus-5`）或填 Claude 模型名，如 `claude-sonnet-5`。
- 使用订阅 token 时不做接口预检（该 token 只供 Claude Code 使用）；token 失效时评审会失败，重新运行 `claude setup-token` 更新 Secret 即可。
