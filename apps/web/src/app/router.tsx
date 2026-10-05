import { createBrowserRouter, type RouteObject } from "react-router";
import { LibraryPage } from "../pages/LibraryPage";
import { AppShell } from "./AppShell/AppShell";

// 路由表单独导出，测试可用内存路由复用同一份定义。
export const routes: RouteObject[] = [
  {
    // 无路径的布局路由：两个页面都渲染在外壳的 <Outlet /> 中。
    element: <AppShell />,
    children: [
      { path: "/", element: <LibraryPage /> },
      {
        path: "/jobs/:jobId",
        // 练习台代码只在进入任务详情时下载，素材库首屏无需承担其体积。
        lazy: async () => {
          const module = await import("../pages/PracticePage");
          return { Component: module.PracticePage };
        }
      }
    ]
  }
];

export function createAppRouter() {
  return createBrowserRouter(routes);
}
