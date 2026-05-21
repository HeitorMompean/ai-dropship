"""FastAPI entry point for the AI Dropshipping Store backend."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import settings
from app.database import init_db
from app.scheduler import agent_scheduler

# Import all routers
from app.routers import webhooks, products, orders, decisions, agents, sms, analytics, telegram, settings as settings_router
from app.routers import telegram_webhook

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Simple bearer token auth
credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or missing Bearer token",
    headers={"WWW-Authenticate": "Bearer"},
)

security = HTTPBearer(auto_error=False)


async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """Verify the Bearer token matches APP_SECRET_KEY."""
    if settings.app_env == "development" and settings.app_secret_key == "demo_secret_key_change_me":
        return "demo"
    if not credentials:
        raise credentials_exception
    if credentials.credentials != settings.app_secret_key:
        raise credentials_exception
    return credentials.credentials


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown events."""
    logger.info("Starting up AI Dropshipping Store backend...")
    await init_db()
    agent_scheduler.start()
    logger.info("Startup complete.")
    yield
    logger.info("Shutting down...")
    agent_scheduler.shutdown()
    logger.info("Shutdown complete.")


app = FastAPI(
    title="AI Dropshipping Store Backend",
    description="Automated AI dropshipping store with human-in-the-loop decisions via SMS.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
# Webhooks have no auth (HMAC verified inside)
app.include_router(webhooks.router)

# SMS inbound webhook has no auth (external gateway calls it)
app.include_router(sms.router)
app.include_router(telegram.router)
app.include_router(telegram_webhook.router)

# REST API routes use Bearer token auth
app.include_router(products.router, dependencies=[Depends(verify_token)])
app.include_router(orders.router, dependencies=[Depends(verify_token)])
app.include_router(decisions.router, dependencies=[Depends(verify_token)])
app.include_router(agents.router, dependencies=[Depends(verify_token)])
app.include_router(analytics.router, dependencies=[Depends(verify_token)])
app.include_router(settings_router.router, dependencies=[Depends(verify_token)])


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "ok", "env": settings.app_env, "demo_mode": settings.is_demo_mode}


@app.get("/")
async def root() -> dict:
    """API root with basic info."""
    return {
        "name": "AI Dropshipping Store Backend",
        "version": "1.0.0",
        "docs": "/docs",
        "demo_mode": settings.is_demo_mode,
    }


