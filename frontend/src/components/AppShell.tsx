"use client";

import { ModeProvider, useMode } from "@/lib/mode-context";

function AppShellInner({ children }: { children: React.ReactNode }) {
  const { mode } = useMode();

  const bgClass = mode === "trader"
    ? "bg-gray-50"
    : "bg-blue-50";

  return (
    <div className={`min-h-screen transition-colors duration-300 ${bgClass}`}>
      <nav className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-4">
          <a href="/" className="text-xl font-bold text-gray-900">
            Earnings<span className={mode === "trader" ? "text-green-600" : "text-blue-600"}>Edge</span>
          </a>
          <div className="flex items-center gap-6">
            <a href="/" className="text-sm text-gray-600 hover:text-gray-900">Dashboard</a>
            <a href="/calendar" className="text-sm text-gray-600 hover:text-gray-900">Calendar</a>
            <a href="/predictions" className="text-sm text-gray-600 hover:text-gray-900">Predictions</a>
            <a href="/alerts" className="text-sm text-gray-600 hover:text-gray-900">Alerts</a>
            <a href="/metrics" className="text-sm text-gray-600 hover:text-gray-900">Metrics</a>
          </div>
        </div>
      </nav>
      <main className="mx-auto max-w-7xl px-4 py-8">{children}</main>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <ModeProvider>
      <AppShellInner>{children}</AppShellInner>
    </ModeProvider>
  );
}
