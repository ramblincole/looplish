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
