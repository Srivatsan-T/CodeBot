
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

async def process_webhook_background(project_name: str, modified_files: List[str]):
    """Background task to run the heavy analysis."""
    print(f"Starting analysis for {project_name}...")
    try:
        updated_docs = incremental_update(project_name, modified_files)
        print(f"Completed analysis. Updated docs: {updated_docs}")
    except Exception as e:
        print(f"Error processing webhook: {e}")

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
        print("WEBHOOK_SECRET not configured. Rejecting payload.")
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
        if stored_url and (stored_url == repo_clone_url or stored_url == repo_html_url or stored_url.rstrip(".git") == repo_html_url):
            matched_project = name
            break
            
    # 2. Fallback Strategy: Check if any project path ends with the repo name
    if not matched_project:
        for name, info in projects.items():
            if Path(info["path"]).name == repo_name:
                matched_project = name
                break
                
    if not matched_project:
        print(f"Could not match repository {repo_name} (URL: {repo_clone_url}) to a project.")
        return {"status": "ignored", "reason": "unknown repository"}
    # Collect modified files and check for infinite loop
    modified_files = set()
    codebot_commit = False
    
    if "commits" in payload:
        for commit in payload["commits"]:
            message = commit.get("message", "")
            if message.startswith("[CodeBot]"):
                codebot_commit = True
                print(f"Ignoring auto-generated CodeBot commit: {message}")
                continue # Skip processing files from our own commits
                
            modified_files.update(commit.get("added", []))
            modified_files.update(commit.get("modified", []))
            # removed? We might want to handle deletion too.
            
    if codebot_commit and not modified_files:
         return {"status": "ignored", "reason": "auto-generated bot commit"}
            
    if not modified_files:
         return {"status": "ignored", "reason": "no file changes"}

    # Run analysis in background
    background_tasks.add_task(process_webhook_background, matched_project, list(modified_files))
    
    return {"status": "accepted", "project": matched_project, "files": list(modified_files)}

@app.get("/")
def health_check():
    return {"status": "ok", "service": "CodeBot Webhook Listener"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
