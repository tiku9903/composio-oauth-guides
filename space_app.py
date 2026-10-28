"""Entry point for Hugging Face Spaces (Gradio SDK, free CPU).

Spaces runs this file with Python and routes traffic to port 7860. We serve the regular FastAPI app;
Gradio itself is not used. Locally you can run it the same way: `python space_app.py`.
"""
import os

import uvicorn

from app.main import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "7860")),
                proxy_headers=True, forwarded_allow_ips="*")
