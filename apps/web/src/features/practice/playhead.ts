export type Playhead = {
  get: () => number;
  set: (time: number) => void;
  subscribe: (listener: () => void) => () => void;
};

/**
 * 音频当前时间的外部存储。时间每帧变化，放进 React state 会让整个练习台每帧重渲染；
 * 放在这里只通知真正订阅了它的组件（遮罩句、时间读数、本句进度条）。
 */
export function createPlayhead(initial = 0): Playhead {
  let time = initial;
  const listeners = new Set<() => void>();
  return {
    get: () => time,
    set: (next) => {
      if (next === time) return;
      time = next;
      for (const listener of listeners) listener();
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    }
  };
}
