"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getWatchlist } from "@/lib/api";
import { formatPercent } from "@/lib/utils";
import { PredictionCard } from "@/components/PredictionCard";
import { Rocket, Calendar, X } from "lucide-react";

export function Watchlist() {
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);

  const { data: picks, isLoading } = useQuery({
    queryKey: ["watchlist"],
    queryFn: getWatchlist,
  });

  if (isLoading) {
    return (
      <div className="card animate-pulse">
        <div className="space-y-4">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-20 rounded-lg bg-gray-100" />
          ))}
        </div>
      </div>
    );
  }

  if (!picks?.length) {
    return (
      <div className="card text-center text-gray-500">
        No high-conviction picks for the next month yet
      </div>
    );
  }

  return (
    <>
      <div className="card">
        <div className="space-y-3">
          {picks.map((pred, i) => (
            <button
              key={pred.id}
              onClick={() => setSelectedTicker(pred.ticker ?? null)}
              className="flex w-full items-center gap-4 rounded-lg border border-gray-100 p-4 text-left hover:border-green-200 hover:bg-green-50/50 transition"
            >
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-green-100 text-green-700 text-sm font-bold">
                {i + 1}
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-bold text-gray-900">{pred.ticker}</span>
                  <span className="text-xs text-gray-500">{pred.company_name}</span>
                </div>
                <div className="mt-1 flex items-center gap-3 text-xs text-gray-500">
                  <span className="flex items-center gap-1">
                    <Calendar className="h-3 w-3" />
                    Reports: {pred.earnings_date}
                  </span>
                  <span>Score: {(pred.confidence_score * 100).toFixed(0)}%</span>
                </div>
              </div>
              <div className="text-right">
                <p className="text-lg font-bold text-green-700">
                  {formatPercent(pred.expected_move_pct)}
                </p>
                <p className="text-xs text-gray-400">expected</p>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Popup Modal */}
      {selectedTicker && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={() => setSelectedTicker(null)}
        >
          <div className="relative w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
            <button
              onClick={() => setSelectedTicker(null)}
              className="absolute -top-3 -right-3 z-10 rounded-full bg-white p-1.5 shadow-lg hover:bg-gray-100"
              aria-label="Close"
            >
              <X className="h-4 w-4 text-gray-600" />
            </button>
            <PredictionCard ticker={selectedTicker} />
          </div>
        </div>
      )}
    </>
  );
}
