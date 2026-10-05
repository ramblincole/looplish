import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { Job, JobResult } from "../api/types";
import { routes } from "../app/router";
import { ACTIVE_POLL_MS } from "../features/jobs/useJobs";
import { installFetchBridge } from "../test/fetchBridge";

const renders = vi.hoisted(() => ({ reel: 0, controls: 0 }));

vi.mock("../features/practice/SentenceReel", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../features/practice/SentenceReel")>();
  return {
    SentenceReel: (props: Parameters<typeof actual.SentenceReel>[0]) => {
      renders.reel += 1;
      return actual.SentenceReel(props);
    }
  };
});

vi.mock("../features/practice/PlaybackSettings", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../features/practice/PlaybackSettings")>();
  return {
    PlaybackSettings: () => {
      renders.controls += 1;
      return actual.PlaybackSettings();
    }
  };
});

const JOB_ID = "JOB1234567890";

type Sentence = JobResult["sentences"][number];

function sentence(
  index: number,
  start: number,
  end: number,
  words: Array<[string, number, number]>
): Sentence {
  return {
    index,
    start,
    end,
    speechStart: words[0][1],
    speechEnd: words[words.length - 1][2],
    duration: Math.round((end - start) * 1000) / 1000,
    text: words
      .map(([text]) => text)
      .join("")
      .trim(),
    // 与服务端一致：词文本带前导空格，句子文本由各词直接拼接。
    words: words.map(([text, wordStart, wordEnd]) => ({
      text,
      start: wordStart,
      end: wordEnd,
      probability: 0.9
    }))
  };
}

// 三句 fixture：播放边界 start/end 含首尾留白，词时间落在 speechStart/speechEnd 内。
const SENTENCES: Sentence[] = [
  sentence(0, 0.3, 2.0, [
    [" Hello", 0.5, 0.9],
    [" there.", 1.0, 1.6]
  ]),
  sentence(1, 2.5, 4.5, [
    [" How", 2.7, 3.0],
    [" are", 3.1, 3.3],
    [" you?", 3.4, 4.0]
  ]),
  sentence(2, 5.0, 6.5, [[" Bye.", 5.2, 6.0]])
];

function result(sentences: Sentence[] = SENTENCES): JobResult {
  return {
    jobId: JOB_ID,
    title: "Everyday Talk",
    sourceUrl: "https://example.test/v",
    uploader: "Example Channel",
    thumbnailUrl: null,
    duration: 7,
    language: "en",
    transcriptSource: "asr:fake:fake",
    audioUrl: `/api/v1/jobs/${JOB_ID}/audio`,
    createdAt: "2026-01-01T00:00:00Z",
    sentenceCount: sentences.length,
    hasClips: false,
    sentences
  };
}

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: JOB_ID,
    source: "https://example.test/v",
    title: "Everyday Talk",
    status: "succeeded",
    stage: null,
    progress: 1,
    message: "处理完成",
    error: null,
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    sentenceCount: 3,
    ...overrides
  };
}

type State = {
  job: Job | null;
  result: JobResult;
  resegmented: JobResult;
  resegmentError: { status: number; code: string; detail: string } | null;
  requests: { job: number; result: number; resegment: unknown[] };
};

let state: State;

const problem = (status: number, code: string, detail: string) =>
  HttpResponse.json(
    { type: "about:blank", title: code, status, code, detail, requestId: "req_1" },
    { status, headers: { "Content-Type": "application/problem+json" } }
  );

const server = setupServer(
  http.get("*/api/v1/jobs/:id", () => {
    state.requests.job += 1;
    return state.job
      ? HttpResponse.json(state.job)
      : problem(404, "JOB_NOT_FOUND", "没有找到指定任务。");
  }),
  http.get("*/api/v1/jobs/:id/result", () => {
    state.requests.result += 1;
    return HttpResponse.json(state.result);
  }),
  http.post("*/api/v1/jobs/:id/resegment", async ({ request }) => {
    state.requests.resegment.push(await request.json());
    if (state.resegmentError) {
      const { status, code, detail } = state.resegmentError;
      return problem(status, code, detail);
    }
    state.result = state.resegmented;
    return HttpResponse.json(state.resegmented);
  })
);

