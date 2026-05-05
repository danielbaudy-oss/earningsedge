"use client";

import { useQuery } from "@tanstack/react-query";
import { getStockChart } from "@/lib/api";
import { AreaChart, Area, ResponsiveContainer, Tooltip, YAxis } from "recharts";

interface PriceChartProps {
  ticker: string;
}

export function PriceChart({ ticker }: PriceChartProps) {
  const { data, isLoading } = useQuery({
    queryKey: ["chart", ticker],
    queryFn: () => getStockChart(ticker),
    staleTime: 300000, // 5 min cache
  });

  if (isLoading) {
    return <div className="h-16 animate-pulse rounded bg-gray-100" />;
  }

  const prices = data?.prices || [];
  if (prices.length < 3) {
    return null;
  }

  // Determine if trending up or down
  const firstPrice = prices[0].price;
  const lastPrice = prices[prices.length - 1].price;
  const isUp = lastPrice >= firstPrice;
  const color = isUp ? "#16a34a" : "#dc2626";
  const gradientId = `gradient-${ticker}`;

  return (
    <div className="mt-4">
      <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
        <span>30-day price</span>
        <span className={isUp ? "text-green-600 font-medium" : "text-red-600 font-medium"}>
          ${lastPrice.toFixed(2)} ({isUp ? "+" : ""}{(((lastPrice - firstPrice) / firstPrice) * 100).toFixed(1)}%)
        </span>
      </div>
      <ResponsiveContainer width="100%" height={60}>
        <AreaChart data={prices} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={color} stopOpacity={0.2} />
              <stop offset="95%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <YAxis domain={["dataMin", "dataMax"]} hide />
          <Tooltip
            contentStyle={{ fontSize: "11px", padding: "4px 8px" }}
            formatter={(value: number) => [`$${value.toFixed(2)}`, "Price"]}
            labelFormatter={() => ""}
          />
          <Area
            type="monotone"
            dataKey="price"
            stroke={color}
            strokeWidth={1.5}
            fill={`url(#${gradientId})`}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
