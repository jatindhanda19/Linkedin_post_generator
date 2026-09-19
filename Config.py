import os
from dotenv import load_dotenv

load_dotenv()

# Credentials
LINKEDIN_EMAIL = os.getenv("LINKEDIN_EMAIL", "")
LINKEDIN_PASSWORD = os.getenv("LINKEDIN_PASSWORD", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# URLs
LINKEDIN_URL = "https://www.linkedin.com"
LINKEDIN_LOGIN_URL = "https://www.linkedin.com/login"
LINKEDIN_FEED_URL = "https://www.linkedin.com/feed/"

# Browser
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"
SLOW_MO = int(os.getenv("SLOW_MO","50"))

# Paths
SESSION_FILE = "sessions/auth.json"
LOG_FILE = "sessions/run_log.json"
ASSETS_FOLDER = "assets/"
ASSETS_DIR = "assets"

PAGE_LOAD_WAIT = 3

# Human delay
ACTION_WAIT_MIN = 1
ACTION_WAIT_MAX = 3

# Typing behaviour
TYPE_DELAY_MIN = 50
TYPE_DELAY_MAX = 150
