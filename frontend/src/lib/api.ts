export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token =
    typeof window !== "undefined" ? localStorage.getItem("token") : null;

  const headers = new Headers(options.headers || {});
  const hasBody = typeof options.body !== "undefined";
  const isForm = typeof FormData !== "undefined" && options.body instanceof FormData;
  if (hasBody && !isForm && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    if (response.status === 401 && typeof window !== "undefined") {
      localStorage.removeItem("token");
      import("./toast").then(({ emitToast }) => {
        emitToast({ message: "Sesión expirada. Iniciá sesión nuevamente.", kind: "error" });
      });
      window.location.href = "/login?reason=expired";
      throw new Error("Session expired");
    }
    const message = await response.text();
    throw new Error(message || "Request failed");
  }

  return response.json() as Promise<T>;
}
