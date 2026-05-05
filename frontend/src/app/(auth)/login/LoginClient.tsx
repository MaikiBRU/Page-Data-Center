"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, API_URL } from "@/lib/api";
import { setToken } from "@/lib/auth";
import { emitToast } from "@/lib/toast";

type LoginClientProps = {
  initialClientId?: string | null;
};

type GoogleCredentialResponse = {
  credential?: string;
};

declare global {
  interface Window {
    google?: {
      accounts?: {
        id?: {
          initialize: (options: {
            client_id: string;
            callback: (response: GoogleCredentialResponse) => void;
          }) => void;
          renderButton: (
            parent: HTMLElement,
            options: {
              theme?: "outline" | "filled_blue" | "filled_black";
              size?: "large" | "medium" | "small";
              type?: "standard" | "icon";
              text?: "signin_with" | "signup_with" | "continue_with" | "signin";
              shape?: "rectangular" | "pill" | "circle" | "square";
              width?: number;
            }
          ) => void;
        };
      };
    };
  }
}

export default function LoginClient({ initialClientId }: LoginClientProps) {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "set_password">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [googleError, setGoogleError] = useState<string | null>(null);
  const [clientId, setClientId] = useState<string | null>(
    initialClientId && initialClientId.length > 0 ? initialClientId : null
  );
  const googleButtonRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const loadClientId = async () => {
      if (clientId) return;
      try {
        const resp = await fetch(`${API_URL}/auth/google-config`);
        const data = await resp.json();
        const fetched = data.client_id ?? "";
        if (!fetched) {
          setGoogleError("Google no está configurado.");
          return;
        }
        setClientId(fetched);
      } catch {
        setGoogleError("No se pudo obtener la configuración de Google.");
      }
    };

    loadClientId();
  }, [clientId]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("set") === "1") {
      setMode("set_password");
      setMessage("Creá una contraseña para usar tu email en futuros accesos.");
    }
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("reason") === "expired") {
      setMessage("Sesión expirada. Iniciá sesión nuevamente.");
      import("@/lib/toast").then(({ emitToast }) => {
        emitToast({ message: "Sesión expirada. Iniciá sesión nuevamente.", kind: "error" });
      });
    }
    if (params.get("reset") === "1") {
      setMessage("Contraseña actualizada. Iniciá sesión.");
      import("@/lib/toast").then(({ emitToast }) => {
        emitToast({ message: "Contraseña actualizada. Iniciá sesión.", kind: "success" });
      });
    }
  }, []);

  useEffect(() => {
    const fillEmail = async () => {
      if (mode !== "set_password") return;
      try {
        const me = await apiFetch<{ email: string }>("/auth/me");
        setEmail(me.email);
      } catch {
        // ignore
      }
    };
    fillEmail();
  }, [mode]);

  useEffect(() => {
    if (!clientId || !googleButtonRef.current) return;

    const mountGoogleButton = () => {
      if (!window.google?.accounts?.id || !googleButtonRef.current) {
        setGoogleError("Google no está disponible en este navegador.");
        return;
      }

      googleButtonRef.current.innerHTML = "";
      window.google.accounts.id.initialize({
        client_id: clientId,
        callback: async (response) => {
          if (!response.credential) {
            setGoogleError("Google no devolvió una credencial válida.");
            return;
          }

          setGoogleError(null);
          setError(null);
          setLoading(true);
          try {
            const token = await apiFetch<{
              access_token: string;
              needs_password_setup?: boolean;
            }>("/auth/google", {
              method: "POST",
              body: JSON.stringify({ id_token: response.credential }),
            });
            setToken(token.access_token);
            emitToast({ message: "Sesión iniciada con Google.", kind: "success" });
            router.push("/dashboard");
          } catch (err) {
            const message = (err as Error).message;
            setGoogleError(message);
            emitToast({ message, kind: "error" });
          } finally {
            setLoading(false);
          }
        },
      });
      window.google.accounts.id.renderButton(googleButtonRef.current, {
        theme: "outline",
        size: "large",
        type: "standard",
        text: "continue_with",
        shape: "rectangular",
        width: 320,
      });
    };

    if (window.google?.accounts?.id) {
      mountGoogleButton();
      return;
    }

    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.onload = mountGoogleButton;
    script.onerror = () => setGoogleError("No se pudo cargar Google.");
    document.head.appendChild(script);

    return () => {
      script.onload = null;
      script.onerror = null;
    };
  }, [clientId, router]);

  const handleLogin = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setMessage(null);
    setLoading(true);
    try {
      const token = await apiFetch<{ access_token: string }>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setToken(token.access_token);
      emitToast({ message: "Sesión iniciada.", kind: "success" });
      router.push("/dashboard");
    } catch (err) {
      const message = (err as Error).message;
      setError(message);
      emitToast({ message, kind: "error" });
    } finally {
      setLoading(false);
    }
  };

  const handleSetPassword = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setMessage(null);
    setLoading(true);
    try {
      if (password !== confirmPassword) {
        throw new Error("Las contraseñas no coinciden");
      }
      await apiFetch("/auth/set-password", {
        method: "POST",
        body: JSON.stringify({ password }),
      });
      emitToast({ message: "Contraseña guardada.", kind: "success" });
      router.push("/dashboard");
    } catch (err) {
      const message = (err as Error).message;
      setError(message);
      emitToast({ message, kind: "error" });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto grid w-full max-w-5xl gap-10 lg:grid-cols-[1.1fr_0.9fr]">
      <div className="panel flex flex-col gap-6">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-white/40">
            Calidad de datos
          </p>
          <h1 className="mt-3 text-3xl font-semibold">Control Center</h1>
          <p className="mt-3 text-sm text-[var(--muted)]">
            Monitoreo de calidad, anomalías y acciones recomendadas para ecommerce
            y logística. Unificá datos críticos y operativos en un solo panel.
          </p>
        </div>
        <div className="grid gap-4 rounded-2xl border border-white/10 bg-white/5 p-5 text-sm text-white/70">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-white/40">Focus</p>
            <p className="mt-2">Direcciones, stock, precios y tiempos de entrega.</p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-white/40">Valor</p>
            <p className="mt-2">Reduce errores y acelera decisiones internas.</p>
          </div>
        </div>
      </div>

      <form
        onSubmit={mode === "login" ? handleLogin : handleSetPassword}
        className="panel flex flex-col gap-6"
      >
        <div>
          <h2 className="text-2xl font-semibold">
            {mode === "login" ? "Ingresar" : "Crear contraseña"}
          </h2>
          <p className="mt-2 text-sm text-[var(--muted)]">
            {mode === "login"
              ? "Usa tu email y contraseña para entrar."
              : "Definí una contraseña para acceder también con tu email."}
          </p>
        </div>
        <label className="text-sm text-white/70">
          Email
          <input
            className="input-base mt-2"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required={mode === "login"}
            disabled={mode === "set_password"}
          />
        </label>
        {mode !== "set_password" && (
          <label className="text-sm text-white/70">
            Password
            <input
              className="input-base mt-2"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              maxLength={128}
              required={mode === "login"}
            />
          </label>
        )}
        {mode === "login" && (
          <div className="flex items-center justify-between text-xs text-white/60">
            <span>¿Olvidaste tu contraseña?</span>
            <a className="text-[var(--accent-2)] hover:text-white" href="/forgot-password">
              Recuperar acceso
            </a>
          </div>
        )}
        {mode === "set_password" && (
          <label className="text-sm text-white/70">
            Contraseña
            <input
              className="input-base mt-2"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              maxLength={128}
              required
            />
            <input
              className="input-base mt-3"
              type="password"
              placeholder="Confirmar contraseña"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              maxLength={128}
              required
            />
          </label>
        )}
        {message && <p className="text-sm text-[var(--accent-2)]">{message}</p>}
        {error && <p className="text-sm text-[var(--danger)]">{error}</p>}
        <button className="btn-primary" type="submit" disabled={loading}>
          {loading
            ? "Procesando..."
            : mode === "login"
            ? "Entrar"
            : "Guardar contraseña"}
        </button>
        {mode === "set_password" && (
          <button
            type="button"
            className="btn-secondary"
            onClick={() => setMode("login")}
          >
            Volver al login
          </button>
        )}

        <div className="grid gap-3">
          <div className="flex min-h-11 justify-center" ref={googleButtonRef} />
          {googleError && <p className="text-xs text-[var(--muted)]">{googleError}</p>}
        </div>
      </form>
    </div>
  );
}