/**
 * jsdom 不实现媒体播放：这里用一个共享对象替身 HTMLMediaElement 的时间与播放状态，
 * 测试通过 playTo 推进 currentTime，再手动执行排队的 RAF 回调，时间推进完全确定。
 */
const media = {
  currentTime: 0,
  paused: true,
  ended: false,
  playbackRate: 1,
  plays: 0,
  seeks: [] as number[]
};
let playResult: () => Promise<void>;
const frames = new Map<number, FrameRequestCallback>();
let nextFrame = 1;
const MEDIA_PROPS = ["currentTime", "paused", "ended", "playbackRate", "play", "pause"] as const;
const savedMedia = new Map<string, PropertyDescriptor | undefined>();

function installFakeMedia() {
  const proto = HTMLMediaElement.prototype;
  for (const name of MEDIA_PROPS)
    savedMedia.set(name, Object.getOwnPropertyDescriptor(proto, name));
  Object.defineProperties(proto, {
    currentTime: {
      configurable: true,
      get: () => media.currentTime,
      set: (value: number) => {
        media.currentTime = value;
        media.seeks.push(value);
      }
    },
    paused: { configurable: true, get: () => media.paused },
    ended: { configurable: true, get: () => media.ended },
    playbackRate: {
      configurable: true,
      get: () => media.playbackRate,
      set: (value: number) => {
        media.playbackRate = value;
      }
    },
    play: {
      configurable: true,
      writable: true,
      value: () => {
        media.plays += 1;
        media.paused = false;
        return playResult();
      }
    },
    pause: {
      configurable: true,
      writable: true,
      value: () => {
        media.paused = true;
      }
    }
  });
}

function restoreFakeMedia() {
  const proto = HTMLMediaElement.prototype;
  for (const [name, descriptor] of savedMedia) {
    if (descriptor) Object.defineProperty(proto, name, descriptor);
  }
}

/** 模拟音频播放到 seconds，然后跑一帧 RAF。 */
function playTo(seconds: number) {
  act(() => {
    media.currentTime = seconds;
    const pending = [...frames.values()];
    frames.clear();
    for (const callback of pending) callback(0);
  });
}

let restoreFetch: () => void;

beforeAll(async () => {
  server.listen({ onUnhandledRequest: "error" });
  restoreFetch = await installFetchBridge();
  installFakeMedia();
});

beforeEach(() => {
  state = {
    job: job(),
    result: result(),
    resegmented: result(
      [
        sentence(0, 0.3, 1.2, [[" Hello", 0.5, 0.9]]),
        sentence(1, 1.2, 2.0, [[" there.", 1.0, 1.6]]),
        SENTENCES[1],
        SENTENCES[2]
      ].map((item, index) => ({ ...item, index }))
    ),
    resegmentError: null,
    requests: { job: 0, result: 0, resegment: [] }
  };
  Object.assign(media, { currentTime: 0, paused: true, ended: false, playbackRate: 1, plays: 0 });
  media.seeks = [];
  playResult = () => Promise.resolve();
  frames.clear();
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    const id = nextFrame++;
    frames.set(id, callback);
    return id;
  });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => {
    frames.delete(id);
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  server.resetHandlers();
});

afterAll(() => {
  restoreFakeMedia();
  restoreFetch();
  server.close();
});

function renderPractice(path = `/jobs/${JOB_ID}`) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const view = render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
  return { client, router, ...view };
}

async function ready(total = 3) {
  await screen.findByRole("heading", { name: `第 1 / ${total} 句` });
}

const heading = () => document.getElementById("current-sentence-title")?.textContent;
const playButton = () => screen.getByRole("button", { name: /^(播放|暂停)$/ });
const transcript = () => document.querySelector("[data-sentence]") as HTMLElement;
const activeWord = () => transcript().querySelector("[data-active='true']")?.textContent ?? null;
const key = (value: string, target: Element = document.body, init: KeyboardEventInit = {}) =>
  fireEvent.keyDown(target, { key: value, ...init });
