"use client";

import { useState } from "react";
import { ModeProvider, useMode } from "@/lib/mode-context";
import { Menu, X } from "lucide-react";

function AppShellInner({ children }: { children: React.ReactNode }) {
  const { mode } = useMode();
  const [menuOpen, setMenuOpen] = useState(false);

  const bgClass = mode === "trader" ? "bg-gray-50" : "bg-blue-50";

  const links = [
    { href: "/", label: "Dashboard" },
    { href: "/calendar", label: "Calendar" },
    { href: "/predictions", label: "Predictions" },
    { href: "/alerts", label: "Alerts" },
    { href: "/metrics", label: "Metrics" },
  ];

  return (
    <div className={`min-h-screen transition-colors duration-300 ${bgClass}`}>
      <nav className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-4">
          <a href="/" className="text-xl font-bold text-gray-900">
            Earnings<span className={mode === "trader" ? "text-green-600" : "text-blue-600"}>Edge</span>
          </a>

          {/* Desktop nav */}
          <div className="hidden md:flex items-center gap-6">
            {links.map((link) => (
              <a key={link.href} href={link.href} className="text-sm text-gray-600 hover:text-gray-900">
                {link.label}
              </a>
            ))}
          </div>

          {/* Mobile hamburger */}
          <button
            onClick={() => setMenuOpen(!menuOpen)}
            className="md:hidden p-2 rounded-lg hover:bg-gray-100"
            aria-label="Toggle menu"
          >
            {menuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>

        {/* Mobile menu */}
        {menuOpen && (
          <div className="md:hidden border-t border-gray-100 bg-white px-4 py-3">
            {links.map((link) => (
              <a
                key={link.href}
                href={link.href}
                className="block py-2.5 text-sm text-gray-700 hover:text-gray-900"
                onClick={() => setMenuOpen(false)}
              >
                {link.label}
              </a>
            ))}
          </div>
        )}
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
