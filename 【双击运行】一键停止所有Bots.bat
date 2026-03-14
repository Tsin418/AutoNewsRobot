@echo off
echo 正在尝试关闭后台运行的所有的 python 脚本...
taskkill /f /im python.exe
taskkill /f /im chromedriver.exe
taskkill /f /im chrome.exe
echo.
echo 关停操作已完成！(如有其他不相关的 Python 进程可能也会被关闭)
pause
