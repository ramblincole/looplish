import {
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type ReactNode
} from "react";
import type { JobResult } from "../../api/types";
import { createPlayhead } from "./playhead";
import { PlayerContext, type PlayerContextValue } from "./playerContext";
import { initialPlayerState, playerReducer, type PlayerEvent } from "./playerReducer";

export function PlayerProvider({ result, children }: { result: JobResult; children: ReactNode }) {
  const [state, dispatch] = useReducer(playerReducer, initialPlayerState);
  const [waiting, setWaiting] = useState(false);
  // 每个练习台只创建一次；重新切句后由 AudioController 在定位句首时更新时间。
  const [playhead] = useState(() => createPlayhead(result.sentences[0]?.start ?? 0));
  // completed 由 RAF 回调触发，需要读取最新已提交状态，而不是闭包中的旧值。
  const stateRef = useRef(state);
  const gapTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sentenceCount = result.sentences.length;

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const clearGap = useCallback(() => {
    if (gapTimer.current !== null) {
      clearTimeout(gapTimer.current);
      gapTimer.current = null;
    }
    setWaiting(false);
  }, []);

  // 卸载时撤销留白计时，避免离开页面后仍向已销毁的 reducer 派发。
  useEffect(() => clearGap, [clearGap]);

  const send = useCallback(
    (event: PlayerEvent) => {
      // 选句、播放/暂停、重听和重置都会让之前安排的「留白后继续」失去意义。
      if (
        event.type === "select" ||
        event.type === "move" ||
        event.type === "togglePlaying" ||
        event.type === "setPlaying" ||
        event.type === "replay" ||
        event.type === "reset"
      ) {
        clearGap();
      }
      dispatch(event);
    },
    [clearGap]
  );

  const completed = useCallback(() => {
    clearGap();
    const current = stateRef.current;
    const event = { type: "completed", sentenceCount } as const;
    // 先同步算出下一状态决定是否继续，再派发同一事件，保证计时决策与 reducer 一致。
    const next = playerReducer(current, event);
    stateRef.current = next;
    dispatch(event);
    const continues =
      next.playCount > current.playCount || next.sentenceIndex !== current.sentenceIndex;
    // 循环已满且不自动前进（或已到末句）时停在原处，不安排任何计时。
    if (!continues) return;
    const finished = result.sentences[current.sentenceIndex];
    // 「与句子等长」按实际听到的时长计算：慢速播放时一句话听得更久，跟读留白也相应变长。
    const seconds =
      current.gapMode.kind === "fixed"
        ? current.gapMode.seconds
        : (finished?.duration ?? 0) / current.rate;
    setWaiting(true);
    // 取整到毫秒：浮点除法（如 1.7 / 0.8）会得到 2124.9999… 这类值，计时器对小数的处理不一致。
    gapTimer.current = setTimeout(
      () => {
        gapTimer.current = null;
        setWaiting(false);
        dispatch({ type: "setPlaying", value: true });
      },
      Math.round(seconds * 1000)
    );
  }, [clearGap, result.sentences, sentenceCount]);

  const value = useMemo<PlayerContextValue>(
    () => ({ state, sentenceCount, waiting, send, completed, playhead }),
    [state, sentenceCount, waiting, send, completed, playhead]
  );

  return <PlayerContext.Provider value={value}>{children}</PlayerContext.Provider>;
}
