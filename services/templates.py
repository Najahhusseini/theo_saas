# services/templates.py
"""
Reusable message templates for consistent formatting
"""

from datetime import datetime

def format_date(date_obj):
    """Format date in a readable way"""
    if isinstance(date_obj, str):
        return date_obj
    return date_obj.strftime("%d %b %Y") if hasattr(date_obj, 'strftime') else str(date_obj)

def divider(char="━", length=25):
    """Create a divider line"""
    return char * length

def header(text, icon="📋", width=25):
    """Create a formatted header"""
    return f"{icon} *{text}*"

# Booking Templates
def new_booking_template(booking):
    """Template for new booking notification"""
    arrival = format_date(booking.arrival_date)
    departure = format_date(booking.departure_date)
    
    return f"""
🏨 *NEW BOOKING REQUEST* #{booking.id}

{divider()}

👤 *Guest*
• {booking.guest_name}
• `{booking.email}`

📅 *Stay*
• In: {arrival}
• Out: {departure}

🛏 *Room*
• {booking.room_type} ×{booking.number_of_rooms}
• {booking.number_of_guests} guest(s)

📝 *Requests*
{booking.special_requests or "─ None ─"}

{divider()}
👇 *Select action*
"""

def draft_template(booking, decision, draft):
    """Template for draft email preview"""
    return f"""
📧 *DRAFT EMAIL* | {decision} #{booking.id}

{divider()}

```{draft}```

{divider()}

👤 To: {booking.guest_name} <{booking.email}>
📅 Stay: {format_date(booking.arrival_date)} → {format_date(booking.departure_date)}

👇 *Review draft*
"""

def booking_details_template(booking):
    """Template for detailed booking view"""
    return f"""
📋 *BOOKING DETAILS* #{booking.id}

{divider()}

📊 *Status:* {booking.status}

👤 *Guest*
• {booking.guest_name}
• {booking.email}

📅 *Stay*
• Check-in: {format_date(booking.arrival_date)}
• Check-out: {format_date(booking.departure_date)}
• Duration: {booking.number_of_rooms} room(s), {booking.number_of_guests} guest(s)

🛏 *Room*
• Type: {booking.room_type}

📝 *Requests*
{booking.special_requests or "─ None ─"}

📎 *Draft*
{booking.draft_reply or "─ Not generated ─"}

{divider()}
"""

# Dashboard Templates
def stats_template(stats):
    """Template for statistics dashboard"""
    return f"""
📊 *DASHBOARD*

{divider()}

*Overview*
Total: {stats['total']}

*Status*
✅ Confirmed: {stats['confirmed']}
⏳ Pending: {stats['pending']}
⏱ Waitlist: {stats['waitlist']}
❌ Rejected: {stats['rejected']}
📝 Draft: {stats['draft_ready']}
📧 Sent: {stats['email_sent']}

*Today*
🛬 Arrivals: {stats['today_arrivals']}
🛫 Departures: {stats['today_departures']}

{divider()}
🕐 {datetime.now().strftime('%H:%M')}
"""

def today_template(arrivals, departures):
    """Template for today's summary"""
    today = datetime.now().strftime("%d %b %Y")
    
    template = f"""
📅 *TODAY* | {today}

{divider()}
"""
    if arrivals:
        template += f"\n*🛬 Arrivals ({len(arrivals)})*\n"
        for b in arrivals[:3]:
            template += f"• #{b.id}: {b.guest_name}\n"
    
    if departures:
        template += f"\n*🛫 Departures ({len(departures)})*\n"
        for b in departures[:3]:
            template += f"• #{b.id}: {b.guest_name}\n"
    
    return template

# Question Answer Templates
def answer_template(answers):
    """Template for Q&A responses"""
    if answers:
        return f"""
📚 *Answer*

{divider()}

{answers}

{divider()}
💡 *Tip:* Use /help for commands
"""
    else:
        return f"""
🤔 *Not sure*

{divider()}

I couldn't find an answer. Try:
• /help for commands
• Being more specific
• Contacting support

{divider()}
"""

# Error Templates
def error_template(error_msg):
    """Template for error messages"""
    return f"""
❌ *Error*

{divider()}

{error_msg}

{divider()}
Please try again or contact support.
"""

# Success Templates
def success_template(action, booking_id):
    """Template for success messages"""
    return f"""
✅ *Success*

{divider()}

{action} for booking #{booking_id}

{divider()}
"""

# Command Help Template
help_template = """
🤖 *THeO Bot Commands*

{divider()}

*Booking Management*
• Buttons on booking messages
• Reply to edit drafts

*Commands*
/stats - View dashboard
/today - Today's arrivals
/pending - Pending bookings
/help - Show this

*Questions*
Ask me about:
• Check-in/out times
• Cancellation policy
• Parking & facilities
• Breakfast & meals
• Pet policy
• WiFi access

{divider()}
✨ *Always here to help!*
"""