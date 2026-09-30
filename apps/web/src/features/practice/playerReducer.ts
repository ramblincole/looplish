export type Repeat = 1 | 2 | 3 | 5 | "infinite";
export type GapMode = { kind: "fixed"; seconds: number } | { kind: "sentence" };

export const REPEAT_OPTIONS: readonly Repeat[] = [1, 2, 3, 5, "infinite"];
export const MIN_RATE = 0.6;
export const MAX_RATE = 1.25;
export const RATE_STEP = 0.05;

export type PlayerState = {
  sentenceIndex: number;
  playCount: number;
  revealed: boolean;
  playing: boolean;
  rate: number;
  repeat: Repeat;
  gapMode: GapMode;
  autoAdvance: boolean;
  alwaysHide: boolean;
  visitedIndexes: ReadonlySet<number>;
  /** 每次「从句首重听」加一，AudioController 据此区分重听与暂停后继续。 */
  replayCount: number;
};

export type PlayerEvent =
  | { type: "select"; index: number }
  | { type: "move"; offset: 1 | -1; sentenceCount: number }
  | { type: "togglePlaying" }
  | { type: "setPlaying"; value: boolean }
  | { type: "replay" }
  | { type: "toggleReveal" }
  | { type: "setRate"; value: number }
  | { type: "stepRate"; direction: 1 | -1 }
  | { type: "setRepeat"; value: Repeat }
  | { type: "cycleRepeat" }
  | { type: "setGap"; value: GapMode }
  | { type: "toggleAutoAdvance" }
  | { type: "toggleAlwaysHide" }
  | { type: "completed"; sentenceCount: number }
  | { type: "reset" };

export const initialPlayerState: PlayerState = {
  sentenceIndex: 0,
  playCount: 0,
  revealed: false,
  playing: false,
  rate: 1,
  repeat: 1,
  gapMode: { kind: "fixed", seconds: 1 },
  autoAdvance: false,
  alwaysHide: true,
  visitedIndexes: new Set(),
  replayCount: 0
};

export function nextRepeat(repeat: Repeat): Repeat {
  return REPEAT_OPTIONS[(REPEAT_OPTIONS.indexOf(repeat) + 1) % REPEAT_OPTIONS.length];
}

export function stepRate(rate: number, direction: 1 | -1): number {
  // 按步长取整，避免 0.05 的浮点累加产生 0.8500000001 这类显示值。
  return Math.round((rate + direction * RATE_STEP) * 100) / 100;
}

export function playerReducer(state: PlayerState, event: PlayerEvent): PlayerState {
  switch (event.type) {
    case "select":
      // 选句会停止当前播放并清空本句循环计数；盲听模式下重新遮罩文本。
      return {
        ...state,
        sentenceIndex: event.index,
        playCount: 0,
        playing: false,
        revealed: state.alwaysHide ? false : state.revealed,
        visitedIndexes: new Set([...state.visitedIndexes, event.index])
      };
    case "move": {
      // 上一句/下一句基于最新索引计算；首尾处保持原状，不因越界请求清空当前循环计数。
      const index = state.sentenceIndex + event.offset;
      if (index < 0 || index >= event.sentenceCount) return state;
      return playerReducer(state, { type: "select", index });
    }
    case "togglePlaying":
      return { ...state, playing: !state.playing };
    case "setPlaying":
      return { ...state, playing: event.value };
    case "replay":
      // 重听重新开始本句的循环计数，并要求音频回到句首而不是从暂停处继续。
      return { ...state, playing: true, playCount: 0, replayCount: state.replayCount + 1 };
    case "toggleReveal":
      return { ...state, revealed: !state.revealed };
    case "setRate":
      // reducer 是最后一道边界，将有限数值的倍速限制在产品范围内；非有限值直接忽略。
      if (!Number.isFinite(event.value)) return state;
      return { ...state, rate: Math.min(MAX_RATE, Math.max(MIN_RATE, event.value)) };
    case "stepRate":
      // 快捷键连发时同一帧内可能到达多次，基于 reducer 中的最新倍速累加，而不是组件闭包里的旧值。
      return playerReducer(state, {
        type: "setRate",
        value: stepRate(state.rate, event.direction)
      });
    case "setRepeat":
      return { ...state, repeat: event.value, playCount: 0 };
    case "cycleRepeat":
      return { ...state, repeat: nextRepeat(state.repeat), playCount: 0 };
    case "setGap":
      return { ...state, gapMode: event.value };
    case "toggleAutoAdvance":
      return { ...state, autoAdvance: !state.autoAdvance };
    case "toggleAlwaysHide":
      return { ...state, alwaysHide: !state.alwaysHide };
    case "completed": {
      const visitedIndexes = new Set([...state.visitedIndexes, state.sentenceIndex]);
      const required = state.repeat === "infinite" ? Number.POSITIVE_INFINITY : state.repeat;
      // 循环次数未满足时留在当前句，由 Provider 在留白结束后重新播放。
      if (state.playCount + 1 < required) {
        return { ...state, playCount: state.playCount + 1, playing: false, visitedIndexes };
      }
      if (state.autoAdvance && state.sentenceIndex + 1 < event.sentenceCount) {
        // 自动前进只在还有下一句时发生，末句永远不会越界。
        return {
          ...state,
          sentenceIndex: state.sentenceIndex + 1,
          playCount: 0,
          playing: false,
          revealed: state.alwaysHide ? false : state.revealed,
          visitedIndexes
        };
      }
      return { ...state, playCount: 0, playing: false, visitedIndexes };
    }
    case "reset":
      // 重新切句后句子索引整体失效：回到第 0 句并清空已练标记，只保留用户的练习偏好。
      return {
        ...state,
        sentenceIndex: 0,
        playCount: 0,
        playing: false,
        revealed: state.alwaysHide ? false : state.revealed,
        visitedIndexes: new Set()
      };
  }
}
