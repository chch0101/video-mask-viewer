"""
비디오 관련 공통 유틸리티 함수
"""
import os
import glob
import re
from pathlib import Path

# 기본 경로 설정
BASE_DIR = Path(__file__).parent.parent
SOURCE_DIR = BASE_DIR / "video" / "source"
MASK_DIR = BASE_DIR / "video" / "mask"


def get_video_pairs(task: str = None) -> list:
    """source와 mask 폴더에서 매칭되는 비디오 쌍 찾기"""
    pairs = []

    if task:
        pattern = f"{task}_*.mp4"
    else:
        pattern = "*.mp4"

    source_files = sorted(glob.glob(str(SOURCE_DIR / pattern)))

    for source_path in source_files:
        filename = os.path.basename(source_path)
        mask_path = MASK_DIR / filename

        if mask_path.exists():
            # 파일명에서 task와 번호 추출 (예: face_0001.mp4 -> face, 0001)
            match = re.match(r"(.+)_(\d+)\.mp4", filename)
            if match:
                task_name = match.group(1)
                number = match.group(2)
                video_name = f"{task_name}_{number}"
                pairs.append({
                    "source": source_path,
                    "mask": str(mask_path),
                    "task": task_name,
                    "number": number,
                    "video_name": video_name
                })

    return pairs
