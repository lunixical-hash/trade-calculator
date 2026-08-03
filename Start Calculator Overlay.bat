@echo off
cd /d "%~dp0"
python calculator_overlay.py
if errorlevel 1 pause
