CAN_API_URL = "http://127.0.0.1:5000/api/info/can"
GPS_API_URL = "http://127.0.0.1:5000/api/info/gps"

# Har necha soniyada CAN + GPS dan so'rov qilinadi
POLL_INTERVAL_SECONDS = 5

# Har necha soatda report yaratib external API ga yuboriladi
REPORT_SEND_INTERVAL_HOURS = 4

# Qaysi report turlari avtomatik yuboriladir
AUTO_REPORT_TYPES = ["daily", "weekly", "monthly"]

EXTERNAL_REPORT_API_URL = "https://dev-gw.tracksafe365.com/services/glssafety/api/ifta/report"
EXTERNAL_API_TIMEOUT    = 30

DB_PATH = "ifta.db"

APP_HOST = "0.0.0.0"
APP_PORT = 8080
DEBUG    = False

LOG_LEVEL = "INFO"
LOG_FILE  = "ifta.log"
