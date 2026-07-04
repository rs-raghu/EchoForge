@echo off
setlocal

set PYTHONPATH=%CD%\src

python -m echoforge %*

endlocal