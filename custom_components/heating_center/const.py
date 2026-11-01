"""Constants for HA Heating Center."""
DOMAIN = "heating_center"
STORAGE_VERSION = 1
DEFAULT_TARGET = 19.0
MIN_TARGET = 5.0
MAX_TARGET = 30.0
TEMP_TOLERANCE = 0.25
RETRY_SECONDS = 15
STALE_SENSOR_SECONDS = 90 * 60
STALE_DEVICE_SECONDS = 4 * 60 * 60
SYNC_SECONDS = 10 * 60
RECONCILE_SECONDS = 60
DEFAULT_SCHEDULE = {
    "0": [{"time": "06:00", "temp": 20}, {"time": "22:00", "temp": 17}],
    "1": [{"time": "06:00", "temp": 20}, {"time": "22:00", "temp": 17}],
    "2": [{"time": "06:00", "temp": 20}, {"time": "22:00", "temp": 17}],
    "3": [{"time": "06:00", "temp": 20}, {"time": "22:00", "temp": 17}],
    "4": [{"time": "06:00", "temp": 20}, {"time": "22:00", "temp": 17}],
    "5": [{"time": "08:00", "temp": 20}, {"time": "23:00", "temp": 17}],
    "6": [{"time": "08:00", "temp": 20}, {"time": "22:00", "temp": 17}],
}
