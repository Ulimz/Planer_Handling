@echo off
rem Arranca la web del planificador en este ordenador. La primera vez instala lo necesario.
cd /d "%~dp0"
where python >NUL 2>NUL || (echo Falta Python. Instalalo desde https://www.python.org/downloads/ marcando "Add python.exe to PATH". & pause & exit /b 1)
if not exist .venv (
  echo Preparando el programa por primera vez, tarda unos minutos...
  python -m venv .venv || (pause & exit /b 1)
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -e .[web] || (pause & exit /b 1)
)
.venv\Scripts\python -m streamlit run web\app.py
pause
