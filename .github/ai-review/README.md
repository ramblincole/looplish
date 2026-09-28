# Claude Code 自动 PR 评审

工作流：`.github/workflows/ai-pr-review.yml`，评审提示词：`.github/ai-review/prompt.md`。
评审 agent 为 [anthropics/claude-code-action](https://github.com/anthropics/claude-code-action)（Claude Code），只开放只读工具（Read / Glob / Grep 和 `git diff/log/show/blame`）：
不能创建或修改任何文件，结论通过 `--json-schema` 约束的 `structured_output` 输出，由工作流发到 PR 评论。

- 超时：Claude Code 评审一步最多 20 分钟、最多 30 轮工具调用（`CLAUDE_REVIEW_MAX_TURNS`），整个任务最多 30 分钟；超时或失败都按「评审失败、不合并」处理。
- 提示词模板从目标分支（`main`）读取，PR 改模板影响不到自己的评审。例外：模板首次引入（`main` 上还没有）时只能读取 PR 自带的版本。
- 增量评审只采信 GitHub Actions 机器人发的、评审成功的上一次评论，并从它记录的提交开始评审（被取消或失败的评审不算）。

## 行为

| 事件 | 评审方式 |
| --- | --- |
| 指向 `main` 的 PR 新建 / 重新打开 / 从草稿转为 Ready | 全量评审 `merge-base...HEAD` |
| PR 有新提交（`synchronize`） | 增量评审：只看上次成功评审之后的新提交，并逐条跟进上次报告的 Critical / Important |
| 没有成功评审过、force-push、或新提交中含合并提交 | 回退为全量评审 |

- 报告以 PR 评论发布，格式为「结论 / Critical / Important / Minor（摘要）/ 做得好的」。
- **无 Critical 且无 Important** 时：自动 squash 合并、删除 PR 分支，并把报告邮件发给仓库所有者。
- 以下任一情况不合并：有 Critical / Important；问题计数为 0 但结论不是「可以合并」；有锁文件 / 构建产物未送审或 diff 被截断（评审覆盖不完整）；评审失败；评审期间有新推送（`--match-head-commit`）。
- 草稿 PR 和来自 fork 的 PR 不评审、不合并。

## 需要配置（Settings → Secrets and variables → Actions）

Secrets：
- `ANTHROPIC_API_KEY`
- （可选，不配置则不发邮件）`SMTP_SERVER`、`SMTP_PORT`（默认 465，走 SSL；587 走 STARTTLS）、`SMTP_USERNAME`、`SMTP_PASSWORD`
  - Gmail 示例：`smtp.gmail.com` / `465` / 你的 Gmail 地址 / 应用专用密码

Variables：
- `REVIEW_REPORT_EMAIL`：报告收件人；未设置时使用仓库所有者 GitHub 资料里公开的邮箱
- `CLAUDE_REVIEW_MODEL`（可选）：评审使用的模型，默认 `claude-opus-5`
- `CLAUDE_REVIEW_MAX_TURNS`（可选）：最多工具调用轮数，默认 `30`
- `AI_REVIEW_MAX_DIFF_BYTES`（可选）：送给模型的 diff 上限（字节），默认 `60000`，超出部分截断

另外请确认 Settings → Actions → General → Workflow permissions 为 “Read and write permissions”。
若 `main` 开启了分支保护（要求审批或状态检查），`GITHUB_TOKEN` 的自动合并会被拒绝，需要相应放宽规则。

## 成本控制

- diff 由工作流预先生成并直接放进提示词，Claude 不用多轮调用工具去拉取改动；只在需要核实上下文时读文件。
- 锁文件、`*.min.*`、`*.map`、`dist/`、`build/`、`vendor/` 不送给模型；diff 超过上限会截断，并附文件列表。
- 有新提交时只做增量评审；同一 PR 的新推送会取消还在运行的旧评审。
- 想再省可以把 `CLAUDE_REVIEW_MODEL` 换成 `claude-sonnet-5`（约为 Opus 5 价格的 40%），或调低 `CLAUDE_REVIEW_MAX_TURNS`（漏报风险会上升）。
