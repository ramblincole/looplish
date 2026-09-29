import { useEffect, useState } from "react";
import { ProcessingOptions } from "../features/intake/ProcessingOptions";
import { SourceForm } from "../features/intake/SourceForm";
import { UploadDropzone } from "../features/intake/UploadDropzone";
import { initialValues, validate, type ProcessingValues } from "../features/intake/processing";
import { JobList } from "../features/jobs/JobList";
import { useJobs, useRuntimeConfig } from "../features/jobs/useJobs";

export function LibraryPage() {
  const config = useRuntimeConfig();
  const jobs = useJobs();
  const [options, setOptions] = useState<ProcessingValues | null>(null);

  useEffect(() => {
    // 只在首次拿到配置时初始化，后台刷新不得覆盖用户正在编辑的参数。
    if (!config.data || options !== null) return;
    setOptions(initialValues(config.data));
  }, [config.data, options]);

  if (config.isError) return <p role="alert">无法读取运行配置，请确认服务已启动后刷新页面。</p>;
  // options 为 null 时不允许提交，避免用硬编码默认值抢跑配置请求。
  if (config.isPending || options === null) return <p role="status">正在加载运行配置…</p>;

  const issues = validate(options);
  const blocked = issues.length > 0;

  return (
    <main className="library">
      <header>
        <h1>Looplish</h1>
        <p>Listen. Loop. Learn.</p>
      </header>
      <section aria-labelledby="create-title">
        <h2 id="create-title">添加学习素材</h2>
        <ProcessingOptions
          value={options}
          onChange={setOptions}
          config={config.data}
          issues={issues}
        />
        <div className="intake">
          <SourceForm
            options={options}
            disabled={blocked}
            allowLocalPaths={config.data.allowLocalPaths}
          />
          <UploadDropzone options={options} disabled={blocked} />
        </div>
      </section>
      <section aria-labelledby="jobs-title">
        <h2 id="jobs-title">素材库</h2>
        {jobs.isPending ? <p role="status">正在加载…</p> : null}
        {/* 只保留一条持续显示的提示；重试与退避由查询层负责，不反复弹出。 */}
        {jobs.isError ? (
          <p role="alert">
            {jobs.data ? "与服务的连接中断，正在重试…" : "暂时无法加载任务，请稍后刷新。"}
          </p>
        ) : null}
        {jobs.data ? <JobList jobs={jobs.data.items} /> : null}
      </section>
    </main>
  );
}
