import os
from pathlib import Path

HEALTH_DATA_DIR = Path(os.environ.get("HEALTH_DATA_DIR", "/data/health-data"))
ARCHIVE_DIR = HEALTH_DATA_DIR / "archive"
INCOMING_DIR = HEALTH_DATA_DIR / "incoming"

AUTH_TOKEN = os.environ.get(
    "HEALTH_CONNECT_AUTH_TOKEN",
    "70b8643f64e27e72768cdfb12d13110b80cbfc884e42916b638bf0d4c2886a26",
)
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "dana-njJIlyJohbRDnHASVMgbGDlfqN")
NTFY_URL = os.environ.get("NTFY_URL", "https://ntfy.sh")

MAX_BODY_SIZE = 100 * 1024 * 1024  # 100MB

# Known package instance signatures for Dana's Pixel 10
DANA_SIGNATURES = {
    "com.android.healthconnect.phone.jc684f7da3b1135ecae02207b0f7823e7",
    "com.android.healthconnect.phone.j25af450ad1c1358ab9eb70055852fcd7",
    "com.android.healthconnect.phone.j19fb52a3a7db3b12b065c8877da13c6e",
    "com.android.healthconnect.phone.j01aed94297373b3cbe2dc8d94a7441fe",
    "com.android.healthconnect.phone.j8bc2ab4a00b73d3690fd0069facfa8fb",
    "com.android.healthconnect.phone.jbdf4de72eada303b93517d5962dca697",
}

# Signatures for Michelle (configurable via env var or dynamically extended)
_michelle_env = os.environ.get("MICHELLE_HEALTH_SIGNATURES", "")
MICHELLE_SIGNATURES = {s.strip() for s in _michelle_env.split(",") if s.strip()}
