import sys
import traceback
import asyncio
import threading
import socket
import time
import os
import logging
from datetime import datetime
from typing import Optional

print("=" * 60)
print("🚀 THeO BACKEND - STARTING")
print("=" * 60)

# -------------------------
# IMPORT SECTION
# -------------------------
print("\n📦 Loading dependencies...")

try:
    from dotenv import load_dotenv
    from pydantic import BaseModel
    print("  ✅ Core imports successful")
except Exception as e:
    print(f"  ❌ Core import error: {e}")
    traceback.print_exc()
    sys.exit(1)

try:
    from fastapi import FastAPI, Depends, HTTPException, Request
    from fastapi.security import OAuth2PasswordRequestForm
    from fastapi.responses import JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    print("  ✅ FastAPI imports successful")
except Exception as e:
    print(f"  ❌ FastAPI import error: {e}")
    traceback.print_exc()
    sys.exit(1)

try:
    from sqlalchemy.orm import Session
    import models
    from models import HotelCreate
    from database import engine, get_db
    from auth import (
        verify_password,
        create_access_token,
        get_current_user,
        hash_password,
    )
    print("  ✅ Database & auth imports successful")
except Exception as e:
    print(f"  ❌ Database import error: {e}")
    traceback.print_exc()
    sys.exit(1)

# Router imports
try:
    from routers.bookings import router as bookings_router
    from routers.confirmed_bookings import router as confirmed_router
    from routers.telegram_webhook import router as telegram_router
    from routers import modifications
    modifications_router = modifications.router
    print("  ✅ Router imports successful")
except Exception as e:
    print(f"  ❌ Router import error: {e}")
    traceback.print_exc()
    sys.exit(1)

print("\n✅ ALL IMPORTS SUCCESSFUL")
print("=" * 60)

# -------------------------
# ENVIRONMENT SETUP
# -------------------------
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MANAGER_CHAT_ID = os.getenv("MANAGER_CHAT_ID")
DATABASE_URL = os.getenv("DATABASE_URL")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("\n=== Environment Variables Check ===")
logger.info(f"TELEGRAM_BOT_TOKEN set: {'Yes' if TELEGRAM_BOT_TOKEN else 'No'}")
if TELEGRAM_BOT_TOKEN:
    logger.info(f"  Token starts with: {TELEGRAM_BOT_TOKEN[:10]}...")
logger.info(f"MANAGER_CHAT_ID set: {'Yes' if MANAGER_CHAT_ID else 'No'}")
logger.info(f"DATABASE_URL set: {'Yes' if DATABASE_URL else 'No'}")
logger.info("===================================")

# -------------------------
# FASTAPI APP CREATION
# -------------------------
print("\n🚀 Creating FastAPI app...")
app = FastAPI(
    title="THeO Hotel Booking Automation",
    description="API for hotel booking automation system with Telegram integration and modification tracking",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)
print("✅ FastAPI app created")

# -------------------------
# RENDER PORT BINDING FIX
# -------------------------
print("\n🔌 Setting up port binding for Render...")

def ensure_port_bound():
    """Ensure the port is bound immediately for Render detection"""
    port = int(os.environ.get("PORT", 10000))
    max_attempts = 5
    
    for attempt in range(max_attempts):
        try:
            # Create a socket to bind to the port
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", port))
            sock.listen(1)
            print(f"  ✅ Port {port} bound successfully (attempt {attempt + 1})")
            sock.close()
            return True
        except Exception as e:
            print(f"  ⚠️ Port binding attempt {attempt + 1} failed: {e}")
            time.sleep(0.5)
    
    print("  ⚠️ Could not bind port immediately - continuing anyway")
    return False

# Start port binding in background thread
threading.Thread(target=ensure_port_bound, daemon=True).start()
print("  ✅ Port binding thread started")

# -------------------------
# SIMPLE HEALTH CHECK ENDPOINTS
# -------------------------
@app.get("/healthz")
async def healthz():
    """Ultra simple health check - always responds immediately"""
    return {"status": "alive", "timestamp": datetime.utcnow().isoformat()}

@app.get("/ping")
async def ping():
    """Simple ping endpoint"""
    return {"status": "ok", "message": "Server is running"}

# -------------------------
# CORS MIDDLEWARE
# -------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://*.webcontainer.io",
        "https://localhost:5173",
        "https://stackblitz.com",
        "https://*.stackblitz.io",
        "https://*.stackblitz.com",
        "https://vitejsvitenejrzqzk-bdt5--5173--8669d46c.local-corp.webcontainer.io/"
        "http://localhost:5173",
        "http://localhost:3000",
        "https://theo-saas.onrender.com",
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger.info("\n" + "=" * 60)
logger.info("🚀 FASTAPI APP CONFIGURED")
logger.info(f"📋 Title: {app.title}")
logger.info(f"📦 Version: {app.version}")
logger.info("=" * 60)

