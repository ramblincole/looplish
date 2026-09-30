import { createContext, useContext, useMemo } from "react";
import type { PlayerEvent, PlayerState } from "./playerReducer";

export type PlayerContextValue = {
  state: PlayerState;
  sentenceCount: number;
  /** 句子播完后正在等待跟读留白，留白结束会自动重播或进入下一句。 */
  waiting: boolean;
  /** 用户事件入口：会先取消尚未触发的留白计时，再派发给 reducer。 */
  send: (event: PlayerEvent) => void;
  /** 由 AudioController 在到达 sentence.end 时调用。 */
  completed: () => void;
};

export const PlayerContext = createContext<PlayerContextValue | null>(null);

export function usePlayer(): PlayerContextValue {
  const value = useContext(PlayerContext);
  // 在 Provider 外读取播放器状态属于组合错误，直接暴露而不是返回默认值掩盖问题。
  if (value === null) throw new Error("usePlayer must be used inside <PlayerProvider>");
  return value;
}

export type PlayerActions = {
  previous: () => void;
  next: () => void;
  togglePlaying: () => void;
  replay: () => void;
  toggleReveal: () => void;
  cycleRepeat: () => void;
  slower: () => void;
  faster: () => void;
  toggleAutoAdvance: () => void;
};

/** 按钮与快捷键共用的动作集合，保证两种入口派发完全相同的 reducer 事件。 */
export function usePlayerActions(): PlayerActions {
  const { sentenceCount, send } = usePlayer();
  return useMemo(
    () => ({
      previous: () => send({ type: "move", offset: -1, sentenceCount }),
      next: () => send({ type: "move", offset: 1, sentenceCount }),
      togglePlaying: () => send({ type: "togglePlaying" }),
      replay: () => send({ type: "replay" }),
      toggleReveal: () => send({ type: "toggleReveal" }),
      cycleRepeat: () => send({ type: "cycleRepeat" }),
      slower: () => send({ type: "stepRate", direction: -1 }),
      faster: () => send({ type: "stepRate", direction: 1 }),
      toggleAutoAdvance: () => send({ type: "toggleAutoAdvance" })
    }),
    [send, sentenceCount]
  );
}
