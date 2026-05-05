"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getPrediction, analyzeTicker } from "@/lib/api";
import { formatPercent, getRecommendationColor } from "@/lib/utils";
import { TrendingUp, TrendingDown, AlertTriangle, Info, Shield, Target, Zap } from "lucide-react";

interface PredictionCardProps {
  ticker: string;
}

export function PredictionCard({ ticker }: PredictionCardProps) {
  const queryClient = useQueryClient();
  const { data: prediction, isLoading, error } = useQuery({
    queryKey: ["prediction", ticker],
    queryFn: () => getPrediction(ticker),
    retry: false,
    staleTime: 60000,
  });

  const analyzeMutation = useMutation({
    mutationFn: () => analyzeTicker(ticker),
    onSuccess: (data) => {
      // Only invalidate if we got a real prediction back
      if (data.recommendation) {
        queryClient.invalidateQueries({ queryKey: ["prediction", ticker] });
      }
    },
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
      <div className="card text-center">
        <p className="text-gray-500">No prediction available for {ticker}</p>
        <button
          onClick={() => analyzeMutation.mutate()}
          disabled={analyzeMutation.isPending}
          className="mt-4 inline-flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
        >
          <Zap className="h-4 w-4" />
          {analyzeMutation.isPending ? "Analyzing..." : "Analyze Now"}
        </button>
        {analyzeMutation.isError && (
          <p className="mt-2 text-xs text-gray-500">
            {(analyzeMutation.error as any)?.response?.data?.message ||
             "No upcoming earnings found or insufficient data."}
          </p>
        )}
        {analyzeMutation.data && !analyzeMutation.data.recommendation && (
          <div className="mt-3 rounded-lg bg-blue-50 p-3 text-sm text-blue-700">
            {analyzeMutation.data.message}
            {analyzeMutation.data.earnings_date && (
              <p className="mt-1 font-medium">📅 Next earnings: {analyzeMutation.data.earnings_date}</p>
            )}
          </div>
        )}
      </div>
    );
  }

  const recIcon = {
    buy: <TrendingUp className="h-6 w-6" />,
    sell: <TrendingDown className="h-6 w-6" />,
    avoid: <AlertTriangle className="h-6 w-6" />,
  };

  const totalScore = prediction.feature_importance?.total_score;
  const riskScore = prediction.feature_importance?.risk_score;
  const topReasons = prediction.feature_importance?.top_reasons as string[] | undefined;

  const moveColor = (prediction.expected_move_pct ?? 0) >= 0
    ? "text-green-700"
    : "text-red-700";

  return (
    <div className="card">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-lg font-bold text-gray-900">{prediction.ticker}</h3>
          <p className="text-sm text-gray-500">{prediction.company_name}</p>
          {prediction.earnings_date && (
            <p className="mt-1 text-xs text-gray-400">📅 Reports: {prediction.earnings_date}</p>
          )}
        </div>
        <div className="text-right">
          <div className={`badge text-lg font-bold uppercase ${getRecommendationColor(prediction.recommendation)}`}>
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

      {/* Main Metrics */}
      <div className="mt-6 grid grid-cols-3 gap-4">
        <div className="rounded-lg bg-gray-50 p-3 text-center">
          <p className="text-xs text-gray-500">Expected Move</p>
          <p className={`text-2xl font-bold ${moveColor}`}>
            {prediction.expected_move_pct !== undefined
              ? `${prediction.expected_move_pct >= 0 ? "+" : ""}${prediction.expected_move_pct.toFixed(1)}%`
              : "—"}
          </p>
          <p className="text-xs text-gray-400">after earnings</p>
        </div>
        <div className="rounded-lg bg-gray-50 p-3 text-center">
          <p className="text-xs text-gray-500">Beats Earnings?</p>
          <p className="text-2xl font-bold text-gray-900">
            {prediction.beat_probability
              ? `${(prediction.beat_probability * 100).toFixed(0)}%`
              : "—"}
          </p>
          <p className="text-xs text-gray-400">
            {prediction.beat_probability && prediction.beat_probability > 0.65
              ? "likely yes"
              : prediction.beat_probability && prediction.beat_probability < 0.4
              ? "likely no"
              : "uncertain"}
          </p>
        </div>
        <div className="rounded-lg bg-gray-50 p-3 text-center">
          <p className="text-xs text-gray-500">Stock Goes Up?</p>
          <p className="text-2xl font-bold text-gray-900">
            {prediction.price_up_probability
              ? `${(prediction.price_up_probability * 100).toFixed(0)}%`
              : "—"}
          </p>
          <p className="text-xs text-gray-400">
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
            <span className="flex items-center gap-1 text-gray-500">
              <Shield className="h-3 w-3" /> Risk Level
            </span>
            <span className={`font-medium ${
              riskScore > 60 ? "text-red-600" : riskScore > 35 ? "text-amber-600" : "text-green-600"
            }`}>
              {riskScore > 60 ? "High" : riskScore > 35 ? "Medium" : "Low"} ({riskScore}%)
            </span>
          </div>
          <div className="mt-1 h-2 w-full rounded-full bg-gray-100">
            <div
              className={`h-2 rounded-full ${
                riskScore > 60 ? "bg-red-500" : riskScore > 35 ? "bg-amber-500" : "bg-green-500"
              }`}
              style={{ width: `${riskScore}%` }}
            />
          </div>
        </div>
      )}

      {/* Top 3 Reasons */}
      {topReasons && topReasons.length > 0 && (
        <div className="mt-5 rounded-lg border border-gray-100 bg-white p-4">
          <div className="flex items-center gap-2 text-sm font-medium text-gray-700">
            <Target className="h-4 w-4" />
            Why this prediction
          </div>
          <ul className="mt-2 space-y-1.5">
            {topReasons.map((reason, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-gray-600">
                <span className="mt-0.5 text-xs">
                  {i === 0 ? "🔑" : i === 1 ? "📊" : "💡"}
                </span>
                {reason}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Fallback explanation */}
      {!topReasons && prediction.explanation_text && (
        <div className="mt-5 rounded-lg bg-gray-50 p-4">
          <div className="flex items-center gap-2 text-sm font-medium text-gray-700">
            <Info className="h-4 w-4" />
            Why this prediction
          </div>
          <p className="mt-2 whitespace-pre-line text-sm text-gray-600">
            {prediction.explanation_text}
          </p>
        </div>
      )}
    </div>
  );
}
