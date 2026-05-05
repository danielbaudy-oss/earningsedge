"use client";

import { useQuery } from "@tanstack/react-query";
import { getStockChart } from "@/lib/api";
import dynamic from "next/dynamic";

const ChartInner = dynamic(() => import("./PriceChartInner"), { ssr: false });

interface PriceChartProps {
  ticker: string;
}

export function PriceChart({ ticker }: PriceChartProps) {
  const { data, isLoading } = useQuery({
    queryKey: ["chart", ticker],
    queryFn: () => getStockChart(ticker),
    staleTime: 300000,
  });

  if (isLoading) {
    return <div className="h-16 mt-4 animate-pulse rounded bg-gray-100" />;
  }

  const prices = data?.prices || [];
  if (prices.length < 2) {
    return null;
  }

  return <ChartInner prices={prices} />;
}
