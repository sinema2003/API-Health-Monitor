import os
import time
import zlib
import boto3
from botocore.config import Config

AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")
TABLE_NAME = os.environ["DDB_TABLE_NAME"]
BUCKET_COUNT = int(os.environ.get("BUCKET_COUNT", "16"))

BOTO_CONFIG = Config(retries={"max_attempts": 5, "mode": "standard"})
ddb = boto3.resource("dynamodb", region_name=AWS_REGION, config=BOTO_CONFIG)
table = ddb.Table(TABLE_NAME)

def now_epoch() -> int:
    return int(time.time())

def bucket_for(endpoint_id: str) -> int:
    # stable hash across runs (unlike Python's hash())
    return zlib.crc32(endpoint_id.encode("utf-8")) % BUCKET_COUNT

ENDPOINTS = [
        {
        "endpoint_id": "google",
        "url": "https://www.google.com",
        "method": "GET",
        "expected_codes": [200],
        "timeout_ms": 2000,
        "interval_sec": 60,
        "failure_threshold": 3,
        "recovery_threshold": 2,
        "enabled": True,
    },
    {
        "endpoint_id": "bad_status_demo",
        "url": "https://httpstat.us/500",
        "method": "GET",
        "expected_codes": [200],
        "timeout_ms": 2000,
        "interval_sec": 60,
        "failure_threshold": 1,
        "recovery_threshold": 1,
        "enabled": True,
    }
    # Add your real endpoints here...
]

t = now_epoch()

for ep in ENDPOINTS:
    ep.setdefault("state", "HEALTHY")
    ep.setdefault("consec_fail", 0)
    ep.setdefault("consec_succ", 0)
    ep.setdefault("last_checked", 0)

    ep["schedule_bucket"] = bucket_for(ep["endpoint_id"])
    ep["next_check_at"] = t  # due immediately on first run

    table.put_item(Item=ep)

print(f"Seeded {len(ENDPOINTS)} endpoints into {TABLE_NAME}")
