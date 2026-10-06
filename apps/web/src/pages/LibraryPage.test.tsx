import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
  within
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { Job, RuntimeConfig } from "../api/types";
import { routes } from "../app/router";
import {
  ACTIVE_POLL_MS,
  HIDDEN_POLL_MS,
  MAX_BACKOFF_MS,
  pollInterval,
  useJobs
} from "../features/jobs/useJobs";
import { installFetchBridge, multipartFields } from "../test/fetchBridge";

const CONFIG: RuntimeConfig = {
  asrBackends: ["local"],
  allowLocalPaths: true,
  defaults: {
    asrBackend: "local",
    asrModel: "small.en",
    language: "en",
    subtitleSource: "auto",
    minDuration: 1,
    maxDuration: 14,
    hardPause: 0.75,
    leadPad: 0.2,
    tailPad: 0.4
  }
};

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: "0123456789ABCDEF",
    source: "https://example.test/v",
    title: "Everyday Talk",
    status: "succeeded",
    stage: null,
    progress: 1,
    message: "处理完成",
    error: null,
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    sentenceCount: 24,
    ...overrides
  };
}

type State = {
  config: RuntimeConfig;
  configGate: Promise<void> | null;
  pages: Job[][];
  jobsStatus: number;
  requests: { jobs: number; created: unknown[]; uploads: string[]; deleted: string[] };
  createError: Record<string, unknown> | null;
  uploadError: Record<string, unknown> | null;
  deleteError: { status: number; code: string; detail: string } | null;
};

let state: State;

function freshState(): State {
  return {
    config: CONFIG,
    configGate: null,
    pages: [[]],
    jobsStatus: 200,
    requests: { jobs: 0, created: [], uploads: [], deleted: [] },
    createError: null,
    uploadError: null,
    deleteError: null
  };
}

const problem = (status: number, code: string, detail: string) =>
  HttpResponse.json(
    { type: "about:blank", title: code, status, code, detail, requestId: "req_1" },
    { status, headers: { "Content-Type": "application/problem+json" } }
  );

const server = setupServer(
  http.get("*/api/v1/config", async () => {
    if (state.configGate) await state.configGate;
    return HttpResponse.json(state.config);
  }),
  http.get("*/api/v1/jobs", () => {
    state.requests.jobs += 1;
    if (state.jobsStatus !== 200)
      return problem(state.jobsStatus, "INTERNAL_ERROR", "服务内部错误。");
    // 依次返回预设的列表快照，最后一个快照一直重复。
    const items = state.pages.length > 1 ? state.pages.shift()! : state.pages[0];
    return HttpResponse.json({ items, nextCursor: null });
  }),
  http.post("*/api/v1/jobs", async ({ request }) => {
    state.requests.created.push(await request.json());
    if (state.createError) {
      const { status, code, detail } = state.createError as {
        status: number;
        code: string;
        detail: string;
      };
      return problem(status, code, detail);
    }
    return HttpResponse.json(job({ status: "queued", progress: 0 }), { status: 202 });
  }),
  http.post("*/api/v1/jobs/upload", async ({ request }) => {
    state.requests.uploads.push(`${request.headers.get("content-type")}\n${await request.text()}`);
    if (state.uploadError) {
      const { status, code, detail } = state.uploadError as {
        status: number;
        code: string;
        detail: string;
      };
      return problem(status, code, detail);
    }
    return HttpResponse.json(job({ status: "queued", progress: 0 }), { status: 202 });
  }),
  http.delete("*/api/v1/jobs/:id", ({ params }) => {
    state.requests.deleted.push(String(params.id));
    if (state.deleteError) {
      const { status, code, detail } = state.deleteError;
      return problem(status, code, detail);
    }
    return new HttpResponse(null, { status: 204 });
  })
);

let restoreFetch: () => void;

beforeAll(async () => {
  server.listen({ onUnhandledRequest: "error" });
  // jsdom 的 FormData/AbortSignal 与 Node fetch 不兼容，在 MSW 之外包一层转换。
  restoreFetch = await installFetchBridge();
});

beforeEach(() => {
  state = freshState();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  server.resetHandlers();
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
});

