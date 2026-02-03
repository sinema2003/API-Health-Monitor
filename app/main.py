import os
import json
import time
import asyncio
import aiohttp
import boto3
from botocore.config import Config
from boto3.dynamodb.conditions import Key

AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")
TABLE_NAME = os.environ["DDB_TABLE_NAME"]
SNS_TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]

DDB_GSI_NAME = os.environ.get("DDB_GSI_NAME", "gsi_due_checks")
BUCKET_COUNT = int(os.environ.get("BUCKET_COUNT", "16"))
BUCKET_START = int(os.environ.get("BUCKET_START", "0"))
BUCKET_END = int(os.environ.get("BUCKET_END", str(BUCKET_COUNT - 1)))

BOTO_CONFIG = Config(retries={"max_attempts": 5, "mode": "standard"})
ddb = boto3.resource("dynamodb", region_name=AWS_REGION, config=BOTO_CONFIG)
sns = boto3.client("sns", region_name=AWS_REGION, config=BOTO_CONFIG)
table = ddb.Table(TABLE_NAME)

DEFAULTS = {
    "method": "GET",
    "expected_codes": [200],
    "timeout_ms": 2000,
    "interval_sec": 60,
    "failure_threshold": 3,
    "recovery_threshold": 2,
    "expected_body_contains": None,
    "max_latency_ms": None,
}

def now_epoch() -> int:
    return int(time.time())

async def fetch_one(session: aiohttp.ClientSession, ep: dict):
    url = ep["url"]
    method = ep.get("method", DEFAULTS["method"]).upper()
    expected_codes = ep.get("expected_codes", DEFAULTS["expected_codes"])
    timeout_ms = int(ep.get("timeout_ms", DEFAULTS["timeout_ms"]))
    body_contains = ep.get("expected_body_contains", DEFAULTS["expected_body_contains"])
    max_latency_ms = ep.get("max_latency_ms", DEFAULTS["max_latency_ms"])

    t0 = time.perf_counter()
    try:
        timeout = aiohttp.ClientTimeout(total=timeout_ms / 1000.0)
        async with session.request(method, url, timeout=timeout) as resp:
            status = resp.status
            text = await resp.text()
    except asyncio.TimeoutError:
        return False, "timeout", None, None
    except Exception as e:
        return False, f"network_error:{type(e).__name__}", None, None

    latency_ms = int((time.perf_counter() - t0) * 1000)

    if status not in expected_codes:
        return False, f"bad_status:{status}", status, latency_ms

    if max_latency_ms is not None and latency_ms > int(max_latency_ms):
        return False, f"slow:{latency_ms}ms", status, latency_ms

    if body_contains and body_contains not in text:
        return False, "body_mismatch", status, latency_ms

    return True, "ok", status, latency_ms

def publish_state_change(ep_id: str, url: str, old: str, new: str, reason: str, status, latency_ms):
    msg = {
        "endpoint_id": ep_id,
        "url": url,
        "old_state": old,
        "new_state": new,
        "reason": reason,
        "http_status": status,
        "latency_ms": latency_ms,
        "ts": now_epoch(),
    }
    sns.publish(
        TopicArn=SNS_TOPIC_ARN,
        Subject=f"[API Monitor] {new} - {ep_id}",
        Message=json.dumps(msg, indent=2),
    )

def compute_next_state(current_state: str, consec_fail: int, consec_succ: int, failure_th: int, recovery_th: int):
    if current_state == "HEALTHY":
        return "UNHEALTHY" if consec_fail >= failure_th else "HEALTHY"
    if current_state == "UNHEALTHY":
        return "HEALTHY" if consec_succ >= recovery_th else "UNHEALTHY"
    return "HEALTHY"

def query_due_endpoints(bucket: int, t: int):
    items = []
    kwargs = {
        "IndexName": DDB_GSI_NAME,
        "KeyConditionExpression": Key("schedule_bucket").eq(bucket) & Key("next_check_at").lte(t),
        "Limit": 200,  # tune as needed
    }
    resp = table.query(**kwargs)
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.query(**kwargs, ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))
    return items

async def main():
    t = now_epoch()

    due = []
    for b in range(BUCKET_START, BUCKET_END + 1):
        due.extend(query_due_endpoints(b, t))

    due = [it for it in due if it.get("enabled", True)]
    if not due:
        print("No endpoints due.")
        return

    conn = aiohttp.TCPConnector(limit=50, ssl=False)
    async with aiohttp.ClientSession(connector=conn) as session:
        results = await asyncio.gather(*[fetch_one(session, ep) for ep in due])

    for ep, (ok, reason, http_status, latency_ms) in zip(due, results):
        ep_id = ep["endpoint_id"]
        url = ep["url"]

        interval_sec = int(ep.get("interval_sec", DEFAULTS["interval_sec"]))
        next_check_at = t + interval_sec

        state = ep.get("state", "HEALTHY")
        consec_fail = int(ep.get("consec_fail", 0))
        consec_succ = int(ep.get("consec_succ", 0))

        failure_th = int(ep.get("failure_threshold", DEFAULTS["failure_threshold"]))
        recovery_th = int(ep.get("recovery_threshold", DEFAULTS["recovery_threshold"]))

        if ok:
            consec_succ += 1
            consec_fail = 0
        else:
            consec_fail += 1
            consec_succ = 0

        new_state = compute_next_state(state, consec_fail, consec_succ, failure_th, recovery_th)
        state_changed = (new_state != state)

        update_expr = [
            "SET last_checked = :lc",
            "next_check_at = :nca",
            "#st = :ns",
            "consec_fail = :cf",
            "consec_succ = :cs",
            "last_reason = :lr",
        ]
        expr_vals = {
            ":lc": t,
            ":nca": next_check_at,
            ":ns": new_state,
            ":cf": consec_fail,
            ":cs": consec_succ,
            ":lr": reason,
        }

        if http_status is not None:
            update_expr.append("last_http_status = :hs")
            expr_vals[":hs"] = int(http_status)
        if latency_ms is not None:
            update_expr.append("last_latency_ms = :lm")
            expr_vals[":lm"] = int(latency_ms)
        if state_changed:
            update_expr.append("last_state_change = :lsc")
            expr_vals[":lsc"] = t

        table.update_item(
            Key={"endpoint_id": ep_id},
            UpdateExpression=", ".join(update_expr),
            ExpressionAttributeValues=expr_vals,
            ExpressionAttributeNames={"#st": "state"},
        )

        if state_changed:
            publish_state_change(ep_id, url, state, new_state, reason, http_status, latency_ms)
            print(f"{ep_id}: {state} -> {new_state} ({reason})")
        else:
            print(f"{ep_id}: {new_state} ({reason})")

if __name__ == "__main__":
    asyncio.run(main())
