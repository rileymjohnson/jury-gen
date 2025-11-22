#!/usr/bin/env python3
import argparse
import json
import sys
import time
from typing import Any, Dict, Optional

try:
    import requests
except ImportError:
    print("This script requires the 'requests' package. Install with: pip install requests", file=sys.stderr)
    sys.exit(1)

# ---------- Customize these URLs ----------
SIGNER_URL = "<PUT_YOUR_SIGNER_LAMBDA_URL_OR_APIGW_ENDPOINT_HERE>"
START_URL  = "<PUT_YOUR_START_LAMBDA_URL_OR_APIGW_ENDPOINT_HERE>"
STATUS_URL = "<PUT_YOUR_STATUS_LAMBDA_URL_OR_APIGW_ENDPOINT_HERE>"
# -----------------------------------------

# Optional: static API key header if you use one (leave None if not)
API_KEY_HEADER = None  # e.g., {"x-api-key": "YOUR_KEY"}


def build_auth_headers(signer_resp: Dict[str, Any]) -> Dict[str, str]:
    """Derive request headers from signer response. Adjust to your payload shape."""
    if isinstance(signer_resp, dict):
        if "headers" in signer_resp and isinstance(signer_resp["headers"], dict):
            return {str(k): str(v) for k, v in signer_resp["headers"].items()}
        if "token" in signer_resp:
            return {"Authorization": f"Bearer {signer_resp['token']}"}
        if "signature" in signer_resp:
            return {"X-Signature": str(signer_resp["signature"])}
    return {}


def extract_execution_id(resp: Dict[str, Any]) -> Optional[str]:
    """Extract execution identifier/ARN from start response."""
    for key in ("executionArn", "execution_arn", "executionId", "id", "arn"):
        if key in resp and isinstance(resp[key], str):
            return resp[key]
    return None


def is_terminal(status: str) -> bool:
    """Return True if the execution status is terminal."""
    status = status.upper()
    return status in ("SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED", "CANCELED", "CANCELLED")


def load_input_json(arg_json: Optional[str], arg_file: Optional[str]) -> Any:
    if arg_json:
        return json.loads(arg_json)
    if arg_file:
        with open(arg_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Start a Step Function via Lambdas and poll status.")
    parser.add_argument("--signer-url", default=SIGNER_URL, help="Signer Lambda URL")
    parser.add_argument("--start-url", default=START_URL, help="Start Lambda URL")
    parser.add_argument("--status-url", default=STATUS_URL, help="Status Lambda URL")
    parser.add_argument("--input-json", help="Inline JSON for the state machine input")
    parser.add_argument("--input-file", help="Path to JSON file for the state machine input")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Seconds between status polls")
    parser.add_argument("--timeout", type=float, default=600.0, help="Max seconds to wait for completion")
    parser.add_argument("--verbose", action="store_true", help="Verbose logs")
    args = parser.parse_args()

    # 1) Get signature/auth
    try:
        signer_body = {
            # Customize as needed; often signer takes context like "for": "start"
            "for": "start"
        }
        headers: Dict[str, str] = {}
        if API_KEY_HEADER:
            headers.update(API_KEY_HEADER)
        resp = requests.post(args.signer_url, json=signer_body, headers=headers, timeout=30)
        resp.raise_for_status()
        signer_resp = resp.json()
        auth_headers = build_auth_headers(signer_resp)
        if args.verbose:
            print(f"[signer] HTTP {resp.status_code}, derived auth headers: {list(auth_headers.keys())}")
    except Exception as e:
        print(f"Failed to call signer: {e}", file=sys.stderr)
        sys.exit(2)

    # 2) Start execution
    try:
        input_payload = load_input_json(args.input_json, args.input_file)
        start_body = {
            # Customize as needed; many backends expect "input" as JSON
            "input": input_payload
        }
        start_headers: Dict[str, str] = {}
        if API_KEY_HEADER:
            start_headers.update(API_KEY_HEADER)
        start_headers.update(auth_headers)
        resp = requests.post(args.start_url, json=start_body, headers=start_headers, timeout=60)
        resp.raise_for_status()
        start_resp = resp.json()
        execution_id = extract_execution_id(start_resp)
        if not execution_id:
            print(f"Start response did not contain an execution ID. Response: {start_resp}", file=sys.stderr)
            sys.exit(3)
        if args.verbose:
            print(f"[start] HTTP {resp.status_code}, execution: {execution_id}")
    except Exception as e:
        print(f"Failed to start execution: {e}", file=sys.stderr)
        sys.exit(3)

    # 3) Poll status
    deadline = time.time() + args.timeout
    last_status: Optional[str] = None
    result_payload: Any = None

    try:
        status_headers: Dict[str, str] = {}
        if API_KEY_HEADER:
            status_headers.update(API_KEY_HEADER)
        status_headers.update(auth_headers)

        while True:
            if time.time() > deadline:
                print(f"Timed out after {args.timeout} seconds waiting for execution to finish.", file=sys.stderr)
                sys.exit(4)

            status_body = {
                # Customize as needed; most backends expect the executionArn/id to check status
                "executionArn": execution_id
            }
            resp = requests.post(args.status_url, json=status_body, headers=status_headers, timeout=30)
            resp.raise_for_status()
            status_resp = resp.json()

            # Common shapes: {"status": "RUNNING", "output": {...}} or {"execution": {"status": ...}}
            status = (
                status_resp.get("status")
                or (status_resp.get("execution") or {}).get("status")
                or (status_resp.get("state") or {}).get("status")
            )
            if not isinstance(status, str):
                print(f"Status response missing 'status' string. Response: {status_resp}", file=sys.stderr)
                sys.exit(5)

            if args.verbose and status != last_status:
                print(f"[status] {status}")
                last_status = status

            if is_terminal(status):
                # Try to extract output if present
                result_payload = (
                    status_resp.get("output")
                    or (status_resp.get("execution") or {}).get("output")
                    or status_resp.get("result")
                )
                break

            time.sleep(args.poll_interval)

    except Exception as e:
        print(f"Failed while polling status: {e}", file=sys.stderr)
        sys.exit(5)

    # 4) Print outcome
    print(json.dumps({
        "execution": execution_id,
        "status": last_status,
        "output": result_payload
    }, indent=2))


if __name__ == "__main__":
    main()

