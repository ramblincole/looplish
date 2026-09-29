import { Link } from "react-router";
import type { Job } from "../../api/types";
import { errorMessage } from "../intake/processing";
import { useDeleteJob } from "./useJobs";

const STATUS_LABELS: Record<Job["status"], string> = {
  queued: "排队中",
  running: "处理中",
  succeeded: "已完成",
  failed: "失败"
};

const STAGE_LABELS: Record<NonNullable<Job["stage"]>, string> = {
  downloading: "下载",
  preparingAudio: "准备音频",
  transcribing: "转写",
  segmenting: "切句"
};

function percent(progress: number): number {
  return Math.round(Math.min(1, Math.max(0, progress)) * 100);
}

export function JobList({ jobs }: { jobs: Job[] }) {
  const remove = useDeleteJob();

  if (jobs.length === 0) return <p>还没有素材，先在上面添加一个吧。</p>;

  function confirmDelete(job: Job) {
    if (window.confirm(`删除「${job.title}」及其全部产物？此操作无法撤销。`)) {
      remove.mutate(job.id);
    }
  }

  return (
    <>
      {remove.isError ? <p role="alert">{errorMessage(remove.error)}</p> : null}
      <table className="jobs">
        <thead>
          <tr>
            <th scope="col">素材</th>
            <th scope="col">状态</th>
            <th scope="col">进度</th>
            <th scope="col">句子数</th>
            <th scope="col">操作</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr key={job.id} data-status={job.status}>
              <td>
                {job.status === "succeeded" ? (
                  <Link to={`/jobs/${encodeURIComponent(job.id)}`}>{job.title}</Link>
                ) : (
                  job.title
                )}
              </td>
              <td>
                {/* 状态用文字表达，不只依赖颜色 */}
                <span className={`status status-${job.status}`}>{STATUS_LABELS[job.status]}</span>
                {job.stage ? <span className="stage">（{STAGE_LABELS[job.stage]}）</span> : null}
                <div className="message">
                  {job.status === "failed" && job.error
                    ? `失败原因：${job.error.detail}`
                    : job.message}
                </div>
              </td>
              <td>
                <progress
                  max={1}
                  value={job.progress}
                  aria-label={`${job.title} 处理进度`}
                  aria-valuetext={`${percent(job.progress)}%`}
                />
                <span className="percent">{percent(job.progress)}%</span>
              </td>
              <td>{job.status === "succeeded" ? job.sentenceCount : "—"}</td>
              <td>
                <button
                  type="button"
                  onClick={() => confirmDelete(job)}
                  // 运行中的任务不能删除，服务端同样会拒绝。
                  disabled={job.status === "running" || remove.isPending}
                  aria-label={`删除 ${job.title}`}
                >
                  删除
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
