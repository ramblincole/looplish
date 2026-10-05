import type { Repeat } from "./playerReducer";

/** 循环设置的展示文案，旋钮选项与快捷键提示共用。 */
export function formatRepeat(repeat: Repeat): string {
  if (repeat === "infinite") return "一直重复";
  return repeat === 1 ? "不循环" : `每句 ${repeat} 遍`;
}

export function formatRate(rate: number): string {
  return `${rate.toFixed(2)}×`;
}

const pad2 = (value: number) => String(value).padStart(2, "0");

/** 本句内的播放时间「00:01.2」：按 0.1 秒向下取整，避免 59.96 进位成「00:60.0」。 */
export function formatClock(seconds: number): string {
  const tenths = Math.floor(Math.max(0, seconds) * 10);
  const minutes = Math.floor(tenths / 600);
  return `${pad2(minutes)}:${((tenths % 600) / 10).toFixed(1).padStart(4, "0")}`;
}

export function formatDuration(seconds: number): string {
  return `${seconds.toFixed(1)}s`;
}

/** 句子清单里的开始发声时间：四舍五入到整秒，「01:04」；满一小时为「1:02:05」。 */
export function formatStart(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = pad2(total % 60);
  return hours > 0 ? `${hours}:${pad2(minutes)}:${rest}` : `${pad2(minutes)}:${rest}`;
}

/** 当前循环轮次：playCount 是本句已完整听完的轮数，正在播放的是下一轮。 */
export function formatLoop(playCount: number, repeat: Repeat): string {
  const round = playCount + 1;
  return repeat === "infinite" ? `循环 ${round}/∞` : `循环 ${Math.min(round, repeat)}/${repeat}`;
}
