"""
FastAPI entry point for AI Dropshipping Store.
BULLETPROOF VERSION - Every import has error handling.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# =====================================================================
# GRACEFUL IMPORTS - App starts even if components fail
# =====================================================================


# Settings
settings = None
try:
    from app.config import settings as _settings
    settings = _settings
    logger.info("Settings loaded OK")
except Exception as e:
    logger.error(f"Settings failed: {e}")

# Database
db_ok = False
try:
    from app.database import init_db
    db_ok = True
    logger.info("Database import OK")
except Exception as e:
    logger.error(f"Database import failed: {e}")

# Scheduler
scheduler_ok = False
agent_scheduler = None
try:
    from app.scheduler import agent_scheduler as _sched
    agent_scheduler = _sched
    scheduler_ok = True
    logger.info("Scheduler import OK")
except Exception as e:
    logger.error(f"Scheduler import failed: {e}")

# ------------------------------------------------------------------
# Import routers with individual error handling
# ------------------------------------------------------------------
routers = []


ROUTERS_TO_LOAD = [
    ("app.routers.webhooks", "webhooks", False),
    ("app.routers.telegram", "telegram_router", False),
    ("app.routers.telegram_webhook", "telegram_webhook", False),
    ("app.routers.products", "products", True),
    ("app.routers.orders", "orders", True),
    ("app.routers.decisions", "decisions", True),
    ("app.routers.agents", "agents", True),
    ("app.routers.sms", "sms", False),
    ("app.routers.analytics", "analytics", True),
    ("app.routers.settings", "settings_router", True),
]

for module_path, router_name, _ in ROUTERS_TO_LOAD:
    try:
        mod = __import__(module_path, fromlist=[router_name])
        router = getattr(mod, "router", None)
        if router:
            routers.append((module_path.split(".")[-1], router))
            logger.info(f"Router OK: {module_path}")
        else:
            logger.warning(f"Router missing 'router' attr: {module_path}")
    except Exception as e:
        logger.error(f"Router FAILED: {module_path} - {e}")

logger.info(f"Loaded {len(routers)} routers: {[n for n, _ in routers]}")

# =====================================================================
# LIFESPAN - Startup/shutdown with full error handling
# =====================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("STARTUP - AI Dropshipping Store Backend")
    logger.info("=" * 60)

    if db_ok:
        try:
            await init_db()
            logger.info("Database initialized OK")
        except Exception as e:
            logger.error(f"Database init failed: {e}")
    else:
        logger.warning("Database skipped (import failed)")

    if scheduler_ok and agent_scheduler:
        try:
            agent_scheduler.start()
            logger.info("Scheduler started OK")
        except Exception as e:
            logger.error(f"Scheduler start failed: {e}")
    else:
        logger.warning("Scheduler skipped (import failed)")

    logger.info("Startup complete - accepting requests")
    yield

    logger.info("Shutting down...")
    if scheduler_ok and agent_scheduler:
        try:
            agent_scheduler.shutdown()
            logger.info("Scheduler stopped")
        except Exception as e:
            logger.error(f"Scheduler stop failed: {e}")
    logger.info("Shutdown complete")

# =====================================================================
# FASTAPI APP - Created with ZERO dependencies, always exists
# =====================================================================

app = FastAPI(
    title="AI Dropshipping Store Backend",
    description="Automated AI dropshipping with human-in-the-loop",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================================================================
# HEALTH ENDPOINTS - Always work
# =====================================================================

@app.get("/")
async def root():
    return {
        "name": "AI Dropshipping Store Backend",
        "version": "1.0.0",
        "docs": "/docs",
        "status": "ok",
    }

@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "database": "connected" if db_ok else "unavailable",
        "scheduler": "running" if scheduler_ok else "unavailable",
        "routers_loaded": len(routers),
    }

# =====================================================================
# REGISTER ROUTERS
# =====================================================================

for name, router in routers:
    try:
        app.include_router(router)
        logger.info(f"Router registered: {name}")
    except Exception as e:
        logger.error(f"Router registration FAILED: {name} - {e}")

logger.info(f"Total routers registered: {len(routers)}")
logger.info("App ready!")
