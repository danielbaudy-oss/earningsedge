import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "EarningsEdge - AI Earnings Predictions",
  description:
    "AI-powered stock earnings predictions. Simple buy/sell/avoid recommendations for retail investors.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <Providers>
          <div className="min-h-screen">
            <nav className="border-b border-gray-200 bg-white">
              <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-4">
                <a href="/" className="text-xl font-bold text-gray-900">
                  Earnings<span className="text-green-600">Edge</span>
                </a>
                <div className="flex items-center gap-6">
                  <a href="/" className="text-sm text-gray-600 hover:text-gray-900">
                    Dashboard
                  </a>
                  <a href="/calendar" className="text-sm text-gray-600 hover:text-gray-900">
                    Calendar
                  </a>
                  <a href="/predictions" className="text-sm text-gray-600 hover:text-gray-900">
                    Predictions
                  </a>
                  <a href="/alerts" className="text-sm text-gray-600 hover:text-gray-900">
                    Alerts
                  </a>
                </div>
              </div>
            </nav>
            <main className="mx-auto max-w-7xl px-4 py-8">{children}</main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
