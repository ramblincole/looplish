import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Modal } from "./Modal";
import { ModalProvider } from "./ModalProvider";
import { useModalOpen } from "./modalRegistry";

function Probe() {
  return <p data-testid="probe">{useModalOpen() ? "open" : "closed"}</p>;
}

function Harness({ onClose = () => {} }: { onClose?: () => void }) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  return (
    <ModalProvider>
      <button ref={trigger} onClick={() => setOpen(true)}>
        打开设置
      </button>
      <Probe />
      <Modal
        open={open}
        title="设置"
        returnFocusTo={trigger}
        onClose={() => {
          onClose();
          setOpen(false);
        }}
      >
        <input aria-label="第一项" />
        <button>确定</button>
      </Modal>
    </ModalProvider>
  );
}

describe("Modal", () => {
  it("renders nothing while closed", () => {
    render(<Harness />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByTestId("probe")).toHaveTextContent("closed");
  });

  it("is a labelled modal dialog that takes focus and reports itself open", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "打开设置" }));

    const dialog = screen.getByRole("dialog", { name: "设置" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByLabelText("第一项")).toHaveFocus();
    expect(screen.getByTestId("probe")).toHaveTextContent("open");
  });

  it("keeps Tab inside the dialog in both directions", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "打开设置" }));

    await user.tab();
    expect(screen.getByRole("button", { name: "确定" })).toHaveFocus();
    await user.tab();
    expect(screen.getByLabelText("第一项")).toHaveFocus();
    await user.tab({ shift: true });
    expect(screen.getByRole("button", { name: "确定" })).toHaveFocus();
  });

  it("closes on Escape, stops the key there and returns focus to the trigger", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const outside = vi.fn();
    window.addEventListener("keydown", outside);
    render(<Harness onClose={onClose} />);
    const trigger = screen.getByRole("button", { name: "打开设置" });
    await user.click(trigger);

    act(() => {
      fireEvent.keyDown(screen.getByLabelText("第一项"), { key: "Escape" });
    });

    window.removeEventListener("keydown", outside);
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(outside).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(screen.getByTestId("probe")).toHaveTextContent("closed");
  });
});
