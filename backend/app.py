from flask import Flask, jsonify, request, send_from_directory, send_file, redirect
from flask_cors import CORS
import os
import sys
import re
import csv
import json
import subprocess
import webbrowser
import threading
import time
from datetime import datetime
from threading import Semaphore, Thread

# 최대 동시 FFmpeg 변환 작업 수 제한 (OOM 방지: 가장 타이트하게 1개로 제한)
FFMPEG_SEMAPHORE = Semaphore(1)

# 변환 상태 추적 (메모리 딕셔너리)
CONVERSION_STATUS = {}

from dotenv import load_dotenv
from utils.system_helpers import show_dialog, show_progress_notification, ensure_ffmpeg
from utils.video_processing import get_video_codec, get_video_fps, get_video_frame_count, convert_to_h264, sync_mask_to_source
import database

# .env 파일 로드
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

# S3 설정 (선택적)
print("=" * 50)
print("[DEBUG] Environment Variables Check:")
print(f"  USE_S3 raw value: '{os.environ.get('USE_S3', 'NOT_SET')}'")
print(f"  S3_BUCKET: '{os.environ.get('S3_BUCKET', 'NOT_SET')}'")
print(f"  S3_REGION: '{os.environ.get('S3_REGION', 'NOT_SET')}'")
print(f"  S3_PREFIX: '{os.environ.get('S3_PREFIX', 'NOT_SET')}'")
print(f"  AWS_ACCESS_KEY_ID: '{os.environ.get('AWS_ACCESS_KEY_ID', 'NOT_SET')[:10] if os.environ.get('AWS_ACCESS_KEY_ID') else 'NOT_SET'}...'")
print(f"  AWS_SECRET_ACCESS_KEY: '{'SET' if os.environ.get('AWS_SECRET_ACCESS_KEY') else 'NOT_SET'}'")
print("=" * 50)

USE_S3 = os.environ.get('USE_S3', 'false').lower() == 'true'
S3_BUCKET = os.environ.get('S3_BUCKET', '')
S3_REGION = os.environ.get('S3_REGION', 'ap-northeast-2')
S3_PREFIX = os.environ.get('S3_PREFIX', 'video')  # S3 내 비디오 폴더 경로

print(f"[S3] USE_S3 evaluated to: {USE_S3}")

s3_client = None
if USE_S3:
    try:
        import boto3
        from botocore.client import Config
        s3_client = boto3.client(
            's3',
            endpoint_url=f'https://s3.{S3_REGION}.amazonaws.com',
            region_name=S3_REGION,
            aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
            config=Config(
                signature_version='s3v4',
                s3={'addressing_style': 'virtual'}
            )
        )
        print(f"[S3] Connected to bucket: {S3_BUCKET} at {S3_REGION}")
    except Exception as e:
        print(f"[S3] Failed to connect: {e}")
        USE_S3 = False


def upload_to_s3(local_path, s3_key):
    """파일을 S3에 업로드"""
    if not s3_client or not S3_BUCKET:
        return False
    try:
        s3_client.upload_file(local_path, S3_BUCKET, s3_key)
        print(f"[S3] Uploaded: {local_path} -> s3://{S3_BUCKET}/{s3_key}")
        return True
    except Exception as e:
        print(f"[S3] Upload failed: {e}")
        return False


def get_s3_presigned_url(key, expiration=3600):
    """S3 pre-signed URL 생성"""
    if not s3_client or not S3_BUCKET:
        return None
    try:
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET, 'Key': key},
            ExpiresIn=expiration
        )
        # Force regional endpoint to avoid 307 redirect (which breaks CORS)
        url = url.replace(
            f'{S3_BUCKET}.s3.amazonaws.com',
            f'{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com'
        )
        return url
    except Exception as e:
        print(f"[S3] Failed to generate presigned URL: {e}")
        return None

def download_db_from_s3():
    """앱 시작 시 S3에서 evaluations.db 다운로드 (Railway Volume 초기화 대응)"""
    if not USE_S3 or not s3_client or not S3_BUCKET:
        return
    
    s3_key = f"{S3_PREFIX}/evaluations.db"
    local_path = database.DB_PATH
    
    # 로컬에 이미 파일이 있으면 굳이 덮어쓰지 않음 (최신 데이터일 확률이 높음)
    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        print(f"[S3-DB] Local DB already exists at {local_path}. Skipping initial download.")
        return

    try:
        print(f"[S3-DB] Checking for DB at s3://{S3_BUCKET}/{s3_key}...")
        s3_client.download_file(S3_BUCKET, s3_key, local_path)
        print(f"[S3-DB] Initialized DB from S3: {local_path}")
    except Exception as e:
        print(f"[S3-DB] No DB found in S3 or download failed: {e}. Starting fresh.")

def upload_db_to_s3():
    """evaluations.db를 S3로 백업"""
    if not USE_S3 or not s3_client or not S3_BUCKET:
        return
    
    s3_key = f"{S3_PREFIX}/evaluations.db"
    local_path = database.DB_PATH
    
    if not os.path.exists(local_path):
        return

    try:
        s3_client.upload_file(local_path, S3_BUCKET, s3_key)
        print(f"[S3-DB] Backed up DB to s3://{S3_BUCKET}/{s3_key}")
    except Exception as e:
        print(f"[S3-DB] Backup failed: {e}")


def s3_file_exists(key):
    """S3에 파일이 존재하는지 확인"""
    if not s3_client or not S3_BUCKET:
        return False
    try:
        s3_client.head_object(Bucket=S3_BUCKET, Key=key)
        return True
    except:
        return False


