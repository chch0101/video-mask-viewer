#!/bin/bash

# Video Mask Comparison Viewer - Run Script
# Backend (Flask) + Frontend (React) 동시 실행

cd "$(dirname "$0")"

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Video Mask Comparison Viewer${NC}"
echo -e "${GREEN}========================================${NC}"

# 종료 시 모든 백그라운드 프로세스 종료
cleanup() {
    echo -e "\n${YELLOW}서버를 종료합니다...${NC}"
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    exit 0
}
trap cleanup SIGINT SIGTERM

# Backend 의존성 설치 및 실행
echo -e "\n${YELLOW}[1/4] Backend 의존성 확인 중...${NC}"
cd backend
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}가상환경 생성 중...${NC}"
    python3 -m venv venv
fi
source venv/bin/activate
pip install -q -r requirements.txt

echo -e "${GREEN}[2/4] Backend 서버 시작 (port 5004)...${NC}"
python app.py &
BACKEND_PID=$!
cd ..

# Frontend 의존성 설치 및 실행
echo -e "\n${YELLOW}[3/4] Frontend 의존성 확인 중...${NC}"
cd frontend
if [ ! -d "node_modules" ]; then
    echo -e "${YELLOW}npm install 실행 중...${NC}"
    npm install
fi

echo -e "${GREEN}[4/4] Frontend 서버 시작 (port 3000)...${NC}"
npm run dev &
FRONTEND_PID=$!
cd ..

echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}  서버가 시작되었습니다!${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "  Frontend: ${YELLOW}http://localhost:3000${NC}"
echo -e "  Backend:  ${YELLOW}http://localhost:5004${NC}"
echo -e "  External: ${GREEN}https://oliver-unmagnetical-softly.ngrok-free.dev${NC}"
echo -e "\n  종료하려면 ${RED}Ctrl+C${NC}를 누르세요."
echo -e "${GREEN}========================================${NC}\n"

echo -e "${YELLOW}[5/5] ngrok 시작 중... (ngrok 창이 열립니다)${NC}"
sleep 1
ngrok http --url=oliver-unmagnetical-softly.ngrok-free.dev 3000
