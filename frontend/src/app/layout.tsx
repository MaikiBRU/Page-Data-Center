import type { Metadata } from "next";
import { Manrope, Sora } from "next/font/google";
import "./globals.css";
import { ToastHost } from "@/components/ToastHost";

const sora = Sora({
  variable: "--font-display",
  subsets: ["latin"],
});

const manrope = Manrope({
  variable: "--font-body",
  subsets: ["latin"],
});

const DESCRIPTION =
  "Demo de portfolio: plataforma de calidad de datos para ecommerce y logistica. " +
  "Validacion de esquema, reglas por dominio, deteccion de outliers y gestion de " +
  "incidencias con SLA. Se prueba sin registro.";

export const metadata: Metadata = {
  // "%s" is filled by each page's own title; the demo landing sets one.
  title: {
    default: "Data Center — Calidad de datos (demo)",
    template: "%s | Data Center",
  },
  description: DESCRIPTION,
  applicationName: "Data Center",
  // Shown when the portfolio link is pasted into a chat or a social card.
  openGraph: {
    type: "website",
    siteName: "Data Center",
    title: "Data Center — Calidad de datos (demo)",
    description: DESCRIPTION,
    locale: "es_AR",
  },
  twitter: {
    card: "summary",
    title: "Data Center — Calidad de datos (demo)",
    description: DESCRIPTION,
  },
  // A demo instance holds throwaway data and has no business being indexed.
  robots: { index: false, follow: false },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="es"
      className={`${sora.variable} ${manrope.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        {children}
        <ToastHost />
      </body>
    </html>
  );
}
