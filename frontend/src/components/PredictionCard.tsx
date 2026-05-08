"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getPrediction, analyzeTicker } from "@/lib/api";
import { formatPercent, getRecommendationColor } from "@/lib/utils";
import { PriceChart } from "@/components/PriceChart";
import { TrendingUp, TrendingDown, AlertTriangle, Info, Shield, Target, Zap } from "lucide-react";

interface PredictionCardProps {
  ticker: string;
}

function DescriptionToggle({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const isLong = text.length > 120;

  return (
    <div className="mt-3">
      <p className={`text-xs text-gray-500 ${!expanded && isLong ? "line-clamp-2" : ""}`}>
        {text}
      </p>
      {isLong && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="mt-0.5 text-xs font-medium text-green-600 hover:text-green-800"
        >
          {expanded ? "← Show less" : "Read more →"}
        </button>
      )}
    </div>
  );
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
            No upcoming earnings found or insufficient data.
          </p>
        )}
        {analyzeMutation.data && !(analyzeMutation.data as any).recommendation && (
          <div className="mt-3 rounded-lg bg-blue-50 p-3 text-sm text-blue-700">
            {(analyzeMutation.data as any).message}
            {(analyzeMutation.data as any).earnings_date && (
              <p className="mt-1 font-medium">Next earnings: {(analyzeMutation.data as any).earnings_date}</p>
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

  // T+1 and T+3 values (from feature_importance JSON)
  const t1Data = prediction.feature_importance?.t1;
  const t3Data = prediction.feature_importance?.t3;
  const moveT1 = t1Data?.expected_move_pct ?? prediction.expected_move_pct ?? 0;
  const moveT3 = t3Data?.expected_move_pct;
  const upProbT1 = t1Data?.direction_prob ?? prediction.price_up_probability;
  const upProbT3 = t3Data?.direction_prob;
  const impliedMove = prediction.feature_importance?.implied_move_pct ?? prediction.implied_move_pct;

  const moveT1Color = moveT1 >= 0 ? "text-green-700" : "text-red-700";
  const moveT3Color = (moveT3 ?? 0) >= 0 ? "text-green-700" : "text-red-700";

  return (
    <div className="card">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-lg font-bold text-gray-900">{prediction.ticker}</h3>
          <p className="text-sm text-gray-500">{prediction.company_name}</p>
          {prediction.earnings_date && (
            <p className="mt-1 text-xs text-gray-400">
              Reports: {prediction.earnings_date}
              {prediction.exchange && (
                <span className="ml-2">
                  {prediction.exchange === "XNAS" ? "Nasdaq" : prediction.exchange === "XNYS" ? "NYSE" : prediction.exchange}
                </span>
              )}
              {prediction.feature_importance?.is_confirmed === false && (
                <span className="ml-2 text-amber-500" title="Date not confirmed by multiple sources">~estimated</span>
              )}
            </p>
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

      {/* Company Description */}
      {prediction.description && (
        <DescriptionToggle text={prediction.description} />
      )}

      {/* Beat Probability */}
      <div className="mt-5 rounded-lg bg-gray-50 p-3">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium text-gray-700">Earnings Beat Probability</p>
          <p className="text-xl font-bold text-gray-900">
            {prediction.beat_probability
              ? `${(prediction.beat_probability * 100).toFixed(0)}%`
              : "—"}
          </p>
        </div>
      </div>

      {/* T+1 and T+3 Predictions */}
      <div className="mt-4 grid grid-cols-2 gap-3">
        {/* T+1 */}
        <div className="rounded-lg border border-gray-100 p-3">
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">T+1 Reaction</p>
          <p className="text-xs text-gray-400 mb-2">Next trading day</p>
          <p className={`text-2xl font-bold ${moveT1Color}`}>
            {moveT1 >= 0 ? "+" : ""}{moveT1.toFixed(1)}%
          </p>
          <div className="mt-1 flex items-center gap-1">
            {moveT1 >= 0 ? (
              <TrendingUp className="h-3 w-3 text-green-600" />
            ) : (
              <TrendingDown className="h-3 w-3 text-red-600" />
            )}
            <span className="text-xs text-gray-500">
              {upProbT1 ? `${(upProbT1 * 100).toFixed(0)}% upside` : ""}
            </span>
          </div>
        </div>

        {/* T+3 */}
        <div className="rounded-lg border border-gray-100 p-3">
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">T+3 Outlook</p>
          <p className="text-xs text-gray-400 mb-2">After 3 trading days</p>
          {moveT3 !== undefined && moveT3 !== null ? (
            <>
              <p className={`text-2xl font-bold ${moveT3Color}`}>
                {moveT3 >= 0 ? "+" : ""}{moveT3.toFixed(1)}%
              </p>
              <div className="mt-1 flex items-center gap-1">
                {moveT3 >= 0 ? (
                  <TrendingUp className="h-3 w-3 text-green-600" />
                ) : (
                  <TrendingDown className="h-3 w-3 text-red-600" />
                )}
                <span className="text-xs text-gray-500">
                  {upProbT3 ? `${(upProbT3 * 100).toFixed(0)}% upside` : ""}
                </span>
              </div>
            </>
          ) : (
            <p className="text-2xl font-bold text-gray-300">—</p>
          )}
        </div>
      </div>

      {/* Implied vs Expected Move */}
      {impliedMove && (
        <div className="mt-3 flex items-center justify-between rounded-lg bg-blue-50 px-3 py-2">
          <span className="text-xs text-blue-700">Options implied move</span>
          <span className="text-sm font-medium text-blue-900">±{impliedMove.toFixed(1)}%</span>
        </div>
      )}

      {/* Price Chart */}
      <PriceChart ticker={ticker} />

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

      {/* Key Context */}
      {topReasons && topReasons.length > 0 && (
        <div className="mt-5 rounded-lg border border-gray-100 bg-white p-4">
          <p className="text-sm font-medium text-gray-700">Key Context</p>
          <ul className="mt-2 space-y-1.5">
            {topReasons.map((reason, i) => (
              <li key={i} className="text-sm text-gray-600">
                {reason}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Fallback explanation */}
      {!topReasons && prediction.explanation_text && (
        <div className="mt-5 rounded-lg bg-gray-50 p-4">
          <p className="text-sm font-medium text-gray-700">Key Context</p>
          <p className="mt-2 whitespace-pre-line text-sm text-gray-600">
            {prediction.explanation_text}
          </p>
        </div>
      )}
    </div>
  );
}
