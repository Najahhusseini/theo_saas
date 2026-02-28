from database import engine

try:
    with engine.connect() as connection:
        print("✅ Database connection successful!")
except Exception as e:
    print("❌ Connection failed:")
    print(e)