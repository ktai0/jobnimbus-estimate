import logging
import os

from dotenv import load_dotenv

load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable is required")

if not GEMINI_API_KEY:
    logger.warning("GEMINI_API_KEY not set — Gemini 2.5 Pro vision will be disabled, accuracy will be reduced")

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)
