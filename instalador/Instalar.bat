@echo off
chcp 65001 >nul
title Instalar o Busca Carro
if not exist "%~dp0programa\python\python.exe" (
  echo Extraia o arquivo .zip antes de instalar:
  echo clique com o botao direito no BuscaCarro-Instalador.zip, escolha "Extrair tudo"
  echo e rode o Instalar.bat da pasta extraida.
  echo.
  pause
  exit /b 1
)
"%~dp0programa\python\python.exe" -I -X utf8 "%~dp0programa\instalar.py" %*
