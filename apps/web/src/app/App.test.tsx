import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "./App";

describe("App", () => {
  it("renders the product identity", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "Looplish" })).toBeInTheDocument();
    expect(screen.getByText("Listen. Loop. Learn.")).toBeInTheDocument();
  });
});
