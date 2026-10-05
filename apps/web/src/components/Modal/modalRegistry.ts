import { createContext, useContext } from "react";

/** 弹层内常驻的两个播报区：aria-modal 会让读屏忽略弹层外的内容，提示必须在弹层里播报。 */
export type ToastHost = { polite: HTMLElement; assertive: HTMLElement };

export type ModalRegistry = {
  open: boolean;
  /** 最上层弹层的播报区；没有弹层时为 null。 */
  toastHost: ToastHost | null;
  /** 弹层挂载时登记（可带播报区），返回的函数在卸载时注销。 */
  register: (host?: ToastHost) => () => void;
};

// Provider 之外（如单独渲染的组件测试）不统计：弹层照常工作，只是不会暂停快捷键。
export const ModalRegistryContext = createContext<ModalRegistry>({
  open: false,
  toastHost: null,
  register: () => () => {}
});

/** 当前是否有任何弹层打开；播放器快捷键据此整体暂停。 */
export function useModalOpen(): boolean {
  return useContext(ModalRegistryContext).open;
}

export function useToastHost(): ToastHost | null {
  return useContext(ModalRegistryContext).toastHost;
}
