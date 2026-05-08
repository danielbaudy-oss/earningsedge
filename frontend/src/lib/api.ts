/**
 * API client for EarningsEdge backend.
 */

import axios from "axios";
import type { Stock, StockDetail, EarningsEvent, Prediction } from "@/types";

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || "/api",
  timeout: 15000,
});

// Stocks
export async function searchStocks(query: string): Promise<Stock[]> {
  const { data } = await api.get("/stocks/search", { params: { q: query } });
  return data;
}

export async function getStock(ticker: string): Promise<StockDetail> {
  const { data } = await api.get(`/stocks/${ticker}`);
  return data;
}

export async function getStockChart(ticker: string, period: string = "1Y"): Promise<{ prices: { date: number; price: number }[]; earnings_dates?: string[] }> {
  const { data } = await api.get(`/stocks/${ticker}/chart`, { params: { period } });
  return data;
}

// Earnings
export async function getEarningsCalendar(
  startDate: string,
  endDate: string
): Promise<EarningsEvent[]> {
  const { data } = await api.get("/earnings/calendar", {
    params: { start_date: startDate, end_date: endDate },
  });
  return data;
}

export async function getUpcomingEarnings(): Promise<EarningsEvent[]> {
  const { data } = await api.get("/earnings/upcoming");
  return data;
}

export async function getEarningsHistory(
  ticker: string
): Promise<EarningsEvent[]> {
  const { data } = await api.get(`/earnings/history/${ticker}`);
  return data;
}

// Predictions
export async function getPrediction(ticker: string): Promise<Prediction> {
  const { data } = await api.get(`/predictions/stock/${ticker}`);
  return data;
}

export async function analyzeTicker(ticker: string, mode: string = "trader"): Promise<Prediction> {
  const { data } = await api.post(`/predictions/analyze/${ticker}?mode=${mode}`, null, { timeout: 60000 });
  return data;
}

export async function getUpcomingPredictions(params?: {
  min_confidence?: number;
  recommendation?: string;
}): Promise<Prediction[]> {
  const { data } = await api.get("/predictions/upcoming/all", { params });
  return data;
}

export async function getWatchlist(): Promise<Prediction[]> {
  const { data } = await api.get("/predictions/watchlist");
  return data;
}
