import os
import sys
import boto3
from dotenv import load_dotenv
from pathlib import Path

# 프로젝트 루트 경로 설정 (backend 위 부모 디렉토리)
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')

USE_S3 = os.environ.get('USE_S3', 'false').lower() == 'true'
S3_BUCKET = os.environ.get('S3_BUCKET', '')
S3_REGION = os.environ.get('S3_REGION', 'ap-northeast-2')
S3_PREFIX = os.environ.get('S3_PREFIX', 'video')

EVALUATIONS_DIR = BASE_DIR / 'evaluations'

def sync_existing_evaluations():
    if not USE_S3:
        print("S3가 활성화되어 있지 않습니다 (USE_S3=false).")
        return

    if not EVALUATIONS_DIR.exists():
        print(f"평가 디렉토리가 존재하지 않습니다: {EVALUATIONS_DIR}")
        return

    s3_client = boto3.client(
        's3',
        region_name=S3_REGION,
        aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY')
    )

    print(f"S3 동기화 시작: {EVALUATIONS_DIR} -> s3://{S3_BUCKET}/{S3_PREFIX}/evaluations/")
    
    count = 0
    # 모든 .csv 파일 찾기
    for csv_file in EVALUATIONS_DIR.rglob('*.csv'):
        # 로컬 상대 경로 계산 (예: rexomni/face/evaluation_face_0001.csv)
        rel_path = csv_file.relative_to(EVALUATIONS_DIR)
        s3_key = f"{S3_PREFIX}/evaluations/{rel_path}"
        
        try:
            s3_client.upload_file(str(csv_file), S3_BUCKET, s3_key)
            print(f"  [성공] {rel_path} -> {s3_key}")
            count += 1
        except Exception as e:
            print(f"  [실패] {rel_path}: {e}")

    print(f"\n총 {count}개의 파일이 동기화되었습니다.")

if __name__ == "__main__":
    sync_existing_evaluations()
