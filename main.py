import sys
import traceback

print("="*60)
print("🚀 STARTING APPLICATION")
print("="*60)

try:
    import os
    import logging
    from dotenv import load_dotenv
    from datetime import datetime
    from pydantic import BaseModel
    from typing import Optional
    print("✅ Basic imports successful")
except Exception as e:
    print(f"❌ Basic import error: {e}")
    traceback.print_exc()
    sys.exit(1)


try:
    from fastapi import FastAPI, Depends, HTTPException, Request
    from fastapi.security import OAuth2PasswordRequestForm
    from fastapi.responses import JSONResponse
    from sqlalchemy.orm import Session
    from fastapi.middleware.cors import CORSMiddleware
    print("✅ FastAPI imports successful")
except Exception as e:
    print(f"❌ FastAPI import error: {e}")
    traceback.print_exc()
    sys.exit(1)

# Catch any import errors at the very beginning
try:
    import models
    from models import HotelCreate  
    from database import engine, get_db
    from auth import (
        verify_password,
        create_access_token,
        get_current_user,
        hash_password,
    )
    print("✅ Local module imports successful")
except Exception as e:
    print(f"❌ Local module import error: {e}")
    traceback.print_exc()
    sys.exit(1)

try:
    from routers.bookings import router as bookings_router
    print("✅ bookings_router imported")
except Exception as e:
    print(f"❌ bookings_router import error: {e}")
    traceback.print_exc()
    sys.exit(1)

try:
    from routers.confirmed_bookings import router as confirmed_router
    print("✅ confirmed_router imported")
except Exception as e:
    print(f"❌ confirmed_router import error: {e}")
    traceback.print_exc()
    sys.exit(1)

try:
    from routers.telegram_webhook import router as telegram_router
    print("✅ telegram_router imported")
except Exception as e:
    print(f"❌ telegram_router import error: {e}")
    traceback.print_exc()
    sys.exit(1)

try:
    from routers import modifications
    modifications_router = modifications.router
    print("✅ modifications_router imported")
except Exception as e:
    print(f"❌ modifications_router import error: {e}")
    traceback.print_exc()
    sys.exit(1)

print("✅ ALL IMPORTS SUCCESSFUL")
print("="*60)

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

    # Add missing columns to hotels table
    from sqlalchemy import text, inspect
    with engine.connect() as conn:
        # Hotel columns (your existing code)
        conn.execute(text("ALTER TABLE hotels ADD COLUMN IF NOT EXISTS address VARCHAR"))
        conn.execute(text("ALTER TABLE hotels ADD COLUMN IF NOT EXISTS city VARCHAR"))
        conn.execute(text("ALTER TABLE hotels ADD COLUMN IF NOT EXISTS country VARCHAR"))
        conn.execute(text("ALTER TABLE hotels ADD COLUMN IF NOT EXISTS phone VARCHAR"))
        conn.execute(text("ALTER TABLE hotels ADD COLUMN IF NOT EXISTS email VARCHAR"))
        conn.execute(text("ALTER TABLE hotels ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()"))
        conn.execute(text("ALTER TABLE hotels ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()"))
        logger.info("✅ Added/verified columns in hotels table")
        
        # ----- NEW DIAGNOSTIC CODE FOR USERS TABLE -----
        # Get existing columns in users table
        inspector = inspect(engine)
        existing_columns = [col['name'] for col in inspector.get_columns('users')]
        logger.info(f"🔍 Existing columns in users table: {existing_columns}")
        
        # Define columns to add with their types
        columns_to_add = [
            ('name', 'VARCHAR'),
            ('phone', 'VARCHAR'),
            ('active', 'BOOLEAN DEFAULT true'),
            ('last_login', 'TIMESTAMP')
        ]
        
        # Add missing columns one by one
        for col_name, col_type in columns_to_add:
            if col_name not in existing_columns:
                try:
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}"))
                    logger.info(f"✅ Added {col_name} column to users table")
                except Exception as e:
                    logger.error(f"❌ Failed to add {col_name}: {e}")
            else:
                logger.info(f"✅ {col_name} column already exists")
        
        # Also check hotels table columns for completeness
        hotel_columns = [col['name'] for col in inspector.get_columns('hotels')]
        logger.info(f"🔍 Existing columns in hotels table: {hotel_columns}")
        
        conn.commit()
        logger.info("✅ Database migration check completed")

