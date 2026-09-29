import { createBrowserRouter, type RouteObject } from "react-router";
import { LibraryPage } from "../pages/LibraryPage";

// 路由表单独导出，测试可用内存路由复用同一份定义。
export const routes: RouteObject[] = [
  { path: "/", element: <LibraryPage /> },
  {
    path: "/jobs/:jobId",
    // 练习台代码只在进入任务详情时下载，素材库首屏无需承担其体积。
    lazy: async () => {
      const module = await import("../pages/PracticePage");
      return { Component: module.PracticePage };
    }
  }
];

export function createAppRouter() {
  return createBrowserRouter(routes);
}
