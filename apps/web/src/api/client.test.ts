// @vitest-environment node
// 只测 HTTP 边界：Node 的 fetch、FormData 与 AbortSignal 同属一套实现，行为与浏览器一致；
// jsdom 的 FormData/AbortSignal 不被 Node fetch 识别，放在 jsdom 下会得到假失败。
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { ApiProblem, api } from "./client";

const problem = {
  type: "https://looplish.dev/problems/job-not-found",
  title: "Job Not Found",
  status: 404,
  code: "JOB_NOT_FOUND",
  detail: "没有找到指定任务。",
  requestId: "req_123"
};

const job = {
  id: "0123456789ABCDEF",
  source: "https://example.test/v",
  title: "https://example.test/v",
  status: "queued",
  stage: null,
  progress: 0,
  message: "等待处理",
  error: null,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
  sentenceCount: 0
};

const BASE_URL = "http://127.0.0.1:5173";
const server = setupServer();

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
  // 客户端按设计只用相对路径；Node 没有页面地址，这里按本机前端地址补全后交给 MSW。
  const intercepted = globalThis.fetch;
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) =>
    intercepted(
      typeof input === "string" && input.startsWith("/") ? new URL(input, BASE_URL) : input,
      init
    )
  );
});
afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
});
afterAll(() => {
  vi.unstubAllGlobals();
  server.close();
});

describe("request boundary", () => {
  it("returns parsed JSON for successful responses", async () => {
    server.use(
      http.get("*/api/v1/config", () =>
        HttpResponse.json({ asrBackends: ["local"], allowLocalPaths: true, defaults: {} })
      )
    );

    await expect(api.getConfig()).resolves.toMatchObject({ asrBackends: ["local"] });
  });

  it("turns Problem Details into ApiProblem with every stable field", async () => {
    server.use(
      http.get("*/api/v1/jobs/:id", () =>
        HttpResponse.json(problem, {
          status: 404,
          headers: { "Content-Type": "application/problem+json" }
        })
      )
    );

    const error = await api.getJob("0123456789ABCDEF").catch((value: unknown) => value);

    expect(error).toBeInstanceOf(ApiProblem);
    const apiProblem = error as ApiProblem;
    expect(apiProblem.problem).toEqual(problem);
    expect(apiProblem.message).toBe(problem.detail);
    expect(apiProblem.name).toBe("ApiProblem");
  });

  it("rejects error payloads that are not Problem Details", async () => {
    server.use(
      http.get("*/api/v1/jobs", () => HttpResponse.json({ detail: "x" }, { status: 500 }))
    );

    await expect(api.listJobs()).rejects.toThrow("Invalid API error payload (500)");
  });

  it("rejects non-JSON error pages without a parse error", async () => {
    server.use(
      http.get("*/api/v1/jobs", () =>
        HttpResponse.text("<html>Bad Gateway</html>", { status: 502 })
      )
    );

    await expect(api.listJobs()).rejects.toThrow("Invalid API error payload (502)");
  });

  it("does not parse the empty body of a 204 response", async () => {
    server.use(http.delete("*/api/v1/jobs/:id", () => new HttpResponse(null, { status: 204 })));
    const json = vi.spyOn(Response.prototype, "json");

    await expect(api.deleteJob("0123456789ABCDEF")).resolves.toBeUndefined();

    expect(json).not.toHaveBeenCalled();
  });

  it("sends JSON for create and resegment", async () => {
    const seen: Array<{ type: string | null; body: unknown; path: string }> = [];
    server.use(
      http.post("*/api/v1/jobs", async ({ request }) => {
        seen.push({
          type: request.headers.get("content-type"),
          body: await request.json(),
          path: new URL(request.url).pathname
        });
        return HttpResponse.json(job, { status: 202 });
      }),
      http.post("*/api/v1/jobs/:id/resegment", async ({ request }) => {
        seen.push({
          type: request.headers.get("content-type"),
          body: await request.json(),
          path: new URL(request.url).pathname
        });
        return HttpResponse.json({ jobId: "a" });
      })
    );

    await api.createJob({ source: "https://example.test/v", makeClips: true });
    await api.resegment("A/B C", { maxDuration: 10 });

    expect(seen).toEqual([
      {
        type: "application/json",
        body: { source: "https://example.test/v", makeClips: true },
        path: "/api/v1/jobs"
      },
      {
        type: "application/json",
        body: { maxDuration: 10 },
        path: "/api/v1/jobs/A%2FB%20C/resegment"
      }
    ]);
  });

  it("uploads FormData and lets the browser set the multipart boundary", async () => {
    let contentType: string | null = null;
    let fileName: string | null = null;
    let language: FormDataEntryValue | null = null;
    server.use(
      http.post("*/api/v1/jobs/upload", async ({ request }) => {
        contentType = request.headers.get("content-type");
        const form = await request.formData();
        const file = form.get("file");
        fileName = file instanceof File ? file.name : null;
        language = form.get("language");
        return HttpResponse.json(job, { status: 202 });
      })
    );
    const form = new FormData();
    form.append("file", new File(["audio"], "talk.wav", { type: "audio/wav" }));
    form.append("language", "auto");

    await expect(api.uploadJob(form)).resolves.toMatchObject({ id: job.id });

    expect(contentType).toMatch(/^multipart\/form-data; boundary=/);
    expect(fileName).toBe("talk.wav");
    expect(language).toBe("auto");
  });

  it("passes the AbortSignal through to fetch", async () => {
    server.use(
      http.get("*/api/v1/jobs", async () => {
        await new Promise((resolve) => setTimeout(resolve, 1000));
        return HttpResponse.json({ items: [], nextCursor: null });
      })
    );
    const controller = new AbortController();

    const pending = api.listJobs(controller.signal);
    controller.abort();

    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });

  it("encodes job ids in JSON endpoints", async () => {
    let path = "";
    server.use(
      http.get("*/api/v1/jobs/:id/result", ({ request }) => {
        path = new URL(request.url).pathname;
        return HttpResponse.json({ jobId: "x" });
      })
    );

    await api.getResult("../secret?x=1");

    expect(path).toBe("/api/v1/jobs/..%2Fsecret%3Fx%3D1/result");
  });
});

describe("download URL helpers", () => {
  it("builds relative, encoded artifact URLs", () => {
    expect(api.urls.audio("A B")).toBe("/api/v1/jobs/A%20B/audio");
    expect(api.urls.subtitle("id/1", "vtt")).toBe("/api/v1/jobs/id%2F1/subtitles.vtt");
    expect(api.urls.clip("abc", 0)).toBe("/api/v1/jobs/abc/clips/0");
    expect(api.urls.bundle("abc")).toBe("/api/v1/jobs/abc/bundle.zip?clips=true");
    expect(api.urls.bundle("abc", false)).toBe("/api/v1/jobs/abc/bundle.zip?clips=false");
  });

  it.each([-1, 1.5, Number.NaN, Number.POSITIVE_INFINITY])(
    "rejects invalid clip index %s",
    (index) => {
      expect(() => api.urls.clip("abc", index)).toThrow(RangeError);
    }
  );
});
