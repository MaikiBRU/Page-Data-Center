"use client";

import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";
import { emitToast } from "@/lib/toast";
import { EmptyState } from "@/components/EmptyState";

type UserRow = {
  id: number;
  email: string;
  is_active: boolean;
  is_verified: boolean;
  is_admin: boolean;
  role: string;
  created_at: string;
};

type Me = {
  id: number;
  email: string;
  is_admin: boolean;
  role?: string;
};

type AuditLog = {
  id: number;
  action: string;
  actor_email: string | null;
  target_email: string | null;
  meta: Record<string, unknown> | null;
  created_at: string;
};

export default function UsersPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newConfirm, setNewConfirm] = useState("");
  const [newAdmin, setNewAdmin] = useState(false);
  const [newRole, setNewRole] = useState("viewer");
  const [resetTarget, setResetTarget] = useState<UserRow | null>(null);
  const [confirmResetTarget, setConfirmResetTarget] = useState<UserRow | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [resetConfirm, setResetConfirm] = useState("");
  const [resetting, setResetting] = useState(false);
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [confirmAction, setConfirmAction] = useState<{
    type: "toggle_active" | "toggle_admin";
    user: UserRow;
  } | null>(null);

  const load = async () => {
    setError(null);
    try {
      const meResp = await apiFetch<Me>("/auth/me");
      setMe(meResp);
      if (!meResp.is_admin) {
        setUsers([]);
        return;
      }
      const list = await apiFetch<UserRow[]>("/users");
      setUsers(list);
      const audit = await apiFetch<AuditLog[]>("/users/audit?limit=50");
      setLogs(audit);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const sorted = useMemo(
    () => [...users].sort((a, b) => (a.created_at < b.created_at ? 1 : -1)),
    [users]
  );

  const updateUser = async (id: number, patch: Partial<UserRow>) => {
    try {
      const updated = await apiFetch<UserRow>(`/users/${id}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      setUsers((prev) => prev.map((user) => (user.id === id ? updated : user)));
      emitToast({ message: "Usuario actualizado.", kind: "success" });
    } catch (err) {
      const message = (err as Error).message;
      setError(message);
      emitToast({ message, kind: "error" });
    }
  };

  const confirmTitle = () => {
    if (!confirmAction) return "";
    if (confirmAction.type === "toggle_active") {
      return confirmAction.user.is_active ? "Dar de baja usuario" : "Reactivar usuario";
    }
    return confirmAction.user.is_admin ? "Quitar rol admin" : "Hacer administrador";
  };

  const confirmText = () => {
    if (!confirmAction) return "";
    if (confirmAction.type === "toggle_active") {
      return confirmAction.user.is_active
        ? "El usuario perderá acceso al sistema hasta que lo reactives."
        : "El usuario podrá iniciar sesión nuevamente.";
    }
    return confirmAction.user.is_admin
      ? "El usuario dejará de tener permisos administrativos."
      : "El usuario tendrá permisos administrativos completos.";
  };

  const handleConfirm = async () => {
    if (!confirmAction) return;
    if (confirmAction.type === "toggle_active") {
      await updateUser(confirmAction.user.id, {
        is_active: !confirmAction.user.is_active,
      });
    } else {
      await updateUser(confirmAction.user.id, {
        is_admin: !confirmAction.user.is_admin,
      });
    }
    setConfirmAction(null);
  };

  const adminCount = users.filter((user) => user.is_admin).length;

  const handleCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    if (newPassword !== newConfirm) {
      setError("Las contraseñas no coinciden");
      return;
    }
    setCreating(true);
    try {
      const created = await apiFetch<UserRow>("/users", {
        method: "POST",
        body: JSON.stringify({
          email: newEmail,
          password: newPassword,
          is_admin: newAdmin,
          role: newRole,
        }),
      });
      setUsers((prev) => [created, ...prev]);
      setNewEmail("");
      setNewPassword("");
      setNewConfirm("");
      setNewAdmin(false);
      setNewRole("viewer");
      emitToast({ message: "Usuario creado correctamente.", kind: "success" });
    } catch (err) {
      const message = (err as Error).message;
      setError(message);
      emitToast({ message, kind: "error" });
    } finally {
      setCreating(false);
    }
  };

  const handleReset = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!resetTarget) return;
    if (resetPassword !== resetConfirm) {
      setError("Las contraseñas no coinciden");
      return;
    }
    setResetting(true);
    try {
      await apiFetch(`/users/${resetTarget.id}/reset-password`, {
        method: "POST",
        body: JSON.stringify({ password: resetPassword }),
      });
      setResetTarget(null);
      setResetPassword("");
      setResetConfirm("");
      emitToast({ message: "Contraseña reseteada.", kind: "success" });
    } catch (err) {
      const message = (err as Error).message;
      setError(message);
      emitToast({ message, kind: "error" });
    } finally {
      setResetting(false);
    }
  };

  if (loading) {
    return (
      <section className="panel">
        <p className="text-sm text-[var(--muted)]">Cargando usuarios...</p>
      </section>
    );
  }

  if (!me?.is_admin) {
    return (
      <section className="panel">
        <h2 className="text-xl font-semibold">Usuarios</h2>
        <p className="mt-2 text-sm text-[var(--muted)]">
          Esta sección es solo para administradores.
        </p>
      </section>
    );
  }

  const renderAction = (log: AuditLog) => {
    switch (log.action) {
      case "user_create":
        return "Alta usuario";
      case "user_update":
        return "Edición usuario";
      case "user_reset_password":
        return "Reset contraseña";
      case "password_reset_request":
        return "Solicitud reset";
      case "password_reset_complete":
        return "Reset completado";
      case "permission_denied":
        return "Permiso denegado";
      default:
        return log.action;
    }
  };

  const renderDetails = (log: AuditLog) => {
    if (!log.meta) return "-";
    if (log.action === "user_update" && typeof log.meta === "object") {
      const changes = (log.meta as { changes?: Record<string, { from: boolean; to: boolean }> })
        .changes;
      if (!changes) return "-";
      const parts = Object.entries(changes).map(
        ([key, value]) => `${key}: ${value.from ? "sí" : "no"} → ${value.to ? "sí" : "no"}`
      );
      return parts.join(" | ");
    }
    if (log.action === "user_create") {
      const isAdmin = (log.meta as { is_admin?: boolean })?.is_admin;
      return `Admin: ${isAdmin ? "sí" : "no"}`;
    }
    if (log.action === "permission_denied" && log.meta) {
      const action = (log.meta as { action?: string }).action ?? "-";
      const path = (log.meta as { path?: string }).path ?? "-";
      return `${action} · ${path}`;
    }
    return "-";
  };

  return (
    <section className="panel flex flex-col gap-6">
      <header>
        <h2 className="text-2xl font-semibold">Usuarios</h2>
        <p className="mt-2 text-sm text-[var(--muted)]">
          Administrá accesos, roles y estado de cada cuenta.
        </p>
      </header>

      {error && <p className="text-sm text-[var(--danger)]">{error}</p>}

      <form
        id="user-create"
        onSubmit={handleCreate}
        className="grid gap-4 rounded-2xl border border-white/10 bg-white/5 p-5"
      >
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-white/40">Nuevo usuario</p>
          <p className="mt-2 text-sm text-[var(--muted)]">
            Creá un usuario interno con contraseña y rol.
          </p>
        </div>
        <div className="grid gap-3 lg:grid-cols-2">
          <label className="text-sm text-white/70">
            Email
            <input
              className="input-base mt-2"
              type="email"
              value={newEmail}
              onChange={(event) => setNewEmail(event.target.value)}
              required
            />
          </label>
          <label className="text-sm text-white/70">
            Contraseña
            <input
              className="input-base mt-2"
              type="password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              maxLength={128}
              required
            />
          </label>
          <label className="text-sm text-white/70">
            Confirmar contraseña
            <input
              className="input-base mt-2"
              type="password"
              value={newConfirm}
              onChange={(event) => setNewConfirm(event.target.value)}
              maxLength={128}
              required
            />
          </label>
          <label className="flex items-center gap-3 text-sm text-white/70">
            <input
              type="checkbox"
              className="h-4 w-4 accent-[var(--accent)]"
              checked={newAdmin}
              onChange={(event) => {
                const next = event.target.checked;
                setNewAdmin(next);
                if (next) setNewRole("admin");
                if (!next && newRole === "admin") setNewRole("viewer");
              }}
            />
            Crear como administrador
          </label>
          <label className="text-sm text-white/70">
            Rol
            <select
              className="input-base mt-2"
              value={newRole}
              onChange={(event) => setNewRole(event.target.value)}
              disabled={newAdmin}
            >
              <option value="viewer">Viewer</option>
              <option value="analyst">Analyst</option>
              <option value="admin">Admin</option>
            </select>
          </label>
        </div>
        <div className="flex justify-end">
          <button className="btn-primary" type="submit" disabled={creating}>
            {creating ? "Creando..." : "Crear usuario"}
          </button>
        </div>
      </form>

      <div className="scroll-soft overflow-auto rounded-2xl border border-white/10">
        <table className="table-base text-sm">
          <thead>
            <tr>
              <th className="px-4 py-3">Email</th>
              <th className="px-4 py-3">Estado</th>
              <th className="px-4 py-3">Rol</th>
              <th className="px-4 py-3">Creado</th>
              <th className="px-4 py-3 text-right">Acciones</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((user) => (
              <tr key={user.id}>
                <td className="px-4 py-3">
                  <div className="text-white/90">{user.email}</div>
                  <div className="text-xs text-white/40">
                    {user.is_verified ? "Verificado" : "Sin verificar"}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span
                    className={
                      user.is_active
                        ? "badge"
                        : "badge border-[var(--danger)]/50 bg-[var(--danger)]/10 text-[var(--danger)]"
                    }
                  >
                    {user.is_active ? "Activo" : "Suspendido"}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <span
                    className={
                      user.is_admin
                        ? "badge"
                        : "badge border-white/15 bg-white/5 text-white/60"
                    }
                  >
                    {user.is_admin ? "Admin" : user.role === "analyst" ? "Analyst" : "Viewer"}
                  </span>
                </td>
                <td className="px-4 py-3 text-white/60">
                  {new Date(user.created_at).toLocaleDateString("es-AR")}
                </td>
                <td className="px-4 py-3">
                  <div className="flex justify-end gap-2">
                    <button
                      type="button"
                      className="btn-mini"
                      onClick={() => setConfirmAction({ type: "toggle_active", user })}
                    >
                      {user.is_active ? "Dar de baja" : "Dar de alta"}
                    </button>
                    <button
                      type="button"
                      className="btn-mini"
                      onClick={() => setConfirmAction({ type: "toggle_admin", user })}
                    >
                      {user.is_admin ? "Quitar admin" : "Hacer admin"}
                    </button>
                    {!user.is_admin && (
                      <select
                        className="input-base h-8 w-28 text-xs"
                        value={user.role}
                        onChange={(event) =>
                          updateUser(user.id, { role: event.target.value })
                        }
                      >
                        <option value="viewer">Viewer</option>
                        <option value="analyst">Analyst</option>
                      </select>
                    )}
                    <button
                      type="button"
                      className="btn-mini"
                      onClick={() => setConfirmResetTarget(user)}
                    >
                      Reset contraseña
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {sorted.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-sm text-[var(--muted)]">
                  <EmptyState
                    title="No hay usuarios para mostrar."
                    description="Creá el primer usuario para habilitar asignaciones."
                    actions={[
                      {
                        label: "Crear usuario",
                        href: "#user-create",
                        variant: "primary",
                      },
                    ]}
                    compact
                  />
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="scroll-soft overflow-auto rounded-2xl border border-white/10">
        <div className="border-b border-white/10 px-4 py-3">
          <h3 className="text-lg font-semibold">Auditoría</h3>
          <p className="text-sm text-[var(--muted)]">
            Últimas acciones administrativas sobre usuarios.
          </p>
        </div>
        <table className="table-base text-sm">
          <thead>
            <tr>
              <th className="px-4 py-3">Fecha</th>
              <th className="px-4 py-3">Actor</th>
              <th className="px-4 py-3">Acción</th>
              <th className="px-4 py-3">Usuario</th>
              <th className="px-4 py-3">Detalle</th>
            </tr>
          </thead>
          <tbody>
            {logs.map((log) => (
              <tr key={log.id}>
                <td className="px-4 py-3 text-white/60">
                  {new Date(log.created_at).toLocaleString("es-AR")}
                </td>
                <td className="px-4 py-3">{log.actor_email ?? "-"}</td>
                <td className="px-4 py-3">{renderAction(log)}</td>
                <td className="px-4 py-3">{log.target_email ?? "-"}</td>
                <td className="px-4 py-3 text-white/60">{renderDetails(log)}</td>
              </tr>
            ))}
            {logs.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-sm text-[var(--muted)]">
                  <EmptyState
                    title="No hay acciones registradas todavía."
                    description="Cuando crees o edites usuarios, las acciones aparecerán aquí."
                    actions={[
                      {
                        label: "Crear usuario",
                        href: "#user-create",
                        variant: "secondary",
                      },
                    ]}
                    compact
                  />
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {resetTarget && (
        <div className="modal-backdrop">
          <form
            onSubmit={handleReset}
            className="modal-panel max-w-lg space-y-4"
          >
            <div>
              <h3 className="text-xl font-semibold">Resetear contraseña</h3>
              <p className="mt-2 text-sm text-[var(--muted)]">
                Usuario: {resetTarget.email}
              </p>
            </div>
            <label className="text-sm text-white/70">
              Nueva contraseña
              <input
                className="input-base mt-2"
                type="password"
                value={resetPassword}
                onChange={(event) => setResetPassword(event.target.value)}
                maxLength={128}
                required
              />
            </label>
            <label className="text-sm text-white/70">
              Confirmar contraseña
              <input
                className="input-base mt-2"
                type="password"
                value={resetConfirm}
                onChange={(event) => setResetConfirm(event.target.value)}
                maxLength={128}
                required
              />
            </label>
            <div className="flex justify-end gap-3">
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setResetTarget(null)}
              >
                Cancelar
              </button>
              <button className="btn-primary" type="submit" disabled={resetting}>
                {resetting ? "Guardando..." : "Guardar"}
              </button>
            </div>
          </form>
        </div>
      )}

      {confirmAction && (
        <div className="modal-backdrop">
          <div className="modal-panel max-w-md space-y-4">
            <div>
              <h3 className="text-lg font-semibold">{confirmTitle()}</h3>
              <p className="mt-2 text-sm text-[var(--muted)]">{confirmText()}</p>
              <p className="mt-2 text-xs text-white/50">
                Usuario: {confirmAction.user.email}
              </p>
            </div>
            {confirmAction.type === "toggle_admin" &&
              confirmAction.user.is_admin &&
              adminCount <= 1 && (
                <p className="text-sm text-[var(--danger)]">
                  No podés quitar el último administrador.
                </p>
              )}
            <div className="flex justify-end gap-3">
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setConfirmAction(null)}
              >
                Cancelar
              </button>
              <button
                type="button"
                className="btn-primary"
                onClick={handleConfirm}
                disabled={
                  confirmAction.type === "toggle_admin" &&
                  confirmAction.user.is_admin &&
                  adminCount <= 1
                }
              >
                Confirmar
              </button>
            </div>
          </div>
        </div>
      )}

      {confirmResetTarget && (
        <div className="modal-backdrop">
          <div className="modal-panel max-w-md space-y-4">
            <div>
              <h3 className="text-lg font-semibold">Resetear contraseña</h3>
              <p className="mt-2 text-sm text-[var(--muted)]">
                Se invalidarán todas las sesiones activas del usuario.
              </p>
              <p className="mt-2 text-xs text-white/50">
                Usuario: {confirmResetTarget.email}
              </p>
            </div>
            <div className="flex justify-end gap-3">
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setConfirmResetTarget(null)}
              >
                Cancelar
              </button>
              <button
                type="button"
                className="btn-primary"
                onClick={() => {
                  setResetTarget(confirmResetTarget);
                  setConfirmResetTarget(null);
                }}
              >
                Continuar
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
