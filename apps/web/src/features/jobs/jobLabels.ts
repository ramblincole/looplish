import type { Job } from "../../api/types";
import { isActive } from "./useJobs";

export const STATUS_LABELS: Record<Job["status"], string> = {
  queued: "排队中",
  running: "处理中",
  succeeded: "已完成",
  failed: "失败"
};

export const STAGE_LABELS: Record<NonNullable<Job["stage"]>, string> = {
  downloading: "下载",
  preparingAudio: "准备音频",
  transcribing: "转写",
  segmenting: "切句"
};

export function progressPercent(progress: number): number {
  if (!Number.isFinite(progress)) return 0;
  return Math.round(Math.min(1, Math.max(0, progress)) * 100);
}

/** 状态文字本身就能说明状态，颜色只作辅助；阶段只在任务仍在处理时有意义。 */
export function statusText(job: Pick<Job, "status" | "stage">): string {
  const label = STATUS_LABELS[job.status];
  return isActive(job.status) && job.stage ? `${label}·${STAGE_LABELS[job.stage]}` : label;
}

const pad = (value: number) => String(value).padStart(2, "0");

type Stage = NonNullable<Job["stage"]>;
const STAGE_ORDER: Stage[] = ["downloading", "preparingAudio", "transcribing", "segmenting"];

export type JobStep = { stage: Stage; label: string; state: "done" | "current" | "pending" };

/** 处理步骤清单；上传和本机文件没有下载这一步，排队时所有步骤都还没开始。 */
export function jobSteps(job: Pick<Job, "source" | "stage">): JobStep[] {
  const downloads = /^https?:\/\//i.test(job.source);
  const stages = STAGE_ORDER.filter((stage) => downloads || stage !== "downloading");
  const current = job.stage ? stages.indexOf(job.stage) : -1;
  return stages.map((stage, index) => ({
    stage,
    label: STAGE_LABELS[stage],
    state: current < 0 || index > current ? "pending" : index === current ? "current" : "done"
  }));
}

/** 从创建到现在的时长，如 0:42、12:05、1:02:05；时钟偏差导致的负数按 0 处理。 */
export function elapsedText(createdAt: string, now: number): string {
  const total = Math.max(0, Math.floor((now - new Date(createdAt).getTime()) / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = pad(total % 60);
  return hours ? `${hours}:${pad(minutes)}:${seconds}` : `${minutes}:${seconds}`;
}

export function formatCreatedAt(iso: string): string {
  const date = new Date(iso);
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function sourceLabel(source: string): string {
  try {
    const url = new URL(source);
    if (url.protocol === "http:" || url.protocol === "https:") {
      return url.hostname.replace(/^www\./, "");
    }
  } catch {
    // 不是 URL（本机路径或上传文件的服务端路径）。
  }
  // 服务端路径属于实现细节，不向用户展示。
  return "本地文件";
}

export function jobMeta(job: Job): string {
  const parts = [formatCreatedAt(job.createdAt), sourceLabel(job.source)];
  if (job.status === "succeeded") parts.unshift(`${job.sentenceCount} 句`);
  return parts.join(" · ");
}
