#!/data/data/com.termux/files/usr/bin/bash
# Start background daemon on Android Termux
termux-wake-lock 2>/dev/null
nohup python scripts/run_production_crawler.py > crawler.log 2>&1 &
PID=$!
echo "🚀 Crawler da khoi chay an ngam [PID: $PID]"
echo "📄 Xem nhip crawl truc tiep: tail -f crawler.log"
echo "⏹️ Lenh dung khi can: bash scripts/stop_termux_daemon.sh"

