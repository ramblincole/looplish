import type { ComponentPropsWithRef } from "react";
import { buttonClass, type ButtonVariant } from "./buttonClass";

type ButtonProps = ComponentPropsWithRef<"button"> & { variant?: ButtonVariant };

export function Button({ variant = "ghost", type = "button", className, ...rest }: ButtonProps) {
  // 默认 type=button：按钮常放在表单里（如设置抽屉），不应意外触发提交。
  return <button type={type} className={buttonClass(variant, className)} {...rest} />;
}

type ButtonLinkProps = ComponentPropsWithRef<"a"> & { variant?: ButtonVariant };

export function ButtonLink({ variant = "ghost", className, ...rest }: ButtonLinkProps) {
  return <a className={buttonClass(variant, className)} {...rest} />;
}
