"use client";

import { useState } from "react";
import { StockSearch } from "@/components/StockSearch";
import { PredictionCard } from "@/components/PredictionCard";
import { UpcomingEarnings } from "@/components/UpcomingEarnings";
import { TopPredictions } from "@/components/TopPredictions";

export default function Dashboard() {
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);

  return (
    <div className="space-y-8">
      {/* Hero / Search */}
      <section className="text-center">
        <h1 className="text-3xl font-bold text-gray-900">
          Should you hold through earnings?
        </h1>
        <p className="mt-2 text-gray-600">
          AI-powered predictions: Buy, Sell, or Avoid before earnings
        </p>
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
