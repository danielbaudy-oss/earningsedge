"use client";

import { useQuery } from "@tanstack/react-query";
import { getPrediction } from "@/lib/api";
import { formatPercent, getRecommendationColor } from "@/lib/utils";
import { useMode } from "@/lib/mode-context";
import { TrendingUp, TrendingDown, AlertTriangle, Info, Shield, Target } from "lucide-react";

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

  const { mode } = useMode();
  const cardClass = mode === "trader"
    ? "rounded-xl border border-gray-700 bg-gray-800 p-6 shadow-lg"
    : "card";
  const textPrimary = mode === "trader" ? "text-white" : "text-gray-900";
  const textSecondary = mode === "trader" ? "text-gray-400" : "text-gray-500";
  const textMuted = mode === "trader" ? "text-gray-500" : "text-gray-400";
  const metricBg = mode === "trader" ? "bg-gray-900" : "bg-gray-50";
  const reasonBg = mode === "trader" ? "border-gray-700 bg-gray-900" : "border-gray-100 bg-white";

  const totalScore = prediction.feature_importance?.total_score;
  const riskScore = prediction.feature_importance?.risk_score;
  const topReasons = prediction.feature_importance?.top_reasons as string[] | undefined;

  // Expected move color
  const moveColor = (prediction.expected_move_pct ?? 0) >= 0
    ? "text-green-700"
    : "text-red-700";

  return (
    <div className={cardClass}>
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h3 className={`text-lg font-bold ${textPrimary}`}>
            {prediction.ticker}
          </h3>
          <p className={`text-sm ${textSecondary}`}>{prediction.company_name}</p>
          {prediction.earnings_date && (
            <p className={`mt-1 text-xs ${textMuted}`}>
              📅 Reports: {prediction.earnings_date}
            </p>
          )}
        </div>

        {/* Recommendation Badge */}
        <div className="text-right">
          <div
            className={`badge text-lg font-bold uppercase ${getRecommendationColor(prediction.recommendation)}`}
          >
            {recIcon[prediction.recommendation]}
            <span className="ml-2">{prediction.recommendation}</span>
          </div>
          {totalScore !== undefined && (
            <p className="mt-1 text-xs text-gray-500">
              Score: <span className="font-bold text-gray-900">{totalScore}%</span>
            </p>
          )}
        </div>
      </div>

      {/* Main Metrics — Simple & Clear */}
      <div className="mt-6 grid grid-cols-3 gap-4">
        {/* Expected Move — THE key number */}
        <div className={`rounded-lg ${metricBg} p-3 text-center`}>
          <p className={`text-xs ${textSecondary}`}>Expected Move</p>
          <p className={`text-2xl font-bold ${moveColor}`}>
            {prediction.expected_move_pct !== undefined
              ? `${prediction.expected_move_pct >= 0 ? "+" : ""}${prediction.expected_move_pct.toFixed(1)}%`
              : "—"}
          </p>
          <p className={`text-xs ${textMuted}`}>after earnings</p>
        </div>

        {/* Will they beat? */}
        <div className={`rounded-lg ${metricBg} p-3 text-center`}>
          <p className={`text-xs ${textSecondary}`}>Beats Earnings?</p>
          <p className={`text-2xl font-bold ${textPrimary}`}>
            {prediction.beat_probability
              ? `${(prediction.beat_probability * 100).toFixed(0)}%`
              : "—"}
          </p>
          <p className={`text-xs ${textMuted}`}>
            {prediction.beat_probability && prediction.beat_probability > 0.65
              ? "likely yes"
              : prediction.beat_probability && prediction.beat_probability < 0.4
              ? "likely no"
              : "uncertain"}
          </p>
        </div>

        {/* Stock goes up? */}
        <div className={`rounded-lg ${metricBg} p-3 text-center`}>
          <p className={`text-xs ${textSecondary}`}>Stock Goes Up?</p>
          <p className={`text-2xl font-bold ${textPrimary}`}>
            {prediction.price_up_probability
              ? `${(prediction.price_up_probability * 100).toFixed(0)}%`
              : "—"}
          </p>
          <p className={`text-xs ${textMuted}`}>
            {prediction.price_up_probability && prediction.price_up_probability > 0.6
              ? "likely yes"
              : prediction.price_up_probability && prediction.price_up_probability < 0.4
              ? "likely no"
              : "coin flip"}
          </p>
        </div>
      </div>

      {/* Risk Bar */}
      {riskScore !== undefined && (
        <div className="mt-4">
          <div className="flex items-center justify-between text-xs">
            <span className={`flex items-center gap-1 ${textSecondary}`}>
              <Shield className="h-3 w-3" /> Risk Level
            </span>
            <span className={`font-medium ${
              riskScore > 60 ? "text-red-600" : riskScore > 35 ? "text-amber-600" : "text-green-600"
            }`}>
              {riskScore > 60 ? "High" : riskScore > 35 ? "Medium" : "Low"} ({riskScore}%)
            </span>
          </div>
          <div className={`mt-1 h-2 w-full rounded-full ${mode === "trader" ? "bg-gray-700" : "bg-gray-100"}`}>
            <div
              className={`h-2 rounded-full ${
                riskScore > 60 ? "bg-red-500" : riskScore > 35 ? "bg-amber-500" : "bg-green-500"
              }`}
              style={{ width: `${riskScore}%` }}
            />
          </div>
        </div>
      )}

      {/* Top 3 Reasons — Clear bullets */}
      {topReasons && topReasons.length > 0 && (
        <div className={`mt-5 rounded-lg border ${reasonBg} p-4`}>
          <div className={`flex items-center gap-2 text-sm font-medium ${textPrimary}`}>
            <Target className="h-4 w-4" />
            Why this prediction
          </div>
          <ul className="mt-2 space-y-1.5">
            {topReasons.map((reason, i) => (
              <li key={i} className={`flex items-start gap-2 text-sm ${textSecondary}`}>
                <span className="mt-0.5 text-xs">
                  {i === 0 ? "🔑" : i === 1 ? "📊" : "💡"}
                </span>
                {reason}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Fallback explanation if no top_reasons */}
      {!topReasons && prediction.explanation_text && (
        <div className={`mt-5 rounded-lg ${metricBg} p-4`}>
          <div className={`flex items-center gap-2 text-sm font-medium ${textPrimary}`}>
            <Info className="h-4 w-4" />
            Why this prediction
          </div>
          <p className={`mt-2 whitespace-pre-line text-sm ${textSecondary}`}>
            {prediction.explanation_text}
          </p>
        </div>
      )}
    </div>
  );
}
