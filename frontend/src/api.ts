let token = '';
export const setToken = (value: string) => {
  token = value;
};

async function workspaceFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const send = () =>
    fetch(url, { ...init, headers: { ...init.headers, 'X-Workspace-Token': token } });
  let response = await send();
  // A quick restart can happen between health polls. This particular 403 is
  // emitted before the server executes the request, so one retry is safe.
  if (response.status === 403) {
    const error = await response
      .clone()
      .json()
      .catch(() => ({}));
    if (error.error === '会话已变化，请刷新页面后重试') {
      const bootstrap = await fetch('/api/bootstrap');
      if (bootstrap.ok) {
        const data = await bootstrap.json();
        if (typeof data.token === 'string') {
          setToken(data.token);
          response = await send();
        }
      }
    }
  }
  return response;
}

export async function api<T>(url: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await workspaceFetch(url, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(method !== 'GET' ? { 'X-Workspace-Token': token } : {}),
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new Error(
      result.error ||
        (typeof result.detail === 'string' ? result.detail : JSON.stringify(result.detail)) ||
        `请求失败 (${response.status})`,
    );
  return result as T;
}

export async function upload(file: File) {
  const form = new FormData();
  form.append('file', file);
  const response = await workspaceFetch('/api/files', {
    method: 'POST',
    headers: { 'X-Workspace-Token': token },
    body: form,
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || result.detail || '上传失败');
  return result;
}

export function downloadJSON(value: unknown, filename: string) {
  downloadText(JSON.stringify(value, null, 2), filename, 'application/json');
}

export function downloadText(value: string, filename: string, type = 'text/plain;charset=utf-8') {
  const url = URL.createObjectURL(new Blob([value], { type }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