const playStatus = () => document.querySelector("[data-readout='loop']")?.textContent;

describe("loading states", () => {
  it("polls a queued job without requesting its result, then opens the player", async () => {
    state.job = job({
      status: "running",
      stage: "transcribing",
      progress: 0.4,
      message: "正在识别"
    });
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    renderPractice();

    expect(await screen.findByText("处理中·转写 · 正在识别")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "处理进度" })).toHaveAttribute(
      "aria-valuetext",
      "40%"
    );
    await act(() => vi.advanceTimersByTimeAsync(ACTIVE_POLL_MS));
    expect(state.requests.job).toBe(2);
    expect(state.requests.result).toBe(0);

    state.job = job();
    await act(() => vi.advanceTimersByTimeAsync(ACTIVE_POLL_MS));
    vi.useRealTimers();

    await ready();
    expect(state.requests.result).toBe(1);
    // 终态后停止轮询。
    const settled = state.requests.job;
    await new Promise((resolve) => setTimeout(resolve, ACTIVE_POLL_MS + 200));
    expect(state.requests.job).toBe(settled);
  });

  it("shows the stable failure detail of a failed job", async () => {
    state.job = job({
      status: "failed",
      message: "处理失败",
      error: { code: "DOWNLOAD_FAILED", detail: "无法下载该媒体。" }
    });
    renderPractice();

    expect(await screen.findByRole("alert")).toHaveTextContent("处理失败：无法下载该媒体。");
    expect(state.requests.result).toBe(0);
  });

  it("does not index sentences[0] of an empty result", async () => {
    state.result = result([]);
    renderPractice();

    expect(await screen.findByText("未找到可练习句段。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "播放" })).not.toBeInTheDocument();
  });

  it("reports a missing job immediately instead of retrying the 404", async () => {
    state.job = null;
    renderPractice();

    expect(await screen.findByRole("alert")).toHaveTextContent("没有找到指定任务。");
    expect(state.requests.job).toBe(1);
    expect(screen.getByRole("link", { name: "← 素材库" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("heading", { level: 1, name: "无法打开练习" })).toBeInTheDocument();
  });
  it("keeps the player and its progress when a background refresh of the job fails", async () => {
    const { client } = renderPractice();
    await ready();
    key("ArrowRight");
    fireEvent.change(screen.getByLabelText("语速"), { target: { value: "0.8" } });

    state.job = null;
    await act(() => client.invalidateQueries({ queryKey: ["job", JOB_ID] }));

    expect(await screen.findByText(/暂时无法从服务刷新任务状态/)).toBeInTheDocument();
    expect(heading()).toBe("第 2 / 3 句");
    expect(screen.getByLabelText("语速")).toHaveValue("0.8");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("names the job title and offers the way back while practising", async () => {
    renderPractice();
    await ready();

    expect(screen.getByRole("heading", { level: 1, name: "Everyday Talk" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "← 素材库" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("region", { name: "第 1 / 3 句" })).toContainElement(playButton());
  });
});

describe("audio boundaries", () => {
  it("seeks to sentence.start, plays, and pauses exactly at sentence.end", async () => {
    renderPractice();
    await ready();
    expect(media.seeks).toEqual([0.3]);

    fireEvent.click(playButton());
    expect(media.plays).toBe(1);
    expect(playButton()).toHaveTextContent("暂停");

    playTo(1.999);
    expect(media.paused).toBe(false);
    playTo(2.0);
    expect(media.paused).toBe(true);
    expect(playButton()).toHaveTextContent("播放");
    // 到达句末后 RAF 链结束，不再有排队的帧。
    expect(frames.size).toBe(0);
    expect(screen.getByText("已练 1 / 3")).toBeInTheDocument();
  });

  it("resumes a paused sentence in place but replays from the start with R", async () => {
    renderPractice();
    await ready();
    fireEvent.click(playButton());
    playTo(1.2);
    fireEvent.click(playButton());
    expect(media.paused).toBe(true);

    fireEvent.click(playButton());
    expect(media.currentTime).toBe(1.2);

    key("r");
    expect(media.seeks.at(-1)).toBe(0.3);
    expect(media.plays).toBe(3);
  });

  it("falls back to timeupdate when the tab is hidden and frames stop", async () => {
    renderPractice();
    await ready();
    fireEvent.click(playButton());

    media.currentTime = 2.2;
    fireEvent(document.querySelector("audio")!, new Event("timeupdate"));

    expect(media.paused).toBe(true);
    expect(playButton()).toHaveTextContent("播放");
    expect(frames.size).toBe(0);
  });

  it("applies the playback rate to the audio element", async () => {
    renderPractice();
    await ready();

    fireEvent.change(screen.getByLabelText("语速"), { target: { value: "0.75" } });

    expect(media.playbackRate).toBe(0.75);
  });

  it("shows a readable error and returns to paused when the browser refuses to play", async () => {
    playResult = () => Promise.reject(new DOMException("denied", "NotAllowedError"));
    renderPractice();
    await ready();

    fireEvent.click(playButton());

    expect(await screen.findByRole("alert")).toHaveTextContent("浏览器拒绝了播放");
    expect(playButton()).toHaveTextContent("播放");
    // 播放被拒不是句子完成，不能计为已练。
    expect(screen.getByText("已练 0 / 3")).toBeInTheDocument();
  });

  it("ignores the AbortError caused by pausing before play resolves", async () => {
    playResult = () => Promise.reject(new DOMException("interrupted", "AbortError"));
    renderPractice();
    await ready();

    fireEvent.click(playButton());
    await act(() => Promise.resolve());

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(playButton()).toHaveTextContent("暂停");
  });

  it("shows where the playhead is within the sentence and how often it was heard", async () => {
    renderPractice();
    await ready();
    const readout = (name: string) => document.querySelector(`[data-readout='${name}']`);
    expect(readout("duration")).toHaveTextContent("1.7s");
    expect(readout("listens")).toHaveTextContent("听了 0 次");

    fireEvent.click(playButton());
    playTo(1.15);
    expect(readout("time")).toHaveTextContent("00:00.8");
    const fill = document.querySelector("[data-sentence-progress] > *") as HTMLElement;
    expect(fill.style.inlineSize).toBe("50%");

    playTo(2.0);
    expect(readout("listens")).toHaveTextContent("听了 1 次");
  });
});

describe("veiled transcript", () => {
  it("veils the words in place and reveals them with Enter", async () => {
    renderPractice();
    await ready();

    expect(transcript()).toHaveAttribute("data-veiled", "true");
    expect(within(transcript()).getByText("文本已隐藏，共 2 个词。")).toBeInTheDocument();
    // 词留在页面上撑出真实宽度，但整段对读屏隐藏。
    expect(within(transcript()).getByText("Hello").closest("p")).toHaveAttribute(
      "aria-hidden",
      "true"
    );

    key("Enter");

    expect(transcript()).toHaveAttribute("data-veiled", "false");
    expect(within(transcript()).getByText("Hello").closest("p")).not.toHaveAttribute("aria-hidden");
    expect(transcript()).toHaveTextContent("Hello there.");
    expect(screen.getByRole("button", { name: "遮住原文" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
  });

  it("highlights only the word whose own time contains the playhead", async () => {
    renderPractice();
    await ready();
    key("Enter");
    fireEvent.click(playButton());

    playTo(0.4);
    expect(activeWord()).toBeNull();
    playTo(0.6);
    expect(activeWord()).toBe("Hello");
    playTo(0.95);
    expect(activeWord()).toBeNull();
    playTo(1.2);
    expect(activeWord()).toBe("there.");
  });

  it("re-veils a new sentence when alwaysHide is on, and keeps it revealed when off", async () => {
    renderPractice();
    await ready();
    key("Enter");

    key("ArrowRight");
    expect(heading()).toBe("第 2 / 3 句");
    expect(within(transcript()).getByText("文本已隐藏，共 3 个词。")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("换句自动遮住"));
    key("Enter");
    key("ArrowRight");
    expect(transcript()).toHaveAttribute("data-veiled", "false");
    expect(transcript()).toHaveTextContent("Bye.");
  });

  it("falls back to whitespace tokens without highlight when words are missing", async () => {
    state.result = result(SENTENCES.map((item) => ({ ...item, words: [] })));
    renderPractice();
    await ready();

    expect(within(transcript()).getByText("文本已隐藏，共 2 个词。")).toBeInTheDocument();
    key("Enter");
    fireEvent.click(playButton());
    playTo(0.6);

    expect(transcript()).toHaveAttribute("data-veiled", "false");
    expect(transcript()).toHaveTextContent("Hello there.");
    expect(activeWord()).toBeNull();
  });

  it("re-renders only playhead consumers while the audio advances", async () => {
    renderPractice();
    await ready();
    key("Enter");
    fireEvent.click(playButton());
    const before = { ...renders };
    // 先确认两个消费者确实渲染过，否则下面的"计数不变"会空转通过。
    expect(before.reel).toBeGreaterThan(0);
    expect(before.controls).toBeGreaterThan(0);

    playTo(0.6);
    playTo(0.95);
    playTo(1.2);

    expect(activeWord()).toBe("there.");
    expect(renders).toEqual(before);
  });
});

describe("loops, gaps and auto advance", () => {
  it("replays after a fixed gap until repeat is reached, then stops without a timer", async () => {
    renderPractice();
    await ready();
    fireEvent.change(screen.getByLabelText("循环"), { target: { value: "2" } });
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });

    fireEvent.click(playButton());
    playTo(2.0);
    expect(playStatus()).toBe("循环 2/2 · 跟读中");

    act(() => vi.advanceTimersByTime(999));
    expect(media.plays).toBe(1);
    act(() => vi.advanceTimersByTime(1));
    expect(media.plays).toBe(2);
    expect(media.seeks.at(-1)).toBe(0.3);

    playTo(2.0);
    expect(playStatus()).toBe("循环 1/2");
    act(() => vi.advanceTimersByTime(10_000));
    expect(media.plays).toBe(2);
  });

  it("keeps looping with infinite repeat until the user pauses", async () => {
    renderPractice();
    await ready();
    fireEvent.change(screen.getByLabelText("循环"), { target: { value: "infinite" } });
    fireEvent.change(screen.getByLabelText("跟读间隔"), { target: { value: "0" } });
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });

    fireEvent.click(playButton());
    for (let round = 2; round <= 4; round += 1) {
      playTo(2.0);
      act(() => vi.advanceTimersByTime(0));
      expect(media.plays).toBe(round);
    }
    expect(playStatus()).toBe("循环 4/∞");

    key(" ");
    expect(media.paused).toBe(true);
    act(() => vi.advanceTimersByTime(10_000));
    expect(media.plays).toBe(4);
  });

  it("waits as long as the finished sentence before auto advancing", async () => {
    renderPractice();
    await ready();
    fireEvent.change(screen.getByLabelText("跟读间隔"), { target: { value: "sentence" } });
    fireEvent.click(screen.getByLabelText("自动下一句"));
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });

    fireEvent.click(playButton());
    playTo(2.0);
    expect(heading()).toBe("第 2 / 3 句");
    expect(media.seeks.at(-1)).toBe(2.5);

    // 第一句 duration = 1.7 秒。
    act(() => vi.advanceTimersByTime(1699));
    expect(media.plays).toBe(1);
    act(() => vi.advanceTimersByTime(1));
    expect(media.plays).toBe(2);
    expect(playButton()).toHaveTextContent("暂停");
  });

  it("does not advance past the last sentence", async () => {
    renderPractice();
    await ready();
    fireEvent.click(screen.getByRole("button", { name: /^第 3 句/ }));
    fireEvent.click(screen.getByLabelText("自动下一句"));
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });

    fireEvent.click(playButton());
    playTo(6.5);
    act(() => vi.advanceTimersByTime(10_000));

    expect(heading()).toBe("第 3 / 3 句");
    expect(media.plays).toBe(1);
    expect(screen.getByRole("button", { name: "下一句" })).toBeDisabled();
  });

  it("cancels the pending gap when the user selects another sentence", async () => {
    renderPractice();
    await ready();
    fireEvent.change(screen.getByLabelText("循环"), { target: { value: "2" } });
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });

    fireEvent.click(playButton());
    playTo(2.0);
    fireEvent.click(screen.getByRole("button", { name: /^第 2 句/ }));
    act(() => vi.advanceTimersByTime(5000));

    expect(media.plays).toBe(1);
    expect(playStatus()).toBe("循环 1/2");
    expect(screen.getByRole("button", { name: /^第 2 句/ })).toHaveAttribute(
      "aria-current",
      "true"
    );
  });

  it("stops frames, timers and sound on unmount", async () => {
    const { unmount } = renderPractice();
    await ready();
    fireEvent.change(screen.getByLabelText("循环"), { target: { value: "2" } });
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    fireEvent.click(playButton());
    playTo(2.0);
    fireEvent.click(playButton());
    expect(frames.size).toBe(1);

    unmount();

    expect(frames.size).toBe(0);
    expect(media.paused).toBe(true);
    act(() => vi.advanceTimersByTime(10_000));
    expect(media.plays).toBe(2);
  });

  it("stretches a sentence-length gap by the playback rate", async () => {
    renderPractice();
    await ready();
    fireEvent.change(screen.getByLabelText("循环"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("跟读间隔"), { target: { value: "sentence" } });
    fireEvent.change(screen.getByLabelText("语速"), { target: { value: "0.8" } });
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });

    fireEvent.click(playButton());
    playTo(2.0);

    // 第一句 duration = 1.7 秒，0.8× 实际听了 2.125 秒。
    act(() => vi.advanceTimersByTime(2124));
    expect(media.plays).toBe(1);
    act(() => vi.advanceTimersByTime(1));
    expect(media.plays).toBe(2);
  });
});

