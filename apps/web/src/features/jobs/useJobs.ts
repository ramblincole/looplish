import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api } from "../../api/client";
import type { CreateJobRequest, Job, JobPage } from "../../api/types";

export const ACTIVE_POLL_MS = 1000;
export const HIDDEN_POLL_MS = 5000;
export const MAX_BACKOFF_MS = 30_000;

export function isActive(status: Job["status"]): boolean {
  return status === "queued" || status === "running";
}

export function pollInterval(
  data: JobPage | undefined,
  failures: number,
  hidden: boolean
): number | false {
  // 只有仍在处理的任务才需要轮询；全部进入终态后立即停表。
  if (!data?.items.some((job) => isActive(job.status))) return false;
  // 后台标签降低请求频率，回到前台时由 refetchOnWindowFocus 主动刷新。
  const base = hidden ? HIDDEN_POLL_MS : ACTIVE_POLL_MS;
  // 连续失败时按指数退避放慢轮询，恢复成功后 failures 归零。
  return Math.min(MAX_BACKOFF_MS, base * 2 ** failures);
}

export function useJobs() {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["jobs"],
    queryFn: ({ signal }) => api.listJobs(signal),
    refetchInterval: (current) =>
      pollInterval(
        current.state.data,
        current.state.fetchFailureCount,
        document.visibilityState === "hidden"
      ),
    // 默认页面隐藏时会完全停止轮询；这里保留低频轮询，间隔由 pollInterval 决定。
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true
  });

  // 任务从进行中进入终态时，让它的详情与结果缓存失效，练习台下次读取拿到最新数据。
  const previous = useRef(new Map<string, Job["status"]>());
  useEffect(() => {
    if (!query.data) return;
    for (const job of query.data.items) {
      const before = previous.current.get(job.id);
      if (before !== undefined && isActive(before) && !isActive(job.status)) {
        void client.invalidateQueries({ queryKey: ["job", job.id] });
        void client.invalidateQueries({ queryKey: ["jobResult", job.id] });
      }
      previous.current.set(job.id, job.status);
    }
  }, [query.data, client]);

  return query;
}

export function useRuntimeConfig() {
  return useQuery({ queryKey: ["runtimeConfig"], queryFn: api.getConfig, staleTime: Infinity });
}

export function useCreateJob() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateJobRequest) => api.createJob(body),
    // 重新读取服务端任务，避免在客户端拼装字段不完整的 Job。
    onSuccess: () => client.invalidateQueries({ queryKey: ["jobs"] })
  });
}

export function useUploadJob() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (form: FormData) => api.uploadJob(form),
    onSuccess: () => client.invalidateQueries({ queryKey: ["jobs"] })
  });
}

export function useDeleteJob() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.deleteJob,
    onSuccess: (_, jobId) => {
      // 已删除任务的详情与结果不再有效，直接移出缓存。
      client.removeQueries({ queryKey: ["job", jobId] });
      client.removeQueries({ queryKey: ["jobResult", jobId] });
      return client.invalidateQueries({ queryKey: ["jobs"] });
    }
  });
}
