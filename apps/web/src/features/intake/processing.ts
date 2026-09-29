import { ApiProblem } from "../../api/client";
import type { CreateJobRequest, RuntimeConfig } from "../../api/types";

export type ProcessingValues = Required<Omit<CreateJobRequest, "source">>;

export const SEGMENT_LIMITS = {
  minDuration: { min: 0.2, max: 10, label: "最短句长" },
  maxDuration: { min: 2, max: 60, label: "最长句长" },
  hardPause: { min: 0.1, max: 5, label: "强制断句停顿" },
  leadPad: { min: 0, max: 2, label: "句首留白" },
  tailPad: { min: 0, max: 2, label: "句尾留白" }
} as const;

export type SegmentField = keyof typeof SEGMENT_LIMITS;

export function initialValues(config: RuntimeConfig): ProcessingValues {
  const value = config.defaults;
  return {
    asrBackend: value.asrBackend,
    subtitleSource: value.subtitleSource,
    language: value.language,
    makeClips: false,
    minDuration: value.minDuration,
    maxDuration: value.maxDuration,
    hardPause: value.hardPause,
    leadPad: value.leadPad,
    tailPad: value.tailPad
  };
}

/** 与服务端相同的范围检查，只用于提前提示；服务端仍是最终校验者。 */
export function validate(values: ProcessingValues): string[] {
  const issues: string[] = [];
  for (const [field, limit] of Object.entries(SEGMENT_LIMITS) as [
    SegmentField,
    (typeof SEGMENT_LIMITS)[SegmentField]
  ][]) {
    const value = values[field];
    if (!Number.isFinite(value)) {
      issues.push(`${limit.label}需要填写数字。`);
    } else if (value < limit.min || value > limit.max) {
      issues.push(`${limit.label}需在 ${limit.min} 到 ${limit.max} 秒之间。`);
    }
  }
  if (values.minDuration >= values.maxDuration) {
    issues.push("最短句长必须小于最长句长。");
  }
  return issues;
}

/** 按 API 字段名逐项写入上传表单；布尔值用小写 true/false，未填语言表示自动检测。 */
export function toUploadForm(file: File, values: ProcessingValues): FormData {
  const form = new FormData();
  form.append("file", file);
  form.append("asrBackend", values.asrBackend ?? "");
  form.append("subtitleSource", values.subtitleSource);
  form.append("language", values.language?.trim() || "auto");
  form.append("makeClips", values.makeClips ? "true" : "false");
  for (const field of Object.keys(SEGMENT_LIMITS) as SegmentField[]) {
    form.append(field, String(values[field]));
  }
  return form;
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiProblem) return error.problem.detail;
  return "请求失败，请检查网络后重试。";
}
