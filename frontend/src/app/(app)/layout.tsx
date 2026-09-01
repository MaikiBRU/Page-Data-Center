import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { DemoBanner } from "@/components/DemoBanner";
import { Sidebar } from "@/components/Sidebar";

/**
 * Routing guard for the application shell.
 *
 * This used to live in `src/proxy.ts` (Next 16's rename of `middleware.ts`),
 * but that file always runs on the Node.js runtime -- the `runtime` option is
 * rejected there -- and OpenNext for Cloudflare cannot deploy Node.js
 * middleware. The deploy failed with "Node.js middleware is not currently
 * supported", so the whole frontend was undeployable. Doing the same check in
 * this server component keeps the behaviour and works on Workers.
 *
 * The point of checking here rather than after hydration: /dashboard used to
 * answer 200 with the full shell to anyone, and the bounce to /login only
 * happened once the sidebar's /auth/me call came back 401. A first-time
 * visitor arriving from the portfolio saw the app flash and then a red
 * "session expired" error for a session they never had.
 *
 * This is a routing decision, not an authorisation one. The cookie holds no
 * credential and only says "this browser has some session". Authorisation
 * still happens in the API on every request, which re-reads the bearer token
 * and its session. A forged cookie buys nothing: the shell renders and every
 * API call behind it returns 401.
 */

const SESSION_COOKIE = "dc_has_session";

export default async function AppLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const cookieStore = await cookies();
  if (cookieStore.get(SESSION_COOKIE)?.value !== "1") {
    redirect("/demo");
  }

  return (
    <div className="min-h-screen w-full lg:grid lg:grid-cols-[260px_1fr]">
      <Sidebar />
      <main className="relative mx-auto flex w-full max-w-[1400px] flex-col gap-8 px-6 py-8 lg:px-12 lg:py-10">
        <DemoBanner />
        {children}
      </main>
    </div>
  );
}