def get_base_dir():
    """PyInstaller 번들 또는 개발 환경에서의 기본 경로 결정"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 번들로 실행 중
        # .app/Contents/MacOS/ 안에서 실행되므로
        # .app이 있는 디렉토리 기준으로 video 폴더를 찾음
        app_dir = os.path.dirname(sys.executable)
        # macOS .app 번들: .app/Contents/MacOS/app_executable
        # 3단계 위로 올라가면 .app이 있는 디렉토리
        base = os.path.dirname(os.path.dirname(os.path.dirname(app_dir)))
        return base
    else:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_resource_dir():
    """번들 내부 리소스 경로 (static 파일 등)"""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    else:
        return os.path.dirname(os.path.abspath(__file__))


# Homebrew 경로를 PATH에 추가 (macOS .app 번들에서는 PATH가 제한적)
for brew_bin in ['/opt/homebrew/bin', '/usr/local/bin']:
    if brew_bin not in os.environ.get('PATH', ''):
        os.environ['PATH'] = brew_bin + ':' + os.environ.get('PATH', '')

# 경로 설정 (환경 변수로 오버라이드 가능)
BASE_DIR = get_base_dir()
RESOURCE_DIR = get_resource_dir()
VIDEO_DIR = os.environ.get('VIDEO_DIR', os.path.join(BASE_DIR, 'video'))
EVALUATIONS_DIR = os.environ.get('EVALUATIONS_DIR', os.path.join(BASE_DIR, 'evaluations'))
CACHE_DIR = os.path.abspath(os.path.join(RESOURCE_DIR, 'cache'))
STATIC_DIR = os.path.abspath(os.path.join(RESOURCE_DIR, 'static'))
# 환경 설정
S3_CACHE_FILE = os.path.join(CACHE_DIR, 's3_cache.json')
S3_CACHE_EXPIRY = 3600  # 1 시간

# S3 요청시 다중 사용자 접속에 의한 병목락 (Lag) 방지용 Lock 객체
S3_CACHE_LOCK = threading.Lock()

# Flask 앱 생성 (정적 파일 서빙 설정)
app = Flask(__name__, static_folder=STATIC_DIR, static_url_path='')
CORS(app)

# 폴더 생성
os.makedirs(EVALUATIONS_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

# 질문 라벨 (CSV 저장용)
QUESTION_LABELS = {
    'Q1': '객체가 여러 영역으로 분할되지 않고 단일 마스크로 온전하게 검출되는가?',
    'Q2': '영상 내 식별 가능한 모든 객체에 대해 누락 없이 마스크가 생성되었는가?',
    'Q3': '인식 대상이 아닌 객체에 대해 마스크가 잘못 생성되지 않았는가?',
    'Q4': '생성된 마스크가 실제 객체의 경계선을 따르는가?',
    'Q5': '영상이 재생되는 동안 마스크가 깜빡거리거나 순간적으로 사라지는 현상이 없는가?',
}

CATEGORIES = {
    'Q1': 'No.1 객체 완전성', 'Q2': 'No.1 객체 완전성',
    'Q3': 'No.2 마스크 정확성', 
    'Q4': 'No.3 경계 정밀도', 
    'Q5': 'No.4 시간적 안정성'
}



def get_task_name(video_name):
    """비디오 이름에서 task 이름 추출 (예: face_0001 → face)"""
    parts = video_name.rsplit('_', 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0]
    return video_name


def download_from_s3(s3_key, local_path):
    """S3에서 영상을 로컬로 다운로드 (로컬 캐시)"""
    if not USE_S3 or not s3_client: 
        return False
    try:
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        print(f"[S3 Download] Downloading {s3_key} to {local_path}...")
        s3_client.download_file(S3_BUCKET, s3_key, local_path)
        return os.path.exists(local_path)
    except Exception as e:
        print(f"[S3 Download] Failed to download {s3_key}: {e}")
        return False


def get_s3_cache():
    """S3 버킷 메타데이터(소스/마스크 목록 등)를 로컬에 캐시하여 API 호출 비용 및 병목 방지"""
    if not USE_S3 or not s3_client:
        return {'sources': [], 'videos': [], 's3_files': set()}
    
    # 락을 걸어서 여러 요청이 동시에 S3 paginator를 돌리는 현상을 방지
    with S3_CACHE_LOCK:
        # 1. 락 획득 후 다시 유효기간 체크
        if os.path.exists(S3_CACHE_FILE):
            try:
                with open(S3_CACHE_FILE, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                
                # 유효시간 내의 캐시면 즉시 반환
                if time.time() - cache_data.get('timestamp', 0) < S3_CACHE_EXPIRY:
                    # 마이그레이션 호환성을 위해 s3_files dict key 생성
                    if 's3_files' not in cache_data:
                        cache_data['s3_files'] = []
                    # set 속도는 매우 빠르니 런타임에서 변환해서 사용 (json엔 list로 저장)
                    cache_data['_s3_files_set'] = set(cache_data.get('s3_files', []))
                    return cache_data
            except Exception as e:
                print(f"[S3 Cache] Error reading cache: {e}")
        
        # 2. 캐시 갱신 시작
        print("[S3 Cache] Refreshing S3 metadata cache. This may take a moment for large buckets...")
        cache_data = {
            'timestamp': time.time(),
            'sources': [],
            'videos': [],
            's3_files': []
        }
        
        try:
            paginator = s3_client.get_paginator('list_objects_v2')
            s3_files_set = set()
            
            # source 영상 캐시
            prefix_source = f"{S3_PREFIX}/source/"
            for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix_source):
                for obj in page.get('Contents', []):
                    key = obj['Key']
                    s3_files_set.add(key)
                    if key.endswith('.mp4'):
                        filename = key.replace(prefix_source, '')
                        if '/' not in filename:  # 루트 바로 아래 파일만
                            cache_data['videos'].append(filename)
                            
            # mask sources 및 파일 개수 캐시
            prefix_masks = f"{S3_PREFIX}/masks/"
            source_counts = {}
            for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix_masks):
                for obj in page.get('Contents', []):
                    key = obj['Key']
                    s3_files_set.add(key)
                    if key.endswith('.mp4'):
                        # 패턴: video/masks/source_name/filename.mp4
                        parts = key.replace(prefix_masks, '').split('/')
                        if len(parts) == 2:
                            source_name = parts[0]
                            source_counts[source_name] = source_counts.get(source_name, 0) + 1
                            
            for source_name, count in source_counts.items():
                cache_data['sources'].append({
                    'name': source_name,
                    'count': count
                })
                
            # s3_files를 list로 변환하여 json 직렬화 가능케 함
            cache_data['s3_files'] = list(s3_files_set)
            
            # 파일로 저장
            with open(S3_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f)
                
            # 런타임 전용 set
            cache_data['_s3_files_set'] = s3_files_set
            
            print("[S3 Cache] Cache refreshed successfully!")
        except Exception as e:
            print(f"[S3 Cache] Failed to refresh cache: {e}")
            
    return cache_data


# ===== React 정적 파일 서빙 =====
@app.route('/')
def serve_index():
    """React 앱의 index.html 서빙"""
    return send_from_directory(STATIC_DIR, 'index.html')


@app.errorhandler(404)
def not_found(e):
    """SPA 라우팅: 알 수 없는 경로는 index.html로"""
    # API나 비디오 경로가 아닌 경우에만 index.html 반환
    if not request.path.startswith('/api/') and not request.path.startswith('/video/'):
        return send_from_directory(STATIC_DIR, 'index.html')
    return jsonify({'error': 'Not found'}), 404


@app.route('/api/mask-sources', methods=['GET'])
def get_mask_sources():
    """masks 폴더 내 하위 폴더 목록 조회 (S3 폴백 지원)"""
    masks_dir = os.path.join(VIDEO_DIR, 'masks')
    sources = []
    local_source_names = set()

    # 로컬 폴더 확인
    if os.path.exists(masks_dir):
        for name in sorted(os.listdir(masks_dir)):
            folder_path = os.path.join(masks_dir, name)
            if os.path.isdir(folder_path) and not name.startswith('.'):
                # 폴더 내 mp4 파일 개수 확인
                mp4_count = len([f for f in os.listdir(folder_path) if f.endswith('.mp4')])
                sources.append({
                    'name': name,
                    'count': mp4_count
                })
                local_source_names.add(name)

    # S3 폴백: 로컬에 없는 mask source 추가 (캐시 사용)
    if USE_S3 and s3_client:
        s3_cache = get_s3_cache()
        for s3_source in s3_cache.get('sources', []):
            if s3_source['name'] not in local_source_names:
                sources.append({
                    'name': s3_source['name'],
                    'count': s3_source['count'],
                    's3': True
                })

    return jsonify({'sources': sources})


@app.route('/api/videos', methods=['GET'])
def get_videos():
    """비디오 목록 조회 (video/source 폴더 스캔, S3 폴백 지원)"""
    source_dir = os.path.join(VIDEO_DIR, 'source')
    mask_dir = os.path.join(VIDEO_DIR, 'mask')
    mask_source = request.args.get('mask_source', '')
    local_video_names = set()

    # 평가 완료된 비디오 이름 수집 (mask_source에 해당하는 것만)
    evaluated_names = set()
    if os.path.exists(EVALUATIONS_DIR):
        # mask_source가 지정되면 해당 폴더만, 아니면 루트의 평가만 검색
        if mask_source:
            search_dir = os.path.join(EVALUATIONS_DIR, mask_source)
        else:
            search_dir = EVALUATIONS_DIR

        if os.path.exists(search_dir):
            for root, dirs, files in os.walk(search_dir):
                # mask_source가 없을 때는 루트 바로 아래의 task 폴더만 검색 (다른 mask_source 폴더 제외)
                if not mask_source:
                    rel_path = os.path.relpath(root, EVALUATIONS_DIR)
                    # 루트 또는 루트 바로 아래의 task 폴더만 (mask_source 폴더 제외)
                    if rel_path != '.' and os.sep in rel_path:
                        continue
                    # mask_source 폴더인지 확인 (해당 폴더 내에 서브폴더가 있으면 mask_source)
                    if rel_path != '.':
                        subpath = os.path.join(EVALUATIONS_DIR, rel_path)
                        subdirs = [d for d in os.listdir(subpath) if os.path.isdir(os.path.join(subpath, d))]
                        if subdirs:  # 서브폴더가 있으면 mask_source 폴더이므로 스킵
                            continue

                for eval_file in files:
                    if eval_file.endswith('.csv'):
                        filepath = os.path.join(root, eval_file)
                        try:
                            with open(filepath, 'r', encoding='utf-8-sig') as f:
                                reader = csv.reader(f)
                                header = next(reader, None)
                                row = next(reader, None)
                                if row and len(row) > 0:
                                    evaluated_names.add(row[0])
                        except Exception:
                            pass

    # 각 비디오에 대해 어떤 mask source들에 마스크가 있는지 확인하기 위한 준비
    masks_dir = os.path.join(VIDEO_DIR, 'masks')
    local_mask_sources = []
    if os.path.exists(masks_dir):
        local_mask_sources = [d for d in os.listdir(masks_dir)
                              if os.path.isdir(os.path.join(masks_dir, d)) and not d.startswith('.')]

    # S3 캐시에서 마스크 정보 가져오기
    s3_cache = get_s3_cache() if USE_S3 and s3_client else {}
    s3_files_set = s3_cache.get('_s3_files_set', set())

    def get_available_masks(video_name):
        """비디오에 대해 사용 가능한 mask source 목록 반환"""
        available = []
        filename = f"{video_name}.mp4"

        # 로컬 masks 폴더 확인
        for source_name in local_mask_sources:
            mask_path = os.path.join(masks_dir, source_name, filename)
            if os.path.exists(mask_path):
                available.append(source_name)

        # S3에서 추가 확인 (로컬에 없는 것만)
        if USE_S3 and s3_files_set:
            for s3_source in s3_cache.get('sources', []):
                source_name = s3_source['name']
                if source_name not in available:
                    s3_key = f"{S3_PREFIX}/masks/{source_name}/{filename}"
                    if s3_key in s3_files_set:
                        available.append(source_name)

        return sorted(available)

    videos = []

    if os.path.exists(source_dir):
        for filename in sorted(os.listdir(source_dir)):
            if filename.endswith('.mp4'):
                name = filename.replace('.mp4', '')
                local_video_names.add(name)

                # 마스크 파일 (소스와 동일한 이름)
                mask_file = filename

                videos.append({
                    'name': name,
                    'source': filename,
                    'mask': mask_file,
                    'evaluated': name in evaluated_names,
                    'availableMasks': get_available_masks(name)
                })

    # S3 폴백: 로컬에 없는 비디오 추가 (캐시 사용)
    if USE_S3 and s3_client:
        for filename in s3_cache.get('videos', []):
            name = filename.replace('.mp4', '')
            if name not in local_video_names:
                videos.append({
                    'name': name,
                    'source': filename,
                    'mask': filename,
                    'evaluated': name in evaluated_names,
                    's3': True,
                    'availableMasks': get_available_masks(name)
                })
        # S3 비디오 포함 후 다시 정렬
        videos.sort(key=lambda x: x['name'])

    return jsonify({'videos': videos})


@app.route('/api/prepare-video/<name>', methods=['POST'])
def prepare_video(name):
    """비디오 시청 전 필요한 변환을 백그라운드로 시작 (Source & Mask) 및 상태 반환. 
    시간 초과(499) 방지를 위한 비동기 방식으로 수정됨."""
    # Ensure name does not already have .mp4 appended from frontend
    name = name.replace('.mp4', '')
    data = request.json
    mask_source = data.get('mask_source', '')
    
    # 1. 상태 즉시 확인 및 폴더 경로 결정
    task = get_task_name(name)
    source_path = os.path.join(VIDEO_DIR, 'source', f'{name}.mp4')
    if mask_source:
        mask_path = os.path.join(VIDEO_DIR, 'masks', mask_source, f'{name}.mp4')
    else:
        mask_path = os.path.join(VIDEO_DIR, 'mask', f'{name}.mp4')

    status_key = f"{mask_source}_{name}"

    if not os.path.exists(source_path):
        # 잦은 s3_file_exists()의 오버헤드 대신 cache 메모리 해시맵으로 체크
        if USE_S3:
            s3_key = f"{S3_PREFIX}/source/{name}.mp4"
            cache = get_s3_cache()
            if '_s3_files_set' in cache and s3_key in cache['_s3_files_set']:
                return jsonify({'success': True, 'converted': [], 'message': 'S3 video exists'})
            elif s3_file_exists(s3_key): # Fallback just in case cache wasn't updated
                return jsonify({'success': True, 'converted': [], 'message': 'S3 video exists'})
        return jsonify({'error': 'Video not found'}), 404

    # 2. 이미 백그라운드에서 진행 중인지 확인
    if status_key in CONVERSION_STATUS and CONVERSION_STATUS[status_key]['status'] == 'processing':
        return jsonify({'success': True, 'status': 'processing', 'message': 'Conversion already in progress'})

    # 3. 변환 필요 여부 신속 체크
    needs_source_conv = False
    needs_mask_conv = False
    
    source_fps = get_video_fps(source_path)
    if abs(source_fps - TARGET_FPS) > 0.5:
        cached_source = os.path.join(CACHE_DIR, f"{name}_src30.mp4")
        if not os.path.exists(cached_source):
            needs_source_conv = True

    if os.path.exists(mask_path):
        codec = get_video_codec(mask_path)
        mask_fps = get_video_fps(mask_path)
        if codec != 'h264' or abs(mask_fps - TARGET_FPS) > 0.5:
            cached_mask = os.path.join(CACHE_DIR, f"{name}_mask30.mp4")
            if not os.path.exists(cached_mask):
                needs_mask_conv = True

    # 아무것도 변환할 게 없으면 바로 완료
    if not needs_source_conv and not needs_mask_conv:
        return jsonify({'success': True, 'status': 'completed', 'converted': []})

    # 4. 백그라운드 스레드 시작 및 즉시 응답 반환
    CONVERSION_STATUS[status_key] = {'status': 'processing', 'error': None}

    def convert_worker():
        converted = []
        try:
            if needs_source_conv:
                cached_source = os.path.join(CACHE_DIR, f"{name}_src30.mp4")
                print(f"[백그라운드] Source {name} 변환 큐 진입...")
                with FFMPEG_SEMAPHORE:
                    subprocess.run(
                        ['ffmpeg', '-y', '-i', source_path,
                         '-threads', '2',
                         '-r', str(TARGET_FPS),
                         '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18',
                         '-c:a', 'copy', cached_source],
                        capture_output=True, check=True
                    )
                converted.append('source')
            
            if needs_mask_conv:
                cached_mask = os.path.join(CACHE_DIR, f"{name}_mask30.mp4")
                print(f"[백그라운드] Mask {name} 변환 큐 진입...")
                with FFMPEG_SEMAPHORE:
                    subprocess.run(
                        ['ffmpeg', '-y', '-i', mask_path,
                         '-threads', '2',
                         '-r', str(TARGET_FPS),
                         '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18',
                         '-c:a', 'copy', cached_mask],
                        capture_output=True, check=True
                    )
                converted.append('mask')
            
            CONVERSION_STATUS[status_key] = {'status': 'completed', 'error': None, 'converted': converted}
            print(f"[백그라운드] {name} 작업 완료!")
        except Exception as e:
            print(f"[백그라운드] 변환 실패: {e}")
            CONVERSION_STATUS[status_key] = {'status': 'failed', 'error': str(e)}

    # 백그라운드로 분리
    Thread(target=convert_worker, daemon=True).start()

    return jsonify({'success': True, 'status': 'processing', 'message': 'Conversion started'})


@app.route('/api/conversion-status/<name>', methods=['GET'])
def get_conversion_status(name):
    """현재 변환 진행 상태 조회 (폴링 엔드포인트)"""
    name = name.replace('.mp4', '')
    mask_source = request.args.get('mask_source', '')
    status_key = f"{mask_source}_{name}"
    
    if status_key not in CONVERSION_STATUS:
        return jsonify({'status': 'unknown'})
        
    return jsonify(CONVERSION_STATUS[status_key])


@app.route('/api/video-meta/<name>', methods=['GET'])
def get_video_meta(name):
    """비디오 메타데이터 (소스, 마스크 각각의 FPS 서빙 기준) 조회"""
    name = name.replace('.mp4', '')
    source_path = os.path.join(VIDEO_DIR, 'source', f'{name}.mp4')
    mask_path = os.path.join(VIDEO_DIR, 'mask', f'{name}.mp4')

    if not os.path.exists(source_path):
        if USE_S3:
            s3_key = f"{S3_PREFIX}/source/{name}.mp4"
            cache = get_s3_cache()
            # 캐시에 S3 파일이 존재하면 True를 반환
            s3_exists = ('_s3_files_set' in cache and s3_key in cache['_s3_files_set']) or s3_file_exists(s3_key)
            if s3_exists:
                # S3 영상일 경우 접근 비용을 줄이기 위해 브라우저에서 읽은 실제 duration에 의존
                # 백엔드는 억지로 TARGET_FPS로 교정하지 않고 30fps 원본이라도 프론트가 알아서 처리하게 null 응답을 권장
                # 호환성을 위해 우선 raw 값을 내보냄 (프론트엔드도 durationRatio 처리로 알아서 맞춤)
                return jsonify({
                    'fps': TARGET_FPS,
                    'rawFps': TARGET_FPS,
                    'sourceFps': TARGET_FPS,
                    'maskFps': TARGET_FPS,
                    'is_s3': True
                })
        return jsonify({'error': 'Video not found'}), 404

    source_fps_raw = get_video_fps(source_path)
    source_frames = get_video_frame_count(source_path)

    # 실제로 서빙될 파일의 FPS 확인
    cached_source_path = os.path.join(CACHE_DIR, f"{name}_src30.mp4")
    if abs(source_fps_raw - TARGET_FPS) > 0.5 and os.path.exists(cached_source_path):
        served_source_fps = TARGET_FPS
        source_frames = get_video_frame_count(cached_source_path)
    else:
        served_source_fps = source_fps_raw

    served_mask_fps = TARGET_FPS  # 기본값
    mask_fps_raw = source_fps_raw # 마스크 없을 때 대비
    mask_frames = source_frames   # 마스크 없을 때 대비
    
    if os.path.exists(mask_path):
        mask_fps_raw = get_video_fps(mask_path)
        mask_frames = get_video_frame_count(mask_path)
        cached_mask_path = os.path.join(CACHE_DIR, f"{name}_mask30.mp4")
        if abs(mask_fps_raw - TARGET_FPS) > 0.5 and os.path.exists(cached_mask_path):
            served_mask_fps = TARGET_FPS
            mask_frames = get_video_frame_count(cached_mask_path)
        else:
            served_mask_fps = mask_fps_raw

    return jsonify({
        'fps': source_fps_raw,           # 원본 프레임 번호 기준 (CSV 매칭용)
        'rawFps': source_fps_raw,
        'sourceFps': served_source_fps,  # 실제 브라우저 재생 FPS
        'maskFps': served_mask_fps,      # 실제 브라우저 재생 FPS
        'totalFrames': source_frames,    # 전체 프레임 수
        'maskFrames': mask_frames        # 마스크 전체 프레임 수 (동기화 확인용)
    })

@app.route('/api/auth/google', methods=['POST'])
def auth_google():
    """Google OAuth2 Token Verify (Supports Access Token and ID Token)"""
    data = request.json
    credential = data.get('credential')
    if not credential:
        return jsonify({'error': 'Missing credential'}), 400
    
    import urllib.request
    import json
    try:
        # try tokeninfo for ID Token or Access Token verification
        # id_token or access_token can be verified via this endpoint
        verify_url = f'https://oauth2.googleapis.com/tokeninfo?id_token={credential}'
        
        try:
            req = urllib.request.Request(verify_url)
            with urllib.request.urlopen(req) as response:
                user_info = json.loads(response.read().decode())
        except Exception:
            # Fallback to access_token verification if id_token failed
            verify_url = f'https://oauth2.googleapis.com/tokeninfo?access_token={credential}'
            req = urllib.request.Request(verify_url)
            with urllib.request.urlopen(req) as response:
                user_info = json.loads(response.read().decode())

        # If still no user_info, try userinfo endpoint (legacy)
        if not user_info.get('sub') and not user_info.get('user_id'):
            req = urllib.request.Request(
                'https://www.googleapis.com/oauth2/v3/userinfo',
                headers={'Authorization': f'Bearer {credential}'}
            )
            with urllib.request.urlopen(req) as response:
                user_info = json.loads(response.read().decode())
        
        user_id = user_info.get('sub') or user_info.get('user_id')
        email = user_info.get('email')
        name = user_info.get('name') or email.split('@')[0] if email else "User"
        picture = user_info.get('picture')
        
        if not user_id:
            return jsonify({'error': 'Invalid token: No user ID found'}), 400

        import database
        database.upsert_user(user_id, email, name, picture)
        count = database.get_user_evaluation_count(user_id)
        
        return jsonify({
            'success': True,
            'user': {
                'id': user_id,
                'email': email,
                'name': name,
                'picture': picture,
                'saved_count': count
            }
        })
    except Exception as e:
        print(f"Error handling Google Login: {e}")
        return jsonify({'error': str(e)}), 400


@app.route('/api/evaluations', methods=['POST'])
def save_evaluation():
    """평가 결과 CSV로 저장 (mask_source/task별 서브디렉토리)"""
    data = request.json
    video_name = data.get('video_name')
    evaluations = data.get('evaluations', {})
    mask_source = data.get('mask_source', '')

    if not video_name or not evaluations:
        return jsonify({'error': 'Missing data'}), 400

    # mask_source/task별 서브디렉토리 생성
    task_name = get_task_name(video_name)
    if mask_source:
        task_dir = os.path.join(EVALUATIONS_DIR, mask_source, task_name)
    else:
        task_dir = os.path.join(EVALUATIONS_DIR, task_name)
    os.makedirs(task_dir, exist_ok=True)

    filename = f"evaluation_{video_name}.csv"
    filepath = os.path.join(task_dir, filename)

    # CSV 작성
    with open(filepath, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(['Video', 'ID', 'Category', 'Question', 'Result', 'Frame'])

        for q_id in sorted(evaluations.keys()):
            eval_data = evaluations[q_id]
            result = eval_data.get('result')

            # 프레임 범위 정보 처리 (여러 범위를 쉼표로 구분)
            frame_ranges = eval_data.get('frameRanges', [])
            if frame_ranges:
                range_strs = []
                for fr in frame_ranges:
                    start = fr.get('start')
                    end = fr.get('end')
                    if start is not None and end is not None:
                        range_strs.append(f'{start}~{end}')
                    elif start is not None:
                        range_strs.append(f'{start}~')
                    elif end is not None:
                        range_strs.append(f'~{end}')
                frame_str = ', '.join(range_strs)
            else:
                frame_str = ''

            writer.writerow([
                video_name,
                q_id,
                CATEGORIES.get(q_id, ''),
                QUESTION_LABELS.get(q_id, ""),
                result if result else 'N/A',
                frame_str
            ])

    # S3 업로드 (선택사항)
    if USE_S3:
        s3_filename = f"evaluations/{mask_source}/{task_name}/{filename}" if mask_source else f"evaluations/{task_name}/{filename}"
        s3_key = f"{S3_PREFIX}/{s3_filename}"
        upload_to_s3(filepath, s3_key)

    # SQLite DB에 로그 기록
    user_info = data.get('user')
    if user_info and user_info.get('id'):
        database.log_evaluation(user_info['id'], video_name, mask_source, filename)
        # DB 저장 후 즉시 S3 백업 (기기/세션 간 공유 및 안전한 보관)
        upload_db_to_s3()

    return jsonify({
        'success': True,
        'filename': filename,
        'task': task_name,
        'mask_source': mask_source,
        'path': filepath
    })


@app.route('/api/evaluations/sync-s3', methods=['POST'])
def sync_evaluations_to_s3():
    """로컬에 저장된 모든 평가 CSV 파일을 S3로 동기화"""
    if not USE_S3:
        return jsonify({'error': 'S3 is not enabled'}), 400
    
    sync_count = 0
    errors = []
    
    def sync_thread():
        nonlocal sync_count
        try:
            for root, dirs, files in os.walk(EVALUATIONS_DIR):
                for file in files:
                    if file.endswith('.csv'):
                        filepath = os.path.join(root, file)
                        rel_path = os.path.relpath(filepath, EVALUATIONS_DIR)
                        s3_key = f"{S3_PREFIX}/evaluations/{rel_path}"
                        if upload_to_s3(filepath, s3_key):
                            sync_count += 1
            print(f"[S3] Manual sync completed: {sync_count} files")
        except Exception as e:
            print(f"[S3] Manual sync failed: {e}")

    # 백그라운드에서 동기화 시작
    thread = threading.Thread(target=sync_thread)
    thread.start()
    
    return jsonify({
        'success': True,
        'message': 'Sync started in background'
    })


@app.route('/api/evaluations', methods=['GET'])
def list_evaluations():
    """저장된 평가 목록 조회 (mask_source 파라미터로 필터링)"""
    mask_source = request.args.get('mask_source', '')
    files = []

    if os.path.exists(EVALUATIONS_DIR):
        # mask_source가 지정되면 해당 폴더만 검색
        if mask_source:
            search_dir = os.path.join(EVALUATIONS_DIR, mask_source)
        else:
            search_dir = EVALUATIONS_DIR

        if os.path.exists(search_dir):
            for root, dirs, filenames in os.walk(search_dir):
                # mask_source가 없을 때는 다른 mask_source 폴더의 평가 제외
                if not mask_source:
                    rel_path = os.path.relpath(root, EVALUATIONS_DIR)
                    # 루트 또는 루트 바로 아래의 task 폴더만
                    if rel_path != '.' and os.sep in rel_path:
                        continue
                    # mask_source 폴더인지 확인
                    if rel_path != '.':
                        subpath = os.path.join(EVALUATIONS_DIR, rel_path)
                        subdirs = [d for d in os.listdir(subpath) if os.path.isdir(os.path.join(subpath, d))]
                        if subdirs:
                            continue

                for filename in filenames:
                    if filename.endswith('.csv'):
                        filepath = os.path.join(root, filename)
                        # task 서브디렉토리명 추출
                        rel_path = os.path.relpath(filepath, EVALUATIONS_DIR)
                        files.append({
                            'filename': rel_path,
                            'created': datetime.fromtimestamp(os.path.getctime(filepath)).isoformat()
                        })

        files.sort(key=lambda x: x['created'], reverse=True)

    return jsonify({'evaluations': files})


@app.route('/api/evaluations/<path:filename>', methods=['GET'])
def get_evaluation(filename):
    """특정 평가 파일 내용 조회 (서브디렉토리 경로 지원)"""
    filepath = os.path.join(EVALUATIONS_DIR, filename)

    if not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 404

    results = []
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        header = next(reader, None)  # 헤더 스킵
        for row in reader:
            if len(row) >= 5:
                # 프레임 범위 파싱 (여러 범위를 쉼표로 구분)
                frame_str = row[5] if len(row) >= 6 else ''
                frame_ranges = []

                if frame_str:
                    # "103~105, 203~214" 형식 파싱
                    range_parts = frame_str.split(',')
                    for part in range_parts:
                        part = part.strip()
                        if '~' in part:
                            sides = part.split('~')
                            start = int(sides[0]) if sides[0] else None
                            end = int(sides[1]) if sides[1] else None
                            if start is not None or end is not None:
                                frame_ranges.append({'start': start, 'end': end})
                        elif part:
                            # 단일 프레임 (시작=끝)
                            frame_num = int(part)
                            frame_ranges.append({'start': frame_num, 'end': frame_num})

                results.append({
                    'id': row[1],
                    'category': row[2],
                    'question': row[3],
                    'result': row[4],
                    'frame': frame_str,
                    'frameRanges': frame_ranges
                })

    return jsonify({'results': results})




@app.route('/video/source/<path:filename>')
def serve_source_video(filename):
    """소스 비디오 서빙 (30fps 아니면 자동 변환, S3 폴백 지원)"""
    source_dir = os.path.join(VIDEO_DIR, 'source')
    source_path = os.path.join(source_dir, filename)

    if not os.path.exists(source_path):
        # S3: pre-signed URL로 즉시 redirect (다운로드 없이)
        if USE_S3:
            s3_key = f"{S3_PREFIX}/source/{filename}"
            url = get_s3_presigned_url(s3_key)
            if url:
                print(f"[S3 Redirect] source/{filename}")
                return redirect(url)
        return jsonify({'error': 'File not found'}), 404

    fps = get_video_fps(source_path)
    if abs(fps - TARGET_FPS) > 0.5:
        cached_filename = f"{os.path.splitext(filename)[0]}_src30.mp4"
        cached_path = os.path.join(CACHE_DIR, cached_filename)
        converting_marker = cached_path + '.converting'

        # 이미 변환 완료된 파일이 있으면 바로 반환
        if os.path.exists(cached_path):
            return send_file(cached_path, mimetype='video/mp4')

        # 다른 요청이 변환 중이면 원본 반환 (변환 완료 후 재시도 예상)
        if os.path.exists(converting_marker):
            print(f"[FPS] Source {filename}: 다른 요청이 변환 중, 원본 반환")
            return send_from_directory(source_dir, filename)

        # 변환 시작
        print(f"[FPS] Source {filename}: {fps}fps → {TARGET_FPS}fps 변환 중...")
        try:
            # 변환 중 마커 파일 생성
            with open(converting_marker, 'w') as f:
                f.write('converting')

            subprocess.run(
                ['ffmpeg', '-y', '-i', source_path,
                 '-r', str(TARGET_FPS),
                 '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
                 '-c:a', 'copy', cached_path],
                capture_output=True, check=True
            )
            print(f"[FPS] Source {filename} 변환 완료")

            # 변환 완료 후 마커 파일 삭제
            if os.path.exists(converting_marker):
                os.remove(converting_marker)

            return send_file(cached_path, mimetype='video/mp4')
        except Exception as e:
            print(f"[FPS] Source 변환 실패: {e}")
            # 실패 시 마커 파일 삭제
            if os.path.exists(converting_marker):
                os.remove(converting_marker)
            return send_from_directory(source_dir, filename)

    return send_from_directory(source_dir, filename)


@app.route('/video/mask/<path:filename>')
def serve_mask_video(filename):
    """전체 mask 폴더 비디오 서빙 (호환성 유지용)"""
    mask_dir = os.path.join(VIDEO_DIR, 'mask')
    original_path = os.path.join(mask_dir, filename)

    if not os.path.exists(original_path):
        # S3: pre-signed URL로 즉시 redirect (다운로드 없이)
        if USE_S3:
            s3_key = f"{S3_PREFIX}/mask/{filename}"
            cache = get_s3_cache()
            s3_exists = ('_s3_files_set' in cache and s3_key in cache['_s3_files_set']) or s3_file_exists(s3_key)
            if s3_exists:
                url = get_s3_presigned_url(s3_key)
                if url:
                    print(f"[S3 Redirect] mask/{filename}")
                    return redirect(url)
        return jsonify({'error': 'File not found'}), 404

    # 로컬 파일: 코덱/FPS 변환 처리
    codec = get_video_codec(original_path)
    fps = get_video_fps(original_path)
    needs_codec = codec != 'h264'
    needs_fps = abs(fps - TARGET_FPS) > 0.5

    if not needs_codec and not needs_fps:
        return send_from_directory(mask_dir, filename)

    # 코덱 또는 FPS 변환 필요
    cached_filename = f"{os.path.splitext(filename)[0]}_mask30.mp4"
    cached_path = os.path.join(CACHE_DIR, cached_filename)
    converting_marker = cached_path + '.converting'

    # 이미 변환 완료된 파일이 있으면 바로 반환
    if os.path.exists(cached_path):
        return send_file(cached_path, mimetype='video/mp4')

    # 다른 요청이 변환 중이면 원본 반환
    if os.path.exists(converting_marker):
        print(f"[변환] Mask {filename}: 다른 요청이 변환 중, 원본 반환")
        return send_from_directory(mask_dir, filename)

    # 변환 시작
    reasons = []
    if needs_codec: reasons.append(f'코덱({codec}→h264)')
    if needs_fps: reasons.append(f'FPS동기화({fps}→{TARGET_FPS})')
    print(f"[변환] Mask {filename}: {', '.join(reasons)} 변환 중...")
    try:
        # 변환 중 마커 파일 생성
        with open(converting_marker, 'w') as f:
            f.write('converting')

        # source 경로 추론 (동일한 파일명 사용)
        source_dir = os.path.join(VIDEO_DIR, 'source')
        source_path = os.path.join(source_dir, filename)

        if needs_fps and os.path.exists(source_path):
            print(f"[변환] Mask {filename}: 인덱스 기반 원본 동기화 수행")
            success = sync_mask_to_source(source_path, original_path, cached_path, TARGET_FPS)
            if not success:
                raise Exception("동기화 실패")
        else:
            print(f"[변환] Mask {filename}: 일반 ffmpeg 변환 수행")
            with FFMPEG_SEMAPHORE:
                subprocess.run(
                    ['ffmpeg', '-y', '-i', original_path,
                     '-threads', '1',
                     '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
                     '-c:a', 'copy', cached_path],
                    capture_output=True, check=True
                )

        print(f"[변환] Mask {filename} 변환 완료")

        # 변환 완료 후 마커 파일 삭제
        if os.path.exists(converting_marker):
            os.remove(converting_marker)

        return send_file(cached_path, mimetype='video/mp4')
    except Exception as e:
        print(f"[변환] Mask 변환 실패: {e}")
        # 실패 시 마커 파일 삭제
        if os.path.exists(converting_marker):
            os.remove(converting_marker)
        return send_from_directory(mask_dir, filename)


@app.route('/api/mosaic-check/<name>', methods=['GET'])
def check_mosaic(name):
    """모자이크 비디오 존재 여부 확인 (mask_source 파라미터 지원, S3 폴백)

    S3 경로 구조: video/mosaic/{mask_source}/{filename}.mp4 (사전 생성된 파일)
    """
    task = get_task_name(name)
    mask_source = request.args.get('mask_source', '')

    if mask_source:
        # 새로운 단순화된 경로: video/mosaic/{mask_source}/{filename}.mp4
        mosaic_path = os.path.join(VIDEO_DIR, 'mosaic', mask_source, f'{name}.mp4')
        video_path = f'/video/mosaic/{mask_source}/{name}.mp4'
        s3_key = f"{S3_PREFIX}/mosaic/{mask_source}/{name}.mp4"
    else:
        mosaic_path = os.path.join(VIDEO_DIR, 'mosaic', f'{name}.mp4')
        video_path = f'/video/mosaic/{name}.mp4'
        s3_key = f"{S3_PREFIX}/mosaic/{name}.mp4"

    # 로컬 또는 S3에 존재하는지 확인 (파일 크기도 확인 - 손상된 파일 제외)
    exists = False
    if os.path.exists(mosaic_path):
        file_size = os.path.getsize(mosaic_path)
        exists = file_size > 1000  # 1KB 이상이어야 유효한 파일로 간주
        if not exists:
            print(f"[Mosaic Check] Invalid file (size={file_size}): {mosaic_path}")
    if not exists and USE_S3:
        exists = s3_file_exists(s3_key)

    return jsonify({
        'exists': exists,
        'task': task,
        'mask_source': mask_source,
        'path': video_path
    })


@app.route('/api/mosaic-generate', methods=['POST'])
def generate_mosaic():
    """모자이크 비디오 생성 (mosaic.py 호출, mask_source 파라미터 지원)"""
    data = request.json
    video_name = data.get('video_name')
    mask_source = data.get('mask_source', '')

    if not video_name:
        return jsonify({'error': 'Missing video_name'}), 400

    task = get_task_name(video_name)
    match = re.match(r'.+_(\d+)$', video_name)
    if not match:
        return jsonify({'error': 'Invalid video name format'}), 400
    number = match.group(1)

    # 경로 설정: 새 구조 video/mosaic/{mask_source}/{filename}.mp4
    if mask_source:
        mosaic_path = os.path.join(VIDEO_DIR, 'mosaic', mask_source, f'{video_name}.mp4')
        video_path = f'/video/mosaic/{mask_source}/{video_name}.mp4'
        mask_path = os.path.join(VIDEO_DIR, 'masks', mask_source, f'{video_name}.mp4')
    else:
        mosaic_path = os.path.join(VIDEO_DIR, 'mosaic', f'{video_name}.mp4')
        video_path = f'/video/mosaic/{video_name}.mp4'
        mask_path = os.path.join(VIDEO_DIR, 'mask', f'{video_name}.mp4')

    # 이미 존재하는지 확인
    if os.path.exists(mosaic_path):
        return jsonify({
            'success': True,
            'message': 'Mosaic already exists',
            'path': video_path
        })

    # source와 mask 파일 존재 확인
    source_path = os.path.join(VIDEO_DIR, 'source', f'{video_name}.mp4')

    source_exists = os.path.exists(source_path)
    mask_exists = os.path.exists(mask_path)
    source_url = None
    mask_url = None

    if not source_exists and USE_S3:
        cache = get_s3_cache()
        s3_source_key = f"{S3_PREFIX}/source/{video_name}.mp4"
        if ('_s3_files_set' in cache and s3_source_key in cache['_s3_files_set']) or s3_file_exists(s3_source_key):
            source_exists = True
            source_url = get_s3_presigned_url(s3_source_key)

    if not mask_exists and USE_S3:
        cache = get_s3_cache()
        s3_mask_key = f"{S3_PREFIX}/masks/{mask_source}/{video_name}.mp4" if mask_source else f"{S3_PREFIX}/mask/{video_name}.mp4"
        if ('_s3_files_set' in cache and s3_mask_key in cache['_s3_files_set']) or s3_file_exists(s3_mask_key):
            mask_exists = True
            mask_url = get_s3_presigned_url(s3_mask_key)

    if not source_exists:
        return jsonify({'error': f'Source video not found: {video_name}.mp4'}), 404
    if not mask_exists:
        return jsonify({'error': f'Mask video not found: {video_name}.mp4 (source: {mask_source or "default"})'}), 404

    # mosaic.py 실행 (루루트 venv의 Python 사용 - cv2가 설치된 환경)
    mosaic_script = os.path.join(BASE_DIR, 'mosaic.py')
    mosaic_python = os.path.join(BASE_DIR, 'venv', 'bin', 'python')
    if not os.path.exists(mosaic_python):
        mosaic_python = sys.executable

    def generate_worker():
        try:
            cmd = [mosaic_python, mosaic_script, '--task', task, '--number', number]
            if mask_source:
                cmd.extend(['--mask-source', mask_source])
            if source_url:
                cmd.extend(['--source-url', source_url])
            if mask_url:
                cmd.extend(['--mask-url', mask_url])

            # PYTHONPATH 설정하여 utils 모듈을 찾을 수 있게 함
            env = os.environ.copy()
            env['PYTHONPATH'] = BASE_DIR + (':' + env.get('PYTHONPATH', '') if env.get('PYTHONPATH') else '')

            with FFMPEG_SEMAPHORE:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env)
            
            if result.returncode != 0:
                print(f"[백그라운드] Mosaic generation error: {result.stderr}")
                CONVERSION_STATUS[status_key] = {'status': 'failed', 'error': result.stderr[:200]}
            else:
                print(f"[백그라운드] Mosaic generated: {result.stdout}")
                CONVERSION_STATUS[status_key] = {'status': 'completed', 'path': video_path}
        except subprocess.TimeoutExpired:
            CONVERSION_STATUS[status_key] = {'status': 'failed', 'error': 'Generation timed out (5min)'}
        except Exception as e:
            CONVERSION_STATUS[status_key] = {'status': 'failed', 'error': str(e)}

    # 백그라운드 작업 시작
    status_key = f"mosaic_{mask_source}_{video_name}"
    
    if status_key in CONVERSION_STATUS and CONVERSION_STATUS[status_key]['status'] == 'processing':
        return jsonify({'success': True, 'status': 'processing', 'message': 'Mosaic generation in progress'})
        
    CONVERSION_STATUS[status_key] = {'status': 'processing'}
    Thread(target=generate_worker, daemon=True).start()

    return jsonify({
        'success': True,
        'status': 'processing',
        'message': 'Mosaic generation started in background'
    })


@app.route('/video/mosaic/<mask_source>/<filename>')
def serve_mosaic_video_simple(mask_source, filename):
    """사전 생성된 모자이크 비디오 서빙 (S3 우선, 로컬 폴백)

    경로 구조: video/mosaic/{mask_source}/{filename}.mp4
    """
    mosaic_dir = os.path.join(VIDEO_DIR, 'mosaic', mask_source)
    mosaic_path = os.path.join(mosaic_dir, filename)

    # 먼저 S3에서 확인 (사전 생성된 파일이 S3에 업로드됨)
    if USE_S3:
        s3_key = f"{S3_PREFIX}/mosaic/{mask_source}/{filename}"
        if s3_file_exists(s3_key):
            url = get_s3_presigned_url(s3_key)
            if url:
                print(f"[S3 Redirect] mosaic/{mask_source}/{filename}")
                return redirect(url)

    # 로컬 파일 확인
    if not os.path.exists(mosaic_path):
        return jsonify({'error': 'File not found'}), 404

    # 코덱 및 FPS 확인 후 필요 시 변환
    codec = get_video_codec(mosaic_path)
    fps = get_video_fps(mosaic_path)
    needs_codec = codec != 'h264'
    needs_fps = abs(fps - TARGET_FPS) > 0.5

    if not needs_codec and not needs_fps:
        return send_from_directory(mosaic_dir, filename)

    # 변환 필요 시 캐시
    cached_filename = f"{mask_source}_{os.path.splitext(filename)[0]}_mosaic30.mp4"
    cached_path = os.path.join(CACHE_DIR, cached_filename)
    converting_marker = cached_path + '.converting'

    if os.path.exists(cached_path):
        return send_file(cached_path, mimetype='video/mp4')

    if os.path.exists(converting_marker):
        print(f"Mosaic {mask_source}/{filename}: 다른 요청이 변환 중, 원본 반환")
        return send_from_directory(mosaic_dir, filename)

    try:
        with open(converting_marker, 'w') as f:
            f.write('converting')

        with FFMPEG_SEMAPHORE:
            subprocess.run(
                ['ffmpeg', '-y', '-i', mosaic_path,
                 '-threads', '1',
                 '-r', str(TARGET_FPS),
                 '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
                 '-c:a', 'copy', cached_path],
                capture_output=True, check=True
            )
        print(f"Mosaic {mask_source}/{filename} 변환 완료")

        if os.path.exists(converting_marker):
            os.remove(converting_marker)

        return send_file(cached_path, mimetype='video/mp4')
    except Exception as e:
        print(f"Mosaic conversion failed: {e}")
        if os.path.exists(converting_marker):
            os.remove(converting_marker)
        return send_from_directory(mosaic_dir, filename)


@app.route('/video/mosaic/<task>/<filename>')
def serve_mosaic_video(task, filename):
    """모자이크 비디오 서빙 - 레거시 경로 (S3 폴백 지원)"""
    mosaic_dir = os.path.join(VIDEO_DIR, 'mosaic', task)
    mosaic_path = os.path.join(mosaic_dir, filename)

    if not os.path.exists(mosaic_path):
        # S3: pre-signed URL로 즉시 redirect
        if USE_S3:
            s3_key = f"{S3_PREFIX}/mosaic/{task}/{filename}"
            url = get_s3_presigned_url(s3_key)
            if url:
                print(f"[S3 Redirect] mosaic/{task}/{filename}")
                return redirect(url)
        return jsonify({'error': 'File not found'}), 404

    # 코덱 및 FPS 확인 후 필요 시 변환
    codec = get_video_codec(mosaic_path)
    fps = get_video_fps(mosaic_path)
    needs_codec = codec != 'h264'
    needs_fps = abs(fps - TARGET_FPS) > 0.5

    if not needs_codec and not needs_fps:
        return send_from_directory(mosaic_dir, filename)

    # 변환 필요 시 캐시
    cached_filename = f"{os.path.splitext(filename)[0]}_mosaic30.mp4"
    cached_path = os.path.join(CACHE_DIR, cached_filename)
    converting_marker = cached_path + '.converting'

    # 이미 변환 완료된 파일이 있으면 바로 반환
    if os.path.exists(cached_path):
        return send_file(cached_path, mimetype='video/mp4')

    # 다른 요청이 변환 중이면 원본 반환
    if os.path.exists(converting_marker):
        print(f"Mosaic {filename}: 다른 요청이 변환 중, 원본 반환")
        return send_from_directory(mosaic_dir, filename)

    # 변환 시작
    try:
        # 변환 중 마커 파일 생성
        with open(converting_marker, 'w') as f:
            f.write('converting')

        with FFMPEG_SEMAPHORE:
            subprocess.run(
                ['ffmpeg', '-y', '-i', mosaic_path,
                 '-threads', '1',
                 '-r', str(TARGET_FPS),
                 '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
                 '-c:a', 'copy', cached_path],
                capture_output=True, check=True
            )
        print(f"Mosaic {filename} 변환 완료")

        # 변환 완료 후 마커 파일 삭제
        if os.path.exists(converting_marker):
            os.remove(converting_marker)

        return send_file(cached_path, mimetype='video/mp4')
    except Exception as e:
        print(f"Mosaic conversion failed: {e}")
        # 실패 시 마커 파일 삭제
        if os.path.exists(converting_marker):
            os.remove(converting_marker)
        return send_from_directory(mosaic_dir, filename)


@app.route('/video/mosaic/<mask_source>/<task>/<filename>')
def serve_mosaic_video_with_source(mask_source, task, filename):
    """모자이크 비디오 서빙 (masks 폴더의 특정 소스 사용, S3 폴백 지원)"""
    mosaic_dir = os.path.join(VIDEO_DIR, 'mosaic', mask_source, task)
    mosaic_path = os.path.join(mosaic_dir, filename)

    if not os.path.exists(mosaic_path):
        # S3: pre-signed URL로 즉시 redirect
        if USE_S3:
            s3_key = f"{S3_PREFIX}/mosaic/{mask_source}/{task}/{filename}"
            url = get_s3_presigned_url(s3_key)
            if url:
                print(f"[S3 Redirect] mosaic/{mask_source}/{task}/{filename}")
                return redirect(url)
        return jsonify({'error': 'File not found'}), 404

    # 코덱 및 FPS 확인 후 필요 시 변환
    codec = get_video_codec(mosaic_path)
    fps = get_video_fps(mosaic_path)
    needs_codec = codec != 'h264'
    needs_fps = abs(fps - TARGET_FPS) > 0.5

    if not needs_codec and not needs_fps:
        return send_from_directory(mosaic_dir, filename)

    # 변환 필요 시 캐시
    cached_filename = f"{mask_source}_{os.path.splitext(filename)[0]}_mosaic30.mp4"
    cached_path = os.path.join(CACHE_DIR, cached_filename)
    converting_marker = cached_path + '.converting'

    if os.path.exists(cached_path):
        return send_file(cached_path, mimetype='video/mp4')

    if os.path.exists(converting_marker):
        print(f"Mosaic {mask_source}/{filename}: 다른 요청이 변환 중, 원본 반환")
        return send_from_directory(mosaic_dir, filename)

    try:
        with open(converting_marker, 'w') as f:
            f.write('converting')

        with FFMPEG_SEMAPHORE:
            subprocess.run(
                ['ffmpeg', '-y', '-i', mosaic_path,
                 '-threads', '1',
                 '-r', str(TARGET_FPS),
                 '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
                 '-c:a', 'copy', cached_path],
                capture_output=True, check=True
            )
        print(f"Mosaic {mask_source}/{filename} 변환 완료")

        if os.path.exists(converting_marker):
            os.remove(converting_marker)

        return send_file(cached_path, mimetype='video/mp4')
    except Exception as e:
        print(f"Mosaic conversion failed: {e}")
        if os.path.exists(converting_marker):
            os.remove(converting_marker)
        return send_from_directory(mosaic_dir, filename)


@app.route('/api/overlay-check/<name>', methods=['GET'])
def check_overlay(name):
    """오버레이 비디오 존재 여부 확인 (mask_source 파라미터 지원, S3 폴백)"""
    task = get_task_name(name)
    mask_source = request.args.get('mask_source', '')

    if mask_source:
        # masks 폴더의 특정 소스 사용
        overlay_path = os.path.join(VIDEO_DIR, 'overlay', mask_source, task, f'{name}.mp4')
        video_path = f'/video/overlay/{mask_source}/{task}/{name}.mp4'
        s3_key = f"{S3_PREFIX}/overlay/{mask_source}/{task}/{name}.mp4"
    else:
        # 기존 mask 폴더 사용
        overlay_path = os.path.join(VIDEO_DIR, 'overlay', task, f'{name}.mp4')
        video_path = f'/video/overlay/{task}/{name}.mp4'
        s3_key = f"{S3_PREFIX}/overlay/{task}/{name}.mp4"

    # 로컬 또는 S3에 존재하는지 확인 (파일 크기도 확인 - 손상된 파일 제외)
    exists = False
    if os.path.exists(overlay_path):
        file_size = os.path.getsize(overlay_path)
        exists = file_size > 1000  # 1KB 이상이어야 유효한 파일로 간주
        if not exists:
            print(f"[Overlay Check] Invalid file (size={file_size}): {overlay_path}")
    if not exists and USE_S3:
        exists = s3_file_exists(s3_key)

    return jsonify({
        'exists': exists,
        'task': task,
        'mask_source': mask_source,
        'path': video_path
    })


@app.route('/api/overlay-generate', methods=['POST'])
def generate_overlay():
    """오버레이 비디오 생성 (overlay.py 호출, mask_source 파라미터 지원)"""
    data = request.json
    video_name = data.get('video_name')
    opacity = data.get('opacity', 0.5)
    mask_source = data.get('mask_source', '')

    if not video_name:
        return jsonify({'error': 'Missing video_name'}), 400

    task = get_task_name(video_name)
    match = re.match(r'.+_(\d+)$', video_name)
    if not match:
        return jsonify({'error': 'Invalid video name format'}), 400
    number = match.group(1)

    # 경로 설정: mask_source가 있으면 다른 폴더 사용
    if mask_source:
        overlay_path = os.path.join(VIDEO_DIR, 'overlay', mask_source, task, f'{video_name}.mp4')
        video_path = f'/video/overlay/{mask_source}/{task}/{video_name}.mp4'
        mask_path = os.path.join(VIDEO_DIR, 'masks', mask_source, f'{video_name}.mp4')
    else:
        overlay_path = os.path.join(VIDEO_DIR, 'overlay', task, f'{video_name}.mp4')
        video_path = f'/video/overlay/{task}/{video_name}.mp4'
        mask_path = os.path.join(VIDEO_DIR, 'mask', f'{video_name}.mp4')

    # 이미 존재하는지 확인
    if os.path.exists(overlay_path):
        return jsonify({
            'success': True,
            'message': 'Overlay already exists',
            'path': video_path
        })

    # source와 mask 파일 존재 확인
    source_path = os.path.join(VIDEO_DIR, 'source', f'{video_name}.mp4')

    source_exists = os.path.exists(source_path)
    mask_exists = os.path.exists(mask_path)
    source_url = None
    mask_url = None

    if not source_exists and USE_S3:
        cache = get_s3_cache()
        s3_source_key = f"{S3_PREFIX}/source/{video_name}.mp4"
        if ('_s3_files_set' in cache and s3_source_key in cache['_s3_files_set']) or s3_file_exists(s3_source_key):
            source_exists = True
            source_url = get_s3_presigned_url(s3_source_key)

    if not mask_exists and USE_S3:
        cache = get_s3_cache()
        s3_mask_key = f"{S3_PREFIX}/masks/{mask_source}/{video_name}.mp4" if mask_source else f"{S3_PREFIX}/mask/{video_name}.mp4"
        if ('_s3_files_set' in cache and s3_mask_key in cache['_s3_files_set']) or s3_file_exists(s3_mask_key):
            mask_exists = True
            mask_url = get_s3_presigned_url(s3_mask_key)

    if not source_exists:
        return jsonify({'error': f'Source video not found: {video_name}.mp4'}), 404
    if not mask_exists:
        return jsonify({'error': f'Mask video not found: {video_name}.mp4 (source: {mask_source or "default"})'}), 404

    # overlay.py 실행
    overlay_script = os.path.join(BASE_DIR, 'overlay.py')
    overlay_python = os.path.join(BASE_DIR, 'venv', 'bin', 'python')
    if not os.path.exists(overlay_python):
        overlay_python = sys.executable

    def overlay_worker():
        try:
            cmd = [overlay_python, overlay_script, '--task', task, '--number', number, '--opacity', str(opacity)]
            if mask_source:
                cmd.extend(['--mask-source', mask_source])
            if source_url:
                cmd.extend(['--source-url', source_url])
            if mask_url:
                cmd.extend(['--mask-url', mask_url])

            # PYTHONPATH 설정하여 utils 모듈을 찾을 수 있게 함
            env = os.environ.copy()
            env['PYTHONPATH'] = BASE_DIR + (':' + env.get('PYTHONPATH', '') if env.get('PYTHONPATH') else '')

            with FFMPEG_SEMAPHORE:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=env)
                
            if result.returncode != 0:
                print(f"[백그라운드] Overlay generation error: {result.stderr}")
                CONVERSION_STATUS[status_key] = {'status': 'failed', 'error': result.stderr[:200]}
            else:
                print(f"[백그라운드] Overlay generated: {result.stdout}")
                CONVERSION_STATUS[status_key] = {'status': 'completed', 'path': video_path}
        except subprocess.TimeoutExpired:
            CONVERSION_STATUS[status_key] = {'status': 'failed', 'error': 'Generation timed out (10min)'}
        except Exception as e:
            CONVERSION_STATUS[status_key] = {'status': 'failed', 'error': str(e)}

    # 백그라운드 작업 시작
    status_key = f"overlay_{mask_source}_{video_name}"
    
    if status_key in CONVERSION_STATUS and CONVERSION_STATUS[status_key]['status'] == 'processing':
        return jsonify({'success': True, 'status': 'processing', 'message': 'Overlay generation in progress'})
        
    CONVERSION_STATUS[status_key] = {'status': 'processing'}
    Thread(target=overlay_worker, daemon=True).start()

    return jsonify({
        'success': True,
        'status': 'processing',
        'message': 'Overlay generation started in background'
    })


@app.route('/video/overlay/<task>/<filename>')
def serve_overlay_video(task, filename):
    """오버레이 비디오 서빙 (기존 mask 폴더 사용, S3 폴백 지원)"""
    overlay_dir = os.path.join(VIDEO_DIR, 'overlay', task)
    overlay_path = os.path.join(overlay_dir, filename)

    if not os.path.exists(overlay_path):
        # S3: pre-signed URL로 즉시 redirect
        if USE_S3:
            s3_key = f"{S3_PREFIX}/overlay/{task}/{filename}"
            url = get_s3_presigned_url(s3_key)
            if url:
                print(f"[S3 Redirect] overlay/{task}/{filename}")
                return redirect(url)
        return jsonify({'error': 'File not found'}), 404

    return send_from_directory(overlay_dir, filename)


@app.route('/video/overlay/<mask_source>/<task>/<filename>')
def serve_overlay_video_with_source(mask_source, task, filename):
    """오버레이 비디오 서빙 (masks 폴더의 특정 소스 사용, S3 폴백 지원)"""
    overlay_dir = os.path.join(VIDEO_DIR, 'overlay', mask_source, task)
    overlay_path = os.path.join(overlay_dir, filename)

    if not os.path.exists(overlay_path):
        # S3: pre-signed URL로 즉시 redirect
        if USE_S3:
            s3_key = f"{S3_PREFIX}/overlay/{mask_source}/{task}/{filename}"
            url = get_s3_presigned_url(s3_key)
            if url:
                print(f"[S3 Redirect] overlay/{mask_source}/{task}/{filename}")
                return redirect(url)
        return jsonify({'error': 'File not found'}), 404

    return send_from_directory(overlay_dir, filename)


@app.route('/video/masks/<source>/<path:filename>')
def serve_masks_video(source, filename):
    """masks 폴더 내 특정 소스의 비디오 서빙 (H264 + 30fps 자동 변환, S3 폴백 지원)"""
    masks_dir = os.path.join(VIDEO_DIR, 'masks', source)
    original_path = os.path.join(masks_dir, filename)

    if not os.path.exists(original_path):
        # S3: pre-signed URL로 즉시 redirect (다운로드 없이)
        if USE_S3:
            s3_key = f"{S3_PREFIX}/masks/{source}/{filename}"
            cache = get_s3_cache()
            s3_exists = ('_s3_files_set' in cache and s3_key in cache['_s3_files_set']) or s3_file_exists(s3_key)
            if s3_exists:
                url = get_s3_presigned_url(s3_key)
                if url:
                    print(f"[S3 Redirect] masks/{source}/{filename}")
                    return redirect(url)
        return jsonify({'error': 'File not found'}), 404

    # 로컬 파일: 코덱/FPS 변환 처리
    codec = get_video_codec(original_path)
    fps = get_video_fps(original_path)
    needs_codec = codec != 'h264'
    needs_fps = abs(fps - TARGET_FPS) > 0.5

    if not needs_codec and not needs_fps:
        return send_from_directory(masks_dir, filename)

    # 코덱 또는 FPS 변환 필요
    base_name = os.path.splitext(filename)[0]
    cached_filename = f"{source}_{base_name}_mask30.mp4"
    cached_path = os.path.join(CACHE_DIR, cached_filename)
    converting_marker = cached_path + '.converting'

    # 이미 변환 완료된 파일이 있으면 바로 반환
    if os.path.exists(cached_path):
        return send_file(cached_path, mimetype='video/mp4')

    # 다른 요청이 변환 중이면 원본 반환
    if os.path.exists(converting_marker):
        print(f"[변환] Masks {source}/{filename}: 다른 요청이 변환 중, 원본 반환")
        return send_from_directory(masks_dir, filename)

    # 변환 시작
    reasons = []
    if needs_codec: reasons.append(f'코덱({codec}→h264)')
    if needs_fps: reasons.append(f'FPS({fps}→{TARGET_FPS})')
    print(f"[변환] Masks {source}/{filename}: {', '.join(reasons)} 변환 중...")
    try:
        # 변환 중 마커 파일 생성
        with open(converting_marker, 'w') as f:
            f.write('converting')

        # source 경로 추론 (동일한 파일명 사용)
        source_dir = os.path.join(VIDEO_DIR, 'source')
        source_path = os.path.join(source_dir, filename)

        if needs_fps and os.path.exists(source_path):
            print(f"[변환] Masks {source}/{filename}: 인덱스 기반 원본 동기화 수행")
            success = sync_mask_to_source(source_path, original_path, cached_path, TARGET_FPS)
            if not success:
                raise Exception("동기화 실패")
        else:
            print(f"[변환] Masks {source}/{filename}: 일반 ffmpeg 변환 수행")
            with FFMPEG_SEMAPHORE:
                subprocess.run(
                    ['ffmpeg', '-y', '-i', original_path,
                     '-threads', '2',
                     '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18',
                     '-c:a', 'copy', cached_path],
                    capture_output=True, check=True
                )

        print(f"[변환] Masks {source}/{filename} 변환 완료")

        # 변환 완료 후 마커 파일 삭제
        if os.path.exists(converting_marker):
            os.remove(converting_marker)

        return send_file(cached_path, mimetype='video/mp4')
    except Exception as e:
        print(f"[변환] Masks 변환 실패: {e}")
        # 실패 시 마커 파일 삭제
        if os.path.exists(converting_marker):
            os.remove(converting_marker)
        return send_from_directory(masks_dir, filename)


def open_browser():
    """서버 시작 후 브라우저 자동 오픈"""
    webbrowser.open('http://localhost:5002')


TARGET_FPS = 30


@app.route('/api/video-urls/<name>', methods=['GET'])
def get_video_urls(name):
    """S3 pre-signed URL 반환 (프론트엔드에서 직접 사용)"""
    name = name.replace('.mp4', '')
    mask_source = request.args.get('mask_source', '')
    urls = {}

    if USE_S3 and s3_client:
        # source URL
        source_key = f"{S3_PREFIX}/source/{name}.mp4"
        source_local = os.path.join(VIDEO_DIR, 'source', f'{name}.mp4')
        if not os.path.exists(source_local):
            url = get_s3_presigned_url(source_key)
            if url:
                urls['source'] = url

        # mask URL
        if mask_source:
            mask_key = f"{S3_PREFIX}/masks/{mask_source}/{name}.mp4"
            mask_local = os.path.join(VIDEO_DIR, 'masks', mask_source, f'{name}.mp4')
        else:
            mask_key = f"{S3_PREFIX}/mask/{name}.mp4"
            mask_local = os.path.join(VIDEO_DIR, 'mask', f'{name}.mp4')

        if not os.path.exists(mask_local):
            cache = get_s3_cache()
            s3_exists = ('_s3_files_set' in cache and mask_key in cache['_s3_files_set']) or s3_file_exists(mask_key)
            if s3_exists:
                url = get_s3_presigned_url(mask_key)
                if url:
                    urls['mask'] = url

    return jsonify(urls)


@app.route('/api/storage-status', methods=['GET'])
def get_storage_status():
    """스토리지 상태 확인 (로컬/S3)"""
    return jsonify({
        'use_s3': USE_S3,
        's3_bucket': S3_BUCKET if USE_S3 else None,
        's3_region': S3_REGION if USE_S3 else None,
        's3_prefix': S3_PREFIX if USE_S3 else None,
        'video_dir': VIDEO_DIR,
        'evaluations_dir': EVALUATIONS_DIR
    })


# ===== 카카오톡 챗봇 Integration =====
def get_evaluation_count(mask_source: str) -> str:
    """S3에서 평가 진행 상황을 집계하여 텍스트로 반환"""
    if not USE_S3 or not s3_client:
        return "S3가 비활성화되어 있습니다."

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
            rel_path = key.replace(eval_prefix, '')
            parts = rel_path.split('/')
            if len(parts) == 2 and parts[1].endswith('.csv'):
                task = parts[0]
                done_by_task[task] += 1

    # 3. 결과 생성 (카카오톡용 포맷)
    all_tasks = sorted(set(total_by_task) | set(done_by_task))
    total_done = total_all = 0

    lines = []
    lines.append(f"📊 평가 진행 현황 [{mask_source}]")
    lines.append("=" * 24)

    for task in all_tasks:
        done = done_by_task[task]
        total = total_by_task[task]
        if total == 0:
            continue
        pct = done / total * 100
        bar = "█" * int(pct // 10) + "░" * (10 - int(pct // 10))
        lines.append(f"{task}: {done}/{total} ({pct:.1f}%)")
        lines.append(f"  {bar}")
        total_done += done
        total_all += total

    lines.append("=" * 24)
    pct_all = total_done / total_all * 100 if total_all > 0 else 0
    lines.append(f"✅ 전체: {total_done}/{total_all} ({pct_all:.1f}%)")

    return "\n".join(lines)


@app.route('/kakao/count', methods=['POST'])
def kakao_count():
    """
    카카오 i 오픈빌더 스킬 엔드포인트
    사용법: "진행현황", "진행현황 sam2" 등
    """
    try:
        body = request.get_json()

        # 사용자 발화에서 mask_source 추출
        utterance = body.get('userRequest', {}).get('utterance', '').strip()

        # "진행현황 sam2" 형태에서 mask_source 추출
        parts = utterance.split()
        mask_source = 'rexomni'  # 기본값

        allowed_sources = ['rexomni', 'sam2', 'cutie']
        for part in parts:
            if part.lower() in allowed_sources:
                mask_source = part.lower()
                break

        # 평가 현황 조회
        result = get_evaluation_count(mask_source)

        # 카카오 응답 형식
        return jsonify({
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {
                            "text": result
                        }
                    }
                ],
                "quickReplies": [
                    {"label": "rexomni", "action": "message", "messageText": "진행현황 rexomni"},
                    {"label": "sam2", "action": "message", "messageText": "진행현황 sam2"},
                    {"label": "cutie", "action": "message", "messageText": "진행현황 cutie"}
                ]
            }
        })
    except Exception as e:
        return jsonify({
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {
                            "text": f"오류가 발생했습니다: {str(e)}"
                        }
                    }
                ]
            }
        })


if __name__ == '__main__':
    print(f"Video directory: {VIDEO_DIR}")
    print(f"Evaluations directory: {EVALUATIONS_DIR}")
    print(f"Static files: {STATIC_DIR}")
    print(f"S3 enabled: {USE_S3}")
    if USE_S3:
        print(f"S3 bucket: {S3_BUCKET}, region: {S3_REGION}, prefix: {S3_PREFIX}")

    # 정적 파일 존재 확인
    if not os.path.exists(STATIC_DIR):
        print(f"[!] WARNING: Static directory NOT FOUND: {STATIC_DIR}")
    else:
        index_path = os.path.join(STATIC_DIR, 'index.html')
        if os.path.exists(index_path):
            print(f"[+] Static directory found and index.html exists: {STATIC_DIR}")
        else:
            print(f"[!] WARNING: Static directory found but index.html MISSING: {STATIC_DIR}")
            print(f"    Directory contents: {os.listdir(STATIC_DIR) if os.path.isdir(STATIC_DIR) else 'Not a directory'}")

    # ffmpeg 자동 설치 확인
    ensure_ffmpeg()

    # S3에서 초기 DB 다운로드
    download_db_from_s3()
    
    # DB 초기화 (테이블 생성 등)
    database.init_db()

    # 번들 모드에서는 자동으로 브라우저 열기
    if getattr(sys, 'frozen', False):
        threading.Timer(1.5, open_browser).start()

    # Railway/Docker 배포 시 PORT 환경 변수 사용
    port = int(os.environ.get('PORT', 5004))
    is_production = os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('DOCKER_ENV')

    app.run(
        host='0.0.0.0' if is_production else '127.0.0.1',
        port=port,
        debug=not getattr(sys, 'frozen', False) and not is_production
    )
