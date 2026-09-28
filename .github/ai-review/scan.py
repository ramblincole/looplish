#!/usr/bin/env python3
"""在把改动交给模型之前，用确定性规则扫描可疑内容。

用法：scan.py <diff 文件> <PR 描述文件>
输出（stdout，每行一条）：命中的问题摘要；没有命中时不输出。

只检查 diff 中新增的行和 PR 描述。命中不会阻止评审，只会让本 PR 不能自动合并，
交给人工确认——模型可能被注入内容骗过，这道检查不依赖模型。
"""
import re
import sys

# 可让代码「看起来」和实际不同的字符（Trojan Source）以及零宽字符
INVISIBLE = {
    "‪": "LRE", "‫": "RLE", "‬": "PDF", "‭": "LRO", "‮": "RLO",
    "⁦": "LRI", "⁧": "RLI", "⁨": "FSI", "⁩": "PDI",
    "​": "零宽空格", "‌": "ZWNJ", "‍": "ZWJ", "⁠": "WJ", "﻿": "BOM/ZWNBSP",
    "­": "软连字符",
}

# 试图操纵评审 agent 的常见话术（中英文）
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier|preceding)\s+(instructions|prompts?|rules)",
    r"disregard\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier)\b",
    r"(forget|override)\s+(all\s+|your\s+)?(previous\s+|prior\s+)?(instructions|rules|system\s+prompt)",
    r"\byou\s+are\s+now\b",
    r"\bnew\s+instructions\s*:",
    r"\b(system|developer)\s+(prompt|message)\s*:",
    r"(AI|LLM|model|reviewer|assistant|claude|codex)\b[^\n]{0,40}\b(must|should)\s+(approve|output|return|respond|report)",
    r"忽略[^\n]{0,8}(以上|之前|前面|上述|先前|所有)[^\n]{0,8}(指令|指示|提示|规则|要求)",
    r"(无视|不要理会)[^\n]{0,8}(指令|指示|提示|规则)",
    r"(评审|审查|审核)[^\n]{0,10}(输出|返回|给出|判定|认定)[^\n]{0,10}(可以合并|通过|无问题)",
    r"(直接|必须|务必)[^\n]{0,6}(输出|返回|判定)[^\n]{0,6}(可以合并|通过)",
    r"\"?(critical|important)\"?\s*:\s*0\b",
    r"\"?conclusion\"?\s*:\s*\"?可以合并",
]
INJECTION_RE = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


def added_lines(diff_text):
    """diff 中新增的行，附带所在文件名。"""
    current = ""
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            current = line[4:].removeprefix("b/")
        elif line.startswith("+") and not line.startswith("+++"):
            yield current, line[1:]


def scan(diff_text, body_text):
    hits = []
    sources = [(f, l) for f, l in added_lines(diff_text)] + [("PR 描述", l) for l in body_text.splitlines()]

    invisible = {}
    for where, line in sources:
        for ch in line:
            if ch in INVISIBLE:
                invisible.setdefault(INVISIBLE[ch], set()).add(where)
    for name, files in sorted(invisible.items()):
        hits.append(f"隐形/双向控制字符 {name}：{', '.join(sorted(files)[:5])}")

    seen = set()
    for where, line in sources:
        for rx in INJECTION_RE:
            m = rx.search(line)
            if m and (where, rx.pattern) not in seen:
                seen.add((where, rx.pattern))
                hits.append(f"疑似提示词注入话术「{m.group(0)[:40]}」：{where}")
    return hits


def main():
    with open(sys.argv[1], encoding="utf-8", errors="replace") as fh:
        diff_text = fh.read()
    with open(sys.argv[2], encoding="utf-8", errors="replace") as fh:
        body_text = fh.read()
    for hit in scan(diff_text, body_text)[:20]:
        print(hit.replace("\n", " "))


if __name__ == "__main__":
    main()
