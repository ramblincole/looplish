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
  'a[href], button:not(:disabled), input:not(:disabled):not([type="hidden"]), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])';

// 已打开的弹层（按打开顺序）。只有最上面一个响应卡片外的按键，叠放时不会互相抢键。
const openSurfaces: object[] = [];

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

  // 监听函数里要用最新的 onClose，又不想因为它变化而反复挂载监听。
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  // 焦点离开卡片（例如提交按钮被禁用后焦点落到 body）时，卡片上的 onKeyDown 收不到按键，
  // 于是 Escape 失效、Tab 会走进被遮住的页面。所以在 document 捕获阶段补一道兜底。
  useEffect(() => {
    const surface = {};
    openSurfaces.push(surface);
    function onDocumentKeyDown(event: globalThis.KeyboardEvent) {
      if (openSurfaces[openSurfaces.length - 1] !== surface) return;
      const dialog = dialogRef.current;
      if (dialog === null) return;
      // 目标在卡片内的按键交给卡片自己的 onKeyDown，避免处理两次。
      if (event.target instanceof Node && dialog.contains(event.target)) return;
      if (event.key === "Escape") {
        // 输入法组字时的 Escape 只用来取消候选词，不能关闭弹层。
        if (event.isComposing) return;
        event.preventDefault();
        onCloseRef.current();
      } else if (event.key === "Tab") {
        event.preventDefault();
        const focusable = dialog.querySelectorAll<HTMLElement>(FOCUSABLE);
        // 把焦点拉回卡片：Tab 到第一项，Shift+Tab 到最后一项；没有可聚焦元素时落在卡片上。
        const target = event.shiftKey ? focusable[focusable.length - 1] : focusable[0];
        (target ?? dialog).focus();
      }
    }
    document.addEventListener("keydown", onDocumentKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onDocumentKeyDown, true);
      openSurfaces.splice(openSurfaces.indexOf(surface), 1);
    };
  }, []);

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
      // 输入法组字时的 Escape 只用来取消候选词，不能关闭弹层。
      if (event.nativeEvent.isComposing) return;
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
    <div
      className={styles.backdrop}
      onMouseDown={(event) => {
        // 按下空白区域背景不应抢走对话框的焦点；规范中没有点击关闭。
        if (event.target === event.currentTarget) {
          event.preventDefault();
        }
      }}
    >
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
