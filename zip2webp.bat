@echo off
title zip2webp - ZIP图片批量转WebP
cd /d "%~dp0"
python "%~dp0zip2webp.py" %*
pause
