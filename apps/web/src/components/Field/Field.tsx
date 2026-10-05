import type { ComponentPropsWithRef, ReactNode } from "react";
import styles from "./Field.module.css";

type FieldProps = {
  label: ReactNode;
  /** stack：标签在上（设置抽屉）；inline：标签在左（练习台旋钮排）。 */
  layout?: "stack" | "inline";
  children: ReactNode;
};

/** 用 label 包住控件，读屏名称直接取标签文字，无需手动关联 id。 */
export function Field({ label, layout = "stack", children }: FieldProps) {
  return (
    <label className={styles.field} data-layout={layout}>
      <span className={styles.label}>{label}</span>
      {children}
    </label>
  );
}

type ToggleFieldProps = Omit<ComponentPropsWithRef<"input">, "type"> & { label: ReactNode };

export function ToggleField({ label, ...input }: ToggleFieldProps) {
  return (
    <label className={styles.toggle}>
      <input type="checkbox" {...input} />
      <span className={styles.label}>{label}</span>
    </label>
  );
}
