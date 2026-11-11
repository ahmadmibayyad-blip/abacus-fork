import os
import uvicorn

if __name__ == "__main__":
    host = os.environ.get("CLONER_HOST", "127.0.0.1")
    port = int(os.environ.get("CLONER_PORT", "8765"))
    print(f"Cloner running on http://{host}:{port}/")
    uvicorn.run("cloner.app:app", host=host, port=port, log_level="info")
