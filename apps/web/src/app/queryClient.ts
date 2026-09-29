import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    // 短暂缓存可吸收同一页面内的重复读取；失败时按指数退避有限重试。
    // mutation 不自动重试，避免重复创建或删除。
    queries: { retry: 2, staleTime: 500 },
    mutations: { retry: false }
  }
});
