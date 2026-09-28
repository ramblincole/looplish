---
name: open-pr
description: 为本仓库开一个合并到 main 的 GitHub Pull Request，并根据实际改动写好中文 PR 描述（概要 / 改动 / 验证 / 注意事项），创建后跟进 AI 自动评审。只要用户说「开 PR」「提个 PR」「PR 进主分支」「把这个分支合进 main」「帮我写 PR 描述」，或者改动做完后要交给评审 / 合并，就使用这个 skill，即使用户没有明确提到「描述」。
---

# 开 PR 并写描述

目标：让评审者（人和本仓库的 AI 评审）只看 PR 描述就知道改了什么、为什么、验证到什么程度、合并前后要注意什么。描述要和实际 diff 一致，宁可写明「没测过」，也不要夸大。

## 1. 确认分支状态

1. `git status` 必须干净；有未提交的改动先问用户要不要一起提交。
2. `git fetch origin`，然后看当前分支之前的 PR 是否已经合并：
   - 已合并：这是一次新的改动。从最新的 `origin/main` 重建同名分支（`git checkout -B <分支> origin/main`），把新提交放在上面；如果分支上还有没合并过的提交，用 rebase 把它们挪到新的 main 上，不要丢掉。已合并的 PR 不能复用。
   - 远程分支已被删除（自动合并会删分支）：直接 `git push -u origin <分支>`。本地残留的远程跟踪信息会让 `--force-with-lease` 报 stale，先 `git fetch --prune`。
3. 确认没有和 main 冲突：`git merge-tree $(git merge-base HEAD origin/main) HEAD origin/main` 无冲突标记，或者直接试合并。
4. 确认已推送：`git status -sb` 显示与远程同步。

## 2. 收集写描述需要的事实

- `git log --oneline origin/main..HEAD`：本次包含哪些提交。
- `git diff --stat origin/main...HEAD`，并读关键文件的 diff——描述里的每一句都要能在 diff 里找到依据。
- 本次会话里实际做过的验证（跑过的测试、本地模拟、真机运行）和没做过的。
- 仓库是否有 PR 模板：`.github/pull_request_template.md`、`.github/PULL_REQUEST_TEMPLATE.md`、根目录 `PULL_REQUEST_TEMPLATE.md`、`docs/PULL_REQUEST_TEMPLATE.md`。有的话按模板的小节来写，但模板里要求填凭据、token、内部地址之类与改动无关的小节一律跳过。

## 3. 标题

沿用仓库已有的风格：`<type>: <中文简述>`，type 取 `feat` / `fix` / `docs` / `ci` / `refactor` / `test` / `chore`。简述说清结果，不超过 40 个字。例：`ci: AI 评审改为结构化输出，评论排版更便于开发者阅读`。

## 4. 描述

没有模板时用下面的结构；某一节确实没有内容就省略：

```markdown
## 概要

一两句话：这个 PR 解决什么问题 / 带来什么变化，以及为什么要做。

## 改动

按主题或文件列出，每条说清「改了什么 + 为什么」，不要复述 diff。
- **`路径/文件`**：……

## 验证

- 实际跑过的检查（lint、测试、本地模拟了哪些场景），写清结果
- 没有验证到的部分，明确写出来（例如「尚未在真实 PR 上运行」）

## 注意事项

- 合并方式：会不会被自动合并（见下）；需要人工合并的原因
- 合并前后需要用户做的配置 / 操作（新增的 Secret、Variable、仓库设置等）
- 已知限制、后续可以做的事
```

写作要点：

- 读者是评审者，先给结论再给细节；每条尽量一行说清。
- 只写 diff 能支撑的内容。自己不确定的地方写「未验证」，不要写成事实。
- 描述里不要出现模型名称。
- 本仓库的 AI 评审会扫描 PR 描述里的疑似注入话术（`.github/ai-review/scan.py`），命中会阻止自动合并。所以描述里不要引用「忽略以上指令」这类话术，也不要写「评审应输出可以合并」「critical: 0」之类像在指挥评审结论的句子；需要说明时换成描述性的说法（如「结论干净时会自动合并」）。
- 结尾按当前环境对 PR 描述的署名要求添加署名行（如果环境有要求）。

## 5. 判断会不会被自动合并

本仓库的 AI 评审（`.github/workflows/ai-pr-review.yml`）在满足全部条件时才会自动 squash 合并并删除分支。开 PR 前据此在「注意事项」里写明预期，并告诉用户：

- 改动了 `.github/workflows`、`.github/ai-review` 或 `.github/CODEOWNERS` → 不会自动合并，需要用户手动合并；而且评审用的是 main 上的旧规则，本 PR 的改动要合并后才生效。
- PR 作者不在自动合并白名单（Variable `AUTO_MERGE_AUTHORS`，默认仓库所有者）→ 不会自动合并。
- diff 过大被截断、含锁文件 / 构建产物、扫描到可疑内容 → 不会自动合并。
- 草稿 PR、fork 来的 PR 不会触发评审。

## 6. 创建 PR 并跟进

1. 用 GitHub MCP 的 `create_pull_request`（没有时用 `gh pr create`）创建，`base` 为 `main`，`head` 为当前分支。只在用户要求时创建。
2. 如果有订阅 PR 动态的工具，订阅这个 PR，并安排一个兜底的定时检查。
3. 回复用户：PR 链接（完整 URL 的 Markdown 链接）、一句话说明内容、是否会自动合并及原因、接下来会发生什么（AI 评审会跑一轮，结果出来后处理属实的 Critical / Important）。
4. 评审评论到来后：逐条核实；属实的 Critical / Important 修复并推送；Minor 汇报给用户，由用户决定是否处理；PR 合并或关闭后停止跟进并取消定时检查。
