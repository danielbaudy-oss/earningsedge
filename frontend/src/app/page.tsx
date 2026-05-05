"use client";

import { useState } from "react";
import { StockSearch } from "@/components/StockSearch";
import { PredictionCard } from "@/components/PredictionCard";
import { UpcomingEarnings } from "@/components/UpcomingEarnings";
import { TopPredictions } from "@/components/TopPredictions";
import { ModeToggle } from "@/components/ModeToggle";
import { MetricsLegend } from "@/components/MetricsLegend";
import { useMode } from "@/lib/mode-context";

export default function Dashboard() {
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const { mode } = useMode();

  const headingColor = mode === "trader" ? "text-white" : "text-gray-900";
  const subColor = mode === "trader" ? "text-gray-400" : "text-gray-600";
  const sectionHeading = mode === "trader" ? "text-gray-100" : "text-gray-900";
  const cardBg = mode === "trader" ? "bg-gray-800 border-gray-700" : "";

  return (
    <div className="space-y-8">
      {/* Hero / Search */}
      <section className="text-center">
        <h1 className={`text-3xl font-bold ${headingColor}`}>
          {mode === "trader"
            ? "What's the play before earnings?"
            : "Should you hold through earnings?"}
        </h1>
        <p className={`mt-2 ${subColor}`}>
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

      {/* Dashboard Grid */}
      <div className="grid gap-8 lg:grid-cols-2">
        <section>
          <h2 className={`mb-4 text-lg font-semibold ${sectionHeading}`}>
            {mode === "trader" ? "🔥 Top Trades" : "📊 Top Predictions"}
          </h2>
          <TopPredictions />
        </section>

        <section>
          <h2 className={`mb-4 text-lg font-semibold ${sectionHeading}`}>
            {mode === "trader" ? "⏰ Reporting Soon" : "📅 Upcoming Earnings"}
          </h2>
          <UpcomingEarnings />
        </section>
      </div>
    </div>
  );
}