describe("hotkeys", () => {
  it("maps every documented key to its player action", async () => {
    renderPractice();
    await ready();

    key(" ");
    expect(playButton()).toHaveTextContent("暂停");
    key(" ");
    expect(playButton()).toHaveTextContent("播放");

    key("ArrowLeft");
    expect(heading()).toBe("第 1 / 3 句");
    key("ArrowRight");
    key("ArrowRight");
    key("ArrowRight");
    expect(heading()).toBe("第 3 / 3 句");
    key("ArrowLeft");
    expect(heading()).toBe("第 2 / 3 句");

    key("l");
    key("L");
    expect(screen.getByLabelText("循环")).toHaveValue("3");

    key("]");
    key("]");
    expect(screen.getByLabelText("语速")).toHaveValue("1.1");
    key("[");
    expect(screen.getByLabelText("语速")).toHaveValue("1.05");

    key("a");
    expect(screen.getByLabelText("自动下一句")).toBeChecked();
  });

  it("ignores keys while typing in text inputs and leaves modifier shortcuts to the browser", async () => {
    renderPractice();
    await ready();
    const search = screen.getByLabelText("搜索句子");

    key(" ", search);
    key("ArrowRight", search);
    key("a", search);
    key("r", document.body, { ctrlKey: true });

    expect(playButton()).toHaveTextContent("播放");
    expect(heading()).toBe("第 1 / 3 句");
    expect(screen.getByLabelText("自动下一句")).not.toBeChecked();
    expect(media.plays).toBe(0);
    // 搜索框里的 Escape 交给浏览器清空，快捷键不拦截。
    expect(fireEvent.keyDown(search, { key: "Escape" })).toBe(true);
  });

  it("keeps player keys working on checkboxes and selects except the keys they own", async () => {
    renderPractice();
    await ready();
    const autoAdvance = screen.getByLabelText("自动下一句");
    const rate = screen.getByLabelText("语速");

    key(" ", autoAdvance);
    expect(playButton()).toHaveTextContent("播放");
    key("ArrowRight", autoAdvance);
    expect(heading()).toBe("第 2 / 3 句");

    key("ArrowLeft", rate);
    expect(heading()).toBe("第 2 / 3 句");
    key("]", rate);
    expect(rate).toHaveValue("1.05");
  });

  it("leaves Space on a focused button to the button itself", async () => {
    renderPractice();
    await ready();

    key(" ", screen.getByRole("button", { name: "下一句" }));

    expect(playButton()).toHaveTextContent("播放");
  });

  it("pauses every player key while a dialog is open", async () => {
    const user = userEvent.setup();
    renderPractice();
    await ready();
    await user.click(screen.getByRole("button", { name: "重新切分" }));

    key("ArrowRight");
    key(" ");

    expect(heading()).toBe("第 1 / 3 句");
    expect(media.plays).toBe(0);
  });

  it("confirms setting changes made by hotkeys with a toast", async () => {
    renderPractice();
    await ready();

    key("l");
    expect(await screen.findByText("循环：每句 2 遍")).toBeInTheDocument();
    key("[");
    expect(await screen.findByText("语速 0.95×")).toBeInTheDocument();
    key("a");
    expect(await screen.findByText("自动下一句：开")).toBeInTheDocument();
  });

  it("pauses player keys while the hotkey panel is open", async () => {
    const user = userEvent.setup();
    renderPractice();
    await ready();
    await user.click(screen.getByRole("button", { name: "快捷键" }));

    key("ArrowRight");

    expect(heading()).toBe("第 1 / 3 句");
  });

  it("labels icon-only transport buttons and shows their hotkeys on hover", async () => {
    renderPractice();
    await ready();

    for (const [name, hint] of [
      ["上一句", "←"],
      ["播放", "空格"],
      ["重听", "R"],
      ["下一句", "→"]
    ]) {
      expect(screen.getByRole("button", { name })).toHaveAttribute("title", `${name}（${hint}）`);
    }
    expect(screen.getByRole("button", { name: "显示原文" })).toHaveAttribute(
      "aria-pressed",
      "false"
    );
  });
});

