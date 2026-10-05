import { Fragment, type RefObject } from "react";
import { Button } from "../../components/Button/Button";
import { Modal } from "../../components/Modal/Modal";
import { HOTKEY_BINDINGS } from "../../features/practice/hotkeys";
import styles from "./HelpPanel.module.css";

type HelpPanelProps = {
  open: boolean;
  onClose: () => void;
  returnFocusTo: RefObject<HTMLElement | null>;
};

export function HelpPanel({ open, onClose, returnFocusTo }: HelpPanelProps) {
  return (
    <Modal open={open} onClose={onClose} title="快捷键" returnFocusTo={returnFocusTo}>
      <dl className={styles.list}>
        {HOTKEY_BINDINGS.map((binding) => (
          <Fragment key={binding.action}>
            <dt>{binding.label}</dt>
            <dd>{binding.description}</dd>
          </Fragment>
        ))}
        {/* Escape 由弹层自身处理，不在按键表里，单独列出。 */}
        <dt>Esc</dt>
        <dd>关闭弹层</dd>
      </dl>
      <Button variant="ghost" onClick={onClose}>
        知道了
      </Button>
    </Modal>
  );
}
