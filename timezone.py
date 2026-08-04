import pytz
from datetime import datetime

def get_iran_time():
    tehran_tz = pytz.timezone('Asia/Tehran')
    return datetime.now(tehran_tz)
