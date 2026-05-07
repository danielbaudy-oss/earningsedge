"use client";

import { useState, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { searchStocks } from "@/lib/api";
import { Search } from "lucide-react";

interface StockSearchProps {
  onSelect: (ticker: string) => void;
}

export function StockSearch({ onSelect }: StockSearchProps) {
  const [query, setQuery] = useState("");
  const [isOpen, setIsOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const { data: results } = useQuery({
    queryKey: ["stockSearch", query],
    queryFn: () => searchStocks(query),
    enabled: query.length >= 1,
  });

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div ref={ref} className="relative">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
        <input
          type="text"
          placeholder="Search by ticker or company name..."
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setIsOpen(true);
          }}
          onFocus={() => setIsOpen(true)}
          className="w-full rounded-lg border border-gray-300 py-3 pl-10 pr-4 text-[16px] sm:text-sm focus:border-green-500 focus:outline-none focus:ring-1 focus:ring-green-500"
          aria-label="Search stocks"
          role="combobox"
          aria-expanded={isOpen && !!results?.length}
        />
      </div>

      {isOpen && results && results.length > 0 && (
        <ul
          className="absolute z-10 mt-1 max-h-60 w-full overflow-auto rounded-lg border border-gray-200 bg-white shadow-lg"
          role="listbox"
        >
          {results.map((stock) => (
            <li
              key={stock.id}
              role="option"
              className="cursor-pointer px-4 py-3 hover:bg-gray-50"
              onClick={() => {
                onSelect(stock.ticker);
                setQuery(stock.ticker);
                setIsOpen(false);
              }}
            >
              <div className="flex items-center justify-between">
                <div>
                  <span className="font-medium text-gray-900">
                    {stock.ticker}
                  </span>
                  <span className="ml-2 text-sm text-gray-500">
                    {stock.company_name}
                  </span>
                </div>
                <span className="text-xs text-gray-400">{stock.sector}</span>
              </div>
            </li>
          ))}
        </ul>
      )}

      {/* No results — let user search by ticker directly */}
      {isOpen && query.length >= 1 && results && results.length === 0 && (
        <div className="absolute z-10 mt-1 w-full rounded-lg border border-gray-200 bg-white p-3 shadow-lg">
          <p className="text-sm text-gray-500">No match found</p>
          <button
            className="mt-2 w-full rounded-md bg-green-50 px-3 py-2 text-left text-sm font-medium text-green-700 hover:bg-green-100"
            onClick={() => {
              onSelect(query.toUpperCase());
              setIsOpen(false);
            }}
          >
            Analyze <span className="font-bold">{query.toUpperCase()}</span> →
          </button>
        </div>
      )}
    </div>
  );
}
