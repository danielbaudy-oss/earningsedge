"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getUpcomingPredictions } from "@/lib/api";
import { PredictionCard } from "@/components/PredictionCard";
import {
  formatPercent,
  getRecommendationColor,
  getConfidenceColor,
} from "@/lib/utils";
import { TrendingUp, TrendingDown, AlertTriangle, Filter } from "lucide-react";

export default function PredictionsPage() {
  const [filter, setFilter] = useState<string | undefined>(undefined);
  const [minConfidence, setMinConfidence] = useState(0);

  const { data: predictions, isLoading } = useQuery({
    queryKey: ["predictions", filter, minConfidence],
    queryFn: () =>
      getUpcomingPredictions({
        recommendation: filter,
        min_confidence: minConfidence,
      }),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">
          Earnings Predictions
        </h1>
        <div className="flex items-center gap-3">
          <Filter className="h-4 w-4 text-gray-400" />
          {["buy", "sell", "avoid"].map((rec) => (
            <button
              key={rec}
              onClick={() => setFilter(filter === rec ? undefined : rec)}
              className={`badge cursor-pointer ${
                filter === rec
                  ? getRecommendationColor(rec)
                  : "border-gray-200 text-gray-500"
              }`}
            >
              {rec.toUpperCase()}
            </button>
          ))}
          <select
            value={minConfidence}
            onChange={(e) => setMinConfidence(Number(e.target.value))}
            className="rounded-lg border border-gray-200 px-3 py-1 text-sm"
            aria-label="Minimum confidence filter"
          >
            <option value={0}>All confidence</option>
            <option value={0.5}>50%+</option>
            <option value={0.7}>70%+</option>
            <option value={0.85}>85%+</option>
          </select>
        </div>
      </div>

      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="card animate-pulse">
              <div className="h-40 rounded bg-gray-100" />
            </div>
          ))}
        </div>
      ) : !predictions?.length ? (
        <div className="card py-12 text-center text-gray-500">
          No predictions match your filters
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {predictions.map((pred) => (
            <PredictionCard key={pred.id} ticker={pred.ticker} />
          ))}
        </div>
      )}
    </div>
  );
}