afterAll(() => {
  restoreFetch();
  server.close();
});

function renderLibrary(
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
) {
  const router = createMemoryRouter(routes, { initialEntries: ["/"] });
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
  return { router, client };
}

async function ready() {
  return screen.findByRole("button", { name: "开始切分" });
}

function setSlider(label: string, value: string) {
  fireEvent.change(screen.getByRole("slider", { name: label }), { target: { value } });
}

describe("submission", () => {
  it("keeps both entries unavailable until the runtime config arrives", async () => {
    let release!: () => void;
    state.configGate = new Promise((resolve) => {
      release = resolve;
    });
    renderLibrary();

    expect(await screen.findByRole("status")).toHaveTextContent("正在加载运行配置");
    expect(screen.queryByRole("button", { name: "开始切分" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("选择本地文件")).not.toBeInTheDocument();

    release();

    expect(await ready()).toBeEnabled();
  });

  it("submits a URL with the complete shared options", async () => {
    const user = userEvent.setup();
    renderLibrary();
    await ready();

    setSlider("最长句长", "10");
    await user.type(screen.getByLabelText("视频链接或本机媒体路径"), "https://example.test/v");
    await user.click(screen.getByRole("button", { name: "开始切分" }));

    await waitFor(() => expect(state.requests.created).toHaveLength(1));
    expect(state.requests.created[0]).toEqual({
      source: "https://example.test/v",
      asrBackend: "local",
      subtitleSource: "auto",
      language: "en",
      makeClips: false,
      minDuration: 1,
      maxDuration: 10,
      hardPause: 0.75,
      leadPad: 0.2,
      tailPad: 0.4
    });
    expect(screen.getByLabelText("视频链接或本机媒体路径")).toHaveValue("");
  });

  it("keeps only the link when pasting a share text", async () => {
    const user = userEvent.setup();
    renderLibrary();
    await ready();
    const input = screen.getByLabelText("视频链接或本机媒体路径");

    await user.click(input);
    await user.paste(
      "【【全英vlog】跟着博主学口语 |“如何享受独处？”】 https://www.bilibili.com/video/BV1EqVJ6dE6R/?share_source=copy_web"
    );
    expect(input).toHaveValue("https://www.bilibili.com/video/BV1EqVJ6dE6R/?share_source=copy_web");

    await user.click(screen.getByRole("button", { name: "开始切分" }));
    await waitFor(() => expect(state.requests.created).toHaveLength(1));
    expect(state.requests.created[0]).toMatchObject({
      source: "https://www.bilibili.com/video/BV1EqVJ6dE6R/?share_source=copy_web"
    });
  });

  it("pastes the link over the selection and keeps the rest of the input", async () => {
    const user = userEvent.setup();
    renderLibrary();
    await ready();
    const input = screen.getByLabelText<HTMLInputElement>("视频链接或本机媒体路径");

    await user.type(input, "https://old.test/v");
    input.setSelectionRange(0, input.value.length);
    await user.paste("【新视频】 https://new.test/v");
    expect(input).toHaveValue("https://new.test/v");
  });

  it("submits only the link from typed share text", async () => {
    state.config = { ...CONFIG, allowLocalPaths: false };
    const user = userEvent.setup();
    renderLibrary();
    await ready();

    await user.type(screen.getByLabelText("视频链接"), "看这个：https://youtu.be/abc。");
    await user.click(screen.getByRole("button", { name: "开始切分" }));

    await waitFor(() => expect(state.requests.created).toHaveLength(1));
    expect(state.requests.created[0]).toMatchObject({ source: "https://youtu.be/abc" });
  });

  it("uploads a file only after the explicit button, as multipart strings", async () => {
    const user = userEvent.setup();
    renderLibrary();
    await ready();

    await user.clear(screen.getByLabelText("语言"));
    await user.click(screen.getByLabelText("预先生成全部单句音频"));
    setSlider("最长句长", "10");
    await user.upload(
      screen.getByLabelText("选择本地文件"),
      new File(["RIFF"], "talk.wav", { type: "audio/wav" })
    );

    expect(screen.getByText("已选择：talk.wav")).toBeInTheDocument();
    expect(state.requests.uploads).toEqual([]);

    await user.click(screen.getByRole("button", { name: "上传并处理" }));

    await waitFor(() => expect(state.requests.uploads).toHaveLength(1));
    const [raw] = state.requests.uploads;
    expect(raw).toMatch(/^multipart\/form-data; boundary=/);
    expect(multipartFields(raw)).toEqual({
      file: "talk.wav",
      asrBackend: "local",
      subtitleSource: "auto",
      language: "auto",
      makeClips: "true",
      minDuration: "1",
      maxDuration: "10",
      hardPause: "0.75",
      leadPad: "0.2",
      tailPad: "0.4"
    });
    expect(screen.queryByText("已选择：talk.wav")).not.toBeInTheDocument();
  });

  it("uses the same options for both entries", async () => {
    const user = userEvent.setup();
    renderLibrary();
    await ready();
    await user.selectOptions(screen.getByLabelText("字幕来源"), "asr");
    setSlider("强制断句停顿", "1.5");

    await user.type(screen.getByLabelText("视频链接或本机媒体路径"), "https://example.test/v");
    await user.click(screen.getByRole("button", { name: "开始切分" }));
    await user.click(await screen.findByRole("button", { name: "放到后台" }));
    await user.upload(
      screen.getByLabelText("选择本地文件"),
      new File(["x"], "a.mp3", { type: "audio/mpeg" })
    );
    await user.click(screen.getByRole("button", { name: "上传并处理" }));
    await waitFor(() => expect(state.requests.uploads).toHaveLength(1));

    const json = state.requests.created[0] as Record<string, unknown>;
    const form = multipartFields(state.requests.uploads[0]);
    expect(json.subtitleSource).toBe(form.subtitleSource);
    expect(String(json.hardPause)).toBe(form.hardPause);
    expect(form.subtitleSource).toBe("asr");
  });

  it("accepts a file dropped anywhere on the intake card and lets it be cancelled", async () => {
    const user = userEvent.setup();
    renderLibrary();
    await ready();
    const card = screen.getByRole("region", { name: "把一段视频拆成一句一句来听" });

    fireEvent.dragOver(card, { dataTransfer: { types: ["Files"] } });
    expect(card).toHaveAttribute("data-dragging", "true");
    fireEvent.drop(card, {
      dataTransfer: {
        types: ["Files"],
        files: [new File(["x"], "dropped.mp4", { type: "video/mp4" })]
      }
    });

    expect(card).not.toHaveAttribute("data-dragging");
    expect(screen.getByText("已选择：dropped.mp4")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "上传并处理" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "取消" }));
    expect(screen.queryByText("已选择：dropped.mp4")).not.toBeInTheDocument();
    expect(screen.getByText("也可以直接拖放到这个区域")).toBeInTheDocument();
  });

  it("ignores drags that do not carry files", async () => {
    renderLibrary();
    await ready();
    const card = screen.getByRole("region", { name: "把一段视频拆成一句一句来听" });

    fireEvent.dragOver(card, { dataTransfer: { types: ["text/uri-list"] } });

    expect(card).not.toHaveAttribute("data-dragging");
  });

  it("clears a previous upload error when a new file is dropped", async () => {
    state.uploadError = {
      status: 413,
      code: "UPLOAD_TOO_LARGE",
      detail: "文件超过大小上限。"
    };
    const user = userEvent.setup();
    renderLibrary();
    await ready();
    const card = screen.getByRole("region", { name: "把一段视频拆成一句一句来听" });

    await user.upload(
      screen.getByLabelText("选择本地文件"),
      new File(["x"], "big.mp4", { type: "video/mp4" })
    );
    await user.click(screen.getByRole("button", { name: "上传并处理" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("文件超过大小上限。");

    fireEvent.drop(card, {
      dataTransfer: {
        types: ["Files"],
        files: [new File(["y"], "next.mp4", { type: "video/mp4" })]
      }
    });

    expect(screen.getByText("已选择：next.mp4")).toBeInTheDocument();
    // TanStack 的状态通知在下一个宏任务里发出，需等待错误提示消失。
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("warns about files that do not look like media without blocking them", async () => {
    const user = userEvent.setup({ applyAccept: false });
    renderLibrary();
    await ready();

    await user.upload(
      screen.getByLabelText("选择本地文件"),
      new File(["x"], "notes.pdf", { type: "application/pdf" })
    );

    expect(screen.getByText(/看起来不是音视频/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "上传并处理" })).toBeEnabled();
  });

  it("lets keyboard users reach the file picker", async () => {
    const user = userEvent.setup();
    renderLibrary();
    await ready();
    const picker = screen.getByLabelText("选择本地文件");

    for (let step = 0; step < 30 && document.activeElement !== picker; step += 1) {
      await user.tab();
    }

    expect(picker).toHaveFocus();
  });

  it("opens the settings drawer and blocks both entries while durations conflict", async () => {
    renderLibrary();
    await ready();
    const drawer = screen.getByText("识别与切分设置").closest("details")!;
    expect(drawer).not.toHaveAttribute("open");

    setSlider("最短句长", "8");
    setSlider("最长句长", "8");

    expect(drawer).toHaveAttribute("open");
    expect(screen.getByRole("alert")).toHaveTextContent("最短句长必须小于最长句长。");
    expect(screen.getByRole("slider", { name: "最长句长" })).toHaveAttribute(
      "aria-invalid",
      "true"
    );
    expect(screen.getByRole("button", { name: "开始切分" })).toBeDisabled();

    setSlider("最长句长", "12");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始切分" })).toBeEnabled();
  });

  it("shows the server's problem detail when creation fails", async () => {
    state.createError = {
      status: 403,
      code: "LOCAL_PATHS_DISABLED",
      detail: "此服务未开放本机文件路径。"
    };
    const user = userEvent.setup();
    renderLibrary();
    await ready();

    await user.type(screen.getByLabelText("视频链接或本机媒体路径"), "C:/media/talk.mp4");
    await user.click(screen.getByRole("button", { name: "开始切分" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("此服务未开放本机文件路径。");
  });

  it("only offers links when the server disables local paths", async () => {
    state.config = { ...CONFIG, allowLocalPaths: false };
    const user = userEvent.setup();
    renderLibrary();
    await ready();

    await user.type(screen.getByLabelText("视频链接"), "C:/media/talk.mp4");
    await user.click(screen.getByRole("button", { name: "开始切分" }));

    expect(screen.getByRole("alert")).toHaveTextContent("只接受 http(s) 链接");
    expect(state.requests.created).toEqual([]);
  });

  it("keeps the settings drawer open while blocking reasons are showing", async () => {
    const user = userEvent.setup();
    renderLibrary();
    await ready();
    const drawer = screen.getByText("识别与切分设置").closest("details")!;

    setSlider("最短句长", "8");
    setSlider("最长句长", "8");
    expect(drawer).toHaveAttribute("open");

    // 提交按钮仍被禁用时不允许收起，否则用户看不到原因。
    await user.click(screen.getByText("识别与切分设置"));

    expect(drawer).toHaveAttribute("open");
    expect(screen.getByRole("alert")).toHaveTextContent("最短句长必须小于最长句长。");
    expect(screen.getByRole("alert")).toBeVisible();
  });

  it("offers only the backends the server reports", async () => {
    renderLibrary();
    await ready();

    const options = screen.getByLabelText("识别引擎").querySelectorAll("option");
    expect([...options].map((option) => option.value)).toEqual(["local"]);
  });
});

describe("job list", () => {
  it("shows status, accessible progress, failures and delete rules", async () => {
    state.pages = [
      [
        job({
          id: "AAAAAAAAAAAAAAAA",
          title: "Running Talk",
          status: "running",
          stage: "transcribing",
          progress: 0.5,
          message: "识别中",
          sentenceCount: 0
        }),
        job({
          id: "BBBBBBBBBBBBBBBB",
          title: "Broken Talk",
          status: "failed",
          progress: 0.3,
          message: "处理失败",
          error: { code: "SUBTITLE_NOT_AVAILABLE", detail: "没有可用的人工字幕。" },
          sentenceCount: 0
        }),
        job({ id: "CCCCCCCCCCCCCCCC", title: "Done Talk" })
      ]
    ];
    renderLibrary();

    const progress = await screen.findByRole("progressbar", { name: "Running Talk 处理进度" });
    expect(progress).toHaveAttribute("aria-valuenow", "50");
    expect(progress).toHaveAttribute("aria-valuetext", "50%");
    expect(screen.getByText("处理中·转写")).toBeInTheDocument();
    expect(screen.getByText("识别中")).toBeInTheDocument();
    expect(screen.getByText("已完成").closest("li")).toHaveAttribute("data-status", "succeeded");
    expect(screen.getByText("失败原因：没有可用的人工字幕。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "删除 Running Talk" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "删除 Broken Talk" })).toBeEnabled();
    expect(screen.getByRole("link", { name: "Done Talk" })).toHaveAttribute(
      "href",
      "/jobs/CCCCCCCCCCCCCCCC"
    );
    expect(screen.queryByRole("link", { name: "Running Talk" })).not.toBeInTheDocument();
  });

  it("opens the practice page for a succeeded job", async () => {
    state.pages = [[job()]];
    server.use(
      http.get("*/api/v1/jobs/:id", () => HttpResponse.json(job())),
      http.get("*/api/v1/jobs/:id/result", () =>
        HttpResponse.json({
          jobId: "0123456789ABCDEF",
          title: "Everyday Talk",
          sourceUrl: null,
          uploader: null,
          thumbnailUrl: null,
          duration: 2,
          language: "en",
          transcriptSource: "asr:fake:fake",
          audioUrl: "/api/v1/jobs/0123456789ABCDEF/audio",
          createdAt: "2026-01-01T00:00:00Z",
          sentenceCount: 1,
          hasClips: false,
          sentences: [
            {
              index: 0,
              start: 0,
              end: 1,
              speechStart: 0.1,
              speechEnd: 0.9,
              duration: 1,
              text: "Hi.",
              words: []
            }
          ]
        })
      )
    );
    const user = userEvent.setup();
    const { router } = renderLibrary();

    await user.click(await screen.findByRole("link", { name: "Everyday Talk" }));

    expect(await screen.findByRole("heading", { name: "第 1 / 1 句" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/jobs/0123456789ABCDEF");
  });

  it("deletes only after confirmation and then moves focus to the list heading", async () => {
    state.pages = [[job()], []];
    const user = userEvent.setup();
    renderLibrary();
    const button = await screen.findByRole("button", { name: "删除 Everyday Talk" });

    await user.click(button);
    const dialog = screen.getByRole("dialog", { name: "删除素材" });
    expect(dialog).toHaveTextContent("删除「Everyday Talk」及其全部产物？此操作无法撤销。");
    await user.click(screen.getByRole("button", { name: "取消" }));
    expect(state.requests.deleted).toEqual([]);
    expect(button).toHaveFocus();

    await user.click(button);
    await user.click(screen.getByRole("button", { name: "删除" }));

    await waitFor(() => expect(state.requests.deleted).toEqual(["0123456789ABCDEF"]));
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "已处理的素材" })).toHaveFocus()
    );
    expect(screen.getByText("还没有素材。上面粘贴一个链接就能开始。")).toBeInTheDocument();
  });

  it("returns focus to the card's delete button when deletion fails", async () => {
    state.pages = [[job()]];
    state.deleteError = { status: 409, code: "JOB_RUNNING", detail: "任务正在处理，不能删除。" };
    const user = userEvent.setup();
    renderLibrary();
    const button = await screen.findByRole("button", { name: "删除 Everyday Talk" });

    await user.click(button);
    await user.click(screen.getByRole("button", { name: "删除" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("任务正在处理，不能删除。");
    await waitFor(() => expect(button).toHaveFocus());
    expect(button).toBeEnabled();
  });

  it("shows one persistent alert when the list cannot load", async () => {
    state.jobsStatus = 500;
    renderLibrary();

    expect(await screen.findByText("暂时无法加载任务，请稍后刷新。")).toBeInTheDocument();
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });
});

describe("polling", () => {
  it("polls every second while jobs are active and stops once they finish", async () => {
    state.pages = [
      [job({ status: "running", progress: 0.2 })],
      [job({ status: "running", progress: 0.6 })],
      [job({ status: "succeeded" })]
    ];
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["jobResult", "0123456789ABCDEF"], { stale: true });
    renderLibrary(client);

    await screen.findByText("20%");
    expect(state.requests.jobs).toBe(1);

    await act(() => vi.advanceTimersByTimeAsync(ACTIVE_POLL_MS));
    await screen.findByText("60%");
    expect(state.requests.jobs).toBe(2);

    await act(() => vi.advanceTimersByTimeAsync(ACTIVE_POLL_MS));
    await screen.findByText("已完成");
    expect(state.requests.jobs).toBe(3);

    await act(() => vi.advanceTimersByTimeAsync(10 * ACTIVE_POLL_MS));
    expect(state.requests.jobs).toBe(3);
    // 任务进入终态时，其结果缓存被标记为失效，练习台会重新读取。
    expect(client.getQueryState(["jobResult", "0123456789ABCDEF"])?.isInvalidated).toBe(true);
  });

  it("slows to five seconds while the tab is hidden", async () => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    state.pages = [[job({ status: "queued", progress: 0 })]];
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    renderLibrary();

    await screen.findByText("排队中");
    expect(state.requests.jobs).toBe(1);

    await act(() => vi.advanceTimersByTimeAsync(ACTIVE_POLL_MS));
    expect(state.requests.jobs).toBe(1);

    await act(() => vi.advanceTimersByTimeAsync(HIDDEN_POLL_MS - ACTIVE_POLL_MS));
    await waitFor(() => expect(state.requests.jobs).toBe(2));
  });

  it("does not poll when no job is active", async () => {
    state.pages = [[job()]];
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    renderLibrary();

    await screen.findByText("已完成");
    await act(() => vi.advanceTimersByTimeAsync(10 * ACTIVE_POLL_MS));

    expect(state.requests.jobs).toBe(1);
  });

  it("reports each job once when it leaves the active states", async () => {
    state.pages = [[job({ status: "running", progress: 0.4 })], [job({ status: "succeeded" })]];
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const finished: string[] = [];
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderHook(() => useJobs({ onFinished: (item) => finished.push(item.status) }), {
      wrapper: ({ children }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      )
    });

    await vi.waitFor(() => expect(state.requests.jobs).toBe(1));
    await act(() => vi.advanceTimersByTimeAsync(ACTIVE_POLL_MS));
    await vi.waitFor(() => expect(finished).toEqual(["succeeded"]));
    await act(() => vi.advanceTimersByTimeAsync(10 * ACTIVE_POLL_MS));
    expect(finished).toEqual(["succeeded"]);
  });
});

describe("pollInterval", () => {
  const page = (status: Job["status"]) => ({ items: [job({ status })], nextCursor: null });

  it("stops without active jobs", () => {
    expect(pollInterval(undefined, 0, false)).toBe(false);
    expect(pollInterval(page("succeeded"), 0, false)).toBe(false);
    expect(pollInterval(page("failed"), 3, false)).toBe(false);
  });

  it("uses visibility-dependent intervals with bounded exponential backoff", () => {
    expect(pollInterval(page("running"), 0, false)).toBe(ACTIVE_POLL_MS);
    expect(pollInterval(page("queued"), 0, true)).toBe(HIDDEN_POLL_MS);
    expect(pollInterval(page("running"), 1, false)).toBe(2 * ACTIVE_POLL_MS);
    expect(pollInterval(page("running"), 3, false)).toBe(8 * ACTIVE_POLL_MS);
    expect(pollInterval(page("running"), 20, false)).toBe(MAX_BACKOFF_MS);
  });
});

describe("progress overlay", () => {
  async function submitUrl(user: ReturnType<typeof userEvent.setup>) {
    await user.type(screen.getByLabelText("视频链接或本机媒体路径"), "https://example.test/v");
    await user.click(screen.getByRole("button", { name: "开始切分" }));
  }

  it("follows the new job from the polled list and offers to start practising", async () => {
    state.pages = [
      [],
      [job({ status: "running", stage: "transcribing", progress: 0.4, message: "正在识别" })],
      [job({ status: "succeeded", sentenceCount: 24 })]
    ];
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"], shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const { router } = renderLibrary();
    await ready();

    await submitUrl(user);

    const dialog = await screen.findByRole("dialog", { name: "正在处理" });
    expect(dialog).toHaveTextContent("Everyday Talk");
    expect(await within(dialog).findByText("正在识别")).toBeInTheDocument();
    const steps = within(dialog).getByRole("list", { name: "处理步骤" });
    expect(
      within(steps)
        .getAllByRole("listitem")
        .map((item) => item.textContent)
    ).toEqual(["下载（已完成）", "准备音频（已完成）", "转写", "切句"]);
    expect(within(steps).getByText("转写")).toHaveAttribute("aria-current", "step");
    expect(dialog).toHaveTextContent(/已用时 \d+:\d{2}/);
    expect(screen.getByRole("progressbar", { name: "处理进度" })).toHaveAttribute(
      "aria-valuenow",
      "40"
    );

    await act(() => vi.advanceTimersByTimeAsync(ACTIVE_POLL_MS));
    expect(await screen.findByRole("dialog", { name: "处理完成 · 共 24 句" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始练习" })).toHaveFocus();
    // 浮层正在展示这个任务，不再额外弹出完成提示。先冲刷 effect，否则可能在 toast 发出之前就断言了。
    await act(async () => {});
    expect(screen.queryByText("「Everyday Talk」处理完成")).not.toBeInTheDocument();

    // 进入练习台后会请求任务与结果；这里只验证跳转，给出最小响应避免未处理请求。
    server.use(
      http.get("*/api/v1/jobs/:id", () => HttpResponse.json(job())),
      http.get("*/api/v1/jobs/:id/result", () => problem(404, "RESULT_NOT_FOUND", "结果不存在。"))
    );
    await user.click(screen.getByRole("button", { name: "开始练习" }));
    // 路由跳转是异步提交的，点击返回时 location 可能还没更新，所以等待而不是立即断言。
    // 练习台路由是懒加载的，冷启动时首次加载可能超过默认的 1 秒，所以放宽超时。
    await vi.waitFor(() => expect(router.state.location.pathname).toBe("/jobs/0123456789ABCDEF"), {
      timeout: 5000
    });
  });

  it("shows the failure reason", async () => {
    state.pages = [
      [],
      [
        job({
          status: "failed",
          progress: 0.3,
          message: "处理失败",
          error: { code: "DOWNLOAD_FAILED", detail: "无法下载该媒体。" }
        })
      ]
    ];
    const user = userEvent.setup();
    renderLibrary();
    await ready();

    await submitUrl(user);

    const dialog = await screen.findByRole("dialog", { name: "处理失败" });
    expect(dialog).toHaveTextContent("无法下载该媒体。");
    await user.click(screen.getByRole("button", { name: "关闭" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("returns focus to the library heading when the overlay is closed", async () => {
    const user = userEvent.setup();
    renderLibrary();
    await ready();

    await user.upload(
      screen.getByLabelText("选择本地文件"),
      new File(["x"], "a.mp3", { type: "audio/mpeg" })
    );
    await user.click(screen.getByRole("button", { name: "上传并处理" }));
    await screen.findByRole("dialog", { name: "正在处理" });

    await user.click(screen.getByRole("button", { name: "放到后台" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "已处理的素材" })).toHaveFocus();
  });

  it("toasts once when a backgrounded job finishes", async () => {
    state.pages = [
      [],
      [job({ status: "running", progress: 0.5, message: "正在识别" })],
      [job({ status: "succeeded" })]
    ];
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"], shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderLibrary();
    await ready();

    await submitUrl(user);
    await user.click(await screen.findByRole("button", { name: "放到后台" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    // 等列表拿到运行中的任务（此时轮询定时器才存在），再推进时间。
    await screen.findByText("处理中");

    await act(() => vi.advanceTimersByTimeAsync(ACTIVE_POLL_MS));
    expect(await screen.findByText("「Everyday Talk」处理完成")).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(10 * ACTIVE_POLL_MS));
    expect(screen.getAllByText("「Everyday Talk」处理完成")).toHaveLength(1);
  });
});