describe("sentence reel", () => {
  it("scrolls only the list, never the page, to keep the current row visible", async () => {
    // jsdom 不做布局：清单可见区设为 100–200px，当前行放在可见区下方 250–280px。
    const rect = (top: number, bottom: number) =>
      ({ top, bottom, left: 0, right: 0, width: 0, height: bottom - top, x: 0, y: top }) as DOMRect;
    const rects = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockImplementation(function (this: HTMLElement) {
        if (this.tagName === "OL") return rect(100, 200);
        if (this.getAttribute("aria-current") === "true") return rect(250, 280);
        return rect(0, 0);
      });
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView
    });
    try {
      renderPractice();
      await ready();
      const list = screen.getByRole("list");
      list.scrollTop = 0;

      key("ArrowRight");

      expect(list.scrollTop).toBe(80);
      expect(scrollIntoView).not.toHaveBeenCalled();
    } finally {
      rects.mockRestore();
      delete (HTMLElement.prototype as { scrollIntoView?: unknown }).scrollIntoView;
    }
  });

  it("blurs the list while the current sentence is veiled and lets search reveal matches", async () => {
    const user = userEvent.setup();
    renderPractice();
    await ready();
    // 盲听时列表原文模糊并对读屏隐藏，行的读屏名称只剩序号与时间。
    expect(screen.getByText("How are you?")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByRole("button", { name: /^第 2 句\s*00:03$/ })).toBeInTheDocument();

    await user.type(screen.getByLabelText("搜索句子"), "how");

    expect(screen.getByText("找到 1 句")).toBeInTheDocument();
    const item = screen.getByRole("button", { name: /^第 2 句/ });
    expect(within(item).getByText("How are you?")).not.toHaveAttribute("aria-hidden");
    await user.click(item);
    expect(item).toHaveAttribute("aria-current", "true");
    expect(item).toHaveTextContent("已练");
  });

  it("shows every sentence once the current one is revealed", async () => {
    renderPractice();
    await ready();

    key("Enter");

    expect(screen.getByText("How are you?")).not.toHaveAttribute("aria-hidden");
    expect(screen.getByText("已练 0 / 3")).toBeInTheDocument();
  });
});

