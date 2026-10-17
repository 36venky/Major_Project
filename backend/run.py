"""
run.py
───────
Development server launcher.

Windows asyncio fix
───────────────────
On Windows, Python 3.10+ defaults to ProactorEventLoop which breaks asyncpg's
getaddrinfo DNS resolution (socket.gaierror: [Errno 11001] getaddrinfo failed).
Switching to SelectorEventLoop before uvicorn starts fixes this.

Usage:
    python run.py
"""
import sys
import asyncio

# ── Windows: force SelectorEventLoop so asyncpg DNS works ─────────────────
# ProactorEventLoop (the Windows default since Python 3.10) does not support
# the socket.getaddrinfo path that asyncpg uses for PostgreSQL connections.
# SelectorEventLoop works correctly on Windows for both asyncpg and uvicorn.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn
from app.core.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG or True,
        log_level=settings.LOG_LEVEL.lower(),
    )
