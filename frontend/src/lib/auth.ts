/**
 * Session token storage.
 *
 * The token itself stays in localStorage and travels in the Authorization
 * header, as before. Alongside it we set a value-free cookie so the Next.js
 * middleware can tell "somebody has a session" from "anonymous visitor" and
 * route accordingly. The cookie carries no credential and grants no access:
 * the API still validates the bearer token on every request. Its only job is
 * to stop the app shell from rendering to a visitor who would immediately be
 * bounced out with a scary "session expired" message.
 */

const TOKEN_KEY = "token";
const SESSION_COOKIE = "dc_has_session";

function writeSessionCookie(present: boolean) {
  if (typeof document === "undefined") return;
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  if (present) {
    document.cookie = `${SESSION_COOKIE}=1; Path=/; SameSite=Lax; Max-Age=86400${secure}`;
  } else {
    document.cookie = `${SESSION_COOKIE}=; Path=/; SameSite=Lax; Max-Age=0${secure}`;
  }
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
  writeSessionCookie(true);
}

export function getToken() {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function clearToken() {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    // ignore: storage may be unavailable in private mode
  }
  writeSessionCookie(false);
}