describe("resegment and export", () => {
  it("sends only filled overrides, replaces the cached result and resets the player", async () => {
    const user = userEvent.setup();
    renderPractice();
    await ready();
    // 先听完第 1 句，让「听了 N 次」在重置前为 1。
    fireEvent.click(playButton());
    playTo(2.0);
    expect(document.querySelector("[data-readout='listens']")).toHaveTextContent("听了 1 次");
    key("ArrowRight");
    const jobRequests = state.requests.job;

    const trigger = screen.getByRole("button", { name: "重新切分" });
    await user.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "重新切分" });
    expect(within(dialog).getByLabelText("最短句长（秒）")).toHaveFocus();
    const apply = within(dialog).getByRole("button", { name: "应用" });
    expect(apply).toBeDisabled();

    await user.type(within(dialog).getByLabelText("最长句长（秒）"), "100");
    expect(within(dialog).getByRole("alert")).toHaveTextContent("最长句长需在 2 到 60 秒之间。");
    expect(apply).toBeDisabled();
    await user.clear(within(dialog).getByLabelText("最长句长（秒）"));
    await user.type(within(dialog).getByLabelText("最长句长（秒）"), "2");
    await user.click(apply);

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(state.requests.resegment).toEqual([{ maxDuration: 2 }]);
    expect(await screen.findByText("重新切分完成，共 4 句")).toBeInTheDocument();
    expect(heading()).toBe("第 1 / 4 句");
    expect(screen.getByText("已练 0 / 4")).toBeInTheDocument();
    expect(document.querySelector("[data-readout='listens']")).toHaveTextContent("听了 0 次");
    // 新结果直接写入缓存，不再请求 result；Job 的句子数交给服务端刷新。
    expect(state.requests.result).toBe(1);
    await waitFor(() => expect(state.requests.job).toBeGreaterThan(jobRequests));
    expect(trigger).toHaveFocus();
  });

  it("shows the server problem when words are not available", async () => {
    state.resegmentError = {
      status: 400,
      code: "WORDS_NOT_AVAILABLE",
      detail: "结果中没有词级时间戳。"
    };
    const user = userEvent.setup();
    renderPractice();
    await ready();

    await user.click(screen.getByRole("button", { name: "重新切分" }));
    await user.type(screen.getByLabelText("强制断句停顿（秒）"), "1");
    await user.click(screen.getByRole("button", { name: "应用" }));

    expect(await within(screen.getByRole("dialog")).findByRole("alert")).toHaveTextContent(
      "结果中没有词级时间戳。"
    );
    expect(heading()).toBe("第 1 / 3 句");
  });

  it("closes with Escape, returns focus, and blocks player hotkeys while open", async () => {
    const user = userEvent.setup();
    renderPractice();
    await ready();
    const trigger = screen.getByRole("button", { name: "重新切分" });
    await user.click(trigger);

    key("ArrowRight");
    expect(heading()).toBe("第 1 / 3 句");

    key("Escape", screen.getByLabelText("最短句长（秒）"));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("links every export through the API URL helpers", async () => {
    renderPractice();
    await ready();
    const exports = within(screen.getByRole("navigation", { name: "导出" }));

    expect(exports.getByRole("link", { name: "下载 SRT" })).toHaveAttribute(
      "href",
      `/api/v1/jobs/${JOB_ID}/subtitles.srt`
    );
    expect(exports.getByRole("link", { name: "下载 VTT" })).toHaveAttribute(
      "href",
      `/api/v1/jobs/${JOB_ID}/subtitles.vtt`
    );
    expect(exports.getByRole("link", { name: "下载文本" })).toHaveAttribute(
      "href",
      `/api/v1/jobs/${JOB_ID}/subtitles.txt`
    );
    expect(exports.getByRole("link", { name: /学习包 ZIP/ })).toHaveAttribute(
      "href",
      `/api/v1/jobs/${JOB_ID}/bundle.zip?clips=true`
    );
  });
});
