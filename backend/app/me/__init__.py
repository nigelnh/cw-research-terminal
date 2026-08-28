"""The ``/api/me/*`` namespace: resources owned by the authenticated caller.

Everything under this router requires a verified Supabase access token
(:func:`app.auth.get_current_user`) and derives ownership solely from the token ``sub``.
Step 9 ships exactly one resource here: the user's primary watchlist.
"""

from app.me.me_router import me_router

__all__ = ["me_router"]
