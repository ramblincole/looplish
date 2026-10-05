import { useRef, useState } from "react";
import { NavLink, Outlet } from "react-router";
import { Button } from "../../components/Button/Button";
import { buttonClass } from "../../components/Button/buttonClass";
import { ModalProvider } from "../../components/Modal/ModalProvider";
import { ToastProvider } from "../../components/Toast/ToastProvider";
import styles from "./AppShell.module.css";
import { HelpPanel } from "./HelpPanel";

/** 布局路由：两个页面共用顶栏，并在此提供弹层登记与 toast。 */
export function AppShell() {
  const [helpOpen, setHelpOpen] = useState(false);
  const helpButton = useRef<HTMLButtonElement>(null);

  return (
    <ModalProvider>
      <ToastProvider>
        <header className={styles.topbar}>
          <p className={styles.brand}>
            {/* 品牌标记：一个亮着的指示灯 */}
            <span className={styles.brandMark} aria-hidden="true" />
            <span className={styles.brandName} aria-hidden="true">
              loop<span className={styles.brandSlash}>/</span>lish
            </span>
            <span className="visuallyHidden">Looplish</span>
          </p>
          <nav className={styles.nav} aria-label="主导航">
            <NavLink to="/" end className={buttonClass("ghost")}>
              素材库
            </NavLink>
            <Button
              ref={helpButton}
              variant="ghost"
              aria-haspopup="dialog"
              onClick={() => setHelpOpen(true)}
            >
              快捷键
            </Button>
          </nav>
        </header>
        <Outlet />
        <HelpPanel open={helpOpen} onClose={() => setHelpOpen(false)} returnFocusTo={helpButton} />
      </ToastProvider>
    </ModalProvider>
  );
}
