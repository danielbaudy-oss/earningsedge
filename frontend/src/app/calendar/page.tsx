"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getEarningsCalendar } from "@/lib/api";
import { format, startOfWeek, endOfWeek, addWeeks } from "date-fns";
import { ChevronLeft, ChevronRight } from "lucide-react";

export default function CalendarPage() {
  const [weekOffset, setWeekOffset] = useState(0);
  const now = new Date();
  const weekStart = startOfWeek(addWeeks(now, weekOffset), { weekStartsOn: 1 });
  const weekEnd = endOfWeek(addWeeks(now, weekOffset), { weekStartsOn: 1 });

  const { data: earnings, isLoading } = useQuery({
    queryKey: ["calendar", format(weekStart, "yyyy-MM-dd")],
    queryFn: () =>
      getEarningsCalendar(
        format(weekStart, "yyyy-MM-dd"),
        format(weekEnd, "yyyy-MM-dd")
      ),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Earnings Calendar</h1>
        <div className="flex items-center gap-4">
          <button
            onClick={() => setWeekOffset((w) => w - 1)}
            className="rounded-lg border p-2 hover:bg-gray-50"
            aria-label="Previous week"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="text-sm font-medium text-gray-700">
            {format(weekStart, "MMM d")} – {format(weekEnd, "MMM d, yyyy")}
          </span>
          <button
            onClick={() => setWeekOffset((w) => w + 1)}
            className="rounded-lg border p-2 hover:bg-gray-50"
            aria-label="Next week"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="card animate-pulse">
          <div className="h-64 rounded bg-gray-100" />
        </div>
      ) : !earnings?.length ? (
        <div className="card text-center text-gray-500 py-12">
          No earnings scheduled for this week
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 text-left text-xs font-medium uppercase text-gray-500">
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3">Ticker</th>
                <th className="px-4 py-3">Company</th>
                <th className="px-4 py-3">Time</th>
                <th className="px-4 py-3">EPS Est.</th>
                <th className="px-4 py-3">Rev Est.</th>
                <th className="px-4 py-3">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {earnings.map((event) => (
                <tr key={event.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium">{event.report_date}</td>
                  <td className="px-4 py-3 font-bold text-gray-900">
                    {event.ticker}
                  </td>
                  <td className="px-4 py-3 text-gray-600">
                    {event.company_name}
                  </td>
                  <td className="px-4 py-3 text-gray-500">
                    {event.report_time === "before_market"
                      ? "Pre-market"
                      : "After-hours"}
                  </td>
                  <td className="px-4 py-3">
                    {event.eps_estimate?.toFixed(2) ?? "—"}
                  </td>
                  <td className="px-4 py-3">
                    {event.revenue_estimate
                      ? `$${(event.revenue_estimate / 1e9).toFixed(2)}B`
                      : "—"}
                  </td>
                  <td className="px-4 py-3">
                    {event.is_confirmed ? (
                      <span className="text-green-600">Confirmed</span>
                    ) : (
                      <span className="text-amber-600">Tentative</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
