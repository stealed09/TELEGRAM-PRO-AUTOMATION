import os
from dotenv import load_dotenv

load_dotenv()

# Bot Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN')
ADMIN_IDS = list(map(int, os.getenv('ADMIN_IDS', '').split(','))) if os.getenv('ADMIN_IDS') else []

# Database
DB_NAME = 'automation.db'

# Session Storage
SESSION_DIR = 'sessions/'
os.makedirs(SESSION_DIR, exist_ok=True)

# Escrow Configuration
ESCROW_TIMEOUT = 3600  # 1 hour for replies
