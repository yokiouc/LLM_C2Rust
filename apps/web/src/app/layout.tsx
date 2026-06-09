import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { Providers } from "@/components/providers";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "C2Rust Repair System",
  description: "Unsafe Rust repair automation dashboard",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <header className="border-b bg-background/95 backdrop-blur">
          <div className="mx-auto flex h-12 max-w-7xl items-center px-4">
            <Link href="/" className="text-sm font-semibold">C2Rust Repair</Link>
            <nav className="ml-8 flex gap-4 text-sm text-muted-foreground">
              <Link href="/" className="hover:text-foreground">Dashboard</Link>
              <Link href="/compare" className="hover:text-foreground">Compare</Link>
            </nav>
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">
          <Providers>{children}</Providers>
        </main>
      </body>
    </html>
  );
}
