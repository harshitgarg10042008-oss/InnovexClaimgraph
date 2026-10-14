const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function apiClient<T>(
  endpoint: string,
  options?: RequestInit,
): Promise<T> {
  const normalizedEndpoint = endpoint.startsWith("/")
    ? endpoint
    : `/${endpoint}`;
  const url =
    endpoint.startsWith("http://") || endpoint.startsWith("https://")
      ? endpoint
      : `${API_BASE_URL.replace(/\/$/, "")}${normalizedEndpoint}`;

  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.status} ${response.statusText}`);
  }

  return response.json() as Promise<T>;
}
