import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import styles from "./Toast.module.css";
import { TOAST_DURATION_MS, ToastContext, type ToastKind } from "./toastContext";
import { useToastHost } from "../Modal/modalRegistry";

type Toast = { id: number; message: string; kind: ToastKind };

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<Toast | null>(null);
  const nextId = useRef(0);

  const notify = useCallback((message: string, kind: ToastKind = "info") => {
    // 每条提示都有新 id：同一句话连续出现时也会重新计时。
    nextId.current += 1;
    setToast({ id: nextId.current, message, kind });
  }, []);

  useEffect(() => {
    if (toast === null) return;
    const timer = setTimeout(() => setToast(null), TOAST_DURATION_MS[toast.kind]);
    return () => clearTimeout(timer);
  }, [toast]);

  const host = useToastHost();
  const renderToast = (kind: ToastKind) => {
    if (toast?.kind !== kind) return null;
    const node = (
      <p key={toast.id} className={styles.toast} data-kind={kind}>
        {toast.message}
      </p>
    );
    // 有弹层时放进弹层自己的常驻播报区，否则 aria-modal 会让读屏忽略页面底部的提示。
    return host ? createPortal(node, host[kind === "info" ? "polite" : "assertive"]) : node;
  };

  return (
    <ToastContext.Provider value={notify}>
      {children}
      {/* 播报区常驻页面，内容变化才会被读屏软件可靠地播报；错误用 assertive 打断当前朗读。 */}
      <div className={styles.viewport}>
        <div aria-live="polite" aria-atomic="true">
          {renderToast("info")}
        </div>
        <div aria-live="assertive" aria-atomic="true">
          {renderToast("error")}
        </div>
      </div>
    </ToastContext.Provider>
  );
}
