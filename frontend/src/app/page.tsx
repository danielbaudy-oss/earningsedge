"use client";

import { useState } from "react";
import { StockSearch } from "@/components/StockSearch";
import { PredictionCard } from "@/components/PredictionCard";
import { TopPredictions } from "@/components/TopPredictions";
import { Watchlist } from "@/components/Watchlist";
import { X } from "lucide-react";

export default function Dashboard() {
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [view, setView] = useState<"7d" | "30d">("7d");

  return (
    <div className="space-y-8">
      {/* Hero / Search */}
      <section className="text-center">
        <h1 className="text-3xl font-bold text-gray-900">
          Earnings are coming. Are you ready?
        </h1>
        <p className="mt-2 text-gray-600">
          AI predicts which stocks move up after reporting
        </p>
        <div className="mx-auto mt-6 max-w-md">
          <StockSearch onSelect={setSelectedTicker} />
        </div>
      </section>

      {/* Selected Stock Prediction */}
      {selectedTicker && (
        <section className="relative">
          <button
            onClick={() => setSelectedTicker(null)}
            className="absolute -top-2 right-0 z-10 rounded-full bg-white border border-gray-200 p-1.5 shadow-sm hover:bg-gray-100"
            aria-label="Close"
          >
            <X className="h-4 w-4 text-gray-500" />
          </button>
          <PredictionCard ticker={selectedTicker} />
        </section>
      )}

      {/* Mobile toggle */}
      <div className="flex items-center gap-1 rounded-lg border border-gray-200 bg-white p-1 lg:hidden">
        <button
          onClick={() => setView("7d")}
          className={`flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition ${
            view === "7d" ? "bg-green-600 text-white" : "text-gray-500"
          }`}
        >
          Next 7 Days
        </button>
        <button
          onClick={() => setView("30d")}
          className={`flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition ${
            view === "30d" ? "bg-green-600 text-white" : "text-gray-500"
          }`}
        >
          Next 30 Days
        </button>
      </div>

      {/* Desktop: side by side */}
      <div className="hidden lg:grid lg:grid-cols-2 lg:gap-8">
        <section>
          <h2 className="mb-4 text-lg font-semibold text-gray-900">
            Top Trades Next 7 Days
          </h2>
          <TopPredictions />
        </section>
        <section>
          <h2 className="mb-4 text-lg font-semibold text-gray-900">
            Top Picks Next 30 Days
          </h2>
          <Watchlist />
        </section>
      </div>

      {/* Mobile: toggled */}
      <div className="lg:hidden">
        {view === "7d" && (
          <section>
            <h2 className="mb-4 text-lg font-semibold text-gray-900">
              Top Trades Next 7 Days
            </h2>
            <TopPredictions />
          </section>
        )}
        {view === "30d" && (
          <section>
            <h2 className="mb-4 text-lg font-semibold text-gray-900">
              Top Picks Next 30 Days
            </h2>
            <Watchlist />
          </section>
        )}
      </div>
    </div>
  );
}
