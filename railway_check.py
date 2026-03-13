import os
import sys

print("="*60)
print("RAILWAY DIAGNOSTIC")
print("="*60)

# 1. Environment variables
print("\n1. Environment variables:")
print(f"   DATABASE_URL: {os.getenv('DATABASE_URL')}")
print(f"   TELEGRAM_BOT_TOKEN: {'SET' if os.getenv('TELEGRAM_BOT_TOKEN') else 'NOT SET'}")
print(f"   MANAGER_CHAT_ID: {'SET' if os.getenv('MANAGER_CHAT_ID') else 'NOT SET'}")

# 2. Try importing key modules
print("\n2. Testing imports:")
try:
    import sqlalchemy
    print("   ✅ sqlalchemy imported")
except Exception as e:
    print(f"   ❌ sqlalchemy import failed: {e}")

try:
    import psycopg2
    print("   ✅ psycopg2 imported")
except Exception as e:
    print(f"   ❌ psycopg2 import failed: {e}")

# 3. Test database connection
print("\n3. Testing database connection:")
db_url = os.getenv('DATABASE_URL')
if db_url:
    try:
        from sqlalchemy import create_engine
        engine = create_engine(db_url)
        connection = engine.connect()
        print("   ✅ Database connection successful")
        connection.close()
    except Exception as e:
        print(f"   ❌ Database connection failed: {e}")
else:
    print("   ⚠️ DATABASE_URL not set, skipping connection test")

print("\n4. Diagnostic complete")