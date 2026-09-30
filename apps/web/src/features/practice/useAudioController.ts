import { useEffect, useRef, useState, type RefObject } from "react";
import type { JobResult } from "../../api/types";
import type { PlayerState } from "./playerReducer";

type Sentence = JobResult["sentences"][number];

/**
 * 独占 HTMLAudioElement 的副作用：定位、播放、暂停、倍速，以及用 RAF 检查句末边界。
 * 组件只通过 reducer 状态驱动它，它只向上报告「句子完成」或「播放失败」。
 * onCompleted 与 onPlaybackError 必须是稳定引用，否则每帧的 setTime 渲染都会重启播放 effect。
 */
export function useAudioController(
  audioRef: RefObject<HTMLAudioElement | null>,
  sentence: Sentence | undefined,
  state: Pick<PlayerState, "playing" | "rate" | "replayCount">,
  onCompleted: () => void,
  onPlaybackError: (error: unknown) => void
) {
  const frame = useRef<number | null>(null);
  const seenReplay = useRef(state.replayCount);
  const [time, setTime] = useState(sentence?.start ?? 0);
  const start = sentence?.start;
  const end = sentence?.end;

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || start === undefined) return;
    // 切句先停播并定位到句首，避免上一句的时间继续泄漏到新句。
    audio.pause();
    audio.currentTime = start;
    setTime(start);
  }, [audioRef, sentence, start]);

  useEffect(() => {
    const audio = audioRef.current;
    if (audio) audio.playbackRate = state.rate;
  }, [audioRef, state.rate]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || start === undefined || end === undefined) return;
    if (!state.playing) {
      audio.pause();
      return;
    }
    const replay = seenReplay.current !== state.replayCount;
    seenReplay.current = state.replayCount;
    // 重听、上一轮已播到句末或位置被拖出本句时回到句首；普通暂停后则从原处继续。
    if (replay || audio.currentTime < start || audio.currentTime >= end) {
      audio.currentTime = start;
    }
    // 浏览器可能因自动播放策略拒绝 Promise，必须转成可见错误状态。
    // 在 play 完成前被 pause 打断会以 AbortError 拒绝，这是正常的状态切换，不算失败。
    audio.play().catch((error: unknown) => {
      if (error instanceof DOMException && error.name === "AbortError") return;
      onPlaybackError(error);
    });
    let finished = false;
    const reachedEnd = () => {
      // 末句的 end 可能因浮点误差略大于媒体时长，媒体自然结束同样视为到达句末。
      if (finished || (audio.currentTime < end && !audio.ended)) return false;
      finished = true;
      audio.pause();
      onCompleted();
      return true;
    };
    const tick = () => {
      setTime(audio.currentTime);
      // RAF 比 timeupdate 更密集，是 sentence.end 播放边界的主检查。
      if (reachedEnd()) {
        frame.current = null;
        return;
      }
      frame.current = requestAnimationFrame(tick);
    };
    // 标签页在后台时浏览器会暂停 RAF，音频却继续播放；timeupdate 仍会低频触发，
    // 只作兜底防止一路播到后面的句子，前台的精确停点仍由 RAF 决定。
    const onTimeUpdate = () => {
      setTime(audio.currentTime);
      if (reachedEnd() && frame.current !== null) {
        cancelAnimationFrame(frame.current);
        frame.current = null;
      }
    };
    audio.addEventListener("timeupdate", onTimeUpdate);
    frame.current = requestAnimationFrame(tick);
    return () => {
      // 状态变化或卸载时撤销旧循环，保证同一时刻只有一个 RAF 链。
      audio.removeEventListener("timeupdate", onTimeUpdate);
      if (frame.current !== null) cancelAnimationFrame(frame.current);
      frame.current = null;
    };
    // 倍速由上面独立的 effect 负责，这里不因倍速变化重新调用 play。
  }, [audioRef, start, end, state.playing, state.replayCount, onCompleted, onPlaybackError]);

  useEffect(() => {
    const audio = audioRef.current;
    // 卸载时停止播放，离开练习台后不应继续发声。
    return () => audio?.pause();
  }, [audioRef]);

  return { time };
}
