@echo off
"%~dp0runtime\ollama.exe" serve <nul >"%~dp0logs\server.stdout.log" 2>"%~dp0logs\server.stderr.log"
