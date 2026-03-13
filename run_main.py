import sys
import traceback

print("="*60)
print("🚀 Starting main.py with error catching")
print("="*60)

try:
    import main
    print("✅ main.py imported successfully")
except Exception as e:
    print(f"❌ Error importing main.py: {e}")
    traceback.print_exc()
    sys.exit(1)

print("="*60)
print("✅ main.py loaded, now starting server...")
print("="*60)

# If we get here, main.py imported successfully
# Now we need to run the uvicorn server
if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)