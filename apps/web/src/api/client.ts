import type {
  CreateJobRequest,
  Job,
  JobPage,
  JobResult,
  ProblemDetails,
  ResegmentRequest,
  RuntimeConfig
} from "./types";

export class ApiProblem extends Error {
  constructor(readonly problem: ProblemDetails) {
    super(problem.detail);
    this.name = "ApiProblem";
  }
}

function isProblemDetails(value: unknown): value is ProblemDetails {
  // 网络响应先视为 unknown，只有所有稳定字段通过检查后才提升类型。
  if (typeof value !== "object" || value === null) return false;
  const item = value as Record<string, unknown>;
  return (
    typeof item.type === "string" &&
    typeof item.title === "string" &&
    typeof item.status === "number" &&
    typeof item.code === "string" &&
    typeof item.detail === "string" &&
    typeof item.requestId === "string"
  );
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    // 反向代理的 HTML 错误页或空响应体都不是 JSON，按「无法识别」处理。
    return undefined;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const value = await readJson(response);
    if (!isProblemDetails(value)) {
      throw new Error(`Invalid API error payload (${response.status})`);
    }
    throw new ApiProblem(value);
  }
  if (response.status === 204) {
    // 删除成功没有响应体，避免对空内容调用 response.json()。
    return undefined as T;
  }
  return (await response.json()) as T;
}

function jobPath(jobId: string): string {
  return `/api/v1/jobs/${encodeURIComponent(jobId)}`;
}

export const api = {
  getConfig: () => request<RuntimeConfig>("/api/v1/config"),
  listJobs: (signal?: AbortSignal) => request<JobPage>("/api/v1/jobs", { signal }),
  getJob: (jobId: string, signal?: AbortSignal) => request<Job>(jobPath(jobId), { signal }),
  getResult: (jobId: string, signal?: AbortSignal) =>
    request<JobResult>(`${jobPath(jobId)}/result`, { signal }),
  createJob: (body: CreateJobRequest) =>
    request<Job>("/api/v1/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }),
  // 不手工设置 Content-Type，由浏览器为 FormData 生成带 boundary 的 multipart 头。
  uploadJob: (form: FormData) =>
    request<Job>("/api/v1/jobs/upload", { method: "POST", body: form }),
  resegment: (jobId: string, body: ResegmentRequest) =>
    request<JobResult>(`${jobPath(jobId)}/resegment`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }),
  deleteJob: (jobId: string) => request<void>(jobPath(jobId), { method: "DELETE" }),
  urls: {
    audio: (jobId: string) => `${jobPath(jobId)}/audio`,
    subtitle: (jobId: string, format: "srt" | "vtt" | "txt") =>
      `${jobPath(jobId)}/subtitles.${format}`,
    clip: (jobId: string, index: number) => {
      // URL helper 在发请求前拒绝小数和负索引，保持服务端路径可预测。
      if (!Number.isInteger(index) || index < 0) throw new RangeError("invalid sentence index");
      return `${jobPath(jobId)}/clips/${index}`;
    },
    bundle: (jobId: string, includeClips = true) =>
      `${jobPath(jobId)}/bundle.zip?clips=${includeClips}`
  }
};
