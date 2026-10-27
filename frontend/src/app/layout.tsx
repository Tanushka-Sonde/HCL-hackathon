import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { TenantProvider } from "@/components/TenantProvider";
import { Header } from "@/components/Header";
import { GoogleOAuthProvider } from "@react-oauth/google";
import { AuthProvider } from "@/lib/auth";
import { DEMO_MODE } from "@/lib/demo";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Knowledge Assistant",
  description: "Grounded answers with citations, SQL tool routing and per-query observability",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const page = (
    <TenantProvider>
      <Header />
      <main className="page-container">{children}</main>
    </TenantProvider>
  );
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body>
        {DEMO_MODE ? (
          // Demo mode: username/password sign-in against the knowledge service.
          <AuthProvider>{page}</AuthProvider>
        ) : (
          <GoogleOAuthProvider clientId={process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || ""}>{page}</GoogleOAuthProvider>
        )}
      </body>
    </html>
  );
}
