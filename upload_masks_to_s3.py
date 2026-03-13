import os
import glob
import boto3
from botocore.config import Config
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# S3 Configuration
S3_BUCKET = os.environ.get('S3_BUCKET', 'video-mask-viewer-videos')
S3_REGION = os.environ.get('S3_REGION', 'ap-northeast-2')
S3_PREFIX = os.environ.get('S3_PREFIX', 'video')

s3_client = boto3.client(
    's3',
    endpoint_url=f'https://s3.{S3_REGION}.amazonaws.com',
    region_name=S3_REGION,
    aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
    config=Config(signature_version='s3v4')
)

def upload_masks(local_dir, mask_source="yolo11"):
    if not os.path.isdir(local_dir):
        print(f"Directory not found: {local_dir}")
        return

    mp4_files = glob.glob(os.path.join(local_dir, '*.mp4'))
    if not mp4_files:
        print(f"No .mp4 files found in {local_dir}")
        return

    print(f"Found {len(mp4_files)} .mp4 files. Uploading to S3 bucket '{S3_BUCKET}' under prefix '{S3_PREFIX}/masks/{mask_source}/'...")

    success_count = 0
    for file_path in mp4_files:
        filename = os.path.basename(file_path)
        s3_key = f"{S3_PREFIX}/masks/{mask_source}/{filename}"
        
        try:
            print(f"Uploading {filename} -> s3://{S3_BUCKET}/{s3_key}")
            # Upload file with explicit ContentType
            s3_client.upload_file(
                file_path, 
                S3_BUCKET, 
                s3_key,
                ExtraArgs={'ContentType': 'video/mp4'}
            )
            success_count += 1
        except Exception as e:
            print(f"Failed to upload {filename}: {e}")

    print(f"Upload completed. {success_count}/{len(mp4_files)} files uploaded successfully.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Upload mask videos to S3")
    parser.add_argument("directory", help="Local directory containing the .mp4 mask files")
    parser.add_argument("--source", default="yolo11", help="Mask source name (e.g., yolo11), forms the S3 path")
    
    args = parser.parse_args()
    upload_masks(args.directory, args.source)
