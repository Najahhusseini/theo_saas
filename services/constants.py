# services/constants.py

# Status emoji mapping
STATUS_EMOJI = {
    "Pending": "⏳",
    "Confirmed": "✅",
    "Waitlist": "⏱",
    "Rejected": "❌",
    "Editing": "✏️",
    "Draft_Ready": "📝",
    "Email_Sent": "📧"
}

# Status colors (for potential future web interface)
STATUS_COLORS = {
    "Pending": "#FFA500",
    "Confirmed": "#00FF00",
    "Waitlist": "#FFFF00",
    "Rejected": "#FF0000",
    "Editing": "#0000FF",
    "Draft_Ready": "#800080",
    "Email_Sent": "#008000"
}

# Action emoji mapping
ACTION_EMOJI = {
    "confirm": "✅",
    "reject": "❌",
    "waitlist": "⏱",
    "edit": "✏️",
    "send": "📧",
    "details": "📋",
    "cancel": "❌",
    "stats": "📊",
    "today": "📅",
    "pending": "⏳",
    "help": "❓"
}

# Hotel information
HOTEL_INFO = {
    "name": "Grand Hotel",
    "check_in": "3:00 PM",
    "check_out": "11:00 AM",
    "phone": "+1 (555) 123-4567",
    "email": "reservations@grandhotel.com",
    "address": "123 Main Street, City, State 12345"
}

# Message templates
WELCOME_MESSAGE = """
🤖 *Welcome to THeO Hotel Automation*

I'm your AI-powered booking assistant. I'll help you manage all hotel booking requests efficiently.

*Commands:*
/stats - View dashboard
/today - Today's arrivals
/pending - Pending bookings
/help - Show help

*Or simply ask me a question!*
"""

HELP_MESSAGE = """
🤖 *THeO Bot Help*

*Commands:*
/stats - Booking statistics
/today - Today's arrivals/departures
/pending - List pending bookings
/help - Show this message

*Booking Management:*
• Click buttons to process bookings
• Reply to edit drafts
• View details for more info

*Quick Questions:*
• Check-in/out times
• Cancellation policy
• Parking & facilities
• Breakfast & dining
• Pet policy
• WiFi access

*Need more help?* Contact support@theo.com
"""
# Add to services/constants.py

# Mode indicators
MODE_INDICATORS = {
    "normal": "💬 *Normal Mode*",
    "editing": "✏️ *EDITING MODE* - Reply to this message to update draft"
}

# Command availability by mode
COMMANDS_BY_MODE = {
    "normal": ["/stats", "/today", "/pending", "/help"],
    "editing": ["/cancel", "/help"]  # Limited commands in editing mode
}

# Mode transition messages
MODE_MESSAGES = {
    "enter_edit": "✏️ *ENTERING EDIT MODE*\n\nYou are now editing the draft. Send your revised message as a reply to this message.\n\nType /cancel to exit edit mode.",
    "exit_edit": "💬 *EXITING EDIT MODE*\n\nYou are back to normal mode. Use /help to see available commands.",
    "already_editing": "⚠️ You are already in edit mode. Please send your draft or type /cancel to exit.",
    "not_editing": "ℹ️ You are not in edit mode. Click 'Edit Draft' on a booking to start editing."
}