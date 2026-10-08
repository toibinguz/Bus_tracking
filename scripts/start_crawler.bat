@echo off
title HUST Bus Cluster 24/7 Production Crawler
echo ======================================================================
echo   DANG KHOI CHAY CRAWLER CU DONG DU LIEU XE BUYT BACH KHOA (5 TUYEN)
echo   Khung gio hoat dong: 05:00 - 22:00 (Tu dong ngu ban dem)
echo ======================================================================
cd /d "%~dp0\.."
python scripts\run_production_crawler.py
pause

