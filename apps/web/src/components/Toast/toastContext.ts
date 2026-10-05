import { createContext, useContext } from "react";

export type ToastKind = "info" | "error";
export type Notify = (message: string, kind?: ToastKind) => void;

export const TOAST_DURATION_MS: Readonly<Record<ToastKind, number>> = { info: 3000, error: 6000 };

// Provider 之外调用既不报错也不显示，便于单独测试使用了 toast 的组件。
export const ToastContext = createContext<Notify>(() => {});

export function useToast(): Notify {
  return useContext(ToastContext);
}
