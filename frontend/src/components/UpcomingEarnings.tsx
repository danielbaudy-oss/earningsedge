"use client";

import { useQuery } from "@tanstack/react-query";
import { getUpcomingEarnings } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import { Calendar } from "lucide-react";

export function UpcomingEarnings() {
  const { data: earnings, isLoading } = useQuery({
    queryKey: ["upcomingEarnings"],
    queryFn: getUpcomingEarnings,
  });

  if (isLoading) {
    return (
      <div className="card animate-pulse">
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-12 rounded bg-gray-100" />
          ))}
        </div>
      </div>
    );
  }

  if (!earnings?.length) {
    return (
      <div className="card text-center text-gray-500">
        No upcoming earnings found
      </div>
    );
  }

  return (
    <div className="card">
      <div className="divide-y divide-gray-100">
        {earnings.slice(0, 10).map((event) => (
          <div
            key={event.id}
            className="flex items-center justify-between py-3"
          >
            <div className="flex items-center gap-3">
              <Calendar className="h-4 w-4 text-gray-400" />
              <div>
                <p className="font-medium text-gray-900">{event.ticker}</p>
                <p className="text-xs text-gray-500">{event.company_name}</p>
              </div>
            </div>
            <div className="text-right">
              <p className="text-sm font-medium text-gray-900">
                {event.report_date}
              </p>
              <p className="text-xs text-gray-500">
                {event.report_time === "before_market" ? "Pre-market" : "After-hours"}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
