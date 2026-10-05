import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vitest";
import { HOTKEY_BINDINGS } from "../../features/practice/hotkeys";
import { AppShell } from "./AppShell";

function renderShell() {
  const router = createMemoryRouter(
    [{ element: <AppShell />, children: [{ path: "/", element: <p>页面内容</p> }] }],
    { initialEntries: ["/"] }
  );
  render(<RouterProvider router={router} />);
}

describe("AppShell", () => {
  it("renders the brand, the navigation and the page", () => {
    renderShell();
    const banner = screen.getByRole("banner");
    expect(within(banner).getByText("Looplish")).toBeInTheDocument();
    const nav = within(banner).getByRole("navigation", { name: "主导航" });
    expect(within(nav).getByRole("link", { name: "素材库" })).toHaveAttribute("href", "/");
    expect(screen.getByText("页面内容")).toBeInTheDocument();
  });

  it("lists every hotkey from the shared table and returns focus when closed", async () => {
    const user = userEvent.setup();
    renderShell();
    const trigger = screen.getByRole("button", { name: "快捷键" });

    await user.click(trigger);

    const panel = screen.getByRole("dialog", { name: "快捷键" });
    for (const binding of HOTKEY_BINDINGS) {
      expect(within(panel).getByText(binding.description)).toBeInTheDocument();
    }
    expect(within(panel).getByText("关闭弹层")).toBeInTheDocument();

    await user.click(within(panel).getByRole("button", { name: "知道了" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});
