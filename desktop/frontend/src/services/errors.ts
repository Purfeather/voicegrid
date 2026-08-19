export type ApiErrorDetail = {
  loc?: Array<string | number>;
  msg?: string;
  detail?: unknown;
  [key: string]: unknown;
};

const FIELD_LABELS: Record<string, string> = {
  target_duration_seconds: "目标时长",
  duration_seconds: "生成时长",
  inference_steps: "推理步数",
  cfg: "CFG",
  sigma_shift: "Sigma Shift",
  temperature: "Temperature",
  top_p: "Top-P",
  top_k: "Top-K",
  repetition_penalty: "重复惩罚",
  max_seconds: "最大秒数",
  max_chars: "每段最大字符",
};

function fieldName(loc: Array<string | number> | undefined): string {
  let field: string | number | undefined;
  for (let index = (loc?.length || 0) - 1; index >= 0; index -= 1) {
    const item = loc?.[index];
    if (typeof item === "string" && item !== "body" && item !== "query" && item !== "path") {
      field = item;
      break;
    }
  }
  return FIELD_LABELS[String(field)] || String(field || "请求参数");
}

function humanizeMessage(message: string): string {
  const greater = message.match(/greater than or equal to\s+(-?\d+(?:\.\d+)?)/i);
  if (greater) return `必须大于或等于 ${greater[1]}`;
  const less = message.match(/less than or equal to\s+(-?\d+(?:\.\d+)?)/i);
  if (less) return `必须小于或等于 ${less[1]}`;
  const atMost = message.match(/at most\s+(\d+)\s+characters?/i);
  if (atMost) return `长度不能超过 ${atMost[1]} 个字符`;
  if (/valid number/i.test(message)) return "必须填写有效数字";
  if (/field required/i.test(message)) return "不能为空";
  return message;
}

function formatDetail(detail: unknown): string | null {
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => formatDetail(item)).filter((item): item is string => Boolean(item));
    return messages.length ? messages.join("；") : null;
  }
  if (detail && typeof detail === "object") {
    const item = detail as ApiErrorDetail;
    if (typeof item.msg === "string") return `${fieldName(item.loc)}：${humanizeMessage(item.msg)}`;
    if (item.detail !== undefined) return formatDetail(item.detail);
    const values = Object.values(item).map((value) => formatDetail(value)).filter((value): value is string => Boolean(value));
    return values.length ? values.join("；") : null;
  }
  return null;
}

export function formatApiErrorPayload(payload: unknown, fallback: string): string {
  return formatDetail(payload) || fallback;
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown, fallback?: string) {
    super(formatApiErrorPayload(detail, fallback || `请求失败（${status}）`));
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message && error.message !== "[object Object]") return error.message;
  return formatApiErrorPayload(error, fallback);
}