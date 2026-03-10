"""
원본 영상과 마스크 영상을 합성하여 오버레이 영상 생성
마스크 영상의 길이가 다른 경우 시간 스트레칭으로 동기화
"""
import os
import cv2
import numpy as np
import subprocess
import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

# 기본 경로 설정
BASE_DIR = Path(__file__).parent
SOURCE_DIR = BASE_DIR / "video" / "source"
MASK_DIR = BASE_DIR / "video" / "mask"
OUTPUT_DIR = BASE_DIR / "video" / "overlay"

TARGET_FPS = 30.0


def get_video_info(video_path):
    """비디오 정보 추출"""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None

    info = {
        'width': int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        'height': int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        'fps': cap.get(cv2.CAP_PROP_FPS),
        'frame_count': int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
    }
    info['duration'] = info['frame_count'] / info['fps'] if info['fps'] > 0 else 0
    cap.release()
    return info


def apply_overlay(source_frame, mask_frame, opacity=0.5):
    """마스크를 소스 위에 오버레이 (마스크 영역만)"""
    if mask_frame is None:
        return source_frame

    # 마스크 크기 맞추기
    if mask_frame.shape[:2] != source_frame.shape[:2]:
        mask_frame = cv2.resize(mask_frame, (source_frame.shape[1], source_frame.shape[0]))

    # 마스크에서 실제 마스크 영역 추출 (0이 아닌 픽셀)
    if len(mask_frame.shape) == 3:
        mask_gray = cv2.cvtColor(mask_frame, cv2.COLOR_BGR2GRAY)
    else:
        mask_gray = mask_frame

    _, binary_mask = cv2.threshold(mask_gray, 1, 255, cv2.THRESH_BINARY)

    # 마스크 영역이 없으면 원본 반환
    if cv2.countNonZero(binary_mask) == 0:
        return source_frame

    # 마스크 영역에 컬러 오버레이 적용
    result = source_frame.copy()
    mask_3ch = cv2.cvtColor(binary_mask, cv2.COLOR_GRAY2BGR) / 255.0

    # 마스크 컬러 오버레이
    overlay = cv2.addWeighted(source_frame, 1 - opacity, mask_frame, opacity, 0)
    result = np.where(mask_3ch > 0, overlay, source_frame)

    return result.astype(np.uint8)


def load_all_frames(video_path: str, width: int, height: int) -> list:
    """비디오의 모든 프레임을 메모리에 로드"""
    frame_size = width * height * 3
    frames = []

    cmd = [
        'ffmpeg', '-v', 'error', '-i', video_path,
        '-f', 'rawvideo', '-pix_fmt', 'bgr24', 'pipe:1'
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=10**8)

    while True:
        data = proc.stdout.read(frame_size)
        if not data or len(data) < frame_size:
            break
        frame = np.frombuffer(data, dtype=np.uint8).reshape((height, width, 3))
        frames.append(frame.copy())

    proc.terminate()
    return frames


def process_video_overlay(source_path: str, mask_path: str, output_path: str, opacity: float = 0.5):
    """
    원본 영상과 마스크 영상을 합쳐서 오버레이 영상 생성
    프레임 인덱스 매핑으로 정확한 동기화 보장
    """
    start_time = time.time()

    # 비디오 정보 추출
    source_info = get_video_info(source_path)
    mask_info = get_video_info(mask_path)

    if not source_info:
        print(f"원본 영상을 열 수 없습니다: {source_path}")
        return False
    if not mask_info:
        print(f"마스크 영상을 열 수 없습니다: {mask_path}")
        return False

    width, height = source_info['width'], source_info['height']
    source_frame_count = source_info['frame_count']
    mask_frame_count = mask_info['frame_count']

    print(f"처리 중: {os.path.basename(source_path)}")
    print(f"  - 해상도: {width}x{height}")
    print(f"  - Source: {source_frame_count} frames ({source_info['duration']:.2f}s)")
    print(f"  - Mask: {mask_frame_count} frames ({mask_info['duration']:.2f}s)")
    print(f"  - Frame ratio: {mask_frame_count/source_frame_count:.4f}")

    # 마스크 영상의 모든 프레임을 미리 로드
    print(f"  - 마스크 프레임 로딩 중...")
    mask_frames = load_all_frames(mask_path, width, height)
    actual_mask_count = len(mask_frames)
    print(f"  - 마스크 프레임 로드 완료: {actual_mask_count} frames")

    if actual_mask_count == 0:
        print(f"마스크 프레임을 읽을 수 없습니다.")
        return False

    frame_size = width * height * 3

    # 소스 영상 읽기
    source_cmd = [
        'ffmpeg', '-v', 'error', '-i', source_path,
        '-f', 'rawvideo', '-pix_fmt', 'bgr24', 'pipe:1'
    ]

    source_proc = subprocess.Popen(source_cmd, stdout=subprocess.PIPE, bufsize=10**8)

    # 출력 폴더 생성
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # FFmpeg 인코더 설정 (환경에 따른 하드웨어 가속 및 속도 최적화)
    # 기본은 libx264 (CPU) + ultrafast
    encoder_cmd = ['-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18']
    
    # 하드웨어 가속 확인
    try:
        check_proc = subprocess.run(['ffmpeg', '-encoders'], capture_output=True, text=True)
        if 'h264_videotoolbox' in check_proc.stdout:
            encoder_cmd = ['-c:v', 'h264_videotoolbox', '-b:v', '8M']
        elif 'h264_nvenc' in check_proc.stdout:
            encoder_cmd = ['-c:v', 'h264_nvenc', '-preset', 'p1', '-qp', '18']
    except:
        pass

    ffmpeg_cmd = [
        'ffmpeg', '-y',
        '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-s', f'{width}x{height}', '-pix_fmt', 'bgr24',
        '-r', str(TARGET_FPS), '-i', '-',
        *encoder_cmd,
        '-pix_fmt', 'yuv420p', '-v', 'error',
        output_path
    ]

    ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    source_idx = 0

    while True:
        s_data = source_proc.stdout.read(frame_size)

        if not s_data or len(s_data) < frame_size:
            break

        source_frame = np.frombuffer(s_data, dtype=np.uint8).reshape((height, width, 3))

        # 프레임 인덱스 매핑: source 프레임에 대응하는 mask 프레임 계산
        mask_idx = int(source_idx * actual_mask_count / source_frame_count)
        mask_idx = min(mask_idx, actual_mask_count - 1)  # 범위 초과 방지

        mask_frame = mask_frames[mask_idx]

        # 오버레이 적용
        result_frame = apply_overlay(source_frame, mask_frame, opacity)

        # 출력
        ffmpeg_proc.stdin.write(result_frame.tobytes())
        source_idx += 1

        if source_idx % 30 == 0:
            progress = (source_idx / source_frame_count) * 100 if source_frame_count > 0 else 0
            print(f"  진행: {source_idx}/{source_frame_count} ({progress:.1f}%)", end='\r')

    ffmpeg_proc.stdin.close()
    ffmpeg_proc.wait()
    source_proc.terminate()

    # 메모리 해제
    del mask_frames

    elapsed_time = time.time() - start_time
    processing_fps = source_idx / elapsed_time if elapsed_time > 0 else 0

    print(f"\n  완료! 저장: {output_path}")
    print(f"  - 처리 프레임: {source_idx}")
    print(f"  - 처리 시간: {elapsed_time:.1f}초 ({processing_fps:.1f} fps)")

    return True


