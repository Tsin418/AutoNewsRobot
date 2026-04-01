@echo off
echo 正在尝试关闭 newsbot 相关进程...
for /f "tokens=2 delims=," %%p in ('wmic process where "name='python.exe' and commandline like '%%newsbot.py%%'" get processid /format:csv ^| findstr /r "^[^,].*,[0-9][0-9]*$"') do (
	taskkill /f /pid %%p >nul 2>nul
)
for /f "tokens=2 delims=," %%p in ('wmic process where "name='python.exe' and commandline like '%%news_scheduler.py%%'" get processid /format:csv ^| findstr /r "^[^,].*,[0-9][0-9]*$"') do (
	taskkill /f /pid %%p >nul 2>nul
)
for /f "tokens=2 delims=," %%p in ('wmic process where "name='chromedriver.exe' and commandline like '%%feishu_crypto_news_bot%%'" get processid /format:csv ^| findstr /r "^[^,].*,[0-9][0-9]*$"') do (
	taskkill /f /pid %%p >nul 2>nul
)
echo.
echo 关停操作已完成！(仅处理 newsbot 相关进程)
pause
