import { File as NodeFile } from "node:buffer";

/**
 * 仅用于 jsdom 测试环境：jsdom 替换了全局的 FormData、File 与 AbortSignal，
 * 而 Node 自带的 fetch 只认自己的实现，直接传入会报类型错误或丢失文件内容。
 * 这里在测试边界把它们转换成 Node 能识别的对象，生产代码不受影响。
 */
function readFile(file: Blob): Promise<Uint8Array<ArrayBuffer>> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    // FileReader 读出的是 jsdom 一侧的 ArrayBuffer，Buffer.from 能跨运行环境识别它。
    reader.onload = () => resolve(new Uint8Array(Buffer.from(reader.result as ArrayBuffer)));
    reader.onerror = () => reject(reader.error);
    reader.readAsArrayBuffer(file);
  });
}

async function toNodeFormData(form: FormData, NodeFormData: typeof FormData): Promise<FormData> {
  const converted = new NodeFormData();
  for (const [key, value] of form.entries()) {
    if (typeof value === "string") {
      converted.append(key, value);
    } else {
      const file = new NodeFile([await readFile(value)], value.name, { type: value.type });
      // 不传第三个参数：传文件名会让 Node 用全局（jsdom）File 重新包装，内容随之丢失。
      converted.append(key, file as unknown as Blob);
    }
  }
  return converted;
}

/** 在 MSW 的 server.listen() 之后调用，包住 MSW 接管后的 fetch；返回恢复函数。 */
export async function installFetchBridge(): Promise<() => void> {
  const nodeFetch = globalThis.fetch;
  // jsdom 没有 Response，全局 Response 仍是 Node 的；借它拿到 Node 的 FormData 构造器。
  const probe = new Response("", {
    headers: { "content-type": "application/x-www-form-urlencoded" }
  });
  const NodeFormData = (await probe.formData()).constructor as typeof FormData;
  const NodeRequest = globalThis.Request;
  // React Router 跳转时会用 jsdom 的 AbortSignal 构造 Node 的 Request；测试中去掉 signal 即可。
  globalThis.Request = class extends NodeRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      super(input, init ? { ...init, signal: undefined } : init);
    }
  } as typeof Request;

  globalThis.fetch = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const { signal, ...rest } = init;
    const body =
      rest.body instanceof FormData ? await toNodeFormData(rest.body, NodeFormData) : rest.body;
    const pending = nodeFetch(input, { ...rest, body });
    if (!signal) return pending;
    // jsdom 的 AbortSignal 不能交给 Node fetch；监听它的 abort 事件，以 AbortError 结束请求。
    return new Promise<Response>((resolve, reject) => {
      const abort = () => reject(new DOMException("The operation was aborted.", "AbortError"));
      if (signal.aborted) abort();
      signal.addEventListener("abort", abort, { once: true });
      pending.then(resolve, reject);
    });
  }) as typeof fetch;
  return () => {
    globalThis.fetch = nodeFetch;
    globalThis.Request = NodeRequest;
  };
}

/** 解析原始 multipart 请求体；jsdom 环境下 MSW 里的 request.formData() 无法解析文件字段。 */
export function multipartFields(body: string): Record<string, string> {
  const fields: Record<string, string> = {};
  const pattern =
    /name="([^"]+)"(?:; filename="([^"]*)")?\r\n(?:Content-Type: [^\r\n]*\r\n)?\r\n([\s\S]*?)\r\n--/g;
  for (const match of body.matchAll(pattern)) {
    const [, name, filename, value] = match;
    fields[name] = filename ?? value;
  }
  return fields;
}
