# Video Mask Comparison Viewer

비디오 마스크 검증 및 평가를 위한 웹 애플리케이션

## 기능

- 소스 비디오와 마스크 비디오 동시 재생
- 실시간 마스크 오버레이 조정 (투명도, 블렌드 모드)
- 모자이크 비디오 생성 및 비교
- 프레임 단위 탐색 (화살표 키)
- Task별 비디오 필터링
- 다중 프레임 범위 기록 (예: 103~105, 203~214)
- 평가 결과 CSV 자동 저장

## 시작하기

### 1. 로컬에서 실행

```bash
# 백엔드 실행
source venv/bin/activate
python backend/app.py
```

브라우저에서 http://localhost:5004 접속

### 2. 다른 사람과 공유 (ngrok)

#### 방법 1: 자동 스크립트 사용

```bash
# 터미널 1: 백엔드 실행
source venv/bin/activate
python backend/app.py

# 터미널 2: ngrok 실행
./start_ngrok.sh
```

#### 방법 2: 수동 실행

```bash
# 최초 1회: ngrok 인증 설정
ngrok config add-authtoken YOUR_AUTHTOKEN_HERE

# ngrok 실행
ngrok http 5004
```

표시되는 `https://xxxx.ngrok-free.app` URL을 공유하세요!

자세한 내용은 [NGROK_GUIDE.md](NGROK_GUIDE.md) 참조

## 키보드 단축키

- **Space**: 재생/일시정지
- **Tab**: 마스크 on/off
- **← / →**: 1프레임 이동
- **Shift + ← / →**: 30프레임 이동
- **Ctrl/Cmd + S**: CSV 저장

## 폴더 구조

```
260220_valid/
├── video/
│   ├── source/     # 원본 비디오
│   ├── mask/       # 마스크 비디오
│   └── mosaic/     # 모자이크 비디오 (자동 생성)
├── evaluations/    # 평가 결과 CSV
│   ├── face/
│   ├── body/
│   └── text/
├── backend/        # Flask 백엔드
├── frontend/       # React 프론트엔드
└── venv/          # Python 가상환경
```

## 평가 프로세스

1. **Task 선택**: Task Filter에서 평가할 task 선택 (face, body, text 등)
2. **비디오 재생**: 비디오를 재생하며 마스크 품질 확인
3. **문제 발견 시**:
   - X 선택
   - "범위 추가" 클릭
   - 문제 시작 프레임에서 "시작" 버튼 클릭
   - 문제 종료 프레임에서 "끝" 버튼 클릭
   - 여러 구간이 있으면 "범위 추가"로 계속 추가
4. **문제 없으면**: O 선택
5. **저장**: Ctrl/Cmd+S 또는 "CSV 저장" 버튼
6. **자동 진행**: 다음 비디오로 자동 이동

## 기술 스택

- **Frontend**: React, Vite
- **Backend**: Flask, Python
- **Video Processing**: FFmpeg
- **Sharing**: ngrok

## 트러블슈팅

### 비디오가 로드되지 않음
- 비디오 변환 중일 수 있습니다 (화면에 표시됨)
- 1-2분 대기 후 자동으로 로드됩니다

### 마스크가 깜빡임
- 재생 중 배속 변경 시 일시적으로 발생 가능
- 일시정지 후 재생하면 해결됩니다

### ngrok URL 공유 후 접속 안 됨
- 백엔드가 실행 중인지 확인
- ngrok이 종료되지 않았는지 확인
- 방화벽 설정 확인

## 라이선스

Internal Use Only
