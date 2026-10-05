import { useCallback, useMemo, useState, type ReactNode } from "react";
import { ModalRegistryContext, type ModalRegistry } from "./modalRegistry";

export function ModalProvider({ children }: { children: ReactNode }) {
  const [count, setCount] = useState(0);
  const register = useCallback(() => {
    setCount((current) => current + 1);
    let active = true;
    return () => {
      // 注销只生效一次，StrictMode 重复执行清理时计数也不会变成负数。
      if (!active) return;
      active = false;
      setCount((current) => current - 1);
    };
  }, []);
  const value = useMemo<ModalRegistry>(() => ({ open: count > 0, register }), [count, register]);
  return <ModalRegistryContext.Provider value={value}>{children}</ModalRegistryContext.Provider>;
}
