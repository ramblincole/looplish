import { useEffect, useRef } from "react";
import { useModalOpen } from "../../components/Modal/modalRegistry";
import { actionForKey, controlOwnsKey, type HotkeyAction } from "./hotkeys";

export type HotkeyHandlers = Record<HotkeyAction, () => void>;

/**
 * 在 window 上监听练习台快捷键。有弹层打开时全部暂停；Escape 不在这里处理，由弹层自己关闭。
 * handlers 每次渲染都可以是新对象：监听器通过 ref 读取最新回调，不会反复重新注册。
 */
export function useHotkeys(handlers: HotkeyHandlers) {
  const modalOpen = useModalOpen();
  const latest = useRef({ handlers, modalOpen });

  useEffect(() => {
    latest.current = { handlers, modalOpen };
  });

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      // 组合键留给浏览器与系统（如 Ctrl+R 刷新），输入法组字中的按键也不处理。
      if (event.defaultPrevented || event.isComposing) return;
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      const action = actionForKey(event.key);
      if (action === undefined) return;
      const { handlers: current, modalOpen: blocked } = latest.current;
      if (blocked || controlOwnsKey(event.target, event.key)) return;
      event.preventDefault();
      current[action]();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
}
