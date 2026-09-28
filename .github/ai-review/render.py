#!/usr/bin/env python3
"""把评审 agent 输出的结构化结论渲染成 PR 评论（Markdown）。

用法：render.py <result.json> <输出.md>
环境变量：REPO（owner/name）、HEAD_SHA、REVIEW_MODE（full / incremental）、SERVER_URL（可选）

模型只负责给出结构化的问题清单，版式、计数和代码链接都在这里统一生成，
保证每次评论格式一致，条数与清单严格对应。
"""
import json
import os
import re
import sys
from urllib.parse import quote

MAX_CHARS = 60000  # GitHub 评论上限 65536，留出页脚余量

SEVERITY = {
    "critical": ("🔴", "Critical", "合入前必须修复"),
    "important": ("🟠", "Important", "合入前应当修复"),
    "minor": ("🟡", "Minor", "可选改进"),
}
FOLLOWUP_STATUS = {
    "fixed": "✅ 已修复",
    "partially_fixed": "🟠 部分修复",
    "still_open": "🔴 仍存在",
}
SAFE_PATH = re.compile(r"^[A-Za-z0-9._/@+\-]+$")


# 放进代码块的字段原样保留：代码块里的 HTML 实体不会被解析，转义反而会让修复代码无法照抄
VERBATIM_FIELDS = {"suggested_code"}


# 只把同一行内成对的反引号当作代码，开头和结尾都必须是完整的反引号串（前后不能再紧挨反引号），
# 和 Markdown「n 个反引号开头只能由恰好 n 个反引号结束」一致。
# 这个判断不必和 GitHub 的解析器完全一致：代码之外的正文会把反斜杠、反引号、[ 和 < 全部转义，
# GitHub 看到的代码就只剩这里认定的这些，不会出现两边切分错位（例如链接目标里的反引号、
# 跨行的代码）让 HTML 漏出去的情况。
CODE_SPAN = re.compile(r"(?<![`\\])(`+)(?!`)[^\n]*?(?<!`)\1(?!`)")


