@echo off
echo Starting Stock Analysis Dashboard...
echo.

start "Backend" cmd /c "cd /mnt/d/Bio_analysis/software/Stock_analysis/backend && /home/ne0tea/miniconda3/envs/stockPanel/bin/python main.py"
timeout /t 3 /nobreak >nul

start "Frontend" cmd /c "cd /mnt/d/Bio_analysis/software/Stock_analysis/frontend && npm run dev"

echo.
echo Backend: http://localhost:8000
echo Frontend: http://localhost:5173
echo API Docs: http://localhost:8000/docs
echo.
pause
