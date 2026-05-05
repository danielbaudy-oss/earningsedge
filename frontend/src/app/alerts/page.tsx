"use client";

import { useState } from "react";
import { StockSearch } from "@/components/StockSearch";
import { Bell, Send, Mail } from "lucide-react";

export default function AlertsPage() {
  const [selectedTicker, setSelectedTicker] = useState("");
  const [alertMethod, setAlertMethod] = useState<"email" | "telegram">("email");
  const [email, setEmail] = useState("");
  const [telegramChatId, setTelegramChatId] = useState("");
  const [daysBefore, setDaysBefore] = useState(3);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!selectedTicker) {
      setError("Please select a stock");
      return;
    }

    const body: Record<string, unknown> = {
      ticker: selectedTicker,
      alert_method: alertMethod,
      days_before: daysBefore,
    };

    if (alertMethod === "email") {
      if (!email) { setError("Email is required"); return; }
      body.email = email;
    } else {
      if (!telegramChatId) { setError("Telegram Chat ID is required"); return; }
      body.telegram_chat_id = telegramChatId;
    }

    try {
      const res = await fetch("/api/alerts/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        setSuccess(true);
        setTimeout(() => setSuccess(false), 4000);
        setSelectedTicker("");
      } else {
        const data = await res.json();
        setError(data.detail || "Failed to create alert");
      }
    } catch (err) {
      setError("Network error");
    }
  }

  return (
    <div className="mx-auto max-w-lg space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Earnings Alerts</h1>
      <p className="text-gray-600">
        Get notified before a stock reports earnings — via email or Telegram.
      </p>

      <form onSubmit={handleSubmit} className="card space-y-4">
        {/* Stock */}
        <div>
          <label className="block text-sm font-medium text-gray-700">Stock</label>
          <div className="mt-1">
            <StockSearch onSelect={setSelectedTicker} />
          </div>
        </div>

        {/* Alert Method Toggle */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Alert Method
          </label>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setAlertMethod("email")}
              className={`flex items-center gap-2 rounded-lg border px-4 py-2 text-sm font-medium transition ${
                alertMethod === "email"
                  ? "border-green-500 bg-green-50 text-green-700"
                  : "border-gray-200 text-gray-500 hover:bg-gray-50"
              }`}
            >
              <Mail className="h-4 w-4" />
              Email
            </button>
            <button
              type="button"
              onClick={() => setAlertMethod("telegram")}
              className={`flex items-center gap-2 rounded-lg border px-4 py-2 text-sm font-medium transition ${
                alertMethod === "telegram"
                  ? "border-blue-500 bg-blue-50 text-blue-700"
                  : "border-gray-200 text-gray-500 hover:bg-gray-50"
              }`}
            >
              <Send className="h-4 w-4" />
              Telegram
            </button>
          </div>
        </div>

        {/* Email Input */}
        {alertMethod === "email" && (
          <div>
            <label htmlFor="email" className="block text-sm font-medium text-gray-700">
              Email
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="mt-1 w-full rounded-lg border border-gray-300 px-4 py-2 text-sm focus:border-green-500 focus:outline-none focus:ring-1 focus:ring-green-500"
            />
          </div>
        )}

        {/* Telegram Input */}
        {alertMethod === "telegram" && (
          <div>
            <label htmlFor="chatid" className="block text-sm font-medium text-gray-700">
              Telegram Chat ID
            </label>
            <input
              id="chatid"
              type="text"
              value={telegramChatId}
              onChange={(e) => setTelegramChatId(e.target.value)}
              placeholder="e.g. 123456789"
              className="mt-1 w-full rounded-lg border border-gray-300 px-4 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            <p className="mt-2 text-xs text-gray-500">
              1. Message <a href="https://t.me/EarningsEdgeBot" target="_blank" className="text-blue-600 underline">@EarningsEdgeBot</a> on Telegram with /start<br />
              2. Send /id to get your Chat ID<br />
              3. Paste it above
            </p>
          </div>
        )}

        {/* Days Before */}
        <div>
          <label htmlFor="days" className="block text-sm font-medium text-gray-700">
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

        {/* Submit */}
        <button
          type="submit"
          className={`flex w-full items-center justify-center gap-2 rounded-lg px-4 py-3 text-sm font-medium text-white focus:outline-none focus:ring-2 focus:ring-offset-2 ${
            alertMethod === "telegram"
              ? "bg-blue-600 hover:bg-blue-700 focus:ring-blue-500"
              : "bg-green-600 hover:bg-green-700 focus:ring-green-500"
          }`}
        >
          {alertMethod === "telegram" ? <Send className="h-4 w-4" /> : <Bell className="h-4 w-4" />}
          Create {alertMethod === "telegram" ? "Telegram" : "Email"} Alert
        </button>

        {success && (
          <p className="text-center text-sm text-green-600">
            ✅ Alert created successfully!
          </p>
        )}
        {error && (
          <p className="text-center text-sm text-red-600">{error}</p>
        )}
      </form>
    </div>
  );
}
