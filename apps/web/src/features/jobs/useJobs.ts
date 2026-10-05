import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { ApiProblem, api } from "../../api/client";
import type { CreateJobRequest, Job, JobPage, ResegmentRequest } from "../../api/types";

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
  return backoffInterval(failures, hidden);
}

export function jobPollInterval(
  job: Job | undefined,
  failures: number,
  hidden: boolean
): number | false {
  // 单个任务的轮询规则与列表一致：只在排队或处理中时刷新。
  if (!job || !isActive(job.status)) return false;
  return backoffInterval(failures, hidden);
}

function backoffInterval(failures: number, hidden: boolean): number {
  // 后台标签降低请求频率，回到前台时由 refetchOnWindowFocus 主动刷新。
  const base = hidden ? HIDDEN_POLL_MS : ACTIVE_POLL_MS;
  // 连续失败时按指数退避放慢轮询，恢复成功后 failures 归零。
  return Math.min(MAX_BACKOFF_MS, base * 2 ** failures);
}

export function useJobs(options: { onFinished?: (job: Job) => void } = {}) {
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

  // 回调通过 ref 读取，调用方每次渲染传新函数也不会重跑下面的状态比较。
  const onFinished = useRef(options.onFinished);
  useEffect(() => {
    onFinished.current = options.onFinished;
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
        onFinished.current?.(job);
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

/** 4xx（任务不存在、结果尚未就绪等）重试也不会变好，立即展示；其余错误有限重试。 */
export function retryUnlessClientError(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiProblem && error.problem.status < 500) return false;
  return failureCount < 2;
}

export function useJob(jobId: string) {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["job", jobId],
    queryFn: ({ signal }) => api.getJob(jobId, signal),
    retry: retryUnlessClientError,
    refetchInterval: (current) =>
      jobPollInterval(
        current.state.data,
        current.state.fetchFailureCount,
        document.visibilityState === "hidden"
      ),
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true
  });

  // 任务在本页进入终态时，素材库列表中的状态与句子数也随之过期。
  const previous = useRef<Job["status"] | undefined>(undefined);
  const status = query.data?.status;
  useEffect(() => {
    if (status === undefined) return;
    if (previous.current !== undefined && isActive(previous.current) && !isActive(status)) {
      void client.invalidateQueries({ queryKey: ["jobs"] });
    }
    previous.current = status;
  }, [status, client]);

  return query;
}

export function useJobResult(jobId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["jobResult", jobId],
    queryFn: ({ signal }) => api.getResult(jobId, signal),
    retry: retryUnlessClientError,
    // 结果只在任务成功后存在；未完成时请求只会得到 409，因此由调用方按状态开启。
    enabled,
    // 结果只会因重新切句而改变，而那条路径会直接写入缓存，无需后台反复刷新。
    staleTime: Infinity
  });
}

export function useResegment(jobId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: ResegmentRequest) => api.resegment(jobId, body),
    onSuccess: (result) => {
      // 响应就是完整的新结果：直接写入缓存，避免练习台短暂显示旧句子。
      client.setQueryData(["jobResult", jobId], result);
      // 句子数与消息保存在 Job 上，交给服务端重新读取。
      void client.invalidateQueries({ queryKey: ["job", jobId] });
      void client.invalidateQueries({ queryKey: ["jobs"] });
    }
  });
}
