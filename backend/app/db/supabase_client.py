"""Supabase client for REST API access (used by API routes)."""

from supabase import create_client, Client
from app.core.config import get_settings

settings = get_settings()

_client: Client | None = None


def get_supabase() -> Client:
    """Get Supabase client using service role key (full access)."""
    global _client
    if _client is None:
        _client = create_client(settings.supabase_url, settings.supabase_service_key)
    return _client
