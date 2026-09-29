import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// 未开启 vitest globals 时 Testing Library 不会自动卸载，这里显式清理，避免测试间互相残留 DOM。
afterEach(() => {
  cleanup();
});
