import type { ComponentPropsWithRef } from "react";
import { Button } from "../../components/Button/Button";
import { usePlayer, usePlayerActions } from "./playerContext";
import styles from "./Transport.module.css";

type TransportButtonProps = ComponentPropsWithRef<"button"> & {
  label: string;
  icon: string;
  hotkey: string;
  main?: boolean;
};

/** 方块走带按钮：图标对读屏隐藏，读屏名称来自隐藏文字，悬停提示带上快捷键。 */
function TransportButton({ label, icon, hotkey, main = false, ...rest }: TransportButtonProps) {
  return (
    <Button
      variant={main ? "transportMain" : "transport"}
      title={`${label}（${hotkey}）`}
      {...rest}
    >
      <span aria-hidden="true">{icon}</span>
      <span className="visuallyHidden">{label}</span>
    </Button>
  );
}

export function Transport() {
  const { state, sentenceCount } = usePlayer();
  const actions = usePlayerActions();
  const { sentenceIndex, playing, revealed } = state;

  return (
    <div className={styles.transport} role="group" aria-label="播放控制">
      <TransportButton
        label="上一句"
        icon="◀◀"
        hotkey="←"
        onClick={actions.previous}
        disabled={sentenceIndex === 0}
        aria-keyshortcuts="ArrowLeft"
      />
      <TransportButton
        main
        label={playing ? "暂停" : "播放"}
        icon={playing ? "❚❚" : "▶"}
        hotkey="空格"
        onClick={actions.togglePlaying}
        aria-keyshortcuts="Space"
      />
      <TransportButton
        label="重听"
        icon="↻"
        hotkey="R"
        onClick={actions.replay}
        aria-keyshortcuts="R"
      />
      <TransportButton
        label="下一句"
        icon="▶▶"
        hotkey="→"
        onClick={actions.next}
        disabled={sentenceIndex + 1 >= sentenceCount}
        aria-keyshortcuts="ArrowRight"
      />
      <Button
        variant="reveal"
        className={styles.reveal}
        onClick={actions.toggleReveal}
        aria-pressed={revealed}
        aria-keyshortcuts="Enter"
        title="显示 / 遮住原文（Enter）"
      >
        {revealed ? "遮住原文" : "显示原文"}
      </Button>
    </div>
  );
}
