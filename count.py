import os
import sys
import boto3
from collections import defaultdict

# S3 설정
S3_BUCKET = os.environ.get('S3_BUCKET', 'video-mask-viewer-videos')
S3_PREFIX = os.environ.get('S3_PREFIX', 'video')
S3_REGION = os.environ.get('S3_REGION', 'ap-northeast-2')

# mask_source 인자 (기본값: rexomni)
mask_source = sys.argv[1] if len(sys.argv) > 1 else 'rexomni'

# S3 클라이언트 생성
s3_client = boto3.client('s3', region_name=S3_REGION)
paginator = s3_client.get_paginator('list_objects_v2')

# 1. source 폴더에서 비디오 목록 가져오기
total_by_task = defaultdict(int)
source_prefix = f"{S3_PREFIX}/source/"

for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=source_prefix):
    for obj in page.get('Contents', []):
        key = obj['Key']
        filename = key.replace(source_prefix, '')
        if filename.endswith('.mp4') and '/' not in filename:
            name = filename[:-4]
            parts = name.rsplit('_', 1)
            if len(parts) == 2 and parts[1].isdigit():
                total_by_task[parts[0]] += 1

# 2. evaluations/{mask_source}/ 폴더에서 평가 파일 카운트
done_by_task = defaultdict(int)
eval_prefix = f"{S3_PREFIX}/evaluations/{mask_source}/"

for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=eval_prefix):
    for obj in page.get('Contents', []):
        key = obj['Key']
        # 경로: video/evaluations/{mask_source}/{task}/{filename}.csv
        rel_path = key.replace(eval_prefix, '')
        parts = rel_path.split('/')
        if len(parts) == 2 and parts[1].endswith('.csv'):
            task = parts[0]
            done_by_task[task] += 1

# 3. 결과 출력
all_tasks = sorted(set(total_by_task) | set(done_by_task))
total_done = total_all = 0

print(f"\n[S3] s3://{S3_BUCKET}/{S3_PREFIX}/evaluations/{mask_source}/")
print("=" * 40)
print(f"{'Task':<12} {'진행':>10}   {'비율':>6}")
print("-" * 40)
for task in all_tasks:
    done = done_by_task[task]
    total = total_by_task[task]
    if total == 0:
        continue  # 전체가 0인 task는 출력하지 않음
    pct = f"{done/total*100:.1f}%"
    print(f"{task:<12} {done:>4}/{total:<4}   {pct:>6}")
    total_done += done
    total_all += total

print("-" * 40)
pct_all = f"{total_done/total_all*100:.1f}%" if total_all > 0 else "-"
print(f"{'전체':<12} {total_done:>4}/{total_all:<4}   {pct_all:>6}")
print("=" * 40)
