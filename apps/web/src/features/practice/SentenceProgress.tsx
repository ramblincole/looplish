import { usePlayhead } from "./playerContext";
import styles from "./SentenceProgress.module.css";

/** 本句播到哪里；时间读数已经表达了同样的信息，所以对读屏隐藏。只展示，不支持点击跳转。 */
export function SentenceProgress({ start, end }: { start: number; end: number }) {
  const time = usePlayhead();
  const span = end - start;
  const ratio = span > 0 ? Math.min(1, Math.max(0, (time - start) / span)) : 0;
  return (
    <div className={styles.track} aria-hidden="true" data-sentence-progress>
      <div className={styles.fill} style={{ inlineSize: `${Math.round(ratio * 1000) / 10}%` }} />
    </div>
  );
}
