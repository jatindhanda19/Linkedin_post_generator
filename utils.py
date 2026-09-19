import asyncio
import random
import os
from datetime import datetime

import Config 

def log(message: str):
    """ Print a timestamped log message."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}]{message}")

async def random_sleep(min_sec: float = None, max_sec: float = None) -> None:
    """Sleep a random amount of time to mimic human behaviour."""
    min_sec = min_sec or Config.ACTION_WAIT_MIN
    max_sec = max_sec or Config.ACTION_WAIT_MAX
    wait = random.uniform(min_sec, max_sec)
    log(f"⏳ Waiting {wait:.1f}s...")
    await asyncio.sleep(wait)

async def human_type(page, selector:str, text:str) -> None:
    """Click a field and type with random per-keystroke delays."""
    await page.click(selector)
    await random_sleep(0.3, 0.7)
    delay =  random.randint(Config.TYPE_DELAY_MIN, Config.TYPE_DELAY_MAX)
    await page.type(selector, text, delay=delay)

def session_exists() -> bool:
    """Return True if a non-empty auth.json session file exists."""
    return(
        os.path.exists(Config.SESSION_FILE)
        and os.path.getsize(Config.SESSION_FILE)> 10
    )

def ensure_folders()-> None:
    """Create required directories if they don't exists"""
    for folder in ("sessions", "assets","logs"):
        os.makedirs(folder, exist_ok=True)

    log("📁 Folders ready")
    