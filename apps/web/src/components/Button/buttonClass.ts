import styles from "./Button.module.css";

export type ButtonVariant =
  "primary" | "ghost" | "danger" | "transport" | "transportMain" | "reveal";

/** 让 <a>、路由 <Link> 也能套用按钮外观，样式只定义一份。 */
export function buttonClass(variant: ButtonVariant, className?: string): string {
  return [styles.button, styles[variant], className].filter(Boolean).join(" ");
}
