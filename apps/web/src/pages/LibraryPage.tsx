import { useEffect, useId, useRef, useState } from "react";
import type { Job } from "../api/types";
import { useToast } from "../components/Toast/toastContext";
import { IntakeCard } from "../features/intake/IntakeCard";
import { initialValues, validate, type ProcessingValues } from "../features/intake/processing";
import { JobList } from "../features/jobs/JobList";
import { ProgressOverlay } from "../features/jobs/ProgressOverlay";
import { useJobs, useRuntimeConfig } from "../features/jobs/useJobs";
import styles from "./LibraryPage.module.css";

export function LibraryPage() {
  const config = useRuntimeConfig();
  const notify = useToast();
  const headingId = useId();
  const jobsHeading = useRef<HTMLHeadingElement>(null);
  const [options, setOptions] = useState<ProcessingValues | null>(null);
  // 浮层跟踪的任务：保存提交接口返回的版本，列表刷新到它之前先用这份数据。
  const [tracked, setTracked] = useState<Job | null>(null);
  const trackedId = useRef<string | null>(null);
  useEffect(() => {
    trackedId.current = tracked?.id ?? null;
  });

  const jobs = useJobs({
    onFinished: (job) => {
      // 浮层正在展示的任务由浮层自己说明结果，不重复提示。
      if (job.id === trackedId.current) return;
      if (job.status === "succeeded") notify(`「${job.title}」处理完成`);
      else notify(`「${job.title}」处理失败`, "error");
    }
  });

  useEffect(() => {
    // 只在首次拿到配置时初始化，后台刷新不得覆盖用户正在编辑的参数。
    if (!config.data || options !== null) return;
    setOptions(initialValues(config.data));
  }, [config.data, options]);

  if (config.isError) {
    return (
      <main className={styles.page}>
        <p role="alert" className={styles.note}>
          无法读取运行配置，请确认服务已启动后刷新页面。
        </p>
      </main>
    );
  }
  // options 为 null 时不允许提交，避免用硬编码默认值抢跑配置请求。
  if (config.isPending || options === null) {
    return (
      <main className={styles.page}>
        <p role="status" className={styles.note}>
          正在加载运行配置…
        </p>
      </main>
    );
  }

  const live = tracked
    ? (jobs.data?.items.find((item) => item.id === tracked.id) ?? tracked)
    : null;

  return (
    <main className={styles.page}>
      <IntakeCard
        config={config.data}
        options={options}
        issues={validate(options)}
        onOptionsChange={setOptions}
        onCreated={setTracked}
      />
      <section className={styles.library} aria-labelledby={headingId}>
        <h2 id={headingId} ref={jobsHeading} tabIndex={-1} className={styles.sectionLabel}>
          已处理的素材
        </h2>
        {jobs.isPending ? (
          <p role="status" className={styles.note}>
            正在加载…
          </p>
        ) : null}
        {/* 只保留一条持续显示的提示；重试与退避由查询层负责，不反复弹出。 */}
        {jobs.isError ? (
          <p role="alert" className={styles.note}>
            {jobs.data ? "与服务的连接中断，正在重试…" : "暂时无法加载任务，请稍后刷新。"}
          </p>
        ) : null}
        {jobs.data ? (
          <JobList jobs={jobs.data.items} onDeleted={() => jobsHeading.current?.focus()} />
        ) : null}
      </section>
      <ProgressOverlay job={live} onClose={() => setTracked(null)} />
    </main>
  );
}
