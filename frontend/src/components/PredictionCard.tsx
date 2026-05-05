"use client";

import { useQuery } from "@tanstack/react-query";
import { getPrediction } from "@/lib/api";
import {
  formatPercent,
  getRecommendationColor,
  getConfidenceColor,
} from "@/lib/utils";
import { TrendingUp, TrendingDown, AlertTriangle, Info } from "lucide-react";

interface PredictionCardProps {
  ticker: string;
}

export function PredictionCard({ ticker }: PredictionCardProps) {
  const { data: prediction, isLoading, error } = useQuery({
    queryKey: ["prediction", ticker],
    queryFn: () => getPrediction(ticker),
  });

  if (isLoading) {
    return (
      <div className="card animate-pulse">
        <div className="h-32 rounded bg-gray-100" />
      </div>
    );
  }

  if (error || !prediction) {
    return (
      <div className="card text-center text-gray-500">
        <p>No prediction available for {ticker}</p>
      </div>
    );
  }

  const recIcon = {
    buy: <TrendingUp className="h-6 w-6" />,
    sell: <TrendingDown className="h-6 w-6" />,
    avoid: <AlertTriangle className="h-6 w-6" />,
  };

  return (
    <div className="card">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-lg font-bold text-gray-900">
            {prediction.ticker}
          </h3>
          <p className="text-sm text-gray-500">{prediction.company_name}</p>
          {prediction.earnings_date && (
            <p className="mt-1 text-xs text-gray-400">
              Earnings: {prediction.earnings_date}
            </p>
          )}
        </div>

        {/* Recommendation Badge */}
        <div
          className={`badge text-lg font-bold uppercase ${getRecommendationColor(prediction.recommendation)}`}
        >
          {recIcon[prediction.recommendation]}
          <span className="ml-2">{prediction.recommendation}</span>
        </div>
      </div>

      {/* Metrics Grid */}
      <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div>
          <p className="text-xs text-gray-500">Beat Probability</p>
          <p className="text-lg font-semibold">
            {prediction.beat_probability
              ? `${(prediction.beat_probability * 100).toFixed(0)}%`
              : "—"}
          </p>
        </div>
        <div>
          <p className="text-xs text-gray-500">Price Up Probability</p>
          <p className="text-lg font-semibold">
            {prediction.price_up_probability
              ? `${(prediction.price_up_probability * 100).toFixed(0)}%`
              : "—"}
          </p>
        </div>
        <div>
          <p className="text-xs text-gray-500">Expected Move</p>
          <p className="text-lg font-semibold">
            {formatPercent(prediction.expected_move_pct)}
          </p>
        </div>
        <div>
          <p className="text-xs text-gray-500">Confidence</p>
          <p
            className={`text-lg font-semibold ${getConfidenceColor(prediction.confidence_score)}`}
          >
            {(prediction.confidence_score * 100).toFixed(0)}%
          </p>
        </div>
      </div>

      {/* Explanation */}
      {prediction.explanation_text && (
        <div className="mt-6 rounded-lg bg-gray-50 p-4">
          <div className="flex items-center gap-2 text-sm font-medium text-gray-700">
            <Info className="h-4 w-4" />
            Why this prediction?
          </div>
          <p className="mt-2 whitespace-pre-line text-sm text-gray-600">
            {prediction.explanation_text}
          </p>
        </div>
      )}

      {/* Feature Importance */}
      {prediction.feature_importance && (
        <div className="mt-4">
          <p className="text-xs font-medium text-gray-500">Key Factors</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {Object.entries(prediction.feature_importance).map(
              ([feature, impact]) => (
                <span
                  key={feature}
                  className={`rounded-full px-2 py-1 text-xs ${
                    impact > 0
                      ? "bg-green-50 text-green-700"
                      : "bg-red-50 text-red-700"
                  }`}
                >
                  {feature.replace(/_/g, " ")} ({impact > 0 ? "+" : ""}
                  {impact.toFixed(3)})
                </span>
              )
            )}
          </div>
        </div>
      )}
    </div>
  );
}
