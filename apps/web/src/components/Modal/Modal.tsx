import {
  useContext,
  useEffect,
  useId,
  useRef,
  type KeyboardEvent,
  type ReactNode,
  type RefObject
} from "react";
import { createPortal } from "react-dom";
import styles from "./Modal.module.css";
import { ModalRegistryContext } from "./modalRegistry";

const FOCUSABLE =
  'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])';

export type ModalProps = {
  open: boolean;
  onClose: () => void;
  title: string;
  /** 关闭后焦点回到哪里；不传时回到打开前的焦点元素。 */
  returnFocusTo?: RefObject<HTMLElement | null>;
  children: ReactNode;
};

export function Modal(props: ModalProps) {
  // 关闭即卸载：打开/关闭与挂载/卸载一一对应，焦点与登记都跟着生命周期走。
  return props.open ? <ModalSurface {...props} /> : null;
}

function ModalSurface({ onClose, title, returnFocusTo, children }: ModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const { register } = useContext(ModalRegistryContext);

  useEffect(() => register(), [register]);

  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const dialog = dialogRef.current;
    const returnTo = returnFocusTo?.current;
    // 焦点移入第一个可操作元素；没有时落在对话框本身，键盘用户不会停留在被遮住的页面上。
    (dialog?.querySelector<HTMLElement>(FOCUSABLE) ?? dialog)?.focus();
    return () => {
      (returnTo ?? previous)?.focus();
    };
  }, [returnFocusTo]);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      // Escape 由弹层自己消费，不再冒泡到页面上的其他监听者。
      event.preventDefault();
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== "Tab" || dialogRef.current === null) return;
    const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE));
    if (focusable.length === 0) {
      event.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    // 模态弹层内循环 Tab，避免焦点跑到遮罩后面的页面。
    if (event.shiftKey && (active === first || active === dialogRef.current)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  // 挂到 body：不受练习台吸顶区域等父级层叠上下文影响。
  return createPortal(
    <div className={styles.backdrop}>
      <div
        ref={dialogRef}
        className={styles.card}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onKeyDown={onKeyDown}
      >
        <h2 id={titleId} className={styles.title}>
          {title}
        </h2>
        {children}
      </div>
    </div>,
    document.body
  );
}
