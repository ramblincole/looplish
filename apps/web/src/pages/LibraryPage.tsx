import { useEffect, useRef, useState } from "react";
import { IntakeCard } from "../features/intake/IntakeCard";
import { initialValues, validate, type ProcessingValues } from "../features/intake/processing";
import { JobList } from "../features/jobs/JobList";
import { useJobs, useRuntimeConfig } from "../features/jobs/useJobs";

export function LibraryPage() {
  const config = useRuntimeConfig();
  const jobs = useJobs();
  const [options, setOptions] = useState<ProcessingValues | null>(null);
  const jobsHeading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    // 只在首次拿到配置时初始化，后台刷新不得覆盖用户正在编辑的参数。
    if (!config.data || options !== null) return;
    setOptions(initialValues(config.data));
  }, [config.data, options]);

  if (config.isError) return <p role="alert">无法读取运行配置，请确认服务已启动后刷新页面。</p>;
  // options 为 null 时不允许提交，避免用硬编码默认值抢跑配置请求。
  if (config.isPending || options === null) return <p role="status">正在加载运行配置…</p>;

  const issues = validate(options);

  return (
    <main className="library">
      <IntakeCard
        config={config.data}
        options={options}
        issues={issues}
        onOptionsChange={setOptions}
        onCreated={() => {}}
      />
      <section aria-labelledby="jobs-title">
        <h2 id="jobs-title" ref={jobsHeading} tabIndex={-1}>
          已处理的素材
        </h2>
        {jobs.isPending ? <p role="status">正在加载…</p> : null}
        {/* 只保留一条持续显示的提示；重试与退避由查询层负责，不反复弹出。 */}
        {jobs.isError ? (
          <p role="alert">
            {jobs.data ? "与服务的连接中断，正在重试…" : "暂时无法加载任务，请稍后刷新。"}
          </p>
        ) : null}
        {jobs.data ? (
          <JobList jobs={jobs.data.items} onDeleted={() => jobsHeading.current?.focus()} />
        ) : null}
      </section>
    </main>
  );
}
