from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
import models
from services.telegram import (
    send_telegram_message, 
    send_modification_notification, 
    send_modification_update_confirmation,
    send_modification_rejected_notification
)
from typing import Optional
from datetime import datetime, date
import os
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/modifications/create-from-email")
async def create_modification_from_email(
    original_booking_id: int,
    guest_name: Optional[str] = None,
    email: Optional[str] = None,
    arrival_date: Optional[date] = None,
    departure_date: Optional[date] = None,
    room_type: Optional[str] = None,
    number_of_rooms: Optional[int] = None,
    number_of_guests: Optional[int] = None,
    special_requests: Optional[str] = None,
    raw_email: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Create a modification request from an email (called by email processor)"""
    
    # Find the original confirmed booking
    original_booking = db.query(models.ConfirmedBooking).filter(
        models.ConfirmedBooking.id == original_booking_id
    ).first()
    
    if not original_booking:
        raise HTTPException(status_code=404, detail="Original booking not found")
    
    # Check if there's already a pending modification
    existing_mod = db.query(models.ModificationRequest).filter(
        models.ModificationRequest.original_booking_id == original_booking_id,
        models.ModificationRequest.status == "Pending"
    ).first()
    
    if existing_mod:
        # Update existing modification request
        if guest_name:
            existing_mod.guest_name = guest_name
        if email:
            existing_mod.email = email
        if arrival_date:
            existing_mod.arrival_date = arrival_date
        if departure_date:
            existing_mod.departure_date = departure_date
        if room_type:
            existing_mod.room_type = room_type
        if number_of_rooms:
            existing_mod.number_of_rooms = number_of_rooms
        if number_of_guests:
            existing_mod.number_of_guests = number_of_guests
        if special_requests:
            existing_mod.special_requests = special_requests
        
        db.commit()
        db.refresh(existing_mod)
        modification = existing_mod
        logger.info(f"Updated existing modification request #{existing_mod.id}")
    else:
        # Create new modification request
        modification = models.ModificationRequest(
            original_booking_id=original_booking.id,
            guest_name=guest_name or original_booking.guest_name,
            email=email or original_booking.email,
            arrival_date=arrival_date or original_booking.arrival_date,
            departure_date=departure_date or original_booking.departure_date,
            room_type=room_type or original_booking.room_type,
            number_of_rooms=number_of_rooms or original_booking.number_of_rooms,
            number_of_guests=number_of_guests or original_booking.number_of_guests,
            special_requests=special_requests or original_booking.special_requests,
            raw_email=raw_email,
            status="Pending"
        )
        db.add(modification)
        db.commit()
        db.refresh(modification)
        logger.info(f"Created new modification request #{modification.id}")
    
    # Mark original booking as having pending modification
    original_booking.has_pending_modification = True
    db.commit()
    
    # Send notification to Telegram
    await send_modification_notification(modification, original_booking)
    
    return {
        "message": "Modification request created",
        "modification_id": modification.id,
        "status": modification.status
    }

@router.post("/modifications/{modification_id}/approve")
async def approve_modification(
    modification_id: int,
    notes: Optional[str] = None,
    user_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """Approve a modification request and update the original booking"""
    
    modification = db.query(models.ModificationRequest).filter(
        models.ModificationRequest.id == modification_id
    ).first()
    
    if not modification:
        raise HTTPException(status_code=404, detail="Modification not found")
    
    if modification.status != "Pending":
        raise HTTPException(status_code=400, detail=f"Modification already {modification.status}")
    
    # Get original booking
    original_booking = db.query(models.ConfirmedBooking).filter(
        models.ConfirmedBooking.id == modification.original_booking_id
    ).first()
    
    if not original_booking:
        raise HTTPException(status_code=404, detail="Original booking not found")
    
    # Track changes in history
    changes = []
    
    # Update original booking with new values
    if modification.guest_name != original_booking.guest_name:
        changes.append(("guest_name", original_booking.guest_name, modification.guest_name))
        original_booking.guest_name = modification.guest_name
    
    if modification.email != original_booking.email:
        changes.append(("email", original_booking.email, modification.email))
        original_booking.email = modification.email
    
    if modification.arrival_date != original_booking.arrival_date:
        changes.append(("arrival_date", str(original_booking.arrival_date), str(modification.arrival_date)))
        original_booking.arrival_date = modification.arrival_date
    
    if modification.departure_date != original_booking.departure_date:
        changes.append(("departure_date", str(original_booking.departure_date), str(modification.departure_date)))
        original_booking.departure_date = modification.departure_date
    
    if modification.room_type != original_booking.room_type:
        changes.append(("room_type", original_booking.room_type, modification.room_type))
        original_booking.room_type = modification.room_type
    
    if modification.number_of_rooms != original_booking.number_of_rooms:
        changes.append(("number_of_rooms", str(original_booking.number_of_rooms), str(modification.number_of_rooms)))
        original_booking.number_of_rooms = modification.number_of_rooms
    
    if modification.number_of_guests != original_booking.number_of_guests:
        changes.append(("number_of_guests", str(original_booking.number_of_guests), str(modification.number_of_guests)))
        original_booking.number_of_guests = modification.number_of_guests
    
    if modification.special_requests != original_booking.special_requests:
        changes.append(("special_requests", original_booking.special_requests, modification.special_requests))
        original_booking.special_requests = modification.special_requests
    
    # Update modification status
    modification.status = "Approved"
    modification.processed_at = datetime.utcnow()
    modification.modification_notes = notes
    if user_id:
        modification.processed_by = user_id
    
    # Clear pending flag
    original_booking.has_pending_modification = False
    original_booking.last_modified_at = datetime.utcnow()
    
    db.commit()
    
    # Log changes to history
    for field, old, new in changes:
        history = models.ModificationHistory(
            booking_id=original_booking.id,
            booking_type="confirmed",
            field_name=field,
            old_value=str(old) if old else None,
            new_value=str(new) if new else None,
            modified_by=user_id,
            modification_reason="guest_request"
        )
        db.add(history)
    
    db.commit()
    
    logger.info(f"Modification #{modification_id} approved. {len(changes)} fields updated.")
    
    # Send confirmation to Telegram
    if changes:
        await send_modification_update_confirmation(modification, original_booking, changes)
    else:
        await send_telegram_message(
            os.getenv("MANAGER_CHAT_ID"),
            f"✅ *Modification Approved*\n\nModification #{modification_id} for Booking #{original_booking.id} was approved with no changes."
        )
    
    return {
        "message": "Modification approved",
        "booking_id": original_booking.id,
        "changes": len(changes),
        "updated_fields": [c[0] for c in changes]
    }

@router.post("/modifications/{modification_id}/reject")
async def reject_modification(
    modification_id: int,
    reason: str,
    user_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """Reject a modification request"""
    
    modification = db.query(models.ModificationRequest).filter(
        models.ModificationRequest.id == modification_id
    ).first()
    
    if not modification:
        raise HTTPException(status_code=404, detail="Modification not found")
    
    if modification.status != "Pending":
        raise HTTPException(status_code=400, detail=f"Modification already {modification.status}")
    
    # Update modification status
    modification.status = "Rejected"
    modification.processed_at = datetime.utcnow()
    modification.modification_notes = reason
    if user_id:
        modification.processed_by = user_id
    
    # Clear pending flag on original booking
    original_booking = db.query(models.ConfirmedBooking).filter(
        models.ConfirmedBooking.id == modification.original_booking_id
    ).first()
    
    if original_booking:
        original_booking.has_pending_modification = False
    
    db.commit()
    
    logger.info(f"Modification #{modification_id} rejected. Reason: {reason}")
    
    # Send notification to Telegram
    await send_modification_rejected_notification(modification, reason)
    
    return {"message": "Modification rejected", "modification_id": modification_id}

@router.get("/modifications/pending")
async def list_pending_modifications(
    db: Session = Depends(get_db),
    limit: int = 50
):
    """List all pending modification requests"""
    
    modifications = db.query(models.ModificationRequest).filter(
        models.ModificationRequest.status == "Pending"
    ).order_by(models.ModificationRequest.created_at.desc()).limit(limit).all()
    
    result = []
    for mod in modifications:
        original = db.query(models.ConfirmedBooking).filter(
            models.ConfirmedBooking.id == mod.original_booking_id
        ).first()
        
        result.append({
            "id": mod.id,
            "original_booking_id": mod.original_booking_id,
            "original_guest": original.guest_name if original else "Unknown",
            "guest_name": mod.guest_name,
            "arrival_date": str(mod.arrival_date) if mod.arrival_date else None,
            "departure_date": str(mod.departure_date) if mod.departure_date else None,
            "room_type": mod.room_type,
            "status": mod.status,
            "created_at": str(mod.created_at) if mod.created_at else None
        })
    
    return {"pending_modifications": result}

@router.get("/modifications/{modification_id}")
async def get_modification_details(
    modification_id: int,
    db: Session = Depends(get_db)
):
    """Get detailed information about a modification request"""
    
    modification = db.query(models.ModificationRequest).filter(
        models.ModificationRequest.id == modification_id
    ).first()
    
    if not modification:
        raise HTTPException(status_code=404, detail="Modification not found")
    
    original = db.query(models.ConfirmedBooking).filter(
        models.ConfirmedBooking.id == modification.original_booking_id
    ).first()
    
    return {
        "id": modification.id,
        "original_booking": {
            "id": original.id if original else None,
            "guest_name": original.guest_name if original else None,
            "email": original.email if original else None,
            "arrival_date": str(original.arrival_date) if original and original.arrival_date else None,
            "departure_date": str(original.departure_date) if original and original.departure_date else None,
            "room_type": original.room_type if original else None,
            "number_of_rooms": original.number_of_rooms if original else None,
            "number_of_guests": original.number_of_guests if original else None,
            "special_requests": original.special_requests if original else None
        } if original else None,
        "requested_changes": {
            "guest_name": modification.guest_name,
            "email": modification.email,
            "arrival_date": str(modification.arrival_date) if modification.arrival_date else None,
            "departure_date": str(modification.departure_date) if modification.departure_date else None,
            "room_type": modification.room_type,
            "number_of_rooms": modification.number_of_rooms,
            "number_of_guests": modification.number_of_guests,
            "special_requests": modification.special_requests
        },
        "status": modification.status,
        "created_at": str(modification.created_at) if modification.created_at else None,
        "processed_at": str(modification.processed_at) if modification.processed_at else None,
        "processed_by": modification.processed_by,
        "modification_notes": modification.modification_notes,
        "raw_email": modification.raw_email
    }