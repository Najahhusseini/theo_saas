def generate_reply_draft(booking, decision: str) -> str:
    
    if decision == "Confirm":
        return f"""
Dear {booking.guest_name},

We are pleased to confirm your reservation for a {booking.room_type}
from {booking.arrival_date} to {booking.departure_date}.

We look forward to welcoming you.

Best regards,
Hotel Management
"""

    elif decision == "Waitlist":
        return f"""
Dear {booking.guest_name},

Thank you for your booking request for a {booking.room_type}
from {booking.arrival_date} to {booking.departure_date}.

Currently we are fully booked, but we have placed you on our waiting list.

We will update you shortly.

Best regards,
Hotel Management
"""

    elif decision == "Reject":
        return f"""
Dear {booking.guest_name},

Unfortunately, we are unable to accommodate your request for
{booking.room_type} from {booking.arrival_date} to {booking.departure_date}.

We apologize for the inconvenience.

Best regards,
Hotel Management
"""

    return "Invalid decision."