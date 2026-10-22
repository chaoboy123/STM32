@echo off
chcp 936 >nul
title Keil 编译产物清理（安全版 v2）
setlocal
cd /d "%~dp0"

echo ==========================================
echo   Keil 编译产物清理脚本（安全版）
echo   工作目录: %CD%
echo ==========================================
echo.
echo 将删除每个工程目录下的:
echo   1. Objects 和 Listings 文件夹
echo   2. 中间文件: *.o *.d *.crf *.dep *.lnp *.axf
echo      *.hex *.bin *.map *.lst *.htm *.iex *.uvguix.*
echo.
echo 不会动: 源代码、工程文件、.git 仓库
echo.
set /p CONF=确认清理? (Y/N):
if /i not "%CONF%"=="Y" echo 已取消。& pause & exit /b

set N=0

rem 逐个进入工程目录内部清理（pushd 方式，规避 for /r 变量路径枚举失效的 cmd 缺陷）
for /d %%P in ("%CD%\*") do (
    if /i not "%%~nxP"==".git" (
        pushd "%%P"
        for /d /r %%D in (Objects Listings) do (
            if exist "%%D" (
                rd /s /q "%%D"
                set /a N+=1
                echo [目录] %%D
            )
        )
        for /r %%F in (*.o *.d *.crf *.dep *.lnp *.axf *.hex *.bin *.map *.lst *.htm *.iex *.uvguix.*) do (
            if exist "%%F" (
                del /q "%%F"
                set /a N+=1
                echo [文件] %%F
            )
        )
        popd
    )
)

echo.
echo ==========================================
echo   完成，共删除 %N% 项。
echo   下次编译 Keil 会自动重建，属正常现象。
echo ==========================================
pause
