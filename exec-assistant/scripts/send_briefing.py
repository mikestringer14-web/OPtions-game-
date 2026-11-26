"""Build the briefing and push it to the owner via ntfy. Run from cron at 6:00 and 22:30."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import db  # noqa: E402
from app.briefing import build_briefing  # noqa: E402
from app.notify import send_ntfy  # noqa: E402

db.connect()
text = build_briefing()["text"]
print(text)
print(send_ntfy("Your briefing", text[:3800], "normal"))
