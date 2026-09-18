@echo off
:: 价格每日自动更新 —— 计划任务登记器
:: 请「右键 → 以管理员身份运行」本脚本，即可在每天 18:00 自动执行 update_prices.ps1
:: （18:00 为收盘后，SMM/我的钢铁网当日价已稳定）
schtasks /create /tn ZaojiaPriceDailyUpdate ^
  /tr "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File \"%~dp0update_prices.ps1\"" ^
  /sc daily /st 18:00 /f
if %ERRORLEVEL%==0 (
  echo [成功] 已登记每日任务 ZaojiaPriceDailyUpdate（每天 18:00 运行）
) else (
  echo [失败] 请以管理员身份运行本脚本（右键 -> 以管理员身份运行）
)
pause
