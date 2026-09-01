export default function AuthLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    // Centred rather than pinned to the top: at 1440x900 the panels used to
    // sit in the upper third with an empty half-screen below them.
    <div className="flex min-h-screen w-full items-center justify-center px-5 py-10 sm:px-6">
      {children}
    </div>
  );
}
