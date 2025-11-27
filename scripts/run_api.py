import argparse
from datetime import datetime
import json
from pathlib import Path
import time
from typing import Any

import requests

DEFAULT_API_URL = "https://z8rj47cgo7.execute-api.us-east-1.amazonaws.com/dev"
DEFAULT_API_KEY = "izVg8ltdAPfuvGVmnKZ5vLAswOAP4Nrz"


def read_json(p: Path) -> Any:
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(p: Path, obj: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def call_api_sign(base_url: str, api_key: str) -> dict[str, Any]:
    url = f"{base_url}/sign"
    r = requests.post(url, headers={"x-api-key": api_key})
    r.raise_for_status()
    return r.json()


def upload_file(put_url: str, path: Path, content_type: str = "application/pdf") -> None:
    with path.open("rb") as f:
        r = requests.put(put_url, data=f, headers={"Content-Type": content_type})
    r.raise_for_status()


def call_api_start(
    base_url: str,
    api_key: str,
    complaint_key: str,
    answer_key: str,
    witness_key: str
) -> dict[str, Any]:
    url = f"{base_url}/jury/start"
    body = {
        "complaint_key": complaint_key,
        "answer_key": answer_key,
        "witness_key": witness_key,
    }
    r = requests.post(url, json=body, headers={"x-api-key": api_key, "Content-Type": "application/json"})
    r.raise_for_status()
    return r.json()


def call_api_status(base_url: str, api_key: str, job_id: str) -> dict[str, Any]:
    url = f"{base_url}/jury/status/{job_id}"
    r = requests.get(url, headers={"x-api-key": api_key})
    r.raise_for_status()
    return r.json()


def run(example: str, env: str, out_root: Path, base_url: str, api_key: str) -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    base_url = base_url.rstrip("/")

    ex_dir = repo_root / "examples" / example
    files_def = read_json(ex_dir / "files.json")
    complaint = ex_dir / files_def["complaint"]
    answer = ex_dir / files_def["answer"]
    witness = ex_dir / files_def["witness_list"]

    run_id = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    out_dir = out_root / f"{env}-{example}-{run_id}"
    (out_dir / "input").mkdir(parents=True, exist_ok=True)
    (out_dir / "responses").mkdir(parents=True, exist_ok=True)

    # 1) Get presigned URLs
    signer_resp = call_api_sign(base_url, api_key)
    write_json(out_dir / "responses" / "sign.json", signer_resp)

    uploads = signer_resp.get("uploads", {})
    c_info = uploads.get("complaint")
    a_info = uploads.get("answer")
    w_info = uploads.get("witness")
    if not (c_info and a_info and w_info):
        raise SystemExit("api_signer did not return expected upload slots")

    # 2) Upload files
    upload_file(c_info["presigned_url"], complaint, c_info.get("content_type", "application/pdf"))
    upload_file(a_info["presigned_url"], answer, a_info.get("content_type", "application/pdf"))
    upload_file(w_info["presigned_url"], witness, w_info.get("content_type", "application/pdf"))

    # 3) Start the workflow
    start_resp = call_api_start(base_url, api_key, c_info["key"], a_info["key"], w_info["key"])
    write_json(out_dir / "responses" / "start.json", start_resp)

    job_id = start_resp.get("jury_instruction_id")
    if not job_id:
        raise SystemExit("api_start did not return jury_instruction_id")

    # 4) Poll status
    poll_path = out_dir / "responses" / "status_progress.jsonl"
    deadline = time.time() + 60 * 30  # 30 minutes
    last_status = None
    with poll_path.open("w", encoding="utf-8") as f:
        while time.time() < deadline:
            status = call_api_status(base_url, api_key, job_id)
            f.write(json.dumps(status) + "\n")
            f.flush()

            if status.get("_not_found"):
                time.sleep(3)
                continue

            last_status = status
            s = str(status.get("status") or "").upper()
            if s == "COMPLETE":
                break
            time.sleep(10)

    if not last_status or str(last_status.get("status", "")).upper() != "COMPLETE":
        raise SystemExit("Timed out waiting for job completion. See status_progress.jsonl for details.")

    # 5) Write outputs
    final = {
        "job_id": job_id,
        "status": last_status.get("status"),
        "case_facts": last_status.get("case_facts"),
        "witnesses": last_status.get("witnesses"),
        "claims": last_status.get("claims"),
        "counterclaims": last_status.get("counterclaims"),
        "instructions": last_status.get("jury_instructions_text"),
        "source_files": last_status.get("source_files"),
        "createdAt": last_status.get("createdAt"),
        "completedAt": last_status.get("completedAt"),
    }
    write_json(out_dir / "final.json", final)

    return out_dir


def main():
    ap = argparse.ArgumentParser(description="Run remote jury-gen pipeline via API Gateway")
    ap.add_argument("--example", choices=["one", "two"], help="Which example folder to use")
    ap.add_argument("--env", choices=["dev", "prod"], default="dev", help="Tag outputs with env (no functional change)")
    ap.add_argument("--out", default="runs", help="Output folder root (default: runs)")
    ap.add_argument("--api-url", default=DEFAULT_API_URL, help="Base API URL (default: dev URL)")
    ap.add_argument("--api-key", default=DEFAULT_API_KEY, help="API key (default: dev key)")
    args = ap.parse_args()

    out_dir = run(args.example, args.env, Path(args.out), args.api_url, args.api_key)
    print(f"Done. Results in: {out_dir}")


if __name__ == "__main__":
    main()
