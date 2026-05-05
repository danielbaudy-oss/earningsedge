"""Supabase client for REST API access (used by API routes)."""

import httpx
from app.core.config import get_settings

settings = get_settings()

_client: httpx.Client | None = None


def get_supabase():
    """Get a simple Supabase REST client using service role key."""
    global _client
    if _client is None:
        _client = SupabaseREST(settings.supabase_url, settings.supabase_service_key)
    return _client


class SupabaseREST:
    """Lightweight Supabase PostgREST client."""

    def __init__(self, url: str, service_key: str):
        self.base_url = f"{url}/rest/v1"
        self.headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        self.http = httpx.Client(timeout=30.0, headers=self.headers)

    def table(self, name: str) -> "TableQuery":
        return TableQuery(self.http, self.base_url, name)


class TableQuery:
    """Chainable query builder for PostgREST."""

    def __init__(self, http: httpx.Client, base_url: str, table: str):
        self.http = http
        self.url = f"{base_url}/{table}"
        self.params: dict = {}
        self._select_cols = "*"
        self._headers: dict = {}

    def select(self, columns: str = "*") -> "TableQuery":
        self._select_cols = columns
        self.params["select"] = columns
        return self

    def eq(self, column: str, value) -> "TableQuery":
        self.params[column] = f"eq.{value}"
        return self

    def gte(self, column: str, value) -> "TableQuery":
        existing = self.params.get(column)
        if existing:
            # Already have a filter on this column, combine them
            self.params[column] = f"gte.{value}"
            # Store the other filter with a different approach
            if "and" not in self.params:
                self.params["and"] = f"({column}.{existing},{column}.gte.{value})"
            del self.params[column]
        else:
            self.params[column] = f"gte.{value}"
        return self

    def lte(self, column: str, value) -> "TableQuery":
        existing = self.params.get(column)
        if existing:
            # Combine: use PostgREST 'and' filter
            self.params["and"] = f"({column}.{existing},{column}.lte.{value})"
            del self.params[column]
        else:
            self.params[column] = f"lte.{value}"
        return self

    def or_(self, filters: str) -> "TableQuery":
        self.params["or"] = f"({filters})"
        return self

    def order(self, column: str, desc: bool = False) -> "TableQuery":
        direction = "desc" if desc else "asc"
        self.params["order"] = f"{column}.{direction}"
        return self

    def limit(self, count: int) -> "TableQuery":
        self._headers["Range"] = f"0-{count - 1}"
        return self

    def execute(self) -> "QueryResult":
        resp = self.http.get(self.url, params=self.params, headers=self._headers)
        resp.raise_for_status()
        return QueryResult(resp.json())

    def insert(self, data: dict | list) -> "QueryResult":
        if isinstance(data, dict):
            data = [data]
        resp = self.http.post(self.url, json=data, headers=self._headers)
        resp.raise_for_status()
        return QueryResult(resp.json())

    def upsert(self, data: dict | list, on_conflict: str = "") -> "QueryResult":
        if isinstance(data, dict):
            data = [data]
        headers = {**self._headers, "Prefer": "resolution=merge-duplicates,return=representation"}
        if on_conflict:
            self.params["on_conflict"] = on_conflict
        resp = self.http.post(self.url, json=data, params=self.params, headers=headers)
        resp.raise_for_status()
        return QueryResult(resp.json())


class QueryResult:
    """Simple result wrapper."""

    def __init__(self, data):
        self.data = data if isinstance(data, list) else [data] if data else []
