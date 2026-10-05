import { useEffect, useRef, useState } from "react";
import type { Job } from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog/ConfirmDialog";
import { errorMessage } from "../intake/processing";
import { JobCard } from "./JobCard";
import styles from "./JobList.module.css";
import { useDeleteJob } from "./useJobs";

type Props = {
  jobs: Job[];
  /** 删除成功且列表刷新后调用：被删的那一行已经不在了，焦点需要一个新的落点。 */
  onDeleted: () => void;
};

export function JobList({ jobs, onDeleted }: Props) {
  const remove = useDeleteJob();
  const [pending, setPending] = useState<Job | null>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const [refocus, setRefocus] = useState(false);

  useEffect(() => {
    // 删除失败的回调先于重新渲染执行，那时删除按钮仍处于禁用状态，focus() 不会生效；
    // 等删除结束、按钮恢复可用后再把焦点送回去。
    if (refocus && !remove.isPending) {
      trigger.current?.focus();
      setRefocus(false);
    }
  }, [refocus, remove.isPending]);

  function confirm() {
    const target = pending;
    setPending(null);
    // useDeleteJob 的 onSuccess 会等列表刷新完成，这里的回调在被删行消失之后才执行。
    if (target) {
      remove.mutate(target.id, {
        onSuccess: onDeleted,
        // 删除失败时被删行还在，焦点应回到它的删除按钮（见上面的 effect）。
        onError: () => setRefocus(true)
      });
    }
  }

  return (
    <>
      {remove.isError ? (
        <p role="alert" className={styles.failure}>
          {errorMessage(remove.error)}
        </p>
      ) : null}
      {jobs.length === 0 ? (
        <p className={styles.empty}>还没有素材。上面粘贴一个链接就能开始。</p>
      ) : (
        <ul className={styles.list}>
          {jobs.map((job) => (
            <JobCard
              key={job.id}
              job={job}
              deleting={remove.isPending}
              onDelete={(button) => {
                trigger.current = button;
                setPending(job);
              }}
            />
          ))}
        </ul>
      )}
      <ConfirmDialog
        open={pending !== null}
        title="删除素材"
        message={`删除「${pending?.title ?? ""}」及其全部产物？此操作无法撤销。`}
        confirmLabel="删除"
        returnFocusTo={trigger}
        onCancel={() => setPending(null)}
        onConfirm={confirm}
      />
    </>
  );
}
