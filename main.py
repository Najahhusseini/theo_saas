import os
import logging
from dotenv import load_dotenv
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

import models
from database import engine, get_db
from auth import (
    verify_password,
    create_access_token,
    get_current_user,
    hash_password,
)

from routers.bookings import router as bookings_router
from routers.confirmed_bookings import router as confirmed_router
from routers.telegram_webhook import router as telegram_router
from routers import modifications
modifications_router = modifications.router

# -------------------------
# SETUP LOGGING
# -------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# -------------------------
# LOAD ENV VARIABLES
# -------------------------
load_dotenv()

# Verify critical environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MANAGER_CHAT_ID = os.getenv("MANAGER_CHAT_ID")
DATABASE_URL = os.getenv("DATABASE_URL")

logger.info("=== Environment Variables Check ===")
logger.info(f"TELEGRAM_BOT_TOKEN set: {'Yes' if TELEGRAM_BOT_TOKEN else 'No'}")
if TELEGRAM_BOT_TOKEN:
    logger.info(f"Token starts with: {TELEGRAM_BOT_TOKEN[:10]}...")
logger.info(f"MANAGER_CHAT_ID set: {'Yes' if MANAGER_CHAT_ID else 'No'}")
logger.info(f"DATABASE_URL set: {'Yes' if DATABASE_URL else 'No'}")
logger.info("===================================")

# -------------------------
# CREATE TABLES
# -------------------------
try:
    models.Base.metadata.create_all(bind=engine)
    logger.info("Database tables created successfully")
except Exception as e:
    logger.error(f"Error creating database tables: {e}")

# -------------------------
# FASTAPI APP
# -------------------------
app = FastAPI(
    title="THeO Hotel Booking Automation",
    description="API for hotel booking automation system with Telegram integration and modification tracking",
    version="2.0.0"  # Updated version
)

# Include routers
app.include_router(bookings_router)
app.include_router(confirmed_router)
app.include_router(telegram_router)
app.include_router(modifications_router)  # NEW ROUTER

