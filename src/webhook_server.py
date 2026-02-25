
import os
import hmac
import hashlib
import json
from typing import List, Dict, Any
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from pydantic import BaseModel

# Add current directory to sys.path to ensure modules are found
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

import logging

# Configure unified logger
log_dir = Path(__file__).parent / "artifacts" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / "webhook.log"

logger = logging.getLogger("webhook")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# File handler
fh = logging.FileHandler(log_file)
fh.setFormatter(formatter)
logger.addHandler(fh)

# Console handler
ch = logging.StreamHandler()
ch.setFormatter(formatter)
logger.addHandler(ch)

def get_project_logger(project_name: str):
    log_file = log_dir / f"{project_name}_webhook.log"
    proj_logger = logging.getLogger(f"webhook_{project_name}")
    if not proj_logger.handlers:
        proj_logger.setLevel(logging.INFO)
        fh = logging.FileHandler(log_file)
        fh.setFormatter(formatter)
        proj_logger.addHandler(fh)
        
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        proj_logger.addHandler(ch)
    return proj_logger

from core.pipeline import incremental_update, initialize_project
from utils import load_projects

from dotenv import load_dotenv

# Load env vars where Streamlit UI saves them
load_dotenv(override=True)

app = FastAPI(title="CodeBot Webhook Server")

# Configuration (In a real app, load from env or config)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

class PushPayload(BaseModel):
    ref: str
    repository: Dict[str, Any]
    commits: List[Dict[str, Any]]

def verify_signature(payload_body: bytes, secret_token: str, signature_header: str):
    """Verify that the payload was sent from GitHub by validating SHA256."""
    if not signature_header:
        raise HTTPException(status_code=403, detail="x-hub-signature-256 header is missing!")
        
    hash_object = hmac.new(secret_token.encode('utf-8'), msg=payload_body, digestmod=hashlib.sha256)
    expected_signature = "sha256=" + hash_object.hexdigest()
    
    if not hmac.compare_digest(expected_signature, signature_header):
        raise HTTPException(status_code=403, detail="Request signatures didn't match!")

async def process_webhook_background(project_name: str, modified_files: List[str], removed_files: List[str] = None, full_rebuild: bool = False):
    """Background task to run the heavy analysis."""
    proj_logger = get_project_logger(project_name)
    proj_logger.info(f"Starting analysis for {project_name}...")
    removed_files = removed_files or []
    try:
        updated_docs = incremental_update(project_name, modified_files, removed_files, full_rebuild=full_rebuild)
        proj_logger.info(f"Completed analysis. Updated docs: {updated_docs}, Removed: {removed_files}")
        
        # Publish artifacts to S3 after updating
        try:
            from s3_sync import upload_artifacts_to_s3
            proj_logger.info("Synchronizing artifacts to S3...")
            upload_artifacts_to_s3()
            proj_logger.info("S3 Synchronization complete.")
        except ImportError:
            proj_logger.warning("s3_sync module not found. Skipping S3 upload.")
            
    except Exception as e:
        proj_logger.error(f"Error processing webhook: {e}")

@app.post("/webhook")
async def handle_webhook(request: Request, background_tasks: BackgroundTasks):
    payload_body = await request.body()
    signature = request.headers.get("x-hub-signature-256")
    
    # Reload env vars dynamically so we don't need to restart the server
    load_dotenv(override=True)
    current_secret = os.getenv("WEBHOOK_SECRET")
    
    # Verify signature
    if not current_secret:
        # If secret isn't configured yet, reject to be safe.
        logger.error("WEBHOOK_SECRET not configured. Rejecting payload.")
        raise HTTPException(status_code=500, detail="Webhook secret not configured on server.")
        
    verify_signature(payload_body, current_secret, signature)
        
    payload = await request.json()
    
    # Extract info
    repo_name = payload.get("repository", {}).get("name")
    repo_clone_url = payload.get("repository", {}).get("clone_url")
    repo_html_url = payload.get("repository", {}).get("html_url")
    
    # Determine project name map
    projects = load_projects()
    
    matched_project = None
    
    # 1. Primary Strategy: Try matching by exactly stored Git URL
    for name, info in projects.items():
        stored_url = info.get("git_url")
        if stored_url:
            # Strip credentials (like PATs) from stored URL for comparison
            import urllib.parse
            parsed = urllib.parse.urlparse(stored_url)
            clean_stored = parsed._replace(netloc=parsed.hostname).geturl() if parsed.hostname else stored_url
            
            # Compare without credentials and case-insensitive
            if (clean_stored.lower() == (repo_clone_url or "").lower() or 
                clean_stored.lower() == (repo_html_url or "").lower() or 
                clean_stored.lower().rstrip(".git") == (repo_html_url or "").lower()):
                matched_project = name
                break
            
    # 2. Fallback Strategy: Check if any project path ends with the repo name (case-insensitive)
    if not matched_project and repo_name:
        for name, info in projects.items():
            if Path(info["path"]).name.lower() == repo_name.lower():
                matched_project = name
                break
                
    if not matched_project:
        logger.warning(f"Could not match repository {repo_name} (URL: {repo_clone_url}) to a project.")
        return {"status": "ignored", "reason": "unknown repository"}
        
    proj_logger = get_project_logger(matched_project)
    
    # Determine event type
    github_event = request.headers.get("x-github-event", "push")
    
    if github_event == "ping":
        proj_logger.info(f"Received GitHub ping for {matched_project}. Triggering initial full analysis...")
        # An empty file list tells incremental_update to rebuild docs for all modules
        background_tasks.add_task(process_webhook_background, matched_project, [], [], full_rebuild=True)
        return {"status": "accepted", "project": matched_project, "action": "initial_ping_analysis"}

    if github_event != "push":
        return {"status": "ignored", "reason": f"unhandled event type: {github_event}"}

    # Collect modified files and check for infinite loop for push events
    modified_files = set()
    removed_files = set()
    codebot_commit = False
    
    if "commits" in payload:
        for commit in payload["commits"]:
            message = commit.get("message", "")
            if message.startswith("[CodeBot]"):
                codebot_commit = True
                proj_logger.info(f"Ignoring auto-generated CodeBot commit: {message}") # skip bots
                continue
                
            modified_files.update(commit.get("added", []))
            modified_files.update(commit.get("modified", []))
            removed_files.update(commit.get("removed", []))
            
    if codebot_commit and not modified_files and not removed_files:
         proj_logger.info("Ignoring push payload entirely (only CodeBot commits found).")
         return {"status": "ignored", "reason": "auto-generated bot commit"}
            
    if not modified_files and not removed_files:
         proj_logger.info("Ignoring push payload (no modified files or removed files).")
         return {"status": "ignored", "reason": "no file changes"}

    # Run analysis in background
    proj_logger.info(f"Accepted webhook for {matched_project}. Modified: {list(modified_files)}, Removed: {list(removed_files)}")
    background_tasks.add_task(process_webhook_background, matched_project, list(modified_files), list(removed_files))
    
    return {"status": "accepted", "project": matched_project, "files": list(modified_files), "removed": list(removed_files)}

@app.get("/")
def health_check():
    return {"status": "ok", "service": "CodeBot Webhook Listener"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
