import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import type { Job, JobResult } from "../api/types";
import { useToast } from "../components/Toast/toastContext";
import { errorMessage } from "../features/intake/processing";
import { isActive, useJob, useJobResult } from "../features/jobs/useJobs";
import { ExportMenu } from "../features/practice/ExportMenu";
import { PlayerProvider } from "../features/practice/PlayerProvider";
import { PracticeControls } from "../features/practice/PracticeControls";
import { ResegmentDialog } from "../features/practice/ResegmentDialog";
import { SentenceReel } from "../features/practice/SentenceReel";
import { VeiledTranscript } from "../features/practice/VeiledTranscript";
import { usePlayer, usePlayerActions } from "../features/practice/playerContext";
import { formatRate, formatRepeat } from "../features/practice/playerLabels";
import { clampRate, nextRepeat, stepRate } from "../features/practice/playerReducer";
import { useAudioController } from "../features/practice/useAudioController";
import { useHotkeys } from "../features/practice/useHotkeys";

const STAGE_LABELS: Record<NonNullable<Job["stage"]>, string> = {
  downloading: "下载",
  preparingAudio: "准备音频",
  transcribing: "转写",
  segmenting: "切句"
};

function BackLink() {
  return (
    <Link to="/" className="back-link">
      ← 返回素材库
    </Link>
  );
}

export function PracticePage() {
  const { jobId = "" } = useParams();
  return (
    <main className="practice">
      {jobId ? <PracticeLoader jobId={jobId} /> : <p role="alert">缺少任务编号。</p>}
    </main>
  );
}

function PracticeLoader({ jobId }: { jobId: string }) {
  const job = useJob(jobId);
  const succeeded = job.data?.status === "succeeded";
  // 结果只在任务成功后请求，避免处理中反复得到 409。
  const result = useJobResult(jobId, succeeded);

  // 只有从没拿到过任务时才显示错误页。已有数据时后台刷新失败（窗口聚焦、重新切句后的刷新）
  // 也会让查询进入 error 状态，此时继续用上次的数据，不能卸载正在练习的播放器。
  const current = job.data;
  if (current === undefined) {
    if (!job.isError) return <p role="status">正在加载任务…</p>;
    return (
      <>
        <BackLink />
        <p role="alert">{errorMessage(job.error)}</p>
      </>
    );
  }
  if (isActive(current.status)) {
    const percent = Math.round(Math.min(1, Math.max(0, current.progress)) * 100);
    return (
      <>
        <BackLink />
        <h1>{current.title}</h1>
        <p role="status">
          {current.status === "queued" ? "排队中" : "处理中"}
          {current.stage ? `（${STAGE_LABELS[current.stage]}）` : null}：{current.message}
        </p>
        <progress
          max={1}
          value={current.progress}
          aria-label="处理进度"
          aria-valuetext={`${percent}%`}
        />
      </>
    );
  }
  if (current.status === "failed") {
    return (
      <>
        <BackLink />
        <h1>{current.title}</h1>
        <p role="alert">处理失败：{current.error?.detail ?? current.message}</p>
      </>
    );
  }

  const data = result.data;
  if (data === undefined) {
    if (!result.isError) return <p role="status">正在加载句子…</p>;
    return (
      <>
        <BackLink />
        <p role="alert">{errorMessage(result.error)}</p>
      </>
    );
  }
  if (data.sentences.length === 0) {
    // 空结果不能进入播放器，否则会索引不存在的 sentences[0]。
    return (
      <>
        <BackLink />
        <h1>{data.title}</h1>
        <p role="status">未找到可练习句段。</p>
      </>
    );
  }

  // 提示与播放器的位置固定，提示出现或消失都不会让播放器重新挂载、丢失练习进度。
  return (
    <>
      {job.isError || result.isError ? (
        <p role="status" className="stale-notice">
          暂时无法从服务刷新任务状态，页面显示的是上次加载的内容。
        </p>
      ) : null}
      <PlayerProvider result={data}>
        <PracticeWorkspace result={data} />
      </PlayerProvider>
    </>
  );
}

function PracticeWorkspace({ result }: { result: JobResult }) {
  const { state, sentenceCount, send, completed, playhead } = usePlayer();
  const actions = usePlayerActions();
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [playbackError, setPlaybackError] = useState<string | null>(null);
  const [resegmentOpen, setResegmentOpen] = useState(false);
  const sentence = result.sentences[state.sentenceIndex];

  const onPlaybackError = useCallback(() => {
    // 播放被拒（如浏览器自动播放策略）不是句子完成：回到暂停并提示用户手动重试。
    send({ type: "setPlaying", value: false });
    setPlaybackError("浏览器拒绝了播放，请点击「播放」按钮重试。");
  }, [send]);

  useEffect(() => {
    // 用户再次开始播放即视为重试，旧的错误提示不再适用；若再次失败会重新显示。
    if (state.playing) setPlaybackError(null);
  }, [state.playing]);

  useAudioController(audioRef, sentence, state, playhead, completed, onPlaybackError);

  const notify = useToast();
  // 快捷键改设置时看不到控件变化，用 toast 告知新值。新值按当前已提交状态推算，
  // 与 reducer 的计算一致；同一帧内连按多次时提示文字可能落后一次，设置本身不受影响。
  useHotkeys({
    ...actions,
    cycleRepeat: () => {
      actions.cycleRepeat();
      notify(`循环：${formatRepeat(nextRepeat(state.repeat))}`);
    },
    slower: () => {
      actions.slower();
      notify(`语速 ${formatRate(clampRate(stepRate(state.rate, -1)))}`);
    },
    faster: () => {
      actions.faster();
      notify(`语速 ${formatRate(clampRate(stepRate(state.rate, 1)))}`);
    },
    toggleAutoAdvance: () => {
      actions.toggleAutoAdvance();
      notify(`自动下一句：${state.autoAdvance ? "关" : "开"}`);
    }
  });

  return (
    <>
      <header className="practice-header">
        <BackLink />
        <h1>{result.title}</h1>
        {result.uploader ? <p className="uploader">{result.uploader}</p> : null}
        <div className="toolbar">
          <ResegmentDialog
            jobId={result.jobId}
            open={resegmentOpen}
            onOpenChange={setResegmentOpen}
          />
          <ExportMenu jobId={result.jobId} />
        </div>
      </header>
      <div className="workspace">
        <SentenceReel sentences={result.sentences} />
        <section className="stage" aria-labelledby="current-sentence-title">
          <h2 id="current-sentence-title">
            第 {state.sentenceIndex + 1} / {sentenceCount} 句
          </h2>
          {sentence ? <VeiledTranscript sentence={sentence} revealed={state.revealed} /> : null}
          <button
            type="button"
            className="secondary"
            onClick={actions.toggleReveal}
            aria-pressed={state.revealed}
            aria-keyshortcuts="Enter"
          >
            {state.revealed ? "隐藏文本" : "显示文本"}
          </button>
          {playbackError ? <p role="alert">{playbackError}</p> : null}
          <PracticeControls />
          <audio
            ref={audioRef}
            src={result.audioUrl}
            preload="auto"
            onError={() => setPlaybackError("音频加载失败，请刷新页面或稍后重试。")}
          />
        </section>
      </div>
    </>
  );
}
