import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatPercent(value: number | undefined): string {
  if (value === undefined || value === null) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export function formatCurrency(value: number | undefined): string {
  if (value === undefined || value === null) return "—";
  if (value >= 1e12) return `$${(value / 1e12).toFixed(1)}T`;
  if (value >= 1e9) return `$${(value / 1e9).toFixed(1)}B`;
  if (value >= 1e6) return `$${(value / 1e6).toFixed(1)}M`;
  return `$${value.toFixed(2)}`;
}

export function getRecommendationColor(rec: string): string {
  switch (rec) {
    case "buy":
      return "text-green-600 bg-green-50 border-green-200";
    case "sell":
      return "text-red-600 bg-red-50 border-red-200";
    case "avoid":
      return "text-amber-600 bg-amber-50 border-amber-200";
    default:
      return "text-gray-600 bg-gray-50 border-gray-200";
  }
}

export function getConfidenceColor(score: number): string {
  if (score >= 0.7) return "text-green-700";
  if (score >= 0.4) return "text-amber-700";
  return "text-red-700";
}
