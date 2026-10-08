#!/data/data/com.termux/files/usr/bin/bash
# Stop background crawler daemon on Android Termux
pkill -f run_production_crawler.py 2>/dev/null
termux-wake-unlock 2>/dev/null
echo "⏹️ Đã dừng Crawler và nhả WakeLock trên Android."

