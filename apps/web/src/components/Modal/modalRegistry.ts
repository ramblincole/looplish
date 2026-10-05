import { createContext, useContext } from "react";

export type ModalRegistry = {
  open: boolean;
  /** 弹层挂载时登记，返回的函数在卸载时注销。 */
  register: () => () => void;
};

// Provider 之外（如单独渲染的组件测试）不统计：弹层照常工作，只是不会暂停快捷键。
export const ModalRegistryContext = createContext<ModalRegistry>({
  open: false,
  register: () => () => {}
});

/** 当前是否有任何弹层打开；播放器快捷键据此整体暂停。 */
export function useModalOpen(): boolean {
  return useContext(ModalRegistryContext).open;
}
