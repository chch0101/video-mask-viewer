import os
import subprocess
import boto3
from pathlib import Path
from botocore.exceptions import NoCredentialsError

# AWS S3 Configuration
BUCKET_NAME = 'video-mask-viewer-videos'
S3_PREFIX = 'video/mosaic/ogq/'
REGION_NAME = 'ap-northeast-2'

def convert_to_h264(input_path, output_path):
    """
    Converts video codec to H.264 using FFmpeg.
    """
    # -c:v libx264: Use H.264 codec
    # -preset fast: Balance between speed and compression
    # -crf 23: Standard quality (lower is better, 18-28 is common)
    # -c:a aac: AAC audio codec for compatibility
    # -movflags +faststart: Move metadata to the beginning for faster web playback
    command = [
        'ffmpeg',
        '-y',
        '-i', str(input_path),
        '-c:v', 'libx264',
        '-preset', 'fast',
        '-crf', '23',
        '-c:a', 'aac',
        '-b:a', '128k',
        '-movflags', '+faststart',
        str(output_path)
    ]
    
    print(f"🔄 Converting: {input_path.name}")
    try:
        # Run ffmpeg and capture output only if it fails
        result = subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(f"✅ Converted: {output_path.name}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to convert {input_path.name}:")
        print(e.stderr.decode('utf-8'))
        return False
    except Exception as e:
        print(f"❌ Unexpected error during conversion: {e}")
        return False

def upload_to_s3(file_path, s3_client):
    """
    Uploads a file to S3 with correct content type.
    """
    s3_key = f"{S3_PREFIX}{file_path.name}"
    
    try:
        print(f"☁️ Uploading to S3: {file_path.name}")
        s3_client.upload_file(
            str(file_path), 
            BUCKET_NAME, 
            s3_key, 
            ExtraArgs={'ContentType': 'video/mp4'}
        )
        print(f"🚀 Uploaded: s3://{BUCKET_NAME}/{s3_key}")
        return True
    except NoCredentialsError:
        print("❌ AWS credentials not found. Please run 'aws configure'.")
        return False
    except Exception as e:
        print(f"❌ Failed to upload {file_path.name}: {e}")
        return False

def main():
    base_dir = Path(__file__).parent
    source_dir = base_dir / 'ogq'
    temp_dir = base_dir / 'temp_ogq_converted'
    
    if not source_dir.exists():
        print(f"❌ Error: 'ogq' directory not found in {base_dir}")
        return

    # Create temp directory for converted files
    temp_dir.mkdir(exist_ok=True)
    
    # Initialize S3 client
    try:
        s3_client = boto3.client('s3', region_name=REGION_NAME)
    except Exception as e:
        print(f"❌ Failed to initialize S3 client: {e}")
        return

    # Supported video formats
    video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.webm'}
    
    files_to_process = [f for f in source_dir.iterdir() if f.is_file() and f.suffix.lower() in video_extensions]
    
    if not files_to_process:
        print("ℹ️ No video files found in 'ogq' folder.")
        return

    print(f"📂 Found {len(files_to_process)} video(s) in 'ogq' folder.")

    for file_path in files_to_process:
        # Use the original filename as requested
        output_filename = file_path.name
        output_path = temp_dir / output_filename
        
        # 1. Convert
        if convert_to_h264(file_path, output_path):
            # 2. Upload
            if upload_to_s3(output_path, s3_client):
                print(f"🚮 Cleaning up temporary file: {output_path.name}")
                output_path.unlink()
            else:
                print(f"⚠️ Keeping temporary file due to upload failure: {output_path}")
        
    # Clean up temp folder if empty
    try:
        if not any(temp_dir.iterdir()):
            temp_dir.rmdir()
            print("✨ All temporary files cleaned up.")
    except Exception:
        pass

    print("\n🏁 All tasks completed!")

if __name__ == "__main__":
    main()
