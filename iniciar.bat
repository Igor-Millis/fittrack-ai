@echo off
setlocal
cd /d "%~dp0"
title FitTrack AI

echo ============================================
echo   FitTrack AI - diario nutricional local
echo ============================================

where python >nul 2>nul
if errorlevel 1 (
  echo [ERRO] Python nao encontrado. Instale o Python 3.11+ em https://www.python.org/downloads/
  echo        e marque "Add python.exe to PATH" durante a instalacao.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Criando ambiente virtual .venv ...
  python -m venv .venv
  if errorlevel 1 ( echo [ERRO] Falha ao criar o ambiente virtual. & pause & exit /b 1 )
)

rem Reinstala dependencias apenas quando requirements.txt mudar
set "STAMP=.venv\.requirements.stamp"
fc /b requirements.txt "%STAMP%" >nul 2>nul
if errorlevel 1 (
  echo [2/3] Instalando dependencias - so na primeira vez ou quando mudarem ...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 ( echo [ERRO] Falha ao instalar dependencias. Verifique a internet. & pause & exit /b 1 )
  copy /y requirements.txt "%STAMP%" >nul
) else (
  echo [2/3] Dependencias ja instaladas.
)

echo [3/3] Abrindo http://localhost:8501  - feche esta janela para encerrar o app.
".venv\Scripts\python.exe" -m streamlit run app\main.py --server.port 8501 --browser.serverAddress localhost --server.headless false
if errorlevel 1 (
  echo.
  echo [ERRO] O aplicativo terminou com erro. Se aparecer "DLL load failed" ou "nome do arquivo muito grande",
  echo        mova a pasta do projeto para um caminho mais curto, ex.: C:\fittrack-ai
  pause
)
endlocal
