import { useEffect, useRef } from "react";

export type HotkeyAction =
  | "togglePlaying"
  | "replay"
  | "previous"
  | "next"
  | "toggleReveal"
  | "cycleRepeat"
  | "slower"
  | "faster"
  | "toggleAutoAdvance"
  | "dismiss";

export type HotkeyHandlers = Record<HotkeyAction, () => void>;

// 字母键按小写匹配，Caps Lock 或 Shift 下同样生效。
export const HOTKEYS: Readonly<Record<string, HotkeyAction>> = {
  " ": "togglePlaying",
  r: "replay",
  ArrowLeft: "previous",
  ArrowRight: "next",
  Enter: "toggleReveal",
  l: "cycleRepeat",
  "[": "slower",
  "]": "faster",
  a: "toggleAutoAdvance",
  Escape: "dismiss"
};

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.tagName === "INPUT" ||
    target.tagName === "TEXTAREA" ||
    target.tagName === "SELECT" ||
    target.isContentEditable
  );
}

function isActivatable(target: EventTarget | null): boolean {
  // 焦点在按钮或链接上时，Space/Enter 属于该控件自身的激活键，交给浏览器处理，避免一次按键触发两次动作。
  return target instanceof HTMLElement && target.closest("button, a[href], summary") !== null;
}

/**
 * 在 window 上监听练习台快捷键。enabled=false（例如对话框打开）时只保留 Escape。
 * handlers 每次渲染都可以是新对象：监听器通过 ref 读取最新回调，不会反复重新注册。
 */
export function useHotkeys(handlers: HotkeyHandlers, enabled: boolean) {
  const latest = useRef({ handlers, enabled });

  useEffect(() => {
    latest.current = { handlers, enabled };
  });

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      // 组合键留给浏览器与系统（如 Ctrl+R 刷新），输入法组字中的按键也不处理。
      if (event.defaultPrevented || event.isComposing) return;
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
      const action = HOTKEYS[key];
      if (action === undefined) return;
      const { handlers: current, enabled: active } = latest.current;
      // Escape 用于关闭对话框，即使焦点在对话框的输入框里也应生效。
      if (action !== "dismiss") {
        if (!active || isEditable(event.target)) return;
        if ((key === " " || key === "Enter") && isActivatable(event.target)) return;
      }
      event.preventDefault();
      current[action]();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
}
