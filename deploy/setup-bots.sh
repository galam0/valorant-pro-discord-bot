#!/usr/bin/env bash
# Oracle Cloud(Ubuntu 24.04) 서버 한 대에 디스코드 봇 여러 개를 올리는 설치 스크립트.
# 사용법: 서버에 접속한 뒤  bash setup-bots.sh
# - 봇마다 폴더(/opt/bots/<이름>), 가상환경, 비밀값 파일(.env), 자동 시작 서비스(systemd)를 만든다.
# - 비밀값(.env)은 직접 채운다. 이 스크립트는 토큰을 모른다.
set -euo pipefail

# 이름|GitHub 저장소|실행 명령|PORT(봇끼리 겹치지 않게)
BOTS=(
  "valorant|galam0/valorant-pro-discord-bot|-m bot.main|8001"
  "discord|galam0/discord-bot|main.py|8002"
  "football|galam0/football-scoreboard-bot|bot.py|8003"
  "travel|galam0/bus-seat-discord-bot|bot.py|8004"
  "pokebot|galam0/pokebot|bot.py|8005"
)
BASE=/opt/bots
RUN_USER="$(id -un)"

echo "== 기본 프로그램 설치 =="
sudo apt-get update -y
sudo apt-get install -y git python3 python3-venv python3-pip build-essential libjpeg-dev zlib1g-dev

# 메모리가 4GB보다 작으면 스왑(디스크를 임시 메모리로)을 만들어 둔다
MEM_MB=$(free -m | awk '/^Mem:/{print $2}')
if [ "$MEM_MB" -lt 4000 ] && ! swapon --show | grep -q .; then
  echo "== 스왑 2GB 생성 (메모리 ${MEM_MB}MB) =="
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
  sudo mkswap /swapfile && sudo swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

sudo mkdir -p "$BASE" && sudo chown "$RUN_USER":"$RUN_USER" "$BASE"

for entry in "${BOTS[@]}"; do
  IFS='|' read -r name repo cmd port <<<"$entry"
  dir="$BASE/$name"
  echo "== [$name] 설치 =="
  if [ ! -d "$dir/.git" ]; then
    git clone "https://github.com/$repo.git" "$dir" || { echo "!! [$name] 저장소를 받지 못했어요(비공개 저장소일 수 있음). 건너뜁니다."; continue; }
  fi
  [ -d "$dir/venv" ] || python3 -m venv "$dir/venv"
  "$dir/venv/bin/pip" install -q --upgrade pip
  [ -f "$dir/requirements.txt" ] && "$dir/venv/bin/pip" install -q -r "$dir/requirements.txt"

  if [ ! -f "$dir/.env" ]; then
    printf '# 이 봇의 비밀값. 예) Render 대시보드 Environment 탭의 값을 그대로 옮긴다.\nDISCORD_TOKEN=\nPORT=%s\n' "$port" > "$dir/.env"
  fi
  chmod 600 "$dir/.env"

  sudo tee "/etc/systemd/system/bot-$name.service" >/dev/null <<UNIT
[Unit]
Description=Discord bot $name
After=network-online.target
Wants=network-online.target

[Service]
User=$RUN_USER
WorkingDirectory=$dir
EnvironmentFile=$dir/.env
ExecStart=$dir/venv/bin/python $cmd
Restart=always
RestartSec=15

[Install]
WantedBy=multi-user.target
UNIT
done
sudo systemctl daemon-reload

# 관리용 짧은 명령: botctl status | logs <이름> | restart <이름> | update <이름> | start <이름>
sudo tee /usr/local/bin/botctl >/dev/null <<'CTL'
#!/usr/bin/env bash
set -e
case "${1:-}" in
  status)  systemctl list-units 'bot-*' --no-pager --all ;;
  logs)    journalctl -u "bot-$2" -n "${3:-60}" --no-pager ;;
  follow)  journalctl -u "bot-$2" -f ;;
  start)   sudo systemctl enable --now "bot-$2" ;;
  restart) sudo systemctl restart "bot-$2" ;;
  stop)    sudo systemctl disable --now "bot-$2" ;;
  update)  cd "/opt/bots/$2" && git pull --ff-only && venv/bin/pip install -q -r requirements.txt && sudo systemctl restart "bot-$2" ;;
  *) echo "사용법: botctl status | logs <이름> [줄수] | follow <이름> | start|restart|stop|update <이름>" ;;
esac
CTL
sudo chmod +x /usr/local/bin/botctl

echo
echo "== 설치 끝 =="
echo "다음 순서로 봇마다 진행하세요:"
echo "  1) nano $BASE/<이름>/.env      ← 비밀값 채우기 (저장: Ctrl+O, Enter / 종료: Ctrl+X)"
echo "  2) botctl start <이름>         ← 시작 (재부팅해도 자동 시작)"
echo "  3) botctl logs <이름>          ← 로그 확인"