except Exception as e:
    logger.error(f"❌ Error creating database tables: {e}")
    # Don't exit, maybe tables already exist

# -------------------------
# FASTAPI APP
# -------------------------
app = FastAPI(
    title="THeO Hotel Booking Automation",
    description="API for hotel booking automation system with Telegram integration and modification tracking",
    version="2.0.0",
    docs_url="/docs",        # Explicitly enable docs
    redoc_url="/redoc",       # Explicitly enable redoc
    openapi_url="/openapi.json"  # Explicitly enable OpenAPI schema
)

logger.info("="*60)
logger.info("🚀 FASTAPI APP CREATED")
logger.info(f"📋 Title: {app.title}")
logger.info(f"📦 Version: {app.version}")
logger.info("="*60)

# 👇 ADD CORS MIDDLEWARE HERE - RIGHT AFTER CREATING APP
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://*.webcontainer.io", 
        "https://localhost:5173", 
        "https://stackblitz.com", 
        "https://*.stackblitz.io", 
        "https://*.stackblitz.com",
        "http://localhost:5173",
        "http://localhost:3000",
        "https://theo-backend.onrender.com",  # Add your Render URL
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
# DEBUG: Check before router includes
# -------------------------
logger.info("="*60)
logger.info("📦 PREPARING TO INCLUDE ROUTERS")
logger.info(f"Current working directory: {os.getcwd()}")
logger.info(f"Files in routers directory: {os.listdir('routers') if os.path.exists('routers') else 'routers folder not found'}")

# Include routers with detailed logging
logger.info("="*60)
logger.info("📦 INCLUDING ROUTERS")

try:
    logger.info("  - Attempting to import bookings_router...")
    from routers.bookings import router as bookings_router
    logger.info("  ✅ bookings_router imported successfully")
    
    logger.info("  - Including bookings_router...")
    app.include_router(bookings_router)
    logger.info("  ✅ bookings_router included")
except Exception as e:
    logger.error(f"❌ Failed with bookings_router: {e}", exc_info=True)
    raise

try:
    logger.info("  - Attempting to import confirmed_router...")
    from routers.confirmed_bookings import router as confirmed_router
    logger.info("  ✅ confirmed_router imported successfully")
    
    logger.info("  - Including confirmed_router...")
    app.include_router(confirmed_router)
    logger.info("  ✅ confirmed_router included")
except Exception as e:
    logger.error(f"❌ Failed with confirmed_router: {e}", exc_info=True)
    raise

try:
    logger.info("  - Attempting to import telegram_router...")
    from routers.telegram_webhook import router as telegram_router
    logger.info("  ✅ telegram_router imported successfully")
    
    logger.info("  - Including telegram_router...")
    app.include_router(telegram_router)
    logger.info("  ✅ telegram_router included")
except Exception as e:
    logger.error(f"❌ Failed with telegram_router: {e}", exc_info=True)
    raise

try:
    logger.info("  - Attempting to import modifications_router...")
    from routers import modifications
    modifications_router = modifications.router
    logger.info("  ✅ modifications_router imported successfully")
    
    logger.info("  - Including modifications_router...")
    app.include_router(modifications_router)
    logger.info("  ✅ modifications_router included")
except Exception as e:
    logger.error(f"❌ Failed with modifications_router: {e}", exc_info=True)
    raise

logger.info("✅ All routers included successfully")
logger.info("="*60)

# Add debug endpoint to check routes
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

# Add OPTIONS handlers for CORS
@app.options("/{rest_of_path:path}")
async def preflight_handler(rest_of_path: str):
    """Handle OPTIONS requests for all routes"""
    return JSONResponse(
        content={"message": "OK"},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, PATCH, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With",
            "Access-Control-Allow-Credentials": "true",
        },
    )

