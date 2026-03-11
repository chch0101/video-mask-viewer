import os
import sys
import cv2
import numpy as np
import subprocess
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from threading import Thread
from queue import Queue

# 현재 파일 기준으로 프로젝트 루트를 PYTHONPATH에 추가
PROJECT_ROOT = Path(__file__).parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.video_utils import get_video_pairs

# M1 Pro 최적화 기본값
DEFAULT_WORKERS = 8   # M1 Pro 성능 코어 수
DEFAULT_BATCH = 32    # 배치 크기
DEFAULT_QUEUE = 4     # 파이프라인 큐 크기 (배치 수)
DEFAULT_PARALLEL = 2  # 동시 처리 영상 수

# 기본 경로 설정
BASE_DIR = Path(__file__).parent
SOURCE_DIR = BASE_DIR / "video" / "source"
MASK_DIR = BASE_DIR / "video" / "masks" / "rexomni"
OUTPUT_DIR = BASE_DIR / "video" / "mosaic"


def apply_mosaic(image, mask, block_size=15):
    """
    마스크 영역에 모자이크 효과 적용

    Args:
        image: 원본 이미지 (BGR)
        mask: 마스크 이미지 (마스킹 영역이 0이 아닌 값)
        block_size: 모자이크 블록 크기 (클수록 더 흐릿함)

    Returns:
        모자이크가 적용된 이미지
    """
    result = image.copy()
    h, w = image.shape[:2]

    # 마스크를 그레이스케일로 변환 (컬러인 경우)
    if len(mask.shape) == 3:
        mask_gray = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)
    else:
        mask_gray = mask

    # 마스크 영역 찾기 (0이 아닌 모든 픽셀)
    _, binary_mask = cv2.threshold(mask_gray, 1, 255, cv2.THRESH_BINARY)

    # 마스크 영역이 없으면 원본 반환
    if cv2.countNonZero(binary_mask) == 0:
        return result

    # 모자이크 효과: 작게 줄였다가 다시 키움
    small = cv2.resize(image, (w // block_size, h // block_size), interpolation=cv2.INTER_LINEAR)
    mosaic = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)

    # 마스크 영역에만 모자이크 적용
    binary_mask_3ch = cv2.cvtColor(binary_mask, cv2.COLOR_GRAY2BGR)
    result = np.where(binary_mask_3ch > 0, mosaic, image)

    return result.astype(np.uint8)


def apply_mosaic_contour(image, mask, block_size=15):
    """
    마스크의 각 컨투어(객체)별로 개별 모자이크 적용
    더 정밀한 모자이크 효과를 위한 방법

    Args:
        image: 원본 이미지 (BGR)
        mask: 마스크 이미지
        block_size: 모자이크 블록 크기

    Returns:
        모자이크가 적용된 이미지
    """
    result = image.copy()

    # 마스크를 그레이스케일로 변환
    if len(mask.shape) == 3:
        mask_gray = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)
    else:
        mask_gray = mask

    # 이진화
    _, binary_mask = cv2.threshold(mask_gray, 1, 255, cv2.THRESH_BINARY)

    # 컨투어 찾기
    contours, _ = cv2.findContours(binary_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    for contour in contours:
        # 바운딩 박스 구하기
        x, y, w, h = cv2.boundingRect(contour)

        if w < 5 or h < 5:  # 너무 작은 영역은 스킵
            continue

        # 해당 영역 추출
        roi = image[y:y+h, x:x+w]

        # 모자이크 적용
        # 블록 크기를 영역 크기에 맞게 조정
        effective_block = max(2, min(block_size, min(w, h) // 4))
        small_w = max(1, w // effective_block)
        small_h = max(1, h // effective_block)

        small = cv2.resize(roi, (small_w, small_h), interpolation=cv2.INTER_LINEAR)
        mosaic_roi = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)

        # 해당 컨투어 영역에만 적용하기 위한 로컬 마스크
        local_mask = np.zeros((h, w), dtype=np.uint8)
        shifted_contour = contour - [x, y]
        cv2.drawContours(local_mask, [shifted_contour], -1, 255, -1)

        # 마스크 영역에만 모자이크 적용
        local_mask_3ch = cv2.cvtColor(local_mask, cv2.COLOR_GRAY2BGR)
        roi_result = np.where(local_mask_3ch > 0, mosaic_roi, roi)
        result[y:y+h, x:x+w] = roi_result

    return result.astype(np.uint8)


def process_video(source_path: str, mask_path: str, output_path: str,
                  block_size: int = 15, use_contour: bool = True,
                  num_workers: int = DEFAULT_WORKERS, batch_size: int = DEFAULT_BATCH):
    """
    원본 영상과 마스크 영상을 합쳐서 모자이크 영상 생성 (배치 처리)
    메모리 캐싱 대신 2-포인터 방식으로 실시간 스트리밍 인덱스 맵핑을 적용하여 OOM 방지와 싱크 해결
    """
    start_time = time.time()

    source_cap = cv2.VideoCapture(source_path)
    mask_cap = cv2.VideoCapture(mask_path)

    if not source_cap.isOpened():
        print(f"원본 영상을 열 수 없습니다: {source_path}")
        return False

    if not mask_cap.isOpened():
        print(f"마스크 영상을 열 수 없습니다: {mask_path}")
        source_cap.release()
        return False

    width = int(source_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(source_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    original_fps = source_cap.get(cv2.CAP_PROP_FPS)
    original_total_frames = int(source_cap.get(cv2.CAP_PROP_FRAME_COUNT))
    original_mask_frames = int(mask_cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # 생성할 영상은 완벽히 source 원본과 프레임 수/FPS 1:1 매칭
    target_fps = original_fps
    total_frames = original_total_frames

    # 출력 폴더 생성
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    print(f"처리 중: {os.path.basename(source_path)}")
    print(f"  - 해상도: {width}x{height}, 서빙 FPS: {target_fps:.2f}")
    print(f"  - 프레임 매칭: Source({original_total_frames}) <-> Mask({original_mask_frames})")

    # FFmpeg 인코더 설정 (환경에 따른 하드웨어 가속 및 속도 최적화)
    # 기본은 libx264 (CPU) + ultrafast
    encoder_cmd = ['-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18']
    
    # macOS 하드웨어 가속 확인
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
        '-r', str(target_fps), '-i', '-',
        *encoder_cmd,
        '-pix_fmt', 'yuv420p', '-v', 'error',
        output_path
    ]
    ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    mosaic_func = apply_mosaic_contour if use_contour else apply_mosaic

    # 파이프라인 큐
    read_queue = Queue(maxsize=DEFAULT_QUEUE)
    write_queue = Queue(maxsize=DEFAULT_QUEUE)
    frame_count = [0]

    def process_frame(args):
        idx, source_frame, mask_frame = args
        if mask_frame is None:
            return idx, source_frame
        if mask_frame.shape[:2] != source_frame.shape[:2]:
            mask_frame = cv2.resize(mask_frame, (width, height))
        return idx, mosaic_func(source_frame, mask_frame, block_size)

    def reader_thread():
        current_source_idx = 0
        current_mask_idx = -1
        last_mask_frame = None

        while True:
            batch = []
            for _ in range(batch_size):
                ret_source, source_frame = source_cap.read()
                if not ret_source:
                    break
                
                # 인덱스 기반 매핑 수식 (source 내 위치 비율을 그대로 mask 위치 비율로 적용)
                if original_total_frames > 0 and original_mask_frames > 0:
                    target_mask_idx = int(current_source_idx * (original_mask_frames / original_total_frames))
                else:
                    target_mask_idx = current_source_idx
                    
                # 범위 초과 방지
                if target_mask_idx >= original_mask_frames:
                    target_mask_idx = original_mask_frames - 1
                
                # target_mask_idx를 만날 때까지 mask를 읽어서 전진시킨다 (메모리 로드 방지)
                while current_mask_idx < target_mask_idx:
                    ret_mask, mask_frame = mask_cap.read()
                    if not ret_mask:
                        break
                    last_mask_frame = mask_frame
                    current_mask_idx += 1
                
                batch.append((current_source_idx, source_frame, last_mask_frame))
                current_source_idx += 1
            
            if not batch:
                read_queue.put(None)
                break
            read_queue.put(batch)

    def writer_thread():
        while True:
            results = write_queue.get()
            if results is None:
                break
            results.sort(key=lambda x: x[0])
            for _, result_frame in results:
                ffmpeg_proc.stdin.write(result_frame.tobytes())
                frame_count[0] += 1
            progress = (frame_count[0] / total_frames) * 100 if total_frames > 0 else 0
            print(f"  진행: {frame_count[0]}/{total_frames} ({progress:.1f}%)", end='\r')

    reader = Thread(target=reader_thread)
    writer = Thread(target=writer_thread)
    reader.start()
    writer.start()

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        while True:
            batch = read_queue.get()
            if batch is None:
                write_queue.put(None)
                break
            results = list(executor.map(process_frame, batch))
            write_queue.put(results)

    reader.join()
    writer.join()

    ffmpeg_proc.stdin.close()
    ffmpeg_proc.wait()
    source_cap.release()
    mask_cap.release()

    actual_frame_count = frame_count[0]
    elapsed_time = time.time() - start_time
    processing_fps = actual_frame_count / elapsed_time if elapsed_time > 0 else 0

    print(f"\n  완료! 저장: {output_path}")
    print(f"  - 처리 시간: {elapsed_time:.1f}초 ({processing_fps:.1f} fps)")

    return True


def process_single_video(task: str, number: str, block_size: int = 15,
                         num_workers: int = DEFAULT_WORKERS, batch_size: int = DEFAULT_BATCH,
                         use_contour: bool = True, mask_source: str = None,
                         source_url: str = None, mask_url: str = None):
    """단일 비디오 처리"""
    video_name = f"{task}_{number}"
    source_path = SOURCE_DIR / f"{video_name}.mp4"

    # mask_source가 지정되면 masks 폴더 사용, 아니면 기본 MASK_DIR 사용
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
    return process_video(actual_source, actual_mask, str(output_path),
                         block_size, use_contour=use_contour,
                         num_workers=num_workers, batch_size=batch_size)


def _process_video_wrapper(args):
    """멀티프로세싱용 래퍼"""
    source, mask, output, block_size, use_contour, num_workers, batch_size = args
    return process_video(source, mask, output, block_size, use_contour, num_workers, batch_size)


def process_all_videos(task: str = None, block_size: int = 15,
                       num_workers: int = DEFAULT_WORKERS, batch_size: int = DEFAULT_BATCH,
                       use_contour: bool = True, parallel: int = 1):
    """모든 비디오 처리"""
    pairs = get_video_pairs(task)

    if not pairs:
        print("처리할 비디오 쌍을 찾을 수 없습니다.")
        return

    total_start = time.time()
    print(f"총 {len(pairs)}개의 비디오를 처리합니다.")

    if parallel > 1:
        # 병렬 처리: 여러 영상 동시 처리
        print(f"병렬 처리: {parallel}개 영상 동시 처리\n")
        # 병렬 처리 시 워커 수 분배
        workers_per_video = max(2, num_workers // parallel)

        tasks = []
        for pair in pairs:
            output_path = OUTPUT_DIR / pair["task"] / f"{pair['video_name']}.mp4"
            tasks.append((pair["source"], pair["mask"], str(output_path),
                         block_size, use_contour, workers_per_video, batch_size))

        with ProcessPoolExecutor(max_workers=parallel) as executor:
            list(executor.map(_process_video_wrapper, tasks))
    else:
        # 순차 처리
        for i, pair in enumerate(pairs, 1):
            print(f"\n[{i}/{len(pairs)}]")
            output_path = OUTPUT_DIR / pair["task"] / f"{pair['video_name']}.mp4"
            process_video(pair["source"], pair["mask"], str(output_path),
                          block_size, use_contour=use_contour,
                          num_workers=num_workers, batch_size=batch_size)

    total_elapsed = time.time() - total_start
    print(f"\n전체 완료! 총 소요 시간: {total_elapsed:.1f}초")


def process_batch(mask_source: str = "rexomni", block_size: int = 15,
                  num_workers: int = DEFAULT_WORKERS, batch_size: int = DEFAULT_BATCH,
                  use_contour: bool = True):
    """
    video/source의 모든 영상을 video/masks/{mask_source}와 매칭하여
    video/result에 모자이크 처리 후 저장 (H.264 코덱)
    - source에 있지만 mask에 없는 영상은 스킵
    """
    result_dir = BASE_DIR / "video" / "result"
    masks_dir = BASE_DIR / "video" / "masks" / mask_source

    if not SOURCE_DIR.exists():
        print(f"소스 폴더가 없습니다: {SOURCE_DIR}")
        return

    if not masks_dir.exists():
        print(f"마스크 폴더가 없습니다: {masks_dir}")
        return

    # 소스 폴더의 모든 mp4 파일 스캔
    source_files = sorted(SOURCE_DIR.glob("*.mp4"))

    if not source_files:
        print("처리할 소스 파일이 없습니다.")
        return

    # 마스크가 있는 파일만 필터링
    pairs = []
    skipped = []
    for source_path in source_files:
        mask_path = masks_dir / source_path.name
        if mask_path.exists():
            pairs.append({
                'source': str(source_path),
                'mask': str(mask_path),
                'output': str(result_dir / source_path.name)
            })
        else:
            skipped.append(source_path.name)

    print(f"=== 배치 처리 시작 ===")
    print(f"소스 폴더: {SOURCE_DIR}")
    print(f"마스크 폴더: {masks_dir}")
    print(f"결과 폴더: {result_dir}")
    print(f"처리할 영상: {len(pairs)}개")
    print(f"스킵 (마스크 없음): {len(skipped)}개")

    if skipped:
        print(f"\n스킵된 영상: {', '.join(skipped[:5])}{'...' if len(skipped) > 5 else ''}")

    if not pairs:
        print("처리할 영상이 없습니다.")
        return

    result_dir.mkdir(parents=True, exist_ok=True)

    total_start = time.time()
    success_count = 0
    fail_count = 0

    for i, pair in enumerate(pairs, 1):
        print(f"\n[{i}/{len(pairs)}]")
        try:
            result = process_video(
                pair['source'], pair['mask'], pair['output'],
                block_size, use_contour=use_contour,
                num_workers=num_workers, batch_size=batch_size
            )
            if result:
                success_count += 1
            else:
                fail_count += 1
        except Exception as e:
            print(f"  에러: {e}")
            fail_count += 1

    total_elapsed = time.time() - total_start
    print(f"\n=== 배치 처리 완료 ===")
    print(f"성공: {success_count}개, 실패: {fail_count}개")
    print(f"총 소요 시간: {total_elapsed:.1f}초")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="원본 영상과 마스크를 합쳐서 모자이크 영상 생성")
    parser.add_argument("--task", type=str, help="처리할 task 유형 (face, tattoo, license, text)")
    parser.add_argument("--number", type=str, help="처리할 비디오 번호 (예: 0001)")
    parser.add_argument("--all", action="store_true", help="모든 비디오 처리")
    parser.add_argument("--batch-all", action="store_true",
                        help="배치 모드: source의 모든 영상을 masks/{mask-source}와 매칭하여 result에 저장")
    parser.add_argument("--block", type=int, default=15, help="모자이크 블록 크기 (기본값: 15, 클수록 더 흐릿함)")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help=f"병렬 처리 워커 수 (기본값: {DEFAULT_WORKERS})")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH, help=f"배치 크기 (기본값: {DEFAULT_BATCH})")
    parser.add_argument("--fast", action="store_true", help="빠른 모드 (컨투어 처리 생략)")
    parser.add_argument("--parallel", "-p", type=int, default=1,
                        help="동시 처리 영상 수 (기본값: 1, 2-3 권장)")
    parser.add_argument("--mask-source", type=str, default="rexomni",
                        help="masks 폴더 내 소스 이름 (기본값: rexomni)")
    parser.add_argument("--source-url", type=str, default=None,
                        help="S3 Presigned URL for source video")
    parser.add_argument("--mask-url", type=str, default=None,
                        help="S3 Presigned URL for mask video")

    args = parser.parse_args()
    use_contour = not args.fast

    if args.batch_all:
        # 배치 모드: source 전체를 masks/{mask_source}와 매칭하여 result에 저장
        process_batch(args.mask_source, args.block, args.workers, args.batch_size, use_contour)
    elif args.task and args.number:
        # 단일 비디오 처리
        success = process_single_video(args.task, args.number, args.block, args.workers,
                                       args.batch_size, use_contour, args.mask_source,
                                       args.source_url, args.mask_url)
        exit(0 if success else 1)
    elif args.all or args.task:
        # 모든 비디오 또는 특정 task의 모든 비디오 처리
        process_all_videos(args.task, args.block, args.workers, args.batch_size, use_contour, args.parallel)
    else:
        # 사용법 출력
        print("사용법:")
        print("  배치 처리: python mosaic.py --batch-all")
        print("  배치 처리 (다른 마스크): python mosaic.py --batch-all --mask-source sam3")
        print("  단일 비디오: python mosaic.py --task face --number 0001")
        print("  특정 task 전체: python mosaic.py --task face --all")
        print("  모든 비디오: python mosaic.py --all")
        print("")
        print("옵션:")
        print("  --batch-all: source 전체를 masks/{mask-source}와 매칭하여 result에 저장")
        print("  --mask-source: 마스크 폴더 이름 (기본값: rexomni)")
        print("  --block: 모자이크 블록 크기 (기본값 15, 클수록 더 강한 모자이크)")
        print(f"  --workers: 병렬 처리 워커 수 (기본값 {DEFAULT_WORKERS})")
        print(f"  --batch-size: 배치 크기 (기본값 {DEFAULT_BATCH})")
        print("  --fast: 빠른 모드 (컨투어 처리 생략)")
