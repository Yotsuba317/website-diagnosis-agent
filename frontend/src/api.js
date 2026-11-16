export async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers },
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求失败，请稍后重试');
  return data;
}

export const post = (path, payload) => api(path, { method: 'POST', body: JSON.stringify(payload) });
export const reportUrl = (path, format) => `/api/download?path=${encodeURIComponent(path)}&format=${format}`;
export const activeJob = job => ['queued', 'running', 'cancelling'].includes(job?.status);
export const LABELS = {
  normal: '基础访问正常', dns_failure: 'DNS 解析失败', tcp_failure: 'TCP 连接失败',
  tls_failure: 'TLS 握手或证书问题', http_error: 'HTTP 错误响应', slow_response: '响应等待偏长',
  insufficient_evidence: '证据不足', execution_error: '模型执行未成功',
};
export const MODES = { baseline: 'A · 直接分析', tools: 'B · 工具调查', skill: 'C · 专业 Skill' };
export const defaultSettings = { engine: 'ollama', mode: 'skill', model: 'qwen3.5:0.8b', host: 'http://127.0.0.1:11434', timeout: 3, slow_ms: 800 };
export function loadSettings() {
  try {
    const value = JSON.parse(localStorage.getItem('netlens:settings:v1'));
    return value && typeof value === 'object' ? { ...defaultSettings, ...Object.fromEntries(Object.entries(value).filter(([key]) => key in defaultSettings)) } : defaultSettings;
  } catch { return defaultSettings; }
}
export function date(value, full = false) {
  if (!value || Number.isNaN(new Date(value).getTime())) return '时间未记录';
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', ...(full ? { year: 'numeric', second: '2-digit' } : {}) }).format(new Date(value));
}
export const percent = value => typeof value === 'number' ? `${(value * 100).toFixed(1)}%` : '—';
export const tone = diagnosis => diagnosis === 'normal' ? 'success' : diagnosis === 'insufficient_evidence' ? 'warning' : 'danger';

export function eventLabel(event) {
  if (!event) return '等待任务开始';
  const names = { check_dns: 'DNS 地址解析', check_tcp: 'TCP 端口连接', check_http: 'TLS / HTTP 响应' };
  if (event.type === 'tool') return `${names[event.tool] || event.tool} · ${event.result?.status === 'ok' ? '已取得观测' : event.result?.status === 'error' ? '检测到异常' : '观测不可用'}`;
  if (event.type === 'model_started') return `模型正在调查 · 第 ${event.request} 次调用`;
  if (event.type === 'model_finished') return `模型已返回 · 第 ${event.request} 次调用`;
  if (event.type === 'validation') return '正在核对模型文字与实测事实';
  if (event.type === 'evaluation_item') return `正在评测 ${event.case_id} · ${MODES[event.mode]} · 第 ${event.repeat} 轮`;
  if (event.type === 'evaluation_scored') return `已完成 ${event.completed} / ${event.total} 次调查`;
  if (event.type === 'diagnosis_finished') return event.diagnosis ? `调查结束 · ${LABELS[event.diagnosis]}` : '模型未能完成调查，已保留工具观测';
  if (event.type === 'evaluation_finished') return '对照评测已完成';
  return event.message || '正在处理';
}
