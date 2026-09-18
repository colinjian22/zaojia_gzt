$ErrorActionPreference = 'Continue'
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$py  = "C:\Users\陈生\.workbuddy\binaries\python\versions\3.13.12\python.exe"
$log = Join-Path $dir "update_prices.log"
$ts  = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

function Log($m) { "$ts  $m" | Out-File -Append -Encoding utf8 $log }

Log "=== 开始价格更新 ==="
Set-Location $dir

# 1) 重新抓取 SMM 电解铜 + 我的钢铁网镀锌板，生成 prices.json
try {
    & $py price_sync.py *>&1 | ForEach-Object { Log $_ }
    Log "price_sync.py 执行完成"
} catch {
    Log "运行 price_sync.py 失败: $_"
}

# 2) 若当前目录是 git 仓库（已连接到你的 GitHub 仓库），则提交并推送，让线上站点同步更新
if (Test-Path (Join-Path $dir ".git")) {
    $env:GIT_TERMINAL_PROMPT = "0"   # 无凭据时直接失败而非卡住等待输入
    git add prices.json
    $msg = "chore: 自动更新价格 " + (Get-Date -Format "yyyy-MM-dd")
    Log (git commit -m $msg 2>&1)
    Log (git push 2>&1)
    Log "已尝试提交并推送到 GitHub"
} else {
    Log "当前目录不是 git 仓库，已跳过提交/推送（仅本地更新 prices.json）"
}
Log "=== 结束 ===`n"
