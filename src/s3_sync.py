import os
import boto3
from pathlib import Path
from botocore.exceptions import ClientError

def get_s3_client():
    """Get an S3 client if credentials and a bucket are configured."""
    bucket_name = os.getenv("AWS_S3_BUCKET_NAME")
    if not bucket_name:
        return None, None
        
    s3 = boto3.client(
        "s3",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY")
    )
    return s3, bucket_name

def upload_artifacts_to_s3():
    """Sync the local artifacts directory UP to the S3 bucket."""
    s3, bucket_name = get_s3_client()
    if not s3 or not bucket_name:
        print("S3 Sync skipped: AWS_S3_BUCKET_NAME not configured.")
        return
        
    artifacts_dir = Path(__file__).parent / "artifacts"
    if not artifacts_dir.exists():
        return
        
    print(f"Uploading artifacts to s3://{bucket_name}/artifacts/")
    for root, _, files in os.walk(artifacts_dir):
        for file in files:
            local_path = Path(root) / file
            # Create a relative path for the S3 key
            relative_path = local_path.relative_to(artifacts_dir)
            s3_key = f"artifacts/{relative_path.as_posix()}"
            
            try:
                s3.upload_file(str(local_path), bucket_name, s3_key)
                print(f"  Uploaded: {s3_key}")
            except ClientError as e:
                print(f"  Error uploading {s3_key}: {e}")

def download_artifacts_from_s3():
    """Sync the S3 artifacts directory DOWN to the local folder."""
    s3, bucket_name = get_s3_client()
    if not s3 or not bucket_name:
        print("S3 Sync skipped: AWS_S3_BUCKET_NAME not configured.")
        return
        
    artifacts_dir = Path(__file__).parent / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Downloading artifacts from s3://{bucket_name}/artifacts/")
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket_name, Prefix="artifacts/"):
            if "Contents" not in page:
                continue
                
            for obj in page["Contents"]:
                s3_key = obj["Key"]
                if s3_key.endswith('/'):
                    continue # Ignore directory keys
                    
                # Calculate local path by stripping 'artifacts/'
                relative_key = s3_key[len("artifacts/"):]
                local_path = artifacts_dir / relative_key
                
                # Create parent directories
                local_path.parent.mkdir(parents=True, exist_ok=True)
                
                s3.download_file(bucket_name, s3_key, str(local_path))
                print(f"  Downloaded: {s3_key}")
                
    except ClientError as e:
         print(f"  Error downloading from S3: {e}")

def delete_artifacts_from_s3(project_name: str):
    """Delete all artifacts for a specific project from the S3 bucket."""
    s3, bucket_name = get_s3_client()
    if not s3 or not bucket_name:
        print("S3 Deletion skipped: AWS_S3_BUCKET_NAME not configured.")
        return
        
    prefix = f"artifacts/{project_name}/"
    print(f"Deleting artifacts from s3://{bucket_name}/{prefix}")
    
    try:
        paginator = s3.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=bucket_name, Prefix=prefix)
        
        objects_to_delete = []
        for page in pages:
            if "Contents" in page:
                for obj in page["Contents"]:
                    objects_to_delete.append({"Key": obj["Key"]})
                    
        if objects_to_delete:
            # S3 delete_objects can handle up to 1000 keys per request
            for i in range(0, len(objects_to_delete), 1000):
                batch = objects_to_delete[i:i + 1000]
                s3.delete_objects(
                    Bucket=bucket_name,
                    Delete={"Objects": batch}
                )
            print(f"  Deleted {len(objects_to_delete)} objects from S3.")
        else:
            print(f"  No objects found to delete for prefix: {prefix}")
            
    except ClientError as e:
        print(f"  Error deleting from S3: {e}")
