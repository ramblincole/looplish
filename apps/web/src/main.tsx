import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router/dom";
import { queryClient } from "./app/queryClient";
import { createAppRouter } from "./app/router";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles.css";

const root = document.getElementById("root");
// HTML 入口缺少挂载点时立即失败，避免静默渲染空白页。
if (root === null) {
  throw new Error("Missing #root element");
}
createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={createAppRouter()} />
    </QueryClientProvider>
  </StrictMode>
);
