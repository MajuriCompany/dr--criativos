@echo off
cd /d "%~dp0"
if not exist .venv (
    echo Criando ambiente virtual...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)
echo.
echo Worker rodando. Deixe esta janela aberta.
echo.
python run_worker.py
pause
