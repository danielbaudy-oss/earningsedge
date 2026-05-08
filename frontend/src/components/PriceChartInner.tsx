"use client";

import {
  AreaChart,
  Area,
  ResponsiveContainer,
  Tooltip,
  YAxis,
  XAxis,
  ReferenceLine,
} from "recharts";

interface PriceChartInnerProps {
  prices: { date: number; price: number }[];
  earningsDates?: string[];
  period?: "1Y" | "ALL";
}

export default function PriceChartInner({ prices, earningsDates = [], period = "1Y" }: PriceChartInnerProps) {
  const firstPrice = prices[0].price;
  const lastPrice = prices[prices.length - 1].price;
  const isUp = lastPrice >= firstPrice;
  const color = isUp ? "#16a34a" : "#dc2626";

  // Convert earnings dates (YYYY-MM-DD) to timestamps
  const earningsTimestamps = earningsDates.map((d) => new Date(d + "T00:00:00").getTime());

  // Build chart data with labels based on period
  const seenLabels = new Set<string>();
  const chartData = prices.map((p, idx) => {
    let label = "";

    if (period === "ALL") {
      // For ALL: show years only
      const year = new Date(p.date).getFullYear().toString();
      if (!seenLabels.has(year)) {
        seenLabels.add(year);
        label = year;
      }
    } else {
      // For 1Y: show months
      const month = new Date(p.date).toLocaleDateString("en-US", { month: "short" });
      if (!seenLabels.has(month)) {
        seenLabels.add(month);
        label = month;
      }
    }

    return { ...p, idx, label };
  });

  // Find data indices closest to each earnings date (within 5 days)
  // Only show earnings lines in 1Y view (too cluttered in ALL)
  const earningsIndices: number[] = [];
  if (period === "1Y") {
    for (const earningsTs of earningsTimestamps) {
      let closestIdx = -1;
      let closestDist = Infinity;
      for (let i = 0; i < prices.length; i++) {
        const dist = Math.abs(prices[i].date - earningsTs);
        if (dist < closestDist && dist < 5 * 24 * 60 * 60 * 1000) {
          closestDist = dist;
          closestIdx = i;
        }
      }
      if (closestIdx >= 0) {
        earningsIndices.push(closestIdx);
      }
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
        <span>{period === "ALL" ? "All time" : "1Y"} price</span>
        <span className={isUp ? "text-green-600 font-medium" : "text-red-600 font-medium"}>
          ${lastPrice.toFixed(2)} ({isUp ? "+" : ""}
          {(((lastPrice - firstPrice) / firstPrice) * 100).toFixed(1)}%)
        </span>
      </div>
      <ResponsiveContainer width="100%" height={80}>
        <AreaChart data={chartData} margin={{ top: 2, right: 10, left: 10, bottom: 0 }}>
          <YAxis domain={["dataMin", "dataMax"]} hide />
          <XAxis
            dataKey="idx"
            axisLine={false}
            tickLine={false}
            tick={{ fontSize: 10, fill: "#9ca3af" }}
            tickFormatter={(idx: number) => chartData[idx]?.label || ""}
            interval={0}
          />
          <Tooltip
            contentStyle={{ fontSize: "11px", padding: "4px 8px" }}
            formatter={(value: number) => [`$${value.toFixed(2)}`, "Price"]}
            labelFormatter={(idx: number) => {
              const point = chartData[idx];
              if (!point) return "";
              return new Date(point.date).toLocaleDateString("en-US", {
                year: "numeric",
                month: "short",
                day: "numeric",
              });
            }}
          />
          {/* Earnings report date vertical lines (1Y only) */}
          {earningsIndices.map((idx, i) => (
            <ReferenceLine
              key={`earnings-${i}`}
              x={idx}
              stroke="#d1d5db"
              strokeWidth={1}
              strokeDasharray="3 3"
            />
          ))}
          <Area
            type="monotone"
            dataKey="price"
            stroke={color}
            strokeWidth={1.5}
            fill={color}
            fillOpacity={0.1}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
