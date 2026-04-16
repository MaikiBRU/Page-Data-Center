"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { setToken } from "@/lib/auth";
import { emitToast } from "@/lib/toast";

export default function GoogleCallbackPage() {
  const router = useRouter();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token");
    const needsPassword = params.get("needs_password_setup") === "1";

    if (token) {
      setToken(token);
      if (needsPassword) {
        emitToast({ message: "Cuenta vinculada. Creá tu contraseña.", kind: "info" });
        router.replace("/login?set=1");
      } else {
        emitToast({ message: "Sesión iniciada con Google.", kind: "success" });
        router.replace("/dashboard");
      }
      return;
    }

    router.replace("/login");
  }, [router]);

  return (
    <div className="panel mx-auto max-w-lg text-center text-sm text-[var(--muted)]">
      Procesando acceso con Google...
    </div>
  );
}
