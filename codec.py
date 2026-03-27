import subprocess
import os
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse


def get_video_codec(file_path: str) -> str:
    """Get the video codec of a file."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip()


def convert_to_h264(input_path: str, preset: str = "fast", crf: int = 23) -> bool:
    """Convert a video file to H.264 codec."""
    input_file = Path(input_path)
    temp_output = input_file.parent / f"{input_file.stem}_h264_temp.mp4"

    cmd = [
        "ffmpeg", "-i", str(input_file),
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf),
        "-c:a", "copy",
        "-y",
        str(temp_output)
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        os.replace(temp_output, input_file)
        return True
    except subprocess.CalledProcessError as e:
        if temp_output.exists():
            temp_output.unlink()
        print(f"Error converting {input_file.name}: {e.stderr}")
        return False


def process_directory(
    directory: str,
    preset: str = "fast",
    crf: int = 23,
    workers: int = 1,
    skip_h264: bool = True
):
    """Process all mp4 files in a directory."""
    dir_path = Path(directory)
    mp4_files = list(dir_path.glob("*.mp4"))

    if not mp4_files:
        print(f"No mp4 files found in {directory}")
        return

    print(f"Found {len(mp4_files)} mp4 files")

    # Filter files that need conversion
    files_to_convert = []
    for f in mp4_files:
        codec = get_video_codec(str(f))
        if skip_h264 and codec == "h264":
            print(f"Skipping {f.name} (already H.264)")
        else:
            files_to_convert.append(f)

    if not files_to_convert:
        print("All files are already H.264")
        return

    print(f"\nConverting {len(files_to_convert)} files to H.264...")
    print(f"Settings: preset={preset}, crf={crf}, workers={workers}\n")

    completed = 0
    failed = 0

    def convert_file(file_path):
        return file_path, convert_to_h264(str(file_path), preset, crf)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(convert_file, f): f for f in files_to_convert}

        for future in as_completed(futures):
            file_path, success = future.result()
            if success:
                completed += 1
                print(f"[{completed + failed}/{len(files_to_convert)}] Converted: {file_path.name}")
            else:
                failed += 1
                print(f"[{completed + failed}/{len(files_to_convert)}] Failed: {file_path.name}")

    print(f"\nDone! Converted: {completed}, Failed: {failed}")


def main():
    parser = argparse.ArgumentParser(description="Convert video files to H.264 codec")
    parser.add_argument(
        "directory",
        nargs="?",
        default="video/masks/sam3",
        help="Directory containing mp4 files (default: video/masks/sam3)"
    )
    parser.add_argument(
        "--preset",
        default="fast",
        choices=["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"],
        help="FFmpeg encoding preset (default: fast)"
    )
    parser.add_argument(
        "--crf",
        type=int,
        default=23,
        help="Constant Rate Factor 0-51, lower=better quality (default: 23)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=2,
        help="Number of parallel workers (default: 2)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Convert even if already H.264"
    )

    args = parser.parse_args()

    if not Path(args.directory).exists():
        print(f"Error: Directory '{args.directory}' does not exist")
        sys.exit(1)

    process_directory(
        args.directory,
        preset=args.preset,
        crf=args.crf,
        workers=args.workers,
        skip_h264=not args.force
    )


if __name__ == "__main__":
    main()
