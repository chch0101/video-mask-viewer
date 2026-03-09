"""
시스템 관련 유틸리티 함수 (macOS 다이얼로그, 알림, ffmpeg 설치)
"""
import os
import subprocess
import shutil


def show_dialog(title, message):
    """macOS 네이티브 다이얼로그 표시"""
    try:
        subprocess.run([
            'osascript', '-e',
            f'display dialog "{message}" with title "{title}" buttons {{"확인"}} default button "확인"'
        ], capture_output=True)
    except Exception:
        print(f"[{title}] {message}")


def show_progress_notification(message):
    """macOS 알림 표시"""
    try:
        subprocess.run([
            'osascript', '-e',
            f'display notification "{message}" with title "Video Mask Viewer"'
        ], capture_output=True)
    except Exception:
        print(message)


def ensure_ffmpeg():
    """ffmpeg가 없으면 자동 설치 (Homebrew 경유)"""
    # ffmpeg가 이미 있는지 확인
    if shutil.which('ffmpeg') and shutil.which('ffprobe'):
        print("✅ ffmpeg already installed")
        return True

    print("⚠️ ffmpeg not found, attempting to install...")
    show_progress_notification("ffmpeg를 설치하고 있습니다. 잠시 기다려주세요...")

    # Homebrew 경로 확인 (Apple Silicon + Intel Mac)
    brew_paths = ['/opt/homebrew/bin/brew', '/usr/local/bin/brew']
    brew_cmd = None
    for bp in brew_paths:
        if os.path.exists(bp):
            brew_cmd = bp
            break

    # Homebrew가 없으면 설치
    if brew_cmd is None:
        print("📦 Homebrew 설치 중...")
        show_progress_notification("Homebrew를 먼저 설치합니다...")
        try:
            install_script = subprocess.run(
                ['curl', '-fsSL', 'https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh'],
                capture_output=True, text=True, check=True
            )
            result = subprocess.run(
                ['bash', '-c', install_script.stdout],
                capture_output=True, text=True,
                env={**os.environ, 'NONINTERACTIVE': '1'}
            )
            if result.returncode != 0:
                print(f"Homebrew install error: {result.stderr}")
                show_dialog("설치 오류",
                            "Homebrew 설치에 실패했습니다.\\n터미널에서 수동으로 설치해주세요:\\n"
                            "/bin/bash -c \\\"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\\\"")
                return False

            # 설치 후 경로 재확인
            for bp in brew_paths:
                if os.path.exists(bp):
                    brew_cmd = bp
                    break
        except Exception as e:
            print(f"Homebrew install exception: {e}")
            show_dialog("설치 오류", "Homebrew 설치 중 오류가 발생했습니다.\\n터미널에서 수동으로 설치해주세요.")
            return False

    if brew_cmd is None:
        show_dialog("설치 오류", "Homebrew를 찾을 수 없습니다.")
        return False

    # ffmpeg 설치
    print("📦 ffmpeg 설치 중...")
    show_progress_notification("ffmpeg를 설치 중입니다... (수 분 소요)")
    try:
        result = subprocess.run(
            [brew_cmd, 'install', 'ffmpeg'],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"ffmpeg install error: {result.stderr}")
            show_dialog("설치 오류",
                        "ffmpeg 설치에 실패했습니다.\\n터미널에서 수동으로 실행해주세요:\\nbrew install ffmpeg")
            return False

        print("✅ ffmpeg 설치 완료!")
        show_progress_notification("ffmpeg 설치가 완료되었습니다!")

        # PATH에 brew bin 추가
        brew_bin = os.path.dirname(brew_cmd)
        if brew_bin not in os.environ.get('PATH', ''):
            os.environ['PATH'] = brew_bin + ':' + os.environ.get('PATH', '')

        return True
    except Exception as e:
        print(f"ffmpeg install exception: {e}")
        show_dialog("설치 오류", "ffmpeg 설치 중 오류가 발생했습니다.")
        return False