# -------------------------
# MIDDLEWARE
# -------------------------
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all incoming requests"""
    logger.info(f"Request: {request.method} {request.url.path}")
    response = await call_next(request)
    logger.info(f"Response status: {response.status_code}")
    return response

# -------------------------
# ROOT ENDPOINT
# -------------------------
@app.get("/")
def read_root():
    """Root endpoint with API information"""
    return {
        "message": "THeO SaaS Backend is running",
        "version": "2.0.0",
        "endpoints": {
            "docs": "/docs",
            "health": "/health",
            "telegram_webhook": "/telegram/webhook",
            "bookings": "/booking-requests",
            "confirmed_bookings": "/confirmed-bookings",
            "modifications": "/modifications",  # NEW ENDPOINT
            "hotels": "/hotels/",
            "users": "/users/",
            "login": "/login"
        },
        "features": {
            "booking_management": True,
            "telegram_integration": True,
            "modification_tracking": True,  # NEW FEATURE
            "ai_drafts": True,
            "manager_qa": True
        }
    }

# -------------------------
# HEALTH CHECK ENDPOINT
# -------------------------
@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    """Health check endpoint for Railway monitoring"""
    from sqlalchemy import text
    
    health_status = {
        "status": "healthy",
        "timestamp": str(datetime.utcnow()),
        "version": "2.0.0",
        "environment": {
            "telegram_token_set": bool(TELEGRAM_BOT_TOKEN),
            "manager_chat_id_set": bool(MANAGER_CHAT_ID),
            "database_url_set": bool(DATABASE_URL)
        }
    }
    
    # Test database connection
    try:
        db.execute(text("SELECT 1"))
        health_status["database"] = "connected"
        
        # Check if new tables exist
        try:
            modification_count = db.query(models.ModificationRequest).count()
            health_status["modifications_table"] = "present"
        except:
            health_status["modifications_table"] = "missing"
            
    except Exception as e:
        health_status["database"] = f"error: {str(e)}"
        health_status["status"] = "degraded"
    
    # Test Telegram bot token format
    if TELEGRAM_BOT_TOKEN:
        if ":" in TELEGRAM_BOT_TOKEN:
            health_status["telegram_token_format"] = "valid"
        else:
            health_status["telegram_token_format"] = "invalid"
            health_status["status"] = "degraded"
    else:
        health_status["telegram_token_format"] = "missing"
        health_status["status"] = "degraded"
    
    return health_status

# -------------------------
# TELEGRAM WEBHOOK SETUP ENDPOINT
# -------------------------
@app.post("/setup-webhook")
def setup_telegram_webhook(request: Request):
    """Endpoint to setup Telegram webhook (call this after deployment)"""
    if not TELEGRAM_BOT_TOKEN:
        return JSONResponse(
            status_code=400,
            content={"error": "TELEGRAM_BOT_TOKEN not set"}
        )
    
    # Get the base URL of the current request
    base_url = str(request.base_url).rstrip('/')
    webhook_url = f"{base_url}/telegram/webhook"
    
    import requests
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"
    
    try:
        response = requests.post(api_url, json={
            "url": webhook_url,
            "allowed_updates": ["message", "callback_query"]
        })
        
        result = response.json()
        
        if result.get("ok"):
            # Get webhook info
            info_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getWebhookInfo"
            info_response = requests.get(info_url)
            webhook_info = info_response.json()
            
            return {
                "message": "Webhook setup successful",
                "webhook_url": webhook_url,
                "set_webhook_response": result,
                "webhook_info": webhook_info
            }
        else:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "Failed to set webhook",
                    "details": result
                }
            )
            
    except Exception as e:
        logger.error(f"Error setting up webhook: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

# -------------------------
# TELEGRAM TEST ENDPOINT
# -------------------------
@app.post("/test-telegram")
def test_telegram_connection():
    """Test Telegram bot connection"""
    if not TELEGRAM_BOT_TOKEN:
        return JSONResponse(
            status_code=400,
            content={"error": "TELEGRAM_BOT_TOKEN not set"}
        )
    
    if not MANAGER_CHAT_ID:
        return JSONResponse(
            status_code=400,
            content={"error": "MANAGER_CHAT_ID not set"}
        )
    
    import requests
    
    # Test 1: Get bot info
    try:
        bot_info = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe"
        ).json()
    except Exception as e:
        bot_info = {"error": str(e)}
    
    # Test 2: Send test message
    try:
        send_result = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": MANAGER_CHAT_ID,
                "text": "🔧 Test message from THeO bot v2.0\n\nModification tracking feature added!"
            }
        ).json()
    except Exception as e:
        send_result = {"error": str(e)}
    
    return {
        "bot_info": bot_info,
        "test_message_result": send_result,
        "manager_chat_id": MANAGER_CHAT_ID,
        "note": "If test message fails, make sure you've started a chat with the bot first"
    }

# -------------------------
# CREATE HOTEL
# -------------------------
@app.post("/hotels/")
def create_hotel(
    name: str, 
    subscription_plan: str, 
    db: Session = Depends(get_db)
):
    """Create a new hotel"""
    try:
        new_hotel = models.Hotel(
            name=name,
            subscription_plan=subscription_plan
        )
        
        db.add(new_hotel)
        db.commit()
        db.refresh(new_hotel)
        
        logger.info(f"Created hotel: {name} (ID: {new_hotel.id})")
        return new_hotel
        
    except Exception as e:
        logger.error(f"Error creating hotel: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# -------------------------
# CREATE USER
# -------------------------
@app.post("/users/")
def create_user(
    email: str,
    password: str,
    role: str,
    hotel_id: int,
    db: Session = Depends(get_db)
):
    """Create a new user"""
    # Check if user already exists
    existing_user = db.query(models.User).filter(
        models.User.email == email
    ).first()
    
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Validate password length
    if len(password) > 72:
        raise HTTPException(status_code=400, detail="Password too long (max 72 characters)")
    
    # Validate role
    if role not in ["admin", "manager", "staff"]:
        raise HTTPException(status_code=400, detail="Invalid role. Must be admin, manager, or staff")
    
    # Check if hotel exists
    hotel = db.query(models.Hotel).filter(models.Hotel.id == hotel_id).first()
    if not hotel:
        raise HTTPException(status_code=404, detail="Hotel not found")
    
    try:
        hashed_pw = hash_password(password)
        
        new_user = models.User(
            email=email,
            hashed_password=hashed_pw,
            role=role,
            hotel_id=hotel_id
        )
        
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        logger.info(f"Created user: {email} (Role: {role})")
        
        return {
            "id": new_user.id,
            "email": new_user.email,
            "role": new_user.role,
            "hotel_id": new_user.hotel_id,
            "message": "User created successfully"
        }
        
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# -------------------------
# LOGIN
# -------------------------
@app.post("/login")
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """Login endpoint - returns JWT token"""
    try:
        user = db.query(models.User).filter(
            models.User.email == form_data.username
        ).first()
        
        if not user:
            logger.warning(f"Login failed: User not found - {form_data.username}")
            raise HTTPException(status_code=400, detail="Invalid credentials")
        
        if not verify_password(form_data.password, user.hashed_password):
            logger.warning(f"Login failed: Invalid password for {form_data.username}")
            raise HTTPException(status_code=400, detail="Invalid credentials")
        
        token = create_access_token({
            "sub": user.email,
            "hotel_id": user.hotel_id,
            "role": user.role
        })
        
        logger.info(f"Login successful: {user.email}")
        
        return {
            "access_token": token,
            "token_type": "bearer",
            "user_id": user.id,
            "email": user.email,
            "role": user.role,
            "hotel_id": user.hotel_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# -------------------------
# PROTECTED TEST ENDPOINTS
# -------------------------
@app.get("/protected")
def protected_route(current_user: models.User = Depends(get_current_user)):
    """Test protected route"""
    return {
        "message": "You are authenticated",
        "user": {
            "id": current_user.id,
            "email": current_user.email,
            "role": current_user.role,
            "hotel_id": current_user.hotel_id
        }
    }

@app.get("/me")
def get_current_user_info(current_user: models.User = Depends(get_current_user)):
    """Get current user information"""
    return {
        "id": current_user.id,
        "email": current_user.email,
        "role": current_user.role,
        "hotel_id": current_user.hotel_id
    }

# -------------------------
# MODIFICATION STATS ENDPOINT
# -------------------------
@app.get("/modifications/stats")
def get_modification_stats(db: Session = Depends(get_db)):
    """Get statistics about modification requests"""
    try:
        total = db.query(models.ModificationRequest).count()
        pending = db.query(models.ModificationRequest).filter(
            models.ModificationRequest.status == "Pending"
        ).count()
        approved = db.query(models.ModificationRequest).filter(
            models.ModificationRequest.status == "Approved"
        ).count()
        rejected = db.query(models.ModificationRequest).filter(
            models.ModificationRequest.status == "Rejected"
        ).count()
        
        # Get bookings with pending modifications
        bookings_with_pending = db.query(models.ConfirmedBooking).filter(
            models.ConfirmedBooking.has_pending_modification == True
        ).count()
        
        return {
            "total_modifications": total,
            "pending": pending,
            "approved": approved,
            "rejected": rejected,
            "bookings_with_pending": bookings_with_pending
        }
    except Exception as e:
        logger.error(f"Error getting modification stats: {e}")
        return {"error": str(e)}

# -------------------------
# ERROR HANDLERS
# -------------------------
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Custom HTTP exception handler"""
    logger.error(f"HTTP {exc.status_code}: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """General exception handler"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )

# -------------------------
# STARTUP EVENT
# -------------------------
@app.on_event("startup")
async def startup_event():
    """Run on application startup"""
    logger.info("="*50)
    logger.info("THeO Application Starting Up - Version 2.0")
    logger.info("="*50)
    
    # Log environment status
    logger.info(f"Environment: {'production' if os.getenv('RAILWAY_ENVIRONMENT') else 'development'}")
    logger.info(f"Database URL: {DATABASE_URL[:20]}..." if DATABASE_URL else "Database URL: Not set")
    
    # Check Telegram configuration
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("⚠️ TELEGRAM_BOT_TOKEN not set - Telegram features disabled")
    if not MANAGER_CHAT_ID:
        logger.warning("⚠️ MANAGER_CHAT_ID not set - Manager notifications disabled")
    
    # Log available endpoints
    logger.info("Available endpoints:")
    for route in app.routes:
        if hasattr(route, "methods") and route.path:
            logger.info(f"  {route.methods} {route.path}")
    
    logger.info("="*50)

# -------------------------
# SHUTDOWN EVENT
# -------------------------
@app.on_event("shutdown")
async def shutdown_event():
    """Run on application shutdown"""
    logger.info("THeO Application Shutting Down - Version 2.0")"# Force rebuild" 
