export type HotkeyAction =
  | "togglePlaying"
  | "replay"
  | "previous"
  | "next"
  | "toggleReveal"
  | "cycleRepeat"
  | "slower"
  | "faster"
  | "toggleAutoAdvance";

export type HotkeyBinding = {
  /** KeyboardEvent.key；字母一律小写，匹配时忽略大小写。 */
  key: string;
  action: HotkeyAction;
  /** 快捷键面板上显示的按键名。 */
  label: string;
  description: string;
};

/** 唯一的按键表：键盘监听与快捷键面板都从这里生成，文档不会和行为对不上。 */
export const HOTKEY_BINDINGS: readonly HotkeyBinding[] = [
  { key: " ", action: "togglePlaying", label: "空格", description: "播放 / 暂停当前句" },
  { key: "r", action: "replay", label: "R", description: "从头重听当前句" },
  { key: "ArrowLeft", action: "previous", label: "←", description: "上一句" },
  { key: "ArrowRight", action: "next", label: "→", description: "下一句" },
  { key: "Enter", action: "toggleReveal", label: "Enter", description: "显示 / 隐藏原文" },
  { key: "l", action: "cycleRepeat", label: "L", description: "切换循环遍数" },
  { key: "[", action: "slower", label: "[", description: "减速" },
  { key: "]", action: "faster", label: "]", description: "加速" },
  { key: "a", action: "toggleAutoAdvance", label: "A", description: "自动下一句开关" }
];

const ACTION_BY_KEY = new Map(HOTKEY_BINDINGS.map((binding) => [binding.key, binding.action]));

export function actionForKey(key: string): HotkeyAction | undefined {
  return ACTION_BY_KEY.get(key.length === 1 ? key.toLowerCase() : key);
}

// 会接收字符输入的 input 类型：聚焦时所有快捷键都让路。
const TEXT_INPUT_TYPES = new Set([
  "text",
  "search",
  "email",
  "url",
  "tel",
  "password",
  "number",
  "date",
  "datetime-local",
  "month",
  "time",
  "week"
]);

const ACTIVATION_KEYS = new Set([" ", "Enter"]);

/**
 * 焦点所在的控件是否要自己处理这个键。返回 true 时快捷键让路，交给浏览器的默认行为。
 * 规则见 spec 5.8：文本类全部让路；复选/单选只留 Space；滑块只留方向键；
 * 下拉框留方向键、Space、Enter；按钮与链接留 Space、Enter。
 */
export function controlOwnsKey(target: EventTarget | null, key: string): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable || target.getAttribute("contenteditable") === "true") return true;
  if (target instanceof HTMLTextAreaElement) return true;
  if (target instanceof HTMLInputElement) {
    if (TEXT_INPUT_TYPES.has(target.type)) return true;
    if (target.type === "checkbox" || target.type === "radio") return key === " ";
    if (target.type === "range") return key.startsWith("Arrow");
    // 其余 input（button、submit、file 等）按按钮处理。
    return ACTIVATION_KEYS.has(key);
  }
  if (target instanceof HTMLSelectElement) {
    return ACTIVATION_KEYS.has(key) || key.startsWith("Arrow");
  }
  if (target.closest("button, a[href], summary") !== null) return ACTIVATION_KEYS.has(key);
  return false;
}
