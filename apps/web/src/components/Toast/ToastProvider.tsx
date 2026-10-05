import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import styles from "./Toast.module.css";
import { TOAST_DURATION_MS, ToastContext, type ToastKind } from "./toastContext";

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

  const render = (kind: ToastKind) =>
    toast?.kind === kind ? (
      <p key={toast.id} className={styles.toast} data-kind={kind}>
        {toast.message}
      </p>
    ) : null;

  return (
    <ToastContext.Provider value={notify}>
      {children}
      {/* 播报区常驻页面，内容变化才会被读屏软件可靠地播报；错误用 assertive 打断当前朗读。 */}
      <div className={styles.viewport}>
        <div aria-live="polite" aria-atomic="true">
          {render("info")}
        </div>
        <div aria-live="assertive" aria-atomic="true">
          {render("error")}
        </div>
      </div>
    </ToastContext.Provider>
  );
}
