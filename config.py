import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


@dataclass(frozen=True)
class S:
    # Emaktab URL'lari
    emaktab_login_url: str = os.getenv("EMAKTAB_LOGIN_URL", "")
    emaktab_home_url: str = os.getenv("EMAKTAB_HOME_URL", "")

    # Firebase
    firebase_credentials: str = os.getenv("FIREBASE_CREDENTIALS", "")
    firebase_credentials_json: str = os.getenv("FIREBASE_CREDENTIALS_JSON", "")

    # Shifrlash — majburiy
    encryption_key: str = os.environ["EMAKTAB_ENC_KEY"]

    # Worker
    batch_size: int = int(os.getenv("SYNC_BATCH_SIZE", "40"))
    headless: bool = os.getenv("CHROME_HEADLESS", "true").lower() == "true"
    class_id: str = os.getenv("CLASS_ID", "9-A")
    api_admin_token: str = os.getenv("API_ADMIN_TOKEN", "")
    allowed_origins: str = os.getenv("ALLOWED_ORIGINS", "*")
    debug_html: bool = os.getenv("EMAKTAB_DEBUG_HTML", "false").lower() == "true"

    # Sovg'a reyting metrikasi
    prize_metric: str = os.getenv("PRIZE_METRIC", "combined")
    prize_avg_weight: float = float(os.getenv("PRIZE_AVG_WEIGHT", "0.6"))
    prize_growth_weight: float = float(os.getenv("PRIZE_GROWTH_WEIGHT", "0.4"))
        # Bot
    bot_token: str = os.getenv("BOT_TOKEN", "")
    bot_username: str = os.getenv("BOT_USERNAME", "")


settings = S()