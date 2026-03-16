#!/usr/bin/env python
"""
Database update script for THeO backend
Run this to add missing columns to your database tables
"""

import os
import sys
import logging
from pathlib import Path

# Add the current directory to Python path so we can import local modules
sys.path.insert(0, str(Path(__file__).parent.absolute()))

# Import our database connection
from database import engine, SessionLocal
from sqlalchemy import text, inspect
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def check_connection():
    """Test database connection"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            logger.info("✅ Database connection successful")
            return True
    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
        return False

def show_all_tables():
    """Display all tables and their columns"""
    try:
        logger.info("="*60)
        logger.info("📋 CURRENT DATABASE SCHEMA")
        logger.info("="*60)
        
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        if not tables:
            logger.warning("No tables found in database")
            return
        
        for table in tables:
            logger.info(f"\n📁 Table: {table}")
            columns = inspector.get_columns(table)
            for col in columns:
                logger.info(f"  • {col['name']}: {col['type']}")
        
        logger.info("\n" + "="*60)
        
    except Exception as e:
        logger.error(f"❌ Error showing tables: {e}")

def update_room_types_table():
    """Add missing columns to room_types table"""
    logger.info("\n🔧 Updating room_types table...")
    
    try:
        inspector = inspect(engine)
        
        # Check if table exists
        if 'room_types' not in inspector.get_table_names():
            logger.warning("⚠️ room_types table doesn't exist yet - creating it")
            with engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE room_types (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR NOT NULL,
                        total_rooms INTEGER NOT NULL,
                        hotel_id INTEGER REFERENCES hotels(id),
                        created_at TIMESTAMP DEFAULT NOW(),
                        updated_at TIMESTAMP DEFAULT NOW()
                    )
                """))
                conn.commit()
                logger.info("✅ Created room_types table")
        
        # Get existing columns
        existing_columns = [col['name'] for col in inspector.get_columns('room_types')]
        logger.info(f"📋 Existing columns: {existing_columns}")
        
        # Define columns to add with their SQL types
        columns_to_add = [
            ('price_per_night', 'INTEGER'),
            ('max_guests', 'INTEGER'),
            ('description', 'TEXT'),
            ('amenities', 'JSONB')
        ]
        
        with engine.connect() as conn:
            for col_name, col_type in columns_to_add:
                if col_name not in existing_columns:
                    try:
                        conn.execute(text(f"ALTER TABLE room_types ADD COLUMN {col_name} {col_type}"))
                        logger.info(f"✅ Added {col_name} column")
                    except Exception as e:
                        logger.error(f"❌ Failed to add {col_name}: {e}")
                else:
                    logger.info(f"⏭️ {col_name} column already exists")
            
            conn.commit()
        
        # Verify columns were added
        updated_columns = [col['name'] for col in inspector.get_columns('room_types')]
        logger.info(f"📋 Updated columns: {updated_columns}")
        
    except Exception as e:
        logger.error(f"❌ Error updating room_types table: {e}")
        raise

def update_users_table():
    """Ensure users table has all required columns"""
    logger.info("\n🔧 Checking users table...")
    
    try:
        inspector = inspect(engine)
        
        if 'users' not in inspector.get_table_names():
            logger.warning("⚠️ users table doesn't exist yet")
            return
        
        existing_columns = [col['name'] for col in inspector.get_columns('users')]
        logger.info(f"📋 Users table columns: {existing_columns}")
        
        # Define columns that should exist
        required_columns = [
            ('name', 'VARCHAR'),
            ('phone', 'VARCHAR'),
            ('active', 'BOOLEAN DEFAULT true'),
            ('last_login', 'TIMESTAMP')
        ]
        
        with engine.connect() as conn:
            for col_name, col_type in required_columns:
                if col_name not in existing_columns:
                    try:
                        conn.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}"))
                        logger.info(f"✅ Added {col_name} column to users table")
                    except Exception as e:
                        logger.error(f"❌ Failed to add {col_name}: {e}")
                else:
                    logger.info(f"⏭️ {col_name} column already exists")
            
            conn.commit()
        
    except Exception as e:
        logger.error(f"❌ Error updating users table: {e}")

def update_hotels_table():
    """Ensure hotels table has all required columns"""
    logger.info("\n🔧 Checking hotels table...")
    
    try:
        inspector = inspect(engine)
        
        if 'hotels' not in inspector.get_table_names():
            logger.warning("⚠️ hotels table doesn't exist yet")
            return
        
        existing_columns = [col['name'] for col in inspector.get_columns('hotels')]
        logger.info(f"📋 Hotels table columns: {existing_columns}")
        
        # Define columns that should exist
        required_columns = [
            ('address', 'VARCHAR'),
            ('city', 'VARCHAR'),
            ('country', 'VARCHAR'),
            ('phone', 'VARCHAR'),
            ('email', 'VARCHAR'),
            ('created_at', 'TIMESTAMP DEFAULT NOW()'),
            ('updated_at', 'TIMESTAMP DEFAULT NOW()')
        ]
        
        with engine.connect() as conn:
            for col_name, col_type in required_columns:
                if col_name not in existing_columns:
                    try:
                        conn.execute(text(f"ALTER TABLE hotels ADD COLUMN {col_name} {col_type}"))
                        logger.info(f"✅ Added {col_name} column to hotels table")
                    except Exception as e:
                        logger.error(f"❌ Failed to add {col_name}: {e}")
                else:
                    logger.info(f"⏭️ {col_name} column already exists")
            
            conn.commit()
        
    except Exception as e:
        logger.error(f"❌ Error updating hotels table: {e}")

def main():
    """Main function to run all updates"""
    logger.info("="*60)
    logger.info("🚀 THeO DATABASE UPDATE SCRIPT")
    logger.info("="*60)
    
    # Check database connection first
    if not check_connection():
        logger.error("Cannot proceed without database connection")
        sys.exit(1)
    
    # Show current schema
    show_all_tables()
    
    # Run updates
    update_hotels_table()
    update_users_table()
    update_room_types_table()
    
    # Show updated schema
    show_all_tables()
    
    logger.info("\n" + "="*60)
    logger.info("✅ Database update completed successfully!")
    logger.info("="*60)

if __name__ == "__main__":
    main()