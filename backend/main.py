"""
FastAPI entry point - reads PORT from Railway environment
"""
import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Read PORT from Railway (falls back to 8000 for local dev)
PORT = int(os.environ.get("PORT", "8000"))
logger.info(f"Configured to use PORT: {PORT}")

# =====================================================================
# GRACEFUL IMPORTS
# =====================================================================

settings = None
try:
    from app.config import settings as _s
    settings = _s
    logger.info("Settings OK")
except Exception as e:
    logger.error(f"Settings fail: {e}")

db_ok = False
try:
    from app.database import init_db
    db_ok = True
    logger.info("Database OK")
except Exception as e:
    logger.error(f"Database fail: {e}")

scheduler_ok = False
agent_scheduler = None
try:
    from app.scheduler import agent_scheduler as _s
    agent_scheduler = _s
    scheduler_ok = True
    logger.info("Scheduler OK")
except Exception as e:
    logger.error(f"Scheduler fail: {e}")

routers = []
ROUTERS_TO_LOAD = [
    ("app.routers.webhooks", False),
    ("app.routers.telegram", False),
    ("app.routers.telegram_webhook", False),
    ("app.routers.products", True),
    ("app.routers.orders", True),
    ("app.routers.decisions", True),
    ("app.routers.agents", True),
    ("app.routers.sms", False),
    ("app.routers.analytics", True),
    ("app.routers.settings", True),
]

for module_path, _ in ROUTERS_TO_LOAD:
    try:
        mod = __import__(module_path, fromlist=["router"])
        router = getattr(mod, "router", None)
        if router:
            routers.append((module_path.split(".")[-1], router))
            logger.info(f"Router OK: {module_path}")
    except Exception as e:
        logger.error(f"Router FAIL: {module_path} - {e}")

logger.info(f"Loaded {len(routers)} routers")

# =====================================================================
# LIFESPAN
# =====================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("STARTUP")
    logger.info("=" * 60)

    if db_ok:
        try:
            await init_db()
            logger.info("DB init OK")
        except Exception as e:
            logger.error(f"DB init fail: {e}")

    if scheduler_ok and agent_scheduler:
        try:
            agent_scheduler.start()
            logger.info("Scheduler started")
        except Exception as e:
            logger.error(f"Scheduler fail: {e}")

    logger.info("Ready - accepting requests")
    yield

    logger.info("Shutting down...")
    if scheduler_ok and agent_scheduler:
        try:
            agent_scheduler.shutdown()
        except:
            pass
    logger.info("Done")

# =====================================================================
# APP
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
# HEALTH
# =====================================================================

@app.get("/")
async def root():
    return {"name": "AI Dropshipping Store Backend", "version": "1.0.0", "status": "ok"}

@app.get("/health")
async def health():
    return {"status": "ok", "database": "ok" if db_ok else "fail", "scheduler": "ok" if scheduler_ok else "fail", "routers": len(routers)}

# =====================================================================
# ROUTERS
# =====================================================================

for name, router in routers:
    try:
        app.include_router(router)
        logger.info(f"Registered: {name}")
    except Exception as e:
        logger.error(f"Register FAIL: {name} - {e}")

logger.info(f"Total: {len(routers)} routers")
logger.info("App ready!")

# =====================================================================
# STARTUP - When run directly, use the PORT from env
# =====================================================================

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting uvicorn on port {PORT}")
    uvicorn.run("main:app", host="0.0.0.0", port=PORT)
