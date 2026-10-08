#!/data/data/com.termux/files/usr/bin/bash
# ==========================================================
# Script khoi tao va chay Crawler tren Termux (Android)
# Tac gia: Antigravity Big Data Team
# ==========================================================

echo "=========================================================="
echo "🚌 HỆ THỐNG THU THẬP DỮ LIỆU XE BUÝT HÀ NỘI TRÊN TERMUX"
echo "=========================================================="

# 1. Kiem tra va cai dat goi he thong
echo "[1/4] Kiem tra cac goi he thong (python, git, openssh)..."
pkg update -y
pkg install -y python git openssh

# 2. Cai dat thu vien phu tro cho Python
echo "[2/4] Cai dat thu vien Python huggingface_hub (neu chua co)..."
pip install huggingface_hub --quiet 2>/dev/null || echo "   (Luu y: pip huggingface_hub bo qua neu co loi, se luu cuc bo)"

# 3. Kiem tra WakeLock de khong bi Android tat ngam
echo "[3/4] Yeu cau WakeLock de giu tien trinh chay ngam khi tat man hinh..."
termux-wake-lock 2>/dev/null || echo "   (Hay keo thanh thong bao xuong va bam 'Acquire WakeLock' neu chua bat)"

# 4. Kiem tra file khoa API
echo "[4/4] Kiem tra API Keys..."
if [ ! -f "Test_tomtom/TOMTOM_API_KEY.txt" ]; then
    mkdir -p Test_tomtom
    echo ">> Chua co file Test_tomtom/TOMTOM_API_KEY.txt."
    read -p ">> Nhap TomTom API Key cua ban (hoac Enter de bo qua): " TT_KEY
    if [ ! -z "$TT_KEY" ]; then
        echo "$TT_KEY" > Test_tomtom/TOMTOM_API_KEY.txt
        echo "   [OK] Da luu TomTom Key!"
    fi
fi

if [ ! -f "access_token_hf.txt" ]; then
    echo ">> Chua co file access_token_hf.txt."
    read -p ">> Nhap Hugging Face Token (hoac Enter neu chi muon luu tren dien thoai): " HF_KEY
    if [ ! -z "$HF_KEY" ]; then
        echo "$HF_KEY" > access_token_hf.txt
        echo "   [OK] Da luu HF Token!"
    fi
fi

echo "=========================================================="
echo "✅ Cai dat hoan tat! Chon che do chay:"
echo "   1) Chay truc tiep tren man hinh Termux (de kiem tra)"
echo "   2) Chay an ngam (background daemon qua nohup)"
echo "=========================================================="
read -p "Nhap lua chon [1 hoac 2]: " CHOICE

if [ "$CHOICE" == "2" ]; then
    nohup python scripts/run_production_crawler.py > crawler.log 2>&1 &
    PID=$!
    echo "🚀 Crawler dang chay ngam voi PID: $PID"
    echo "📄 Xem log thoi gian thuc: tail -f crawler.log"
    echo "⏹️ Dung tien trinh: bash scripts/stop_termux_daemon.sh"
else
    python scripts/run_production_crawler.py
fi