@app.options("/hotels/")
async def hotels_options():
    """Handle OPTIONS requests for CORS preflight"""
    return JSONResponse(
        content={"message": "OK"},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        },
    )

@app.options("/users/")
async def users_options():
    """Handle OPTIONS requests for CORS preflight"""
    return JSONResponse(
        content={"message": "OK"},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        },
    )

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
# TEST ENDPOINTS (for debugging)
# -------------------------
@app.get("/ping")
async def ping():
    """Simple ping endpoint to check if server is running"""
    return {"status": "ok", "message": "Server is running", "timestamp": str(datetime.utcnow())}

@app.get("/debug-env")
async def debug_env():
    """Debug endpoint to check environment variables (without exposing secrets)"""
    return {
        "telegram_token_set": bool(TELEGRAM_BOT_TOKEN),
        "manager_chat_id_set": bool(MANAGER_CHAT_ID),
        "database_url_set": bool(DATABASE_URL),
        "environment": os.getenv("RAILWAY_ENVIRONMENT", "development")
    }

@app.get("/debug-db")
async def debug_db(db: Session = Depends(get_db)):
    """Debug endpoint to check database connection"""
    try:
        from sqlalchemy import text
        result = db.execute(text("SELECT 1")).scalar()
        user_count = db.query(models.User).count()
        hotel_count = db.query(models.Hotel).count()
        
        # Check users table columns
        from sqlalchemy import inspect
        inspector = inspect(db.bind)
        user_columns = [col['name'] for col in inspector.get_columns('users')]
        
        return {
            "database_connected": bool(result == 1),
            "user_count": user_count,
            "hotel_count": hotel_count,
            "user_columns": user_columns,
            "status": "healthy"
        }
    except Exception as e:
        return {
            "database_connected": False,
            "error": str(e),
            "status": "degraded"
        }

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
            "redoc": "/redoc",
            "openapi": "/openapi.json",
            "health": "/health",
            "ping": "/ping",
            "debug-env": "/debug-env",
            "debug-db": "/debug-db",
            "debug-routes": "/debug-routes",
            "telegram_webhook": "/telegram/webhook",
            "bookings": "/booking-requests",
            "confirmed_bookings": "/confirmed-bookings",
            "modifications": "/modifications",
            "hotels": "/hotels/",
            "users": "/users/",
            "login": "/login",
            "room_types": {
                "create_test": "/room-types/create-test",
                "list": "/room-types/list",
                "by_hotel": "/room-types/by-hotel/{hotel_id}",
                "create": "/room-types/create",
                "update": "/room-types/{room_type_id}",
                "delete": "/room-types/{room_type_id}"
            }
        },
        "features": {
            "booking_management": True,
            "telegram_integration": True,
            "modification_tracking": True,
            "ai_drafts": True,
            "manager_qa": True,
            "room_type_management": True
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
    hotel: HotelCreate,
    db: Session = Depends(get_db)
):
    """Create a new hotel with complete information"""
    try:
        logger.info(f"📥 Received hotel creation request: {hotel.name}")
        
        # Check if hotel with same email already exists
        if hotel.email:
            existing = db.query(models.Hotel).filter(models.Hotel.email == hotel.email).first()
            if existing:
                logger.warning(f"❌ Hotel with email {hotel.email} already exists")
                raise HTTPException(status_code=400, detail="Hotel with this email already exists")
        
        # Create new hotel with all fields
        new_hotel = models.Hotel(
            name=hotel.name,
            subscription_plan=hotel.subscription_plan,
            address=hotel.address,
            city=hotel.city,
            country=hotel.country,
            phone=hotel.phone,
            email=hotel.email
        )
        
        db.add(new_hotel)
        db.commit()
        db.refresh(new_hotel)
        
        logger.info(f"✅ Created hotel: {hotel.name} (ID: {new_hotel.id})")
        logger.info(f"📤 Returning hotel data with ID: {new_hotel.id}")
        
        # Return the created hotel with ALL fields including ID
        response_data = {
            "id": new_hotel.id,
            "name": new_hotel.name,
            "subscription_plan": new_hotel.subscription_plan,
            "address": new_hotel.address,
            "city": new_hotel.city,
            "country": new_hotel.country,
            "phone": new_hotel.phone,
            "email": new_hotel.email
        }
        
        logger.info(f"📤 Response data: {response_data}")
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error creating hotel: {e}")
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
    try:
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
        
        logger.info(f"✅ Created user: {email} (Role: {role}) for hotel {hotel_id}")
        
        return {
            "id": new_user.id,
            "email": new_user.email,
            "role": new_user.role,
            "hotel_id": new_user.hotel_id,
            "message": "User created successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error creating user: {e}")
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
        logger.info("="*50)
        logger.info("🔐 LOGIN ATTEMPT")
        logger.info(f"Username: {form_data.username}")
        
        # Query user with all fields
        user = db.query(models.User).filter(
            models.User.email == form_data.username
        ).first()
        
        if not user:
            logger.warning(f"Login failed: User not found - {form_data.username}")
            raise HTTPException(status_code=400, detail="Invalid credentials")
        
        logger.info(f"User found: ID={user.id}, Email={user.email}, Role={user.role}, Hotel ID={user.hotel_id}")
        logger.info(f"User active status: {getattr(user, 'active', 'field not found')}")
        
        # Check if user is active (if the field exists)
        if hasattr(user, 'active') and user.active is False:
            logger.warning(f"Login failed: User account is deactivated - {form_data.username}")
            raise HTTPException(status_code=403, detail="Account is deactivated")
        
        # Verify password
        if not verify_password(form_data.password, user.hashed_password):
            logger.warning(f"Login failed: Invalid password for {form_data.username}")
            raise HTTPException(status_code=400, detail="Invalid credentials")
        
        # Update last login timestamp (if field exists)
        if hasattr(user, 'last_login'):
            try:
                user.last_login = datetime.utcnow()
                db.commit()
                logger.info(f"✅ Updated last_login for user {user.id}")
            except Exception as e:
                logger.error(f"Failed to update last_login: {e}")
                db.rollback()
                # Don't fail login if last_login update fails
        
        # Create access token with user data
        token_data = {
            "sub": user.email,
            "user_id": user.id,
            "hotel_id": user.hotel_id,
            "role": user.role
        }
        
        # Add name to token if it exists
        if hasattr(user, 'name') and user.name:
            token_data["name"] = user.name
        
        token = create_access_token(token_data)
        
        logger.info(f"✅ Login successful: {user.email}")
        
        # Build response with all available fields
        response_data = {
            "access_token": token,
            "token_type": "bearer",
            "user_id": user.id,
            "email": user.email,
            "role": user.role,
            "hotel_id": user.hotel_id
        }
        
        # Add optional fields if they exist
        if hasattr(user, 'name') and user.name:
            response_data["name"] = user.name
        
        if hasattr(user, 'phone') and user.phone:
            response_data["phone"] = user.phone
            
        if hasattr(user, 'active') and user.active is not None:
            response_data["active"] = user.active
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Login error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    
# -------------------------
# GET BOOKING REQUESTS
# -------------------------
@app.get("/booking-requests")
def get_booking_requests(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Get all booking requests for the user's hotel"""
    try:
        logger.info(f"📋 Fetching booking requests for hotel {current_user.hotel_id}")
        
        # Get booking requests for the user's hotel
        booking_requests = db.query(models.BookingRequest).filter(
            models.BookingRequest.hotel_id == current_user.hotel_id
        ).all()
        
        logger.info(f"✅ Found {len(booking_requests)} booking requests")
        
        # Return as list
        return [
            {
                "id": req.id,
                "hotel_id": req.hotel_id,
                "guest_name": req.guest_name,
                "email": req.email,
                "room_type": req.room_type,
                "arrival_date": str(req.arrival_date),
                "departure_date": str(req.departure_date),
                "number_of_rooms": req.number_of_rooms,
                "number_of_guests": req.number_of_guests,
                "special_requests": req.special_requests,
                "status": req.status,
                "draft_reply": req.draft_reply,
                "raw_email": req.raw_email, 
                "created_at": str(req.created_at) if req.created_at else None
            }
            for req in booking_requests
        ]
        
    except Exception as e:
        logger.error(f"❌ Error fetching booking requests: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
# ROOM TYPE MANAGEMENT ENDPOINTS
# -------------------------
@app.post("/room-types/create-test")
def create_test_room_types(db: Session = Depends(get_db)):
    """Create test room types for hotel_id=1"""
    try:
        # First, check if hotel 1 exists, if not create it
        hotel = db.query(models.Hotel).filter(models.Hotel.id == 1).first()
        if not hotel:
            hotel = models.Hotel(name="Default Hotel", subscription_plan="basic")
            db.add(hotel)
            db.flush()
            logger.info(f"Created default hotel with ID: {hotel.id}")
        
        # Check if room types already exist
        existing = db.query(models.RoomType).filter(models.RoomType.hotel_id == 1).count()
        if existing > 0:
            return {
                "message": f"Room types already exist ({existing} found)",
                "room_types": [
                    {"name": rt.name, "total_rooms": rt.total_rooms} 
                    for rt in db.query(models.RoomType).filter(models.RoomType.hotel_id == 1).all()
                ]
            }
        
        # Create standard room types
        room_types = [
            models.RoomType(name="Standard", total_rooms=20, hotel_id=1),
            models.RoomType(name="Deluxe", total_rooms=15, hotel_id=1),
            models.RoomType(name="Suite", total_rooms=10, hotel_id=1),
            models.RoomType(name="Family", total_rooms=8, hotel_id=1)
        ]
        
        for rt in room_types:
            db.add(rt)
        
        db.commit()
        
        return {
            "message": "Test room types created successfully",
            "room_types": [{"name": rt.name, "total_rooms": rt.total_rooms} for rt in room_types]
        }
    except Exception as e:
        logger.error(f"Error creating room types: {e}")
        db.rollback()
        return {"error": str(e)}

@app.get("/room-types/list")
def list_room_types(db: Session = Depends(get_db)):
    """List all room types"""
    try:
        room_types = db.query(models.RoomType).all()
        if not room_types:
            return {"message": "No room types found", "room_types": []}
        
        return [
            {
                "id": rt.id,
                "name": rt.name,
                "total_rooms": rt.total_rooms,
                "hotel_id": rt.hotel_id
            }
            for rt in room_types
        ]
    except Exception as e:
        logger.error(f"Error listing room types: {e}")
        return {"error": str(e)}

@app.get("/room-types/by-hotel/{hotel_id}")
def get_room_types_by_hotel(hotel_id: int, db: Session = Depends(get_db)):
    """Get room types for a specific hotel"""
    try:
        room_types = db.query(models.RoomType).filter(models.RoomType.hotel_id == hotel_id).all()
        return [
            {
                "id": rt.id,
                "name": rt.name,
                "total_rooms": rt.total_rooms
            }
            for rt in room_types
        ]
    except Exception as e:
        logger.error(f"Error getting room types: {e}")
        return {"error": str(e)}

@app.post("/room-types/create")
def create_room_type(
    name: str,
    total_rooms: int,
    hotel_id: int,
    db: Session = Depends(get_db)
):
    """Create a new room type for a hotel"""
    try:
        # Check if hotel exists
        hotel = db.query(models.Hotel).filter(models.Hotel.id == hotel_id).first()
        if not hotel:
            raise HTTPException(status_code=404, detail="Hotel not found")
        
        # Check if room type already exists for this hotel
        existing = db.query(models.RoomType).filter(
            models.RoomType.hotel_id == hotel_id,
            models.RoomType.name == name
        ).first()
        
        if existing:
            raise HTTPException(status_code=400, detail="Room type already exists for this hotel")
        
        new_room_type = models.RoomType(
            name=name,
            total_rooms=total_rooms,
            hotel_id=hotel_id
        )
        
        db.add(new_room_type)
        db.commit()
        db.refresh(new_room_type)
        
        logger.info(f"Created room type: {name} for hotel {hotel_id}")
        
        return {
            "id": new_room_type.id,
            "name": new_room_type.name,
            "total_rooms": new_room_type.total_rooms,
            "hotel_id": new_room_type.hotel_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating room type: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/room-types/{room_type_id}")
def update_room_type(
    room_type_id: int,
    total_rooms: int = None,
    name: str = None,
    db: Session = Depends(get_db)
):
    """Update a room type"""
    try:
        room_type = db.query(models.RoomType).filter(models.RoomType.id == room_type_id).first()
        if not room_type:
            raise HTTPException(status_code=404, detail="Room type not found")
        
        if total_rooms is not None:
            room_type.total_rooms = total_rooms
        if name is not None:
            room_type.name = name
        
        db.commit()
        db.refresh(room_type)
        
        return {
            "id": room_type.id,
            "name": room_type.name,
            "total_rooms": room_type.total_rooms,
            "hotel_id": room_type.hotel_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating room type: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/room-types/{room_type_id}")
def delete_room_type(room_type_id: int, db: Session = Depends(get_db)):
    """Delete a room type"""
    try:
        room_type = db.query(models.RoomType).filter(models.RoomType.id == room_type_id).first()
        if not room_type:
            raise HTTPException(status_code=404, detail="Room type not found")
        
        db.delete(room_type)
        db.commit()
        
        return {"message": "Room type deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting room type: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

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
# ADMIN: CLEAR DATABASE (TEMPORARY)
# -------------------------
from sqlalchemy import text

@app.delete("/admin/clear-database")
def clear_database(db: Session = Depends(get_db)):
    """Clear all data from database (admin only)"""
    try:
        # Delete in correct order to avoid foreign key issues
        db.execute(text("DELETE FROM modification_requests"))
        db.execute(text("DELETE FROM confirmed_bookings"))
        db.execute(text("DELETE FROM booking_requests"))
        db.execute(text("DELETE FROM room_types"))
        db.execute(text("DELETE FROM users"))
        db.execute(text("DELETE FROM hotels"))
        db.commit()
        
        return {"message": "✅ Database cleared successfully"}
    except Exception as e:
        db.rollback()
        return {"error": str(e)}
    
# -------------------------
# USER MANAGEMENT ENDPOINTS
# -------------------------
@app.get("/users/hotel/{hotel_id}")
def get_users_by_hotel(
    hotel_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Get all users for a specific hotel"""
    # Only admins and managers can view staff
    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    users = db.query(models.User).filter(models.User.hotel_id == hotel_id).all()
    return [
        {
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "role": u.role,
            "hotel_id": u.hotel_id,
            "phone": u.phone,
            "active": u.active,
            "last_login": u.last_login,
            "created_at": u.created_at
        }
        for u in users
    ]

@app.put("/users/{user_id}")
def update_user(
    user_id: int,
    name: str = None,
    email: str = None,
    role: str = None,
    phone: str = None,
    active: bool = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Update user information"""
    # Check authorization
    if current_user.role not in ["admin", "manager"] and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if name is not None:
        user.name = name
    if email is not None:
        # Check if email is already taken
        existing = db.query(models.User).filter(
            models.User.email == email,
            models.User.id != user_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already in use")
        user.email = email
    if role is not None:
        if current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Only admins can change roles")
        user.role = role
    if phone is not None:
        user.phone = phone
    if active is not None:
        user.active = active
    
    db.commit()
    db.refresh(user)
    
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "hotel_id": user.hotel_id,
        "phone": user.phone,
        "active": user.active
    }

@app.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Delete a user (admin only)"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can delete users")
    
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    db.delete(user)
    db.commit()
    
    return {"message": "User deleted successfully"}

# -------------------------
# SHUTDOWN EVENT
# -------------------------
@app.on_event("shutdown")
async def shutdown_event():
    """Run on application shutdown"""
    logger.info("THeO Application Shutting Down - Version 2.0")

# -------------------------
# START SERVER (for direct execution)
# -------------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    print(f"🚀 Starting server on port {port}")
    print(f"📡 Host: 0.0.0.0")
    print(f"🔗 URL: http://0.0.0.0:{port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False, log_level="info")