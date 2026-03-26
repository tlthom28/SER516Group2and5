import os

class Config:
    APP_NAME = os.getenv("APP_NAME", "RepoPulse")
    DEBUG = os.getenv("DEBUG", "false").lower() in ("true", "1", "t")
    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = int(os.getenv("PORT", 8000))
    # InfluxDB
    INFLUX_URL = os.getenv("INFLUX_URL", "http://influxdb:8086")
    INFLUX_TOKEN = os.getenv("INFLUX_TOKEN")
    # Also support reading token from a file (for Docker secrets)
    INFLUX_TOKEN_FILE = os.getenv("INFLUX_TOKEN_FILE")
    if not INFLUX_TOKEN and INFLUX_TOKEN_FILE and os.path.exists(INFLUX_TOKEN_FILE):
        try:
            with open(INFLUX_TOKEN_FILE, "r") as f:
                INFLUX_TOKEN = f.read().strip()
        except Exception:
            INFLUX_TOKEN = None

    INFLUX_ORG = os.getenv("INFLUX_ORG", "RepoPulseOrg")
    INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "repopulse_metrics")
    INFLUX_RETENTION_DAYS = int(os.getenv("INFLUX_RETENTION_DAYS", "90"))
    # Worker pool
    WORKER_POOL_SIZE = int(os.getenv("WORKER_POOL_SIZE", "4"))