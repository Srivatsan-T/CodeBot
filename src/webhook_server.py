
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

app = FastAPI(title="CodeBot Webhook Server")

# Configuration (In a real app, load from env or config)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "my-secret-token")

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
    
    # Verify signature
    # In production, use the configured secret. 
    # For prototype, we might skip if not set, but let's be safe.
    if WEBHOOK_SECRET and WEBHOOK_SECRET != "my-secret-token":
        verify_signature(payload_body, WEBHOOK_SECRET, signature)
        
    payload = await request.json()
    
    # Extract info
    repo_name = payload.get("repository", {}).get("name")
    
    # Determine project name map
    # We need to map git repo name to our internal project name.
    # For now, let's assume project_name == repo_name or we scan our projects.
    projects = load_projects()
    
    # Simple matching strategy: 
    # Check if any project path ends with the repo name
    matched_project = None
    for name, path in projects.items():
        if Path(path).name == repo_name:
            matched_project = name
            break
            
    if not matched_project:
        # Fallback: check if 'project_name' query param is passed? 
        # GitHub webhooks don't easily allow query params configuration in the payload itself.
        # We might need to store repo_url in projects.json to match reliably.
        # For now, let's try to match by name match.
        print(f"Could not match repository {repo_name} to a project.")
        return {"status": "ignored", "reason": "unknown repository"}
        
    # Collect modified files
    modified_files = set()
    if "commits" in payload:
        for commit in payload["commits"]:
            modified_files.update(commit.get("added", []))
            modified_files.update(commit.get("modified", []))
            # removed? We might want to handle deletion too.
            
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
