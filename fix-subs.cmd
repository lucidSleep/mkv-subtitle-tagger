@echo off
rem Windows launcher for fix_subs.py (needs Python 3.9+ and MKVToolNix). Usage: README.md.
rem   fix-subs "<folder or .mkv>"           dry run: what it found + simulated result, writes nothing
rem   fix-subs "<folder or .mkv>" --apply   writes the tags (reuses the dry run's plan if files are unchanged)
rem Don't end a quoted folder path with a backslash: "Z:\Show\" breaks cmd's argument parsing.
rem -I = isolated mode (the subtitle text comes from outside), -X utf8 = UTF-8 output.
rem The py launcher comes first: "python" can be the Microsoft Store placeholder when Python isn't installed.
setlocal
set "PYTHON=python"
where py >nul 2>nul && set "PYTHON=py -3"
%PYTHON% -I -X utf8 "%~dp0fix_subs.py" %*
exit /b %ERRORLEVEL%
