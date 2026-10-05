import styles from "./ProgressBar.module.css";

type ProgressBarProps = {
  /** 0–1；越界或非有限值按边界或 0 处理，避免进度条宽度失控。 */
  value: number;
  label: string;
  size?: "regular" | "thin";
};

export function ProgressBar({ value, label, size = "regular" }: ProgressBarProps) {
  const ratio = Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0;
  const percent = Math.round(ratio * 100);
  return (
    <div
      className={styles.track}
      data-size={size}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent}
      aria-valuetext={`${percent}%`}
    >
      <div className={styles.fill} style={{ inlineSize: `${percent}%` }} />
    </div>
  );
}
