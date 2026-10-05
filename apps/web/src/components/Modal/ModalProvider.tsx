import { useCallback, useMemo, useState, type ReactNode } from "react";
import { ModalRegistryContext, type ModalRegistry, type ToastHost } from "./modalRegistry";

type Entry = { host: ToastHost | null };

export function ModalProvider({ children }: { children: ReactNode }) {
  // 按打开顺序保存；最后一个是最上层弹层。
  const [entries, setEntries] = useState<Entry[]>([]);
  const register = useCallback((host?: ToastHost) => {
    const entry: Entry = { host: host ?? null };
    setEntries((current) => [...current, entry]);
    return () => setEntries((current) => current.filter((item) => item !== entry));
  }, []);
  const value = useMemo<ModalRegistry>(
    () => ({
      open: entries.length > 0,
      toastHost: entries.at(-1)?.host ?? null,
      register
    }),
    [entries, register]
  );
  return <ModalRegistryContext.Provider value={value}>{children}</ModalRegistryContext.Provider>;
}
