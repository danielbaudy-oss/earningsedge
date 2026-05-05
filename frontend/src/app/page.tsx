"use client";

import { useState } from "react";
import { StockSearch } from "@/components/StockSearch";
import { PredictionCard } from "@/components/PredictionCard";
import { UpcomingEarnings } from "@/components/UpcomingEarnings";
import { TopPredictions } from "@/components/TopPredictions";
import { ModeToggle } from "@/components/ModeToggle";
import { MetricsLegend } from "@/components/MetricsLegend";

export default function Dashboard() {
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [mode, setMode] = useState<"trader" | "longterm">("trader");

  return (
    <div className="space-y-8">
      {/* Hero / Search */}
      <section className="text-center">
        <h1 className="text-3xl font-bold text-gray-900">
          Should you hold through earnings?
        </h1>
        <p className="mt-2 text-gray-600">
          {mode === "trader"
            ? "Short-term signals: buy before, sell after earnings"
            : "Long-term view: is this a quality compounder to hold?"}
        </p>
        <div className="mx-auto mt-4 flex items-center justify-center gap-4">
          <ModeToggle mode={mode} onChange={setMode} />
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
          <h2 className="mb-4 text-lg font-semibold text-gray-900">
            Top Predictions
          </h2>
          <TopPredictions />
        </section>

        <section>
          <h2 className="mb-4 text-lg font-semibold text-gray-900">
            Upcoming Earnings
          </h2>
          <UpcomingEarnings />
        </section>
      </div>
    </div>
  );
}
