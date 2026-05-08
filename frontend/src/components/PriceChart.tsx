"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getStockChart } from "@/lib/api";
import dynamic from "next/dynamic";

const ChartInner = dynamic(() => import("./PriceChartInner"), { ssr: false });

interface PriceChartProps {
  ticker: string;
}

export function PriceChart({ ticker }: PriceChartProps) {
  const [period, setPeriod] = useState<"1Y" | "ALL">("1Y");

  const { data, isLoading } = useQuery({
    queryKey: ["chart", ticker, period],
    queryFn: () => getStockChart(ticker, period),
    staleTime: 300000,
  });

  if (isLoading) {
    return <div className="h-16 mt-4 animate-pulse rounded bg-gray-100" />;
  }

  const prices = data?.prices || [];
  const earningsDates = data?.earnings_dates || [];

  if (prices.length < 2) {
    return null;
  }

  return (
    <div className="mt-4">
      <div className="flex items-center gap-1 mb-1">
        <button
          onClick={() => setPeriod("1Y")}
          className={`px-2 py-0.5 text-xs rounded ${
            period === "1Y" ? "bg-gray-900 text-white" : "text-gray-400 hover:text-gray-600"
          }`}
        >
          1Y
        </button>
        <button
          onClick={() => setPeriod("ALL")}
          className={`px-2 py-0.5 text-xs rounded ${
            period === "ALL" ? "bg-gray-900 text-white" : "text-gray-400 hover:text-gray-600"
          }`}
        >
          All
        </button>
      </div>
      <ChartInner prices={prices} earningsDates={earningsDates} period={period} />
    </div>
  );
}
