import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(i) for i in os.getenv("ADMIN_IDS", "").split(",") if i.strip()]
BOT_USERNAME = os.getenv("BOT_USERNAME", "KinolarAro_bot")

MOVIES_FILE = "data/movies.json"
CHANNELS_FILE = "data/channels.json"
STATS_FILE = "data/stats.json"