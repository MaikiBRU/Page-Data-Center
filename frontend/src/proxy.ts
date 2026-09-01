import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Routing guard for the application shell.
 *
 * Next 16 renamed the `middleware` file convention to `proxy`; this runs on
 * the Node.js runtime before any route is rendered.
 *
 * Before this existed, /dashboard answered 200 with the full shell to anyone.
 * The bounce to /login only happened after hydration, when the sidebar's
 * /auth/me call came back 401 — so a first-time visitor arriving from the
 * portfolio saw the app flash and then a red "session expired" error for a
 * session they never had.
 *
 * This is a routing decision, not an authorisation one. It reads a cookie
 * that holds no credential and only says "this browser has some session".
 * Authorisation still happens in the API on every request, which re-reads the
 * bearer token and its session. A forged cookie buys nothing: the page loads
 * and every API call behind it returns 401.
 */

const SESSION_COOKIE = "dc_has_session";

const PROTECTED_PREFIXES = [
  "/dashboard",
  "/datasets",
  "/runs",
  "/cases",
  "/recommendations",
  "/users",
];

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  const isProtected = PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`)
  );
  if (!isProtected) {
    return NextResponse.next();
  }

  if (request.cookies.get(SESSION_COOKIE)?.value === "1") {
    return NextResponse.next();
  }

  // Send anonymous visitors to the demo entry point and remember where they
  // were headed so the sandbox can drop them there.
  const target = request.nextUrl.clone();
  target.pathname = "/demo";
  target.search = "";
  const wanted = `${pathname}${search}`;
  if (wanted !== "/dashboard") {
    target.searchParams.set("next", wanted);
  }
  return NextResponse.redirect(target);
}

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/datasets/:path*",
    "/runs/:path*",
    "/cases/:path*",
    "/recommendations/:path*",
    "/users/:path*",
  ],
};
