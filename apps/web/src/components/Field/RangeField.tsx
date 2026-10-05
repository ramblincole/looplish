import { useId } from "react";
import styles from "./Field.module.css";

type RangeFieldProps = {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit?: string;
  format?: (value: number) => string;
  invalid?: boolean;
  onChange: (value: number) => void;
};

export function RangeField({
  label,
  value,
  min,
  max,
  step,
  unit = "",
  format = String,
  invalid = false,
  onChange
}: RangeFieldProps) {
  const id = useId();
  const text = `${format(value)}${unit}`;
  return (
    <div className={styles.field} data-layout="stack">
      {/* 读数放在 label 之外，滑块的读屏名称保持为固定的参数名，数值由 aria-valuetext 给出。 */}
      <span className={styles.rangeHead}>
        <label htmlFor={id} className={styles.label}>
          {label}
        </label>
        <output htmlFor={id} className={styles.readout}>
          {text}
        </output>
      </span>
      <input
        id={id}
        className={styles.range}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        aria-valuetext={text}
        aria-invalid={invalid || undefined}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </div>
  );
}
