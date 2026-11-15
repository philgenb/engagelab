export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail));
  }
  return body as T;
}

