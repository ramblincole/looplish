import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TOAST_DURATION_MS, useToast, type ToastKind } from "./toastContext";
import { ToastProvider } from "./ToastProvider";

function Trigger({ message, kind }: { message: string; kind?: ToastKind }) {
  const notify = useToast();
  return <button onClick={() => notify(message, kind)}>{`发出：${message}`}</button>;
}

function renderToasts() {
  render(
    <ToastProvider>
      <Trigger message="循环：每句 3 遍" />
      <Trigger message="语速 0.90×" />
      <Trigger message="重新切分失败" kind="error" />
    </ToastProvider>
  );
}

const fire = (message: string) =>
  fireEvent.click(screen.getByRole("button", { name: `发出：${message}` }));
const liveness = (message: string) =>
  screen.getByText(message).closest("[aria-live]")?.getAttribute("aria-live");

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("Toast", () => {
  it("announces info politely and hides it after the info duration", () => {
    renderToasts();
    fire("循环：每句 3 遍");

    expect(liveness("循环：每句 3 遍")).toBe("polite");
    act(() => vi.advanceTimersByTime(TOAST_DURATION_MS.info - 1));
    expect(screen.getByText("循环：每句 3 遍")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(1));
    expect(screen.queryByText("循环：每句 3 遍")).not.toBeInTheDocument();
  });

  it("announces errors assertively and keeps them longer", () => {
    renderToasts();
    fire("重新切分失败");

    expect(liveness("重新切分失败")).toBe("assertive");
    act(() => vi.advanceTimersByTime(TOAST_DURATION_MS.info));
    expect(screen.getByText("重新切分失败")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(TOAST_DURATION_MS.error - TOAST_DURATION_MS.info));
    expect(screen.queryByText("重新切分失败")).not.toBeInTheDocument();
  });

  it("shows one toast at a time and restarts the timer for the newest", () => {
    renderToasts();
    fire("循环：每句 3 遍");
    act(() => vi.advanceTimersByTime(2000));
    fire("语速 0.90×");

    expect(screen.queryByText("循环：每句 3 遍")).not.toBeInTheDocument();
    act(() => vi.advanceTimersByTime(2000));
    expect(screen.getByText("语速 0.90×")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(1000));
    expect(screen.queryByText("语速 0.90×")).not.toBeInTheDocument();
  });
});
