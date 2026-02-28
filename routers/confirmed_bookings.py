from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import ConfirmedBooking

router = APIRouter()

@router.get("/confirmed-bookings")
def get_confirmed_bookings(db: Session = Depends(get_db)):
    return db.query(ConfirmedBooking).all()
