import type { Repeat } from "./playerReducer";

/** 循环设置的展示文案，旋钮选项与快捷键提示共用。 */
export function formatRepeat(repeat: Repeat): string {
  if (repeat === "infinite") return "一直重复";
  return repeat === 1 ? "不循环" : `每句 ${repeat} 遍`;
}

export function formatRate(rate: number): string {
  return `${rate.toFixed(2)}×`;
}
