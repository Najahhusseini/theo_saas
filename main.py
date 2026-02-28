import os
from dotenv import load_dotenv

# Load .env using absolute path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

print("Loaded TOKEN:", os.getenv("TELEGRAM_BOT_TOKEN"))

from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError


import models
from routers.bookings import router as bookings_router
from routers.confirmed_bookings import router as confirmed_router
from routers.telegram_webhook import router as telegram_router

from database import engine, Base
from database import engine, get_db
from auth import (
    verify_password,
    create_access_token,
    get_current_user,
    hash_password,
)

# Create tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI()
app.include_router(bookings_router)
app.include_router(confirmed_router)
app.include_router(telegram_router)

# -------------------------
# CREATE HOTEL
# -------------------------
@app.post("/hotels/")
def create_hotel(name: str, subscription_plan: str, db: Session = Depends(get_db)):
    new_hotel = models.Hotel(
        name=name,
        subscription_plan=subscription_plan
    )

    db.add(new_hotel)
    db.commit()
    db.refresh(new_hotel)

    return new_hotel


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
     # Safety limit
    if len(password) > 72:
        raise HTTPException(status_code=400, detail="Password too long (max 72 characters)")
    # 🔐 Hash the password FIRST
    hashed_pw = hash_password(password)

    # 👤 Create user with hashed password
    new_user = models.User(
        email=email,
        hashed_password=hashed_pw,
        role=role,
        hotel_id=hotel_id
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "id": new_user.id,
        "email": new_user.email,
        "role": new_user.role,
        "hotel_id": new_user.hotel_id
    }
# -------------------------
# GET BOOKINGS PER HOTEL
# -------------------------
@app.get("/bookings/")
def get_bookings(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    bookings = db.query(models.Booking).filter(
        models.Booking.hotel_id == current_user.hotel_id
    ).all()

    return bookings


@app.get("/")
def read_root():
    return {"message": "THeO SaaS Backend is running"}
@app.post("/login")
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(
        models.User.email == form_data.username
    ).first()

    if not user:
        raise HTTPException(status_code=400, detail="Invalid credentials")

    if not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Invalid credentials")

    token = create_access_token({
        "sub": user.email,
        "hotel_id": user.hotel_id
    })

    return {
        "access_token": token,
        "token_type": "bearer"
    }
@app.post("/users/")
def create_user(email: str, password: str, role: str, hotel_id: int, db: Session = Depends(get_db)):

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

    return {
        "id": new_user.id,
        "email": new_user.email,
        "role": new_user.role,
        "hotel_id": new_user.hotel_id
    }
@app.get("/protected")
def protected_route(current_user: models.User = Depends(get_current_user)):
    return {"message": "You are authenticated"}

Base.metadata.create_all(bind=engine)