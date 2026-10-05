import type { JobResult } from "../../api/types";
import { usePlayer, usePlayhead } from "./playerContext";
import { formatClock, formatDuration, formatLoop } from "./playerLabels";
import styles from "./Readout.module.css";

type Sentence = JobResult["sentences"][number];

/** 全等宽字体的计数窗：第几句、循环轮次、听了几次、本句时间、句长。 */
export function Readout({ sentence }: { sentence: Sentence }) {
  const { state, sentenceCount, waiting } = usePlayer();
  const listens = state.listenCounts.get(state.sentenceIndex) ?? 0;
  return (
    <div className={styles.readout}>
      {/* 读屏读到「第 3 / 24 句」，视觉上只显示琥珀色的「3 / 24」。 */}
      <h2 id="current-sentence-title" className={styles.index}>
        <span className="visuallyHidden">第 </span>
        <em>{state.sentenceIndex + 1}</em>
        <span className={styles.of}> / </span>
        {sentenceCount}
        <span className="visuallyHidden"> 句</span>
      </h2>
      {/* 循环轮次与跟读留白会随播放变化，放在状态区里播报。 */}
      <span className={styles.item} data-readout="loop" role="status">
        {formatLoop(state.playCount, state.repeat)}
        {waiting ? <span className={styles.lamp}> · 跟读中</span> : null}
      </span>
      <span className={styles.item} data-readout="listens">
        听了 <em>{listens}</em> 次
      </span>
      <ReadoutClock start={sentence.start} />
      <span className={styles.duration} data-readout="duration">
        {formatDuration(sentence.duration)}
      </span>
    </div>
  );
}

function ReadoutClock({ start }: { start: number }) {
  // 单独订阅播放进度：每帧只重渲染这一个数字，读数条其余部分不动。
  const time = usePlayhead();
  return (
    <span className={styles.time} data-readout="time" aria-hidden="true">
      {formatClock(time - start)}
    </span>
  );
}
