"use client";

import { useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import { emitToast } from "@/lib/toast";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setMessage(null);
    try {
      await apiFetch("/auth/forgot-password", {
        method: "POST",
        body: JSON.stringify({ email }),
      });
      const info =
        "Si el email existe, enviamos un link de recuperación. Revisá los logs del backend.";
      setMessage(info);
      emitToast({ message: "Solicitud enviada.", kind: "success" });
    } catch (err) {
      const msg = (err as Error).message || "No se pudo enviar la solicitud";
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
            Recuperación
          </p>
          <h1 className="mt-3 text-3xl font-semibold">Restablecer contraseña</h1>
          <p className="mt-3 text-sm text-[var(--muted)]">
            Te enviamos un enlace para que puedas crear una nueva contraseña de acceso.
          </p>
        </div>
        <div className="grid gap-4 rounded-2xl border border-white/10 bg-white/5 p-5 text-sm text-white/70">
          <p className="text-xs uppercase tracking-[0.3em] text-white/55">Recomendación</p>
          <p>
            Usá una contraseña de al menos 8 caracteres con letras y números.
          </p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="panel flex flex-col gap-6">
        <div>
          <h2 className="text-2xl font-semibold">Solicitar link</h2>
          <p className="mt-2 text-sm text-[var(--muted)]">
            Ingresá tu email y te enviaremos el enlace.
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
        {message && <p className="text-sm text-[var(--muted)]">{message}</p>}
        <button className="btn-primary" type="submit" disabled={loading}>
          {loading ? "Enviando..." : "Enviar enlace"}
        </button>
        <Link href="/login" className="btn-secondary text-center">
          Volver al login
        </Link>
      </form>
    </div>
  );
}
