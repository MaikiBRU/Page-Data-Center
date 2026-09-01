"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { emitToast } from "@/lib/toast";

const isPasswordValid = (value: string) => {
  if (value.length < 8) return false;
  if (!/[A-Za-z]/.test(value)) return false;
  if (!/\d/.test(value)) return false;
  return true;
};

export default function ResetPasswordPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const emailParam = params.get("email") ?? "";
    const tokenParam = params.get("token") ?? "";
    if (emailParam) setEmail(emailParam);
    if (tokenParam) setToken(tokenParam);
  }, []);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setMessage(null);
    if (!isPasswordValid(password)) {
      const msg = "La contraseña debe tener al menos 8 caracteres, letras y números.";
      setMessage(msg);
      emitToast({ message: msg, kind: "error" });
      return;
    }
    if (password !== confirm) {
      const msg = "Las contraseñas no coinciden.";
      setMessage(msg);
      emitToast({ message: msg, kind: "error" });
      return;
    }
    setLoading(true);
    try {
      await apiFetch("/auth/reset-password", {
        method: "POST",
        body: JSON.stringify({ email, token, password }),
      });
      emitToast({ message: "Contraseña actualizada.", kind: "success" });
      router.push("/login?reset=1");
    } catch (err) {
      const msg = (err as Error).message || "No se pudo actualizar la contraseña";
      setMessage(msg);
      emitToast({ message: msg, kind: "error" });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto grid w-full max-w-4xl gap-10 lg:grid-cols-[1fr_1fr]">
      <div className="panel flex flex-col gap-6">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-white/55">
            Nuevo acceso
          </p>
          <h1 className="mt-3 text-3xl font-semibold">Crear nueva contraseña</h1>
          <p className="mt-3 text-sm text-[var(--muted)]">
            Pegá el token del enlace y definí tu nueva contraseña.
          </p>
        </div>
        <div className="grid gap-3 rounded-2xl border border-white/10 bg-white/5 p-5 text-sm text-white/70">
          <p className="text-xs uppercase tracking-[0.3em] text-white/55">Condiciones</p>
          <p>8+ caracteres, letras y números.</p>
          <p>El enlace vence a los 30 minutos.</p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="panel flex flex-col gap-6">
        <div>
          <h2 className="text-2xl font-semibold">Restablecer</h2>
          <p className="mt-2 text-sm text-[var(--muted)]">
            Confirmá tu email y token para continuar.
          </p>
        </div>
        <label className="text-sm text-white/70">
          Email
          <input
            className="input-base mt-2"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
        </label>
        <label className="text-sm text-white/70">
          Token
          <input
            className="input-base mt-2"
            type="text"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            required
          />
        </label>
        <label className="text-sm text-white/70">
          Nueva contraseña
          <input
            className="input-base mt-2"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            maxLength={128}
          />
          <input
            className="input-base mt-3"
            type="password"
            placeholder="Confirmar contraseña"
            value={confirm}
            onChange={(event) => setConfirm(event.target.value)}
            required
            maxLength={128}
          />
        </label>
        {message && <p className="text-sm text-[var(--muted)]">{message}</p>}
        <button className="btn-primary" type="submit" disabled={loading}>
          {loading ? "Guardando..." : "Guardar contraseña"}
        </button>
        <Link href="/login" className="btn-secondary text-center">
          Volver al login
        </Link>
      </form>
    </div>
  );
}
