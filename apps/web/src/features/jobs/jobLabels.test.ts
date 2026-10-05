import { describe, expect, it } from "vitest";
import type { Job } from "../../api/types";
import { formatCreatedAt, jobMeta, progressPercent, sourceLabel, statusText } from "./jobLabels";

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: "0123456789ABCDEF",
    source: "https://www.example.test/v",
    title: "Coffee Talk",
    status: "succeeded",
    stage: null,
    progress: 1,
    message: "处理完成",
    error: null,
    // 用本地时间构造，断言与运行环境的时区无关。
    createdAt: new Date(2026, 8, 30, 17, 40).toISOString(),
    updatedAt: new Date(2026, 8, 30, 17, 45).toISOString(),
    sentenceCount: 24,
    ...overrides
  };
}

describe("jobLabels", () => {
  it.each([
    [0.5, 50],
    [0.004, 0],
    [1.4, 100],
    [-1, 0],
    [Number.NaN, 0]
  ])("progressPercent(%s) = %s", (value, expected) => {
    expect(progressPercent(value)).toBe(expected);
  });

  it("adds the stage only while a job is active", () => {
    expect(statusText({ status: "running", stage: "transcribing" })).toBe("处理中·转写");
    expect(statusText({ status: "queued", stage: null })).toBe("排队中");
    expect(statusText({ status: "succeeded", stage: "segmenting" })).toBe("已完成");
    expect(statusText({ status: "failed", stage: "downloading" })).toBe("失败");
  });

  it("formats the creation time in local time", () => {
    expect(formatCreatedAt(new Date(2026, 0, 5, 9, 3).toISOString())).toBe("01-05 09:03");
  });

  it("labels web sources by host and everything else as a local file", () => {
    expect(sourceLabel("https://www.bilibili.com/video/BV1")).toBe("bilibili.com");
    expect(sourceLabel("http://example.test:8080/a")).toBe("example.test");
    expect(sourceLabel("C:\\data\\jobs\\X\\source\\talk.mp4")).toBe("本地文件");
    expect(sourceLabel("not a url")).toBe("本地文件");
  });

  it("shows the sentence count only for finished jobs", () => {
    expect(jobMeta(job())).toBe("24 句 · 09-30 17:40 · example.test");
    expect(jobMeta(job({ status: "running", sentenceCount: 0 }))).toBe(
      "09-30 17:40 · example.test"
    );
  });
});