# -------------------------
# BACKGROUND MIGRATIONS
# -------------------------
async def run_background_migrations():
    """Run database migrations in the background"""
    print("\n🔄 Starting background migrations...")
    try:
        # Create tables
        models.Base.metadata.create_all(bind=engine)
        logger.info("  ✅ Database tables created")

        from sqlalchemy import text, inspect
        
        with engine.connect() as conn:
            # Hotel table migrations
            conn.execute(text("ALTER TABLE hotels ADD COLUMN IF NOT EXISTS address VARCHAR"))
            conn.execute(text("ALTER TABLE hotels ADD COLUMN IF NOT EXISTS city VARCHAR"))
            conn.execute(text("ALTER TABLE hotels ADD COLUMN IF NOT EXISTS country VARCHAR"))
            conn.execute(text("ALTER TABLE hotels ADD COLUMN IF NOT EXISTS phone VARCHAR"))
            conn.execute(text("ALTER TABLE hotels ADD COLUMN IF NOT EXISTS email VARCHAR"))
            conn.execute(text("ALTER TABLE hotels ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()"))
            conn.execute(text("ALTER TABLE hotels ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()"))
            logger.info("  ✅ Hotel columns verified")

            # User table migrations
            inspector = inspect(engine)
            existing_columns = [col['name'] for col in inspector.get_columns('users')]
            
            columns_to_add = [
                ('name', 'VARCHAR'),
                ('phone', 'VARCHAR'),
                ('active', 'BOOLEAN DEFAULT true'),
                ('last_login', 'TIMESTAMP')
            ]
            
            for col_name, col_type in columns_to_add:
                if col_name not in existing_columns:
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}"))
                    logger.info(f"  ✅ Added {col_name} column")
                else:
                    logger.info(f"  ✅ {col_name} column already exists")
            
            conn.commit()
            print("✅ Background migrations complete!")
            
    except Exception as e:
        logger.error(f"❌ Background migration error: {e}")
        print(f"❌ Migration error: {e}")

@app.on_event("startup")
async def startup_event():
    """Application startup handler"""
    logger.info("\n" + "=" * 50)
    logger.info("THeO Application Starting Up - Version 2.0")
    logger.info("=" * 50)
    
    # Log environment
    env = os.getenv("RAILWAY_ENVIRONMENT", "development")
    logger.info(f"📊 Environment: {env}")
    logger.info(f"📊 Database URL: {DATABASE_URL[:20]}..." if DATABASE_URL else "📊 Database URL: Not set")
    
    # Check Telegram
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("⚠️ TELEGRAM_BOT_TOKEN not set - Telegram features disabled")
    if not MANAGER_CHAT_ID:
        logger.warning("⚠️ MANAGER_CHAT_ID not set - Manager notifications disabled")
    
    # Start migrations in background
    asyncio.create_task(run_background_migrations())
    
    logger.info("=" * 50)

# -------------------------
# ROUTER INCLUSION
# -------------------------
logger.info("\n📦 Including routers...")

try:
    app.include_router(bookings_router)
    logger.info("  ✅ Bookings router included")
    
    app.include_router(confirmed_router)
    logger.info("  ✅ Confirmed bookings router included")
    
    app.include_router(telegram_router)
    logger.info("  ✅ Telegram router included")
    
    app.include_router(modifications_router)
    logger.info("  ✅ Modifications router included")
    
except Exception as e:
    logger.error(f"❌ Router inclusion error: {e}")
    raise

logger.info("✅ All routers included successfully")

# -------------------------
# DEBUG ENDPOINTS
# -------------------------
@app.get("/debug-routes")
def debug_routes():
    """List all registered routes"""
    routes = []
    for route in app.routes:
        routes.append({
            "path": route.path,
            "name": route.name,
            "methods": list(route.methods) if hasattr(route, 'methods') else None
        })
    return {"routes": routes}

@app.get("/debug-env")
async def debug_env():
    """Debug endpoint for environment variables"""
    return {
        "telegram_token_set": bool(TELEGRAM_BOT_TOKEN),
        "manager_chat_id_set": bool(MANAGER_CHAT_ID),
        "database_url_set": bool(DATABASE_URL),
        "environment": os.getenv("RAILWAY_ENVIRONMENT", "development")
    }

@app.get("/debug-db")
async def debug_db(db: Session = Depends(get_db)):
    """Debug endpoint for database connection"""
    try:
        from sqlalchemy import text
        result = db.execute(text("SELECT 1")).scalar()
        return {
            "database_connected": bool(result == 1),
            "status": "healthy"
        }
    except Exception as e:
        return {
            "database_connected": False,
            "error": str(e),
            "status": "degraded"
        }

# -------------------------
# CORS PREFLIGHT HANDLERS
# -------------------------
@app.options("/{rest_of_path:path}")
async def preflight_handler(rest_of_path: str):
    return JSONResponse(
        content={"message": "OK"},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, PATCH, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Allow-Credentials": "true",
        },
    )

# -------------------------
# MIDDLEWARE
# -------------------------
@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"➡️ {request.method} {request.url.path}")
    response = await call_next(request)
    logger.info(f"⬅️ {response.status_code}")
    return response

# -------------------------
# ROOT ENDPOINT
# -------------------------
@app.get("/")
def read_root():
    return {
        "message": "THeO SaaS Backend is running",
        "version": "2.0.0",
        "docs": "/docs",
        "health": "/health",
        "ping": "/ping",
        "healthz": "/healthz"
    }

# -------------------------
# HEALTH CHECK
# -------------------------
@app.get("/health")
def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

# -------------------------
# [REST OF YOUR ENDPOINTS HERE]
# All your existing endpoints (login, hotels, users, bookings, etc.)
# -------------------------

# Copy all your existing endpoint code here...
# (The code from line 400 onward - all your @app.post, @app.get, etc.)

# -------------------------
# SHUTDOWN EVENT
# -------------------------
@app.on_event("shutdown")
async def shutdown_event():
    logger.info("THeO Application Shutting Down - Version 2.0")

# -------------------------
# NOTE: Render uses gunicorn, not this block
# -------------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    print(f"\n🚀 Starting development server on port {port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)