import { useEffect, useRef } from "react";
import { useNavigate } from "react-router";
import type { Job } from "../../api/types";
import { Button } from "../../components/Button/Button";
import { Modal } from "../../components/Modal/Modal";
import { ProgressBar } from "../../components/ProgressBar/ProgressBar";
import { statusText } from "./jobLabels";
import styles from "./ProgressOverlay.module.css";
import { isActive } from "./useJobs";

type Props = {
  /** 正在跟踪的任务；为 null 时浮层关闭。 */
  job: Job | null;
  onClose: () => void;
};

function titleOf(job: Job): string {
  if (job.status === "succeeded") return `处理完成 · 共 ${job.sentenceCount} 句`;
  if (job.status === "failed") return "处理失败";
  return "正在处理";
}

export function ProgressOverlay({ job, onClose }: Props) {
  const navigate = useNavigate();
  const primary = useRef<HTMLButtonElement>(null);
  const status = job?.status;

  useEffect(() => {
    // 进入终态时原来的「放到后台」按钮消失，把焦点交给新的主操作，键盘用户不会落到 body。
    if (status === "succeeded" || status === "failed") primary.current?.focus();
  }, [status]);

  if (job === null) return null;
  const active = isActive(job.status);

  return (
    <Modal open onClose={onClose} title={titleOf(job)}>
      <p className={styles.jobTitle}>{job.title}</p>
      {active ? <ProgressBar value={job.progress} label="处理进度" /> : null}
      {/* 状态变化由这里播报；标题变化不会被读屏可靠地朗读。 */}
      <p className={styles.stage} data-status={job.status} aria-live="polite">
        {job.status === "failed"
          ? (job.error?.detail ?? job.message)
          : job.status === "succeeded"
            ? "可以开始练习了。"
            : `${statusText(job)} · ${job.message}`}
      </p>
      {active ? <p className={styles.note}>可以放到后台，任务会继续处理。</p> : null}
      <div className={styles.actions}>
        {active ? (
          <Button variant="ghost" onClick={onClose}>
            放到后台
          </Button>
        ) : null}
        {job.status === "succeeded" ? (
          <>
            <Button variant="ghost" onClick={onClose}>
              留在素材库
            </Button>
            <Button
              ref={primary}
              variant="primary"
              onClick={() => {
                onClose();
                navigate(`/jobs/${encodeURIComponent(job.id)}`);
              }}
            >
              开始练习
            </Button>
          </>
        ) : null}
        {job.status === "failed" ? (
          <Button ref={primary} variant="ghost" onClick={onClose}>
            关闭
          </Button>
        ) : null}
      </div>
    </Modal>
  );
}
