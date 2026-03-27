#!/usr/bin/env python3
"""
마스크 비디오를 H.264 코덱으로 변환하는 스크립트
사용법: python convert_masks.py --source yolo11
"""
import os
import sys
import subprocess
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import time

BASE_DIR = Path(__file__).parent
MASKS_DIR = BASE_DIR / "video" / "masks"


def convert_video(input_path: Path, output_path: Path) -> bool:
    """비디오를 H.264 코덱으로 변환"""
    try:
        # 임시 파일로 먼저 변환
        temp_path = output_path.with_suffix('.tmp.mp4')

        cmd = [
            'ffmpeg', '-y', '-i', str(input_path),
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
            '-pix_fmt', 'yuv420p',
            '-an',  # 오디오 제거 (마스크에는 필요 없음)
            str(temp_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            # 성공하면 원본을 대체
            temp_path.rename(output_path)
            return True
        else:
            print(f"  에러: {result.stderr[:200]}")
            if temp_path.exists():
                temp_path.unlink()
            return False
    except Exception as e:
        print(f"  예외: {e}")
        return False


def get_codec(video_path: Path) -> str:
    """비디오 코덱 확인"""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=codec_name', '-of', 'csv=p=0',
             str(video_path)],
            capture_output=True, text=True
        )
        return result.stdout.strip()
    except:
        return "unknown"


def process_mask_source(source_name: str, dry_run: bool = False, workers: int = 4):
    """특정 마스크 소스의 모든 비디오 변환"""
    source_dir = MASKS_DIR / source_name

    if not source_dir.exists():
        print(f"마스크 폴더가 없습니다: {source_dir}")
        return

    # 변환이 필요한 파일 찾기
    videos = sorted(source_dir.glob("*.mp4"))

    if not videos:
        print(f"변환할 비디오가 없습니다: {source_dir}")
        return

    # 코덱 확인
    need_convert = []
    already_h264 = []

    print(f"=== 코덱 확인 중: {source_name} ({len(videos)}개 파일) ===")

    for video in videos:
        codec = get_codec(video)
        if codec == 'h264':
            already_h264.append(video.name)
        else:
            need_convert.append((video, codec))

    print(f"  - 이미 H.264: {len(already_h264)}개")
    print(f"  - 변환 필요: {len(need_convert)}개")

    if not need_convert:
        print("모든 파일이 이미 H.264입니다.")
        return

    if dry_run:
        print("\n변환이 필요한 파일:")
        for video, codec in need_convert[:10]:
            print(f"  - {video.name} ({codec})")
        if len(need_convert) > 10:
            print(f"  ... 외 {len(need_convert) - 10}개")
        return

    # 변환 시작
    print(f"\n=== 변환 시작 ({workers}개 병렬) ===")
    start_time = time.time()
    success = 0
    failed = 0

    def convert_one(args):
        idx, total, video, codec = args
        print(f"[{idx}/{total}] {video.name} ({codec} -> h264)...")
        if convert_video(video, video):
            return True
        return False

    tasks = [(i+1, len(need_convert), v, c) for i, (v, c) in enumerate(need_convert)]

    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(convert_one, tasks))

    success = sum(1 for r in results if r)
    failed = len(results) - success

    elapsed = time.time() - start_time
    print(f"\n=== 완료 ===")
    print(f"성공: {success}개, 실패: {failed}개")
    print(f"소요 시간: {elapsed:.1f}초")


def main():
    parser = argparse.ArgumentParser(description="마스크 비디오를 H.264로 변환")
    parser.add_argument("--source", required=True, help="마스크 소스 이름 (예: yolo11)")
    parser.add_argument("--dry-run", action="store_true", help="실제 변환 없이 확인만")
    parser.add_argument("--workers", type=int, default=4, help="병렬 처리 수 (기본값: 4)")

    args = parser.parse_args()

    process_mask_source(args.source, args.dry_run, args.workers)


if __name__ == "__main__":
    main()
