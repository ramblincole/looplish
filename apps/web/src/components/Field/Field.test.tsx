import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Field, ToggleField } from "./Field";
import { RangeField } from "./RangeField";

describe("Field", () => {
  it("labels the wrapped control", () => {
    render(
      <Field label="语言">
        <input />
      </Field>
    );
    expect(screen.getByLabelText("语言")).toBeInstanceOf(HTMLInputElement);
  });
});

describe("ToggleField", () => {
  it("is a labelled checkbox", () => {
    const onChange = vi.fn();
    render(<ToggleField label="自动下一句" checked={false} onChange={onChange} />);
    fireEvent.click(screen.getByLabelText("自动下一句"));
    expect(screen.getByRole("checkbox", { name: "自动下一句" })).toBeInTheDocument();
    expect(onChange).toHaveBeenCalledTimes(1);
  });
});

describe("RangeField", () => {
  it("shows the formatted value and reports numbers on change", () => {
    const onChange = vi.fn();
    render(
      <RangeField
        label="最短句"
        value={1}
        min={0.2}
        max={10}
        step={0.1}
        unit="s"
        format={(value) => value.toFixed(1)}
        onChange={onChange}
      />
    );
    const slider = screen.getByRole("slider", { name: "最短句" });
    expect(slider).toHaveAttribute("aria-valuetext", "1.0s");
    expect(screen.getByText("1.0s")).toBeInTheDocument();

    fireEvent.change(slider, { target: { value: "1.5" } });
    expect(onChange).toHaveBeenCalledWith(1.5);
  });

  it("marks an invalid value for assistive technology", () => {
    render(
      <RangeField label="最长句" value={1} min={2} max={60} step={1} invalid onChange={() => {}} />
    );
    expect(screen.getByRole("slider", { name: "最长句" })).toHaveAttribute("aria-invalid", "true");
  });

  it("renders no status role so the readout does not announce separately", () => {
    render(
      <RangeField
        label="最短句"
        value={1}
        min={0.2}
        max={10}
        step={0.1}
        unit="s"
        format={(value) => value.toFixed(1)}
        onChange={() => {}}
      />
    );
    expect(screen.getByText("1.0s")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
