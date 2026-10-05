import { fireEvent, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { describe, expect, it, vi } from "vitest";
import { Button, ButtonLink } from "./Button";

describe("Button", () => {
  it("defaults to type=button so it never submits a surrounding form by accident", () => {
    render(<Button>播放</Button>);
    expect(screen.getByRole("button", { name: "播放" })).toHaveAttribute("type", "button");
  });

  it("keeps an explicit submit type, forwards the ref and click handler", () => {
    const ref = createRef<HTMLButtonElement>();
    const onClick = vi.fn();
    render(
      <Button ref={ref} type="submit" variant="primary" onClick={onClick}>
        开始切分
      </Button>
    );
    const button = screen.getByRole("button", { name: "开始切分" });
    fireEvent.click(button);
    expect(button).toHaveAttribute("type", "submit");
    expect(ref.current).toBe(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("does not fire clicks while disabled", () => {
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        删除
      </Button>
    );
    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe("ButtonLink", () => {
  it("renders a real link with the button look", () => {
    render(
      <ButtonLink href="/api/v1/jobs/a/subtitles.srt" download>
        下载 SRT
      </ButtonLink>
    );
    const link = screen.getByRole("link", { name: "下载 SRT" });
    expect(link).toHaveAttribute("href", "/api/v1/jobs/a/subtitles.srt");
    expect(link).toHaveAttribute("download");
  });
});
