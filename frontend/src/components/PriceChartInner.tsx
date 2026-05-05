"use client";

import { AreaChart, Area, ResponsiveContainer, Tooltip, YAxis } from "recharts";

interface PriceChartInnerProps {
  prices: { date: number; price: number }[];
}

export default function PriceChartInner({ prices }: PriceChartInnerProps) {
  const firstPrice = prices[0].price;
  const lastPrice = prices[prices.length - 1].price;
  const isUp = lastPrice >= firstPrice;
  const color = isUp ? "#16a34a" : "#dc2626";

  return (
    <div className="mt-4">
      <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
        <span>YTD price</span>
        <span className={isUp ? "text-green-600 font-medium" : "text-red-600 font-medium"}>
          ${lastPrice.toFixed(2)} ({isUp ? "+" : ""}{(((lastPrice - firstPrice) / firstPrice) * 100).toFixed(1)}%)
        </span>
      </div>
      <ResponsiveContainer width="100%" height={60}>
        <AreaChart data={prices} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
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
            fill={color}
            fillOpacity={0.1}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
