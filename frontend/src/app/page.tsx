"use client";

import { useState } from "react";
import { StockSearch } from "@/components/StockSearch";
import { PredictionCard } from "@/components/PredictionCard";
import { TopPredictions } from "@/components/TopPredictions";
import { ModeToggle } from "@/components/ModeToggle";
import { MetricsLegend } from "@/components/MetricsLegend";
import { useMode } from "@/lib/mode-context";

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
          <MetricsLegend />
        </div>
        <div className="mx-auto mt-6 max-w-md">
          <StockSearch onSelect={setSelectedTicker} />
        </div>
      </section>

      {/* Selected Stock Prediction */}
      {selectedTicker && (
        <section>
          <PredictionCard ticker={selectedTicker} />
        </section>
      )}

      {/* Dashboard — Single focused section */}
      <section>
        <h2 className="mb-4 text-lg font-semibold text-gray-900">
          {mode === "trader" ? "🔥 Top Trades This Week" : "📊 Best Opportunities This Week"}
        </h2>
        <TopPredictions />
      </section>
    </div>
  );
}
