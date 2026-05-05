"use client";

import { useState } from "react";
import { StockSearch } from "@/components/StockSearch";
import { Bell, Plus } from "lucide-react";

export default function AlertsPage() {
  const [selectedTicker, setSelectedTicker] = useState("");
  const [email, setEmail] = useState("");
  const [daysBefore, setDaysBefore] = useState(3);
  const [success, setSuccess] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedTicker || !email) return;

    try {
      const res = await fetch("/api/alerts/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticker: selectedTicker,
          email,
          days_before: daysBefore,
        }),
      });
      if (res.ok) {
        setSuccess(true);
        setTimeout(() => setSuccess(false), 3000);
        setSelectedTicker("");
      }
    } catch (err) {
      console.error("Failed to create alert:", err);
    }
  }

  return (
    <div className="mx-auto max-w-lg space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Earnings Alerts</h1>
      <p className="text-gray-600">
        Get notified before a stock reports earnings with our AI prediction.
      </p>

      <form onSubmit={handleSubmit} className="card space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700">
            Stock
          </label>
          <div className="mt-1">
            <StockSearch onSelect={setSelectedTicker} />
          </div>
        </div>

        <div>
          <label
            htmlFor="email"
            className="block text-sm font-medium text-gray-700"
          >
            Email
          </label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            className="mt-1 w-full rounded-lg border border-gray-300 px-4 py-2 text-sm focus:border-green-500 focus:outline-none focus:ring-1 focus:ring-green-500"
            required
          />
        </div>

        <div>
          <label
            htmlFor="days"
            className="block text-sm font-medium text-gray-700"
          >
            Alert me this many days before earnings
          </label>
          <select
            id="days"
            value={daysBefore}
            onChange={(e) => setDaysBefore(Number(e.target.value))}
            className="mt-1 w-full rounded-lg border border-gray-300 px-4 py-2 text-sm"
          >
            <option value={1}>1 day before</option>
            <option value={2}>2 days before</option>
            <option value={3}>3 days before</option>
            <option value={5}>5 days before</option>
            <option value={7}>1 week before</option>
          </select>
        </div>

        <button
          type="submit"
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-green-600 px-4 py-3 text-sm font-medium text-white hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2"
        >
          <Bell className="h-4 w-4" />
          Create Alert
        </button>

        {success && (
          <p className="text-center text-sm text-green-600">
            Alert created successfully!
          </p>
        )}
      </form>
    </div>
  );
}
