import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://meetsync:devpassword@localhost:5432/meetsync"
)