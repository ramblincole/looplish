# Claude 自动 PR 评审

工作流：`.github/workflows/claude-pr-review.yml`，评审提示词：`.github/claude-review/prompt.md`。

## 行为

| 事件 | 评审方式 |
| --- | --- |
| 指向 `main` 的 PR 新建 / 重新打开 / 从草稿转为 Ready | 全量评审 `merge-base...HEAD` |
| PR 有新提交（`synchronize`） | 增量评审：只看新提交（跳过从 main 合并进来的改动），并逐条跟进上次报告的 Critical / Important |
| force-push 或此前没有评审记录 | 回退为全量评审 |

- 报告以 PR 评论发布，格式为「结论 / Critical / Important / Minor（摘要）/ 做得好的」。
- **无 Critical 且无 Important** 时：自动 squash 合并、删除 PR 分支，并把报告邮件发给仓库所有者。
- 有 Critical / Important、评审失败、或评审期间有新推送（`--match-head-commit`）时：不合并。
- 草稿 PR 和来自 fork 的 PR 不评审、不合并。

## 需要配置（Settings → Secrets and variables → Actions）

Secrets：
- `ANTHROPIC_API_KEY` 或 `CLAUDE_CODE_OAUTH_TOKEN`（二选一）
- `SMTP_SERVER`、`SMTP_PORT`（默认 465，走 SSL；587 走 STARTTLS）、`SMTP_USERNAME`、`SMTP_PASSWORD`
  - Gmail 示例：`smtp.gmail.com` / `465` / 你的 Gmail 地址 / 应用专用密码

Variables：
- `REVIEW_REPORT_EMAIL`：报告收件人；未设置时使用仓库所有者 GitHub 资料里公开的邮箱
- `CLAUDE_REVIEW_MODEL`（可选）：评审使用的模型，默认 `claude-opus-5-5`

另外需要安装 Claude GitHub App（https://github.com/apps/claude），
并确认 Settings → Actions → General → Workflow permissions 为 “Read and write permissions”。
若 `main` 开启了分支保护（要求审批或状态检查），`GITHUB_TOKEN` 的自动合并会被拒绝，需要相应放宽规则。
