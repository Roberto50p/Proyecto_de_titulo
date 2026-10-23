@echo off
cd /d %~dp0
call .venv\Scripts\python.exe manage.py migrate --noinput
call .venv\Scripts\python.exe manage.py runserver
