import { clearToken, getToken } from "@/lib/auth";
import { isDemoMode, markDemoMode } from "@/lib/demo";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

/**
 * The API answers with a mix of English and Spanish `detail` strings, and the
 * interface is in Spanish. Rather than rewording every call site, the known
 * English details are translated once, here, on their way in.
 */
const MENSAJES: Record<string, string> = {
  "Admin only": "Esta accion es solo para administradores.",
  "Blocked reason required": "Indica el motivo del bloqueo.",
  "Cannot deactivate last admin": "No podes desactivar al ultimo administrador.",
  "Cannot remove last admin": "No podes quitar al ultimo administrador.",
  "Case not found": "El caso no existe o no pertenece a esta sesion.",
  "Could not validate credentials": "Tu sesion no es valida. Inicia sesion de nuevo.",
  "Dataset file not found": "El archivo del dataset ya no esta disponible. Volve a subirlo.",
  "Dataset not found": "El dataset no existe o no pertenece a esta sesion.",
  "Dataset not found or no file uploaded":
    "El dataset no existe o todavia no tiene un archivo cargado.",
  "Demo session required": "Necesitas una sesion de demo activa.",
  "Email already registered": "Ese email ya esta registrado.",
  "Escalation level must be 1-5": "El nivel de escalamiento debe estar entre 1 y 5.",
  "Escalation reason required": "Indica el motivo del escalamiento.",
  Forbidden: "No tenes permisos para hacer esto.",
  "Google account missing email": "La cuenta de Google no expone un email.",
  "Google client id not configured": "El acceso con Google no esta configurado.",
  "Google client secret not configured": "El acceso con Google no esta configurado.",
  "Google token exchange failed": "No se pudo completar el acceso con Google.",
  "Insufficient permissions": "No tenes permisos para hacer esto.",
  "Invalid Google token": "El acceso con Google no es valido.",
  "Invalid assignment mode": "El modo de asignacion no es valido.",
  "Invalid credentials": "Email o contrasena incorrectos.",
  "Invalid format": "El formato pedido no es valido.",
  "Invalid reset token": "El enlace de recuperacion no es valido.",
  "Invalid severity": "La severidad no es valida.",
  "Invalid state": "El estado de la solicitud no es valido.",
  "Invalid status": "El estado no es valido.",
  "Max 200 items per batch": "Como maximo 200 elementos por lote.",
  "Missing code": "Falta el codigo de autorizacion.",
  "Missing id_token": "Falta el token de identidad.",
  "No changes provided": "No enviaste ningun cambio.",
  "No demo datasets found": "No hay datasets de demo cargados.",
  "Not found": "No se encontro el recurso.",
  "Owner must be an active user": "El responsable debe ser un usuario activo.",
  "Owner required for owner mode": "Elegi un responsable para el modo owner fijo.",
  "Password must be 8-256 chars, include letters and numbers":
    "La contrasena debe tener entre 8 y 256 caracteres, con letras y numeros.",
  "Recommendation must be 20+ chars": "La recomendacion necesita al menos 20 caracteres.",
  "Reset token expired": "El enlace de recuperacion vencio.",
  "SLA must be between 1 and 168 hours": "El SLA debe estar entre 1 y 168 horas.",
  "Session expired": "Tu sesion expiro.",
  "Summary must be 20+ chars": "El resumen necesita al menos 20 caracteres.",
  "Title must be 6-140 chars": "El titulo debe tener entre 6 y 140 caracteres.",
  "Unsupported format": "Ese formato no esta soportado.",
  "Use Google to sign in": "Esta cuenta ingresa con Google.",
  "User is inactive": "La cuenta esta desactivada.",
  "User not found": "El usuario no existe.",
  "case_ids required": "Selecciona al menos un caso.",
  "items required": "Selecciona al menos un elemento.",
};

function traducir(detail: string): string {
  return MENSAJES[detail] ?? detail;
}

/** Turn a FastAPI error body into something worth showing a person. */
async function readError(response: Response): Promise<string> {
  const raw = await response.text();
  if (!raw) return "La solicitud fallo.";
  try {
    const parsed = JSON.parse(raw);
    if (typeof parsed?.detail === "string") return traducir(parsed.detail);
    if (Array.isArray(parsed?.detail) && parsed.detail[0]?.msg) {
      return String(parsed.detail[0].msg);
    }
  } catch {
    // not JSON: fall through to the raw text
  }
  return raw;
}

export class ApiError extends Error {
  status: number;
  /** Present on 409 replies caused by a demo quota, e.g. "datasets". */
  demoLimit: string | null;

  constructor(message: string, status: number, demoLimit: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.demoLimit = demoLimit;
  }
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getToken();

  const headers = new Headers(options.headers || {});
  const hasBody = typeof options.body !== "undefined";
  const isForm = typeof FormData !== "undefined" && options.body instanceof FormData;
  if (hasBody && !isForm && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers,
    });
  } catch {
    // fetch only rejects on a network level failure: the API is unreachable,
    // still waking up, or the request was blocked. The browser message for
    // that ("Failed to fetch", "Load failed") means nothing to a visitor, so
    // it never reaches the interface.
    throw new ApiError(
      "No se pudo contactar el servidor. Puede estar iniciando: espera unos segundos y volve a intentar.",
      0,
    );
  }

  if (!response.ok) {
    if (response.status === 401 && typeof window !== "undefined") {
      const demo = isDemoMode();
      clearToken();
      const { emitToast } = await import("./toast");
      if (demo) {
        // A visitor whose sandbox lapsed should be offered a new one, not sent
        // to a login form they have no credentials for.
        markDemoMode(false);
        emitToast({
          message: "La sesion de demo expiro. Podes iniciar una nueva.",
          kind: "info",
        });
        window.location.href = "/demo?reason=expired";
      } else {
        emitToast({ message: "Sesion expirada. Inicia sesion nuevamente.", kind: "error" });
        window.location.href = "/login?reason=expired";
      }
      throw new ApiError("Session expired", 401);
    }
    const message = await readError(response);
    throw new ApiError(message, response.status, response.headers.get("X-Demo-Limit"));
  }

  return response.json() as Promise<T>;
}
