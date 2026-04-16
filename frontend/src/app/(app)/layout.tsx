import { Sidebar } from "@/components/Sidebar";

export default function AppLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <div className="min-h-screen w-full lg:grid lg:grid-cols-[260px_1fr]">
      <Sidebar />
      <main className="relative mx-auto flex w-full max-w-[1400px] flex-col gap-8 px-6 py-8 lg:px-12 lg:py-10">
        {children}
      </main>
    </div>
  );
}
