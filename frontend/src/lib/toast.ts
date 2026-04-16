export type ToastKind = "success" | "error" | "info";

export type ToastPayload = {
  message: string;
  kind?: ToastKind;
  durationMs?: number;
};

export function emitToast(payload: ToastPayload) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent("app-toast", {
      detail: {
        message: payload.message,
        kind: payload.kind ?? "info",
        durationMs: payload.durationMs ?? 3500,
      },
    })
  );
}
