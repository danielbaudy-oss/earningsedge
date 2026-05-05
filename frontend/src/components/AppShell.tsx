"use client";

import { ModeProvider, useMode } from "@/lib/mode-context";

function AppShellInner({ children }: { children: React.ReactNode }) {
  const { mode } = useMode();

  const bgClass = mode === "trader"
    ? "bg-gray-900 text-gray-100"
    : "bg-slate-50 text-gray-900";

  const navClass = mode === "trader"
    ? "border-b border-gray-700 bg-gray-950"
    : "border-b border-gray-200 bg-white";

  const linkClass = mode === "trader"
    ? "text-sm text-gray-400 hover:text-white"
    : "text-sm text-gray-600 hover:text-gray-900";

  const logoAccent = mode === "trader" ? "text-emerald-400" : "text-green-600";

  return (
    <div className={`min-h-screen transition-colors duration-300 ${bgClass} ${mode === "trader" ? "dark-mode" : ""}`}>
      <nav className={`${navClass} transition-colors duration-300`}>
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-4">
          <a href="/" className="text-xl font-bold">
            Earnings<span className={logoAccent}>Edge</span>
          </a>
          <div className="flex items-center gap-6">
            <a href="/" className={linkClass}>Dashboard</a>
            <a href="/calendar" className={linkClass}>Calendar</a>
            <a href="/predictions" className={linkClass}>Predictions</a>
            <a href="/alerts" className={linkClass}>Alerts</a>
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
