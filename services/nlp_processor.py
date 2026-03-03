import re
import dateparser
from datetime import datetime, timedelta, date
from typing import Optional, Tuple, Dict, Any
import logging

logger = logging.getLogger(__name__)

class NLPProcessor:
    """Process natural language queries for hotel operations"""
    
    def __init__(self):
        self.patterns = {
            # Availability queries
            'availability': [
                r'(?:what|how many).*?(?:room|available).*?(?:on|for)?\s*(.+)',
                r'(?:is|are).*?(?:room|available).*?(?:on|for)?\s*(.+)',
                r'free rooms?\s*(?:on|for)?\s*(.+)',
                r'availability\s*(?:on|for)?\s*(.+)',
            ],
            
            # Booking listings
            'list_bookings': [
                r'(?:show|list|get).*?(?:bookings|reservations).*?(?:from|between)?\s*(.+?)\s*(?:to|and|until)?\s*(.+)',
                r'(?:bookings|reservations)\s*(?:from|between)?\s*(.+?)\s*(?:to|and|until)?\s*(.+)',
                r'what.*?(?:bookings|reservations).*?(?:on|for)?\s*(.+)',
            ],
            
            # Booking modifications
            'modify_booking': [
                r'(?:change|modify|update|move)\s*(?:booking)?\s*#?(\d+)\s*(?:to|on)?\s*(.+)',
                r'(?:booking)?\s*#?(\d+).*?(?:change|modify|update|move).*?(?:to|on)?\s*(.+)',
            ],
            
            # Cancellations
            'cancel_booking': [
                r'(?:cancel|delete|remove)\s*(?:booking)?\s*#?(\d+)',
                r'(?:booking)?\s*#?(\d+).*?(?:cancel|delete|remove)',
            ],
            
            # Guest counts
            'guest_count': [
                r'(?:how many|number of).*?(?:guests|people).*?(?:on|for)?\s*(.+)',
                r'(?:guests|people).*?(?:arriving|coming|staying).*?(?:on|for)?\s*(.+)',
            ],
            
            # Check-in/out times
            'policy': [
                r'(?:check.?in|arrival).*?(?:time|when)',
                r'(?:check.?out|departure).*?(?:time|when)',
                r'(?:cancellation|parking|breakfast|wifi|pet).*?(?:policy|allowed|fee)',
            ],
        }
        
    def parse_date(self, date_text: str) -> Optional[date]:
        """Parse natural language date strings"""
        if not date_text:
            return None
            
        # Handle relative dates
        date_text = date_text.lower().strip()
        
        # Special cases
        today = datetime.now().date()
        
        if date_text in ['today', 'tonight']:
            return today
        elif date_text in ['tomorrow', 'tmr']:
            return today + timedelta(days=1)
        elif date_text in ['day after tomorrow', 'overmorrow']:
            return today + timedelta(days=2)
        elif 'next week' in date_text:
            return today + timedelta(days=7)
        elif 'next month' in date_text:
            # Rough approximation
            return today + timedelta(days=30)
        
        # Use dateparser for other cases
        try:
            parsed = dateparser.parse(date_text)
            if parsed:
                return parsed.date()
        except:
            pass
        
        return None
    
    def extract_booking_id(self, text: str) -> Optional[int]:
        """Extract booking ID from text"""
        match = re.search(r'#?(\d+)', text)
        if match:
            return int(match.group(1))
        return None
    
    def parse_query(self, text: str) -> Dict[str, Any]:
        """Parse natural language query and return intent and parameters"""
        text = text.lower().strip()
        result = {
            'intent': None,
            'booking_id': None,
            'dates': [],
            'room_type': None,
            'confidence': 0
        }
        
        # Check each intent pattern
        for intent, patterns in self.patterns.items():
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    result['intent'] = intent
                    result['confidence'] = 0.8
                    
                    # Extract booking ID if present
                    booking_id = self.extract_booking_id(text)
                    if booking_id:
                        result['booking_id'] = booking_id
                    
                    # Extract dates
                    groups = match.groups()
                    if groups:
                        for group in groups:
                            if group and not group.isdigit():
                                parsed_date = self.parse_date(group)
                                if parsed_date:
                                    result['dates'].append(parsed_date)
                    
                    # Check for room types
                    room_types = ['standard', 'deluxe', 'suite', 'family', 'presidential']
                    for rt in room_types:
                        if rt in text:
                            result['room_type'] = rt.capitalize()
                            break
                    
                    break
            if result['intent']:
                break
        
        # If no intent matched, check for simple questions
        if not result['intent']:
            if '?' in text or any(word in text for word in ['what', 'when', 'where', 'how']):
                result['intent'] = 'question'
                result['confidence'] = 0.5
        
        return result

# Create singleton instance
nlp = NLPProcessor()