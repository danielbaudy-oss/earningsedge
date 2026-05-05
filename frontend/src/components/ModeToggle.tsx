"use client";

import { useMode } from "@/lib/mode-context";
import { TrendingUp, Clock } from "lucide-react";

export function ModeToggle() {
  const { mode, setMode } = useMode();

  return (
    <div className={`flex items-center gap-1 rounded-lg p-1 ${
      mode === "trader" ? "border border-gray-700 bg-gray-800" : "border border-gray-200 bg-white"
    }`}>
      <button
        onClick={() => setMode("trader")}
        className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition ${
          mode === "trader"
            ? "bg-emerald-500 text-white shadow-sm"
            : "text-gray-500 hover:text-gray-700"
        }`}
      >
        <TrendingUp className="h-3.5 w-3.5" />
        Trader
      </button>
      <button
        onClick={() => setMode("longterm")}
        className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition ${
          mode === "longterm"
            ? "bg-blue-600 text-white shadow-sm"
            : "text-gray-500 hover:text-gray-700"
        }`}
      >
        <Clock className="h-3.5 w-3.5" />
        Long-term
      </button>
    </div>
  );
}
