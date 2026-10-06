// 链接只取 ASCII 可见字符：分享文案里紧贴链接的中文、全角标点和空白都会在这里截断。
const HTTP_URL_IN_TEXT = /https?:\/\/[!-~]+/i;
// 句末标点和包裹链接的括号、引号不属于链接本身。
const TRAILING_PUNCTUATION = /[.,;:!?'"`)\]}>]+$/;

/** 从分享文案中取出第一个 http(s) 链接，例如「【标题】 https://…」；找不到时返回 null。 */
export function extractSourceUrl(text: string): string | null {
  const match = HTTP_URL_IN_TEXT.exec(text);
  if (!match) return null;
  const url = match[0].replace(TRAILING_PUNCTUATION, "");
  // 只剩协议头说明不是可用链接。
  return /^https?:\/\/[^/?#]+/i.test(url) ? url : null;
}

/** 输入里有链接时只提交链接；没有链接时原样保留，交给本机路径分支和服务端校验。 */
export function normalizeSource(text: string): string {
  return extractSourceUrl(text) ?? text.trim();
}
