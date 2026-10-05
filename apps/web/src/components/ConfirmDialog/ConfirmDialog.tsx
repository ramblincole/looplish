import type { ReactNode, RefObject } from "react";
import { Button } from "../Button/Button";
import { Modal } from "../Modal/Modal";
import styles from "./ConfirmDialog.module.css";

type ConfirmDialogProps = {
  open: boolean;
  title: string;
  message: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  returnFocusTo?: RefObject<HTMLElement | null>;
};

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel,
  onConfirm,
  onCancel,
  returnFocusTo
}: ConfirmDialogProps) {
  // 「取消」排在前面，打开时默认聚焦它：误按 Enter 不会执行危险操作。
  return (
    <Modal open={open} onClose={onCancel} title={title} returnFocusTo={returnFocusTo}>
      <p className={styles.message}>{message}</p>
      <div className={styles.actions}>
        <Button variant="ghost" onClick={onCancel}>
          取消
        </Button>
        <Button variant="danger" onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}
