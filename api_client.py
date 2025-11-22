#!/usr/bin/env python3
import argparse
import json
import time
import requests


def main():
    parser = argparse.ArgumentParser(description="Minimal client for sign/start/status")
    parser.add_argument("--base-url", required=True, help="API base URL, e.g. https://.../prod")
    parser.add_argument("--api-key", help="x-api-key value if your API requires it")
    parser.add_argument("--complaint", required=True, help="Path to complaint PDF")
    parser.add_argument("--answer", required=True, help="Path to answer PDF")
    parser.add_argument("--witness", required=True, help="Path to witness PDF")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Seconds between status polls")
    parser.add_argument("--timeout", type=float, default=600.0, help="Max seconds to wait for completion")
    args = parser.parse_args()

    headers = {}
    if args.api_key:
        headers["x-api-key"] = args.api_key

    # 1) Get presigned upload URLs
    sign_url = f"{args.base_url}/sign"
    r = requests.post(sign_url, headers=headers, timeout=30)
    r.raise_for_status()
    signed = r.json()
    uploads = signed["uploads"]

    # 2) Upload files (Content-Type must match signer expectation)
    def put_file(url: str, path: str):
        with open(path, "rb") as f:
            pr = requests.put(url, data=f, headers={"Content-Type": "application/pdf"}, timeout=120)
            pr.raise_for_status()

    put_file(uploads["complaint"]["presigned_url"], args.complaint)
    put_file(uploads["answer"]["presigned_url"], args.answer)
    put_file(uploads["witness"]["presigned_url"], args.witness)

    # 3) Start the job
    start_url = f"{args.base_url}/jury/start"
    payload = {
        "complaint_key": uploads["complaint"]["key"],
        "answer_key": uploads["answer"]["key"],
        "witness_key": uploads["witness"]["key"],
    }
    r = requests.post(start_url, json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    started = r.json()
    job_id = started["jury_instruction_id"]

    # 4) Poll status
    status_url = f"{args.base_url}/jury/status/{job_id}"
    deadline = time.time() + args.timeout
    last_status = None

    while True:
        if time.time() > deadline:
            raise TimeoutError(f"Timed out after {args.timeout} seconds")

        rs = requests.get(status_url, headers=headers, timeout=15)
        if rs.status_code == 404:
            time.sleep(args.poll_interval)
            continue
        rs.raise_for_status()
        item = rs.json()
        status = item.get("status")

        if status != last_status:
            print(f"status: {status}")
            last_status = status

        if status in ("COMPLETE", "ERROR"):
            print(json.dumps(item, indent=2))
            break

        time.sleep(args.poll_interval)


if __name__ == "__main__":
    main()

