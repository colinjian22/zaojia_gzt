@echo off
setlocal EnableDelayedExpansion

:: ============================================================
:: 造价工作台 · 一键推送到 GitHub
:: 用法：用记事本打开本文件，把下面 REPO_URL 改成你的真实仓库地址，保存后双击运行。
:: ============================================================

:: 1) 找到 git 命令（优先系统 git，否则用本机便携版，无需安装）
set "GIT=git"
where git >nul 2>nul || set "GIT=C:\Users\陈生\.workbuddy\binaries\PortableGit\versions\1.2.0\cmd\git.exe"

:: 2) 你的仓库地址（HTTPS 或 SSH）—— 改成真实地址再运行！
set "REPO_URL=https://github.com/你的用户名/你的仓库名.git"

if "%REPO_URL%"=="https://github.com/你的用户名/你的仓库名.git" (
  echo.
  echo 【第一步】请先用记事本打开本文件，把 REPO_URL 那一行改成你的真实仓库地址，
  echo        保存后重新双击运行本文件。
  echo        仓库地址获取：github.com 打开你的仓库 → 点绿色 Code 按钮 → 复制地址。
  pause
  exit /b 1
)

:: 3) 克隆到临时文件夹（避免本地无 .git 导致推送冲突，自动规避 rejected 报错）
set "SRC=%~dp0"
set "TMP=C:\zaojia_github_clone_tmp"
if exist "%TMP%" rmdir /s /q "%TMP%"

echo.
echo 【正在克隆仓库，首次会弹窗请你登录 GitHub，请完成登录】
"%GIT%" clone "%REPO_URL%" "%TMP%"
if errorlevel 1 (
  echo.
  echo 克隆失败：请检查仓库地址是否正确、网络是否通畅、是否已登录 GitHub。
  pause
  exit /b 1
)

:: 4) 把本文件夹的最新文件复制进克隆文件夹（覆盖旧文件）
echo.
echo 【正在复制最新文件到仓库...】
xcopy "%SRC%\*" "%TMP%\" /E /Y /Q

:: 5) 提交并推送
cd /d "%TMP%"
"%GIT%" config user.name "陈生"
"%GIT%" config user.email "chen@example.com"
"%GIT%" add -A
"%GIT%" commit -m "更新造价工作台页面与材料价格数据"
echo.
echo 【正在推送到 GitHub...】
"%GIT%" push -u origin HEAD
if errorlevel 1 (
  echo.
  echo 推送失败：多半是没登录或地址有误。
  echo 解决：改用 Personal Access Token（推送时用户名填 GitHub 用户名，密码框填 token），
  echo       或把 REPO_URL 换成 SSH 地址（git@github.com:用户名/仓库名.git）。
  pause
  exit /b 1
)

echo.
echo ============================================================
echo  成功！文件已推送到 GitHub。
echo  约 1 分钟后访问你的站点即可看到更新（含两行导航 + 母线槽市场铜价面板）。
echo  想立刻刷新价格：进仓库 Actions → 每日更新材料价格 → Run workflow → Run。
echo  以后每天 18:00（北京时间）GitHub 会自动更新三个价格，无需再手动推送、无需开电脑。
echo ============================================================
pause
