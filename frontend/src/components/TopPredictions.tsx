"use client";

import { useQuery } from "@tanstack/react-query";
import { getUpcomingPredictions } from "@/lib/api";
import {
  formatPercent,
  getRecommendationColor,
  getConfidenceColor,
} from "@/lib/utils";
import { TrendingUp, TrendingDown, AlertTriangle } from "lucide-react";

export function TopPredictions() {
  const { data: predictions, isLoading } = useQuery({
    queryKey: ["topPredictions"],
    queryFn: () => getUpcomingPredictions({ min_confidence: 0.5 }),
  });

  if (isLoading) {
    return (
      <div className="card animate-pulse">
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-16 rounded bg-gray-100" />
          ))}
        </div>
      </div>
    );
  }

  if (!predictions?.length) {
    return (
      <div className="card text-center text-gray-500">
        No high-confidence predictions available
      </div>
    );
  }

  const recIcon = {
    buy: <TrendingUp className="h-4 w-4" />,
    sell: <TrendingDown className="h-4 w-4" />,
    avoid: <AlertTriangle className="h-4 w-4" />,
  };

  return (
    <div className="card">
      <div className="divide-y divide-gray-100">
        {predictions.slice(0, 8).map((pred) => (
          <div key={pred.id} className="flex items-center justify-between py-3">
            <div className="flex items-center gap-3">
              <span
                className={`badge ${getRecommendationColor(pred.recommendation)}`}
              >
                {recIcon[pred.recommendation]}
                <span className="ml-1 uppercase">{pred.recommendation}</span>
              </span>
              <div>
                <p className="font-medium text-gray-900">{pred.ticker}</p>
                <p className="text-xs text-gray-500">
                  Earnings: {pred.earnings_date}
                </p>
              </div>
            </div>
            <div className="text-right">
              <p
                className={`text-sm font-semibold ${getConfidenceColor(pred.confidence_score)}`}
              >
                {(pred.confidence_score * 100).toFixed(0)}% conf
              </p>
              <p className="text-xs text-gray-500">
                {formatPercent(pred.expected_move_pct)} expected
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
