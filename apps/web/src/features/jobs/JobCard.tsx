import { Link } from "react-router";
import type { Job } from "../../api/types";
import { ProgressBar } from "../../components/ProgressBar/ProgressBar";
import { jobMeta, progressPercent, statusText } from "./jobLabels";
import styles from "./JobList.module.css";
import { isActive } from "./useJobs";

type Props = {
  job: Job;
  deleting: boolean;
  onDelete: (trigger: HTMLButtonElement) => void;
};

export function JobCard({ job, deleting, onDelete }: Props) {
  const active = isActive(job.status);
  return (
    <li className={styles.card} data-status={job.status}>
      <div className={styles.body}>
        {job.status === "succeeded" ? (
          // 标题是唯一的链接，伪元素把点击区域扩大到整张卡片。
          <Link to={`/jobs/${encodeURIComponent(job.id)}`} className={styles.titleLink}>
            {job.title}
          </Link>
        ) : (
          <span className={styles.title}>{job.title}</span>
        )}
        <p className={styles.meta}>{jobMeta(job)}</p>
        {active ? (
          <div className={styles.progress}>
            <ProgressBar value={job.progress} label={`${job.title} 处理进度`} size="thin" />
            <span className={styles.percent}>{progressPercent(job.progress)}%</span>
            <span className={styles.message}>{job.message}</span>
          </div>
        ) : null}
        {job.status === "failed" ? (
          <p className={styles.failure}>失败原因：{job.error?.detail ?? job.message}</p>
        ) : null}
      </div>
      <span className={styles.status} data-status={job.status}>
        {statusText(job)}
      </span>
      <button
        type="button"
        className={styles.delete}
        aria-label={`删除 ${job.title}`}
        // 运行中的任务不能删除，服务端同样会拒绝。
        disabled={job.status === "running" || deleting}
        onClick={(event) => onDelete(event.currentTarget)}
      >
        ×
      </button>
    </li>
  );
}