OPACITY = 0.5
NUM_WORKERS = max(1, multiprocessing.cpu_count() // 2)  # CPU 절반 사용


def process_single_task(args):
    """멀티프로세싱용 단일 태스크 처리"""
    source_path, mask_path, output_path, idx, total = args
    try:
        print(f"[{idx}/{total}] {Path(source_path).stem}")
        return process_video_overlay(source_path, mask_path, output_path, OPACITY)
    except Exception as e:
        print(f"[{idx}/{total}] 에러: {e}")
        return False


def process_all_videos():
    """video/mask 폴더의 모든 영상을 병렬 처리"""
    mask_files = sorted(MASK_DIR.glob("*.mp4"))

    if not mask_files:
        print(f"마스크 영상이 없습니다: {MASK_DIR}")
        return

    tasks = []
    for mask_path in mask_files:
        filename = mask_path.stem
        parts = filename.rsplit("_", 1)
        if len(parts) != 2:
            continue

        task = parts[0]
        source_path = SOURCE_DIR / f"{filename}.mp4"
        output_path = OUTPUT_DIR / task / f"{filename}.mp4"

        if output_path.exists() or not source_path.exists():
            continue

        output_path.parent.mkdir(parents=True, exist_ok=True)
        tasks.append((str(source_path), str(mask_path), str(output_path)))

    if not tasks:
        print("처리할 영상이 없습니다.")
        return

    print(f"총 {len(tasks)}개 영상 / {NUM_WORKERS} 프로세스\n")

    indexed_tasks = [(s, m, o, i+1, len(tasks)) for i, (s, m, o) in enumerate(tasks)]
    start_time = time.time()
    success = 0

    with ProcessPoolExecutor(max_workers=NUM_WORKERS) as executor:
        for result in executor.map(process_single_task, indexed_tasks):
            if result:
                success += 1

    print(f"\n완료: {success}/{len(tasks)} ({time.time() - start_time:.1f}초)")


def process_single_video(task, number, opacity=0.5, mask_source=None, source_url=None, mask_url=None):
    """단일 비디오 처리 (명령줄 호출용)"""
    video_name = f"{task}_{number}"
    source_path = SOURCE_DIR / f"{video_name}.mp4"

    # mask_source가 지정되면 masks 폴더 사용, 아니면 기존 mask 폴더
    if mask_source:
        mask_path = BASE_DIR / "video" / "masks" / mask_source / f"{video_name}.mp4"
        output_path = OUTPUT_DIR / mask_source / task / f"{video_name}.mp4"
    else:
        mask_path = MASK_DIR / f"{video_name}.mp4"
        output_path = OUTPUT_DIR / task / f"{video_name}.mp4"

    actual_source = source_url if source_url else str(source_path)
    actual_mask = mask_url if mask_url else str(mask_path)

    if not source_url and not source_path.exists():
        print(f"원본 영상을 찾을 수 없습니다: {source_path}")
        return False
    if not mask_url and not mask_path.exists():
        print(f"마스크 영상을 찾을 수 없습니다: {mask_path}")
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    return process_video_overlay(actual_source, actual_mask, str(output_path), opacity)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Overlay 비디오 생성')
    parser.add_argument('--task', type=str, help='Task 이름 (예: face)')
    parser.add_argument('--number', type=str, help='비디오 번호 (예: 0001)')
    parser.add_argument('--opacity', type=float, default=0.5, help='오버레이 투명도 (0-1)')
    parser.add_argument('--mask-source', type=str, default=None, help='masks 폴더 내 소스 이름 (예: sam3)')
    parser.add_argument('--source-url', type=str, default=None, help='S3 Presigned URL for source video')
    parser.add_argument('--mask-url', type=str, default=None, help='S3 Presigned URL for mask video')

    args = parser.parse_args()

    if args.task and args.number:
        # 단일 비디오 처리
        success = process_single_video(args.task, args.number, args.opacity, args.mask_source, args.source_url, args.mask_url)
        exit(0 if success else 1)
    else:
        # 모든 비디오 처리
        process_all_videos()
