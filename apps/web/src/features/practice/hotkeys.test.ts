import { describe, expect, it } from "vitest";
import { actionForKey, controlOwnsKey, HOTKEY_BINDINGS } from "./hotkeys";

function element(html: string): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = html;
  return host.firstElementChild as HTMLElement;
}

const KEYS = [" ", "Enter", "ArrowRight", "r", "]"] as const;

// 每行：聚焦元素 → 各按键是否归控件自己（true = 快捷键让路）。
const MATRIX: Array<[string, string, Record<(typeof KEYS)[number], boolean>]> = [
  [
    "文本输入框",
    '<input type="text">',
    { " ": true, Enter: true, ArrowRight: true, r: true, "]": true }
  ],
  [
    "搜索框",
    '<input type="search">',
    { " ": true, Enter: true, ArrowRight: true, r: true, "]": true }
  ],
  [
    "数字框",
    '<input type="number">',
    { " ": true, Enter: true, ArrowRight: true, r: true, "]": true }
  ],
  [
    "多行文本",
    "<textarea></textarea>",
    { " ": true, Enter: true, ArrowRight: true, r: true, "]": true }
  ],
  [
    "可编辑区域",
    '<div contenteditable="true"></div>',
    { " ": true, Enter: true, ArrowRight: true, r: true, "]": true }
  ],
  [
    "复选框",
    '<input type="checkbox">',
    { " ": true, Enter: false, ArrowRight: false, r: false, "]": false }
  ],
  [
    "单选框",
    '<input type="radio">',
    { " ": true, Enter: false, ArrowRight: false, r: false, "]": false }
  ],
  [
    "滑块",
    '<input type="range">',
    { " ": false, Enter: false, ArrowRight: true, r: false, "]": false }
  ],
  [
    "下拉框",
    "<select></select>",
    { " ": true, Enter: true, ArrowRight: true, r: false, "]": false }
  ],
  [
    "按钮",
    "<button></button>",
    { " ": true, Enter: true, ArrowRight: false, r: false, "]": false }
  ],
  [
    "链接",
    '<a href="/">x</a>',
    { " ": true, Enter: true, ArrowRight: false, r: false, "]": false }
  ],
  ["普通区域", "<div></div>", { " ": false, Enter: false, ArrowRight: false, r: false, "]": false }]
];

describe("controlOwnsKey", () => {
  it.each(MATRIX)("%s", (_, html, expected) => {
    const target = element(html);
    for (const key of KEYS) {
      expect([key, controlOwnsKey(target, key)]).toEqual([key, expected[key]]);
    }
  });

  it("treats a missing or non-element target as the page", () => {
    expect(controlOwnsKey(null, " ")).toBe(false);
    expect(controlOwnsKey(window, " ")).toBe(false);
  });
});

describe("actionForKey", () => {
  it("matches letters case-insensitively and ignores unknown keys", () => {
    expect(actionForKey(" ")).toBe("togglePlaying");
    expect(actionForKey("L")).toBe("cycleRepeat");
    expect(actionForKey("l")).toBe("cycleRepeat");
    expect(actionForKey("Escape")).toBeUndefined();
    expect(actionForKey("x")).toBeUndefined();
  });

  it("documents every action exactly once", () => {
    const actions = HOTKEY_BINDINGS.map((binding) => binding.action);
    expect(new Set(actions).size).toBe(actions.length);
    expect(HOTKEY_BINDINGS.every((binding) => binding.description.length > 0)).toBe(true);
  });
});
