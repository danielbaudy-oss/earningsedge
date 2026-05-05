"use client";

import { useState } from "react";
import { StockSearch } from "@/components/StockSearch";
import { PredictionCard } from "@/components/PredictionCard";
import { TopPredictions } from "@/components/TopPredictions";
import { Watchlist } from "@/components/Watchlist";
import { ModeToggle } from "@/components/ModeToggle";
import { useMode } from "@/lib/mode-context";
import { X } from "lucide-react";

export default function Dashboard() {
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const { mode } = useMode();

  return (
    <div className="space-y-8">
      {/* Hero / Search */}
      <section className="text-center">
        <h1 className="text-3xl font-bold text-gray-900">
          {mode === "trader"
            ? "What's the play before earnings?"
            : "Should you hold through earnings?"}
        </h1>
        <p className="mt-2 text-gray-600">
          {mode === "trader"
            ? "Short-term signals — buy before, sell after"
            : "Long-term view — quality compounders to hold"}
        </p>
        <div className="mx-auto mt-4 flex items-center justify-center gap-4">
          <ModeToggle />
        </div>
        <div className="mx-auto mt-6 max-w-md">
          <StockSearch onSelect={setSelectedTicker} />
        </div>
      </section>

      {/* Selected Stock Prediction */}
      {selectedTicker && (
        <section className="relative">
          <button
            onClick={() => setSelectedTicker(null)}
            className="absolute -top-2 right-0 z-10 rounded-full bg-white border border-gray-200 p-1.5 shadow-sm hover:bg-gray-100"
            aria-label="Close"
          >
            <X className="h-4 w-4 text-gray-500" />
          </button>
          <PredictionCard ticker={selectedTicker} />
        </section>
      )}

      {/* Dashboard — Top Trades + Watchlist */}
      <div className="grid gap-8 lg:grid-cols-2">
        <section>
          <h2 className="mb-4 text-lg font-semibold text-gray-900">
            {mode === "trader" ? "Top Trades Next 7 Days" : "Best Opportunities Next 7 Days"}
          </h2>
          <TopPredictions />
        </section>

        <section>
          <h2 className="mb-4 text-lg font-semibold text-gray-900">
            Top Picks Next 30 Days
          </h2>
          <Watchlist />
        </section>
      </div>
    </div>
  );
}