def neutralize(text):
    """代码之外的正文：转义反斜杠、反引号和 [（不能再开启代码、链接和图片），以及 <（不能写 HTML，
    防止隐藏内容、伪造评审标记、<img> 外发请求）。
    反引号包起来的代码原样保留，GitHub 不会渲染其中的 HTML 和图片。"""
    out, pos = [], 0
    for m in CODE_SPAN.finditer(text):
        out.append(_neutralize_prose(text[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(_neutralize_prose(text[pos:]))
    # 图片语法无论在不在代码里都改掉：宁可代码片段里多一个反斜杠，也不留外发请求的口子
    return "".join(out).replace("![", "!\\[")


def _neutralize_prose(text):
    # 先转义反斜杠：否则模型写的 \` 会变成 \\`，反引号又能开启代码
    for ch in ("\\", "`", "["):
        text = text.replace(ch, "\\" + ch)
    return text.replace("<", "&lt;")


def sanitize(value):
    """递归处理模型给出的正文字符串（见 neutralize）。"""
    if isinstance(value, str):
        return neutralize(value)
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, dict):
        return {k: v if k in VERBATIM_FIELDS else sanitize(v) for k, v in value.items()}
    return value


def one_line(text):
    """列表里的字段压成一行，避免破坏 Markdown 结构。"""
    return re.sub(r"\s*\n\s*", " ", str(text or "")).strip()


def cell(text):
    """表格单元格：压成一行并转义竖线。"""
    return one_line(text).replace("|", "\\|")


def location(f, repo, sha, server):
    path = re.sub(r"^(\./)+", "", str(f.get("file") or "").strip()).lstrip("/")
    if not path:
        return ""
    start = int(f.get("line_start") or 0)
    end = int(f.get("line_end") or 0)
    label = path
    if start > 0:
        label += f":{start}" + (f"-{end}" if end > start else "")
    # 只给看起来正常的仓库内相对路径生成链接
    if not SAFE_PATH.match(path) or ".." in path.split("/"):
        return f"`{label}`"
    url = f"{server}/{repo}/blob/{sha}/{quote(path)}"
    if start > 0:
        url += f"#L{start}" + (f"-L{end}" if end > start else "")
    return f"[`{label}`]({url})"


def fence(code):
    """代码块围栏比内容里最长的反引号串多一个，防止被截断。"""
    longest = max((len(m) for m in re.findall(r"`+", code)), default=0)
    return "`" * max(3, longest + 1)


def render_finding(i, f, repo, sha, server):
    tags = [location(f, repo, sha, server)]
    if f.get("verified"):
        tags.append("✅ 已核实")
    if f.get("needs_human"):
        tags.append("👤 需人工确认")
    out = [f"#### {i}. {one_line(f.get('title'))}", " · ".join(t for t in tags if t), ""]
    out.append(f"**问题**：{str(f.get('problem') or '').strip()}")
    if str(f.get("impact") or "").strip():
        out.append("")
        out.append(f"**影响**：{str(f.get('impact')).strip()}")
    if str(f.get("suggestion") or "").strip():
        out.append("")
        out.append(f"**建议**：{str(f.get('suggestion')).strip()}")
    code = str(f.get("suggested_code") or "").rstrip()
    if code:
        fc = fence(code)
        out += ["", f"{fc}{one_line(f.get('code_language')) or ''}", code, fc]
    out.append("")
    return out


def render(data, repo, sha, mode, server, include_code=True, include_optional=True):
    findings = [f for f in data.get("findings") or [] if isinstance(f, dict)]
    by_sev = {k: [f for f in findings if f.get("severity") == k] for k in SEVERITY}
    n_crit, n_imp, n_min = (len(by_sev[k]) for k in ("critical", "important", "minor"))
    blocking = n_crit + n_imp
    mode_label = "增量" if mode == "incremental" else "全量"

    lines = []
    # 这里只表达评审发现；能否自动合并还取决于覆盖完整性等条件，由页脚说明
    if blocking:
        verdict = "❌ 有需要修复的问题"
    elif data.get("conclusion") != "可以合并":
        verdict = "⚠️ 未列出阻塞问题，但评审结论为「建议修复后再看」"
    else:
        verdict = "✅ 未发现阻塞问题"
    lines.append(f"## AI 评审（{mode_label}）：{verdict}")
    lines.append("")
    summary = str(data.get("summary") or "").strip()
    if summary:
        lines += ["> " + s for s in summary.splitlines()] + [""]
    lines.append("| 🔴 Critical | 🟠 Important | 🟡 Minor |")
    lines.append("| :---: | :---: | :---: |")
    lines.append(f"| {n_crit} | {n_imp} | {n_min} |")
    lines.append("")

    # 阻塞合并的问题完整展开，其余折叠，开发者先看到必须处理的内容
    for key in ("critical", "important"):
        items = by_sev[key]
        if not items:
            continue
        emoji, name, hint = SEVERITY[key]
        lines.append(f"### {emoji} {name}（{len(items)}）— {hint}")
        lines.append("")
        for i, f in enumerate(items, 1):
            lines += render_finding(i, f if include_code else {**f, "suggested_code": ""}, repo, sha, server)

    followups = [x for x in data.get("followups") or [] if isinstance(x, dict)]
    if followups:
        lines.append("### 🔁 上次问题跟进")
        lines.append("")
        lines.append("| 问题 | 状态 | 说明 |")
        lines.append("| --- | --- | --- |")
        for x in followups:
            status = FOLLOWUP_STATUS.get(x.get("status"), cell(x.get("status")))
            lines.append(f"| {cell(x.get('title'))} | {status} | {cell(x.get('note'))} |")
        lines.append("")

    if by_sev["minor"] and include_optional:
        lines.append(f"<details><summary>🟡 Minor（{n_min}）— 可选改进，点击展开</summary>")
        lines.append("")
        for f in by_sev["minor"]:
            loc = location(f, repo, sha, server)
            text = one_line(f.get("problem"))
            sug = one_line(f.get("suggestion"))
            lines.append(f"- **{one_line(f.get('title'))}**" + (f" {loc}" if loc else "") + f"：{text}" + (f"；建议：{sug}" if sug else ""))
        lines += ["", "</details>", ""]

    highlights = [one_line(h) for h in data.get("highlights") or [] if str(h).strip()]
    if not include_optional and (by_sev["minor"] or highlights):
        lines += ["_报告过长，Minor 和「做得好的」已省略。_", ""]
    if highlights and include_optional:
        lines.append(f"<details><summary>👍 做得好的（{len(highlights)}）</summary>")
        lines.append("")
        lines += [f"- {h}" for h in highlights]
        lines += ["", "</details>", ""]

    text = "\n".join(lines).rstrip() + "\n"
    return text, n_crit, n_imp, n_min


def render_within_limit(data, repo, sha, mode, server):
    """超长时依次省略修复代码、Minor 和「做得好的」；仍然超长就在条目边界截断，不切断代码块或折叠块。"""
    for include_code, include_optional in ((True, True), (False, True), (False, False)):
        text, *counts = render(data, repo, sha, mode, server, include_code, include_optional)
        if len(text) <= MAX_CHARS:
            return (text, *counts)
    cut = text.rfind("\n#### ", 0, MAX_CHARS)
    text = text[: cut if cut > 0 else MAX_CHARS] + "\n\n…（报告过长，其余条目已截断）\n"
    return (text, *counts)


def main():
    with open(sys.argv[1], encoding="utf-8") as fh:
        data = sanitize(json.load(fh))
    text, n_crit, n_imp, n_min = render_within_limit(
        data,
        repo=os.environ.get("REPO", ""),
        sha=os.environ.get("HEAD_SHA", ""),
        mode=os.environ.get("REVIEW_MODE", "full"),
        server=os.environ.get("SERVER_URL", "https://github.com"),
    )
    with open(sys.argv[2], "w", encoding="utf-8") as fh:
        fh.write(text)
    # 供工作流读取的计数
    print(f"critical={n_crit}")
    print(f"important={n_imp}")
    print(f"minor={n_min}")


if __name__ == "__main__":
    main()
