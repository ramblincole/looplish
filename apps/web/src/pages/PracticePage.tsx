import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router";
import type { JobResult } from "../api/types";
import { buttonClass } from "../components/Button/buttonClass";
import { ProgressBar } from "../components/ProgressBar/ProgressBar";
import { useToast } from "../components/Toast/toastContext";
import { errorMessage } from "../features/intake/processing";
import { statusText } from "../features/jobs/jobLabels";
import { isActive, useJob, useJobResult } from "../features/jobs/useJobs";
import { PlaybackSettings } from "../features/practice/PlaybackSettings";
import { PlayerProvider } from "../features/practice/PlayerProvider";
import { PracticeActions } from "../features/practice/PracticeActions";
import { Readout } from "../features/practice/Readout";
import { SentenceProgress } from "../features/practice/SentenceProgress";
import { SentenceReel } from "../features/practice/SentenceReel";
import { Transport } from "../features/practice/Transport";
import { VeiledSentence } from "../features/practice/VeiledSentence";
import { usePlayer, usePlayerActions } from "../features/practice/playerContext";
import { formatRate, formatRepeat } from "../features/practice/playerLabels";
import { clampRate, nextRepeat, stepRate } from "../features/practice/playerReducer";
import { useAudioController } from "../features/practice/useAudioController";
import { useHotkeys } from "../features/practice/useHotkeys";
import styles from "./PracticePage.module.css";

function BackLink() {
  return (
    <Link to="/" className={buttonClass("ghost")}>
      ← 素材库
    </Link>
  );
}

/** 排队、处理中、失败、空结果、任务不存在：都用同一种居中卡片。 */
function StateCard({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className={styles.stateCard}>
      <BackLink />
      {title ? <h1 className={styles.stateTitle}>{title}</h1> : null}
      {children}
    </section>
  );
}

export function PracticePage() {
  const { jobId = "" } = useParams();
  return (
    <main className={styles.page}>
      {jobId ? (
        <PracticeLoader jobId={jobId} />
      ) : (
        <StateCard>
          <p role="alert">缺少任务编号。</p>
        </StateCard>
      )}
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
    if (!job.isError) {
      return (
        <p role="status" className={styles.note}>
          正在加载任务…
        </p>
      );
    }
    return (
      <StateCard>
        <p role="alert">{errorMessage(job.error)}</p>
      </StateCard>
    );
  }
  if (isActive(current.status)) {
    return (
      <StateCard title={current.title}>
        <ProgressBar value={current.progress} label="处理进度" />
        <p role="status" className={styles.stageLine}>
          {`${statusText(current)} · ${current.message}`}
        </p>
      </StateCard>
    );
  }
  if (current.status === "failed") {
    return (
      <StateCard title={current.title}>
        <p role="alert" className={styles.failure}>
          处理失败：{current.error?.detail ?? current.message}
        </p>
      </StateCard>
    );
  }

  const data = result.data;
  if (data === undefined) {
    if (!result.isError) {
      return (
        <p role="status" className={styles.note}>
          正在加载句子…
        </p>
      );
    }
    return (
      <StateCard>
        <p role="alert">{errorMessage(result.error)}</p>
      </StateCard>
    );
  }
  if (data.sentences.length === 0) {
    // 空结果不能进入播放器，否则会索引不存在的 sentences[0]。
    return (
      <StateCard title={data.title}>
        <p role="status">未找到可练习句段。</p>
      </StateCard>
    );
  }

  // 提示与播放器的位置固定，提示出现或消失都不会让播放器重新挂载、丢失练习进度。
  return (
    <>
      {job.isError || result.isError ? (
        <p role="status" className={styles.note}>
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
  const { state, send, completed, playhead } = usePlayer();
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
    <div className={styles.workspace}>
      <section className={styles.stage} aria-labelledby="current-sentence-title">
        <div className={styles.meta}>
          <BackLink />
          <h1 className={styles.title} title={result.title}>
            {result.title}
          </h1>
        </div>
        {sentence ? (
          <>
            <Readout sentence={sentence} />
            <VeiledSentence sentence={sentence} revealed={state.revealed} />
            <SentenceProgress start={sentence.start} end={sentence.end} />
          </>
        ) : null}
        {playbackError ? (
          <p role="alert" className={styles.failure}>
            {playbackError}
          </p>
        ) : null}
        <Transport />
        <PlaybackSettings />
        <PracticeActions
          jobId={result.jobId}
          resegmentOpen={resegmentOpen}
          onResegmentOpenChange={setResegmentOpen}
        />
        <audio
          ref={audioRef}
          src={result.audioUrl}
          preload="auto"
          onError={() => setPlaybackError("音频加载失败，请刷新页面或稍后重试。")}
        />
      </section>
      <SentenceReel sentences={result.sentences} />
    </div>
  );
}
