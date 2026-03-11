"""
비디오 처리 관련 유틸리티 함수 (코덱 확인, FPS 확인, 변환, 동기화)
"""
import os
import subprocess
import time
import cv2

def get_video_codec(filepath):
    """비디오 코덱 확인"""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=codec_name', '-of', 'default=noprint_wrappers=1:nokey=1',
             filepath],
            capture_output=True, text=True
        )
        return result.stdout.strip()
    except Exception:
        return None

def get_video_fps(filepath):
    """비디오 FPS 확인 (ffprobe 사용)"""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=r_frame_rate', '-of', 'default=noprint_wrappers=1:nokey=1',
             filepath],
            capture_output=True, text=True
        )
        fps_str = result.stdout.strip()
        if '/' in fps_str:
            num, den = fps_str.split('/')
            return round(int(num) / int(den), 2)
        return round(float(fps_str), 2)
    except Exception:
        return 30.0

def get_video_frame_count(filepath):
    """비디오 총 프레임 수 확인 (ffprobe 사용)"""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=nb_frames', '-of', 'default=noprint_wrappers=1:nokey=1',
             filepath],
            capture_output=True, text=True
        )
        frames_str = result.stdout.strip()
        if frames_str and frames_str != 'N/A':
            return int(frames_str)
        
        # nb_frames가 N/A인 경우 (주로 인코딩 방식에 따라 다름)
        # 전체 길이를 구해서 FPS를 곱하는 방식으로 추정
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1',
             filepath],
            capture_output=True, text=True
        )
        duration = float(result.stdout.strip())
        fps = get_video_fps(filepath)
        return int(duration * fps)
    except Exception:
        return 0

def convert_to_h264(input_path, output_path):
    """H264로 변환"""
    try:
        subprocess.run(
            ['ffmpeg', '-y', '-i', input_path,
             '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18',
             '-c:a', 'copy', output_path],
            capture_output=True, check=True
        )
        return True
    except Exception as e:
        print(f"Conversion error: {e}")
        return False

def sync_mask_to_source(source_path, mask_path, output_path, target_fps=30.0):
    """
    원본 영상의 프레임 진행율에 맞춰 마스크 영상을 1:1 매핑하여 동기화 생성
    메모리 캐싱 대신 2-포인터 방식으로 실시간 스트리밍 인덱스 맵핑을 적용
    """
    start_time = time.time()
    
    source_cap = cv2.VideoCapture(source_path)
    mask_cap = cv2.VideoCapture(mask_path)
    
    if not source_cap.isOpened() or not mask_cap.isOpened():
        if source_cap.isOpened(): source_cap.release()
        if mask_cap.isOpened(): mask_cap.release()
        return False
        
    width = int(mask_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(mask_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    original_total_frames = int(source_cap.get(cv2.CAP_PROP_FRAME_COUNT))
    original_mask_frames = int(mask_cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    # 출력 코덱/포맷 설정 (H264 웹 서빙용)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v') # OpenCV 기본 mp4 코덱
    
    # 더 나은 압축과 브라우저 호환성을 위해 ffmpeg 프로세스 파이프보단 임시 OpenCV mp4 -> ffmpeg H264 가 안전함
    # 여기서는 ffmpeg 파이프라인으로 직접 인코딩하여 출력합니다
    ffmpeg_cmd = [
        'ffmpeg', '-y',
        '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-s', f'{width}x{height}', '-pix_fmt', 'bgr24',
        '-r', str(target_fps), '-i', '-',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18',
        '-pix_fmt', 'yuv420p', '-v', 'error',
        output_path
    ]
    ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                   
    current_source_idx = 0
    current_mask_idx = -1
    last_mask_frame = None
    frame_count = 0
    
    while current_source_idx < original_total_frames:
        if original_total_frames > 0 and original_mask_frames > 0:
            target_mask_idx = int(current_source_idx * (original_mask_frames / original_total_frames))
        else:
            target_mask_idx = current_source_idx
            
        if target_mask_idx >= original_mask_frames:
            target_mask_idx = original_mask_frames - 1
            
        while current_mask_idx < target_mask_idx:
            ret_mask, mask_frame = mask_cap.read()
            if not ret_mask:
                break
            last_mask_frame = mask_frame
            current_mask_idx += 1
            
        if last_mask_frame is not None:
            ffmpeg_proc.stdin.write(last_mask_frame.tobytes())
            frame_count += 1
            
        current_source_idx += 1

    ffmpeg_proc.stdin.close()
    ffmpeg_proc.wait()
    source_cap.release()
    mask_cap.release()

    elapsed = time.time() - start_time
    print(f"[동기화] 마스크 영상 생성 완료: {frame_count} frames / {elapsed:.1f} sec")
    return True
