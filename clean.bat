@echo off
chcp 936 >nul
title Keil 工程一键清理
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo    Keil 工程一键清理
echo    目录: %CD%
echo ============================================
echo.
echo 将清理: Objects / Listings 目录，编译中间文件与日志
echo         *.o *.d *.crf *.dep *.lnp *.axf *.hex *.bin
echo         *.map *.lst *.htm *.iex *.uvguix.* *.log
echo 不会动: 源代码、头文件、工程文件、.git 仓库
echo.

tasklist /nh /fi "imagename eq UV4.exe" 2>nul | findstr /i /c:"UV4.exe" >nul
if not errorlevel 1 (
    echo [注意] Keil uVision 正在运行，被占用的文件可能删不掉
    echo        建议先关闭 Keil 再运行本脚本
    echo.
)

set /a N=0
set /a DIRN=0
set /a FILEN=0

echo 正在清理，请稍候...

rem ---------- 1. 清理 Objects / Listings 目录 ----------
rem dir /s /b /ad 递归列出所有同名目录
rem 逐个判断路径里是否含 .git\ ，含则跳过，避免删掉 Git 仓库的库对象
for /f "delims=" %%D in ('dir /s /b /ad "%CD%\Objects" "%CD%\Listings" 2^>nul') do (
    set "P=%%D"
    if "!P:\.git\=!"=="!P!" (
        if exist "%%D" (
            rd /s /q "%%D" 2>nul
            if not exist "%%D" (
                set /a N+=1
                set /a DIRN+=1
            )
        )
    )
)

rem ---------- 2. 清理编译中间文件与日志 ----------
rem /a-d 只列文件，避免误匹配同名文件夹；同样跳过 .git 下的东西
for /f "delims=" %%F in ('dir /s /b /a-d "%CD%\*.o" "%CD%\*.d" "%CD%\*.crf" "%CD%\*.dep" "%CD%\*.lnp" "%CD%\*.axf" "%CD%\*.hex" "%CD%\*.bin" "%CD%\*.map" "%CD%\*.lst" "%CD%\*.htm" "%CD%\*.iex" "%CD%\*.uvguix.*" "%CD%\*.log" 2^>nul') do (
    set "P=%%F"
    if "!P:\.git\=!"=="!P!" (
        if exist "%%F" (
            del /q "%%F" 2>nul
            if not exist "%%F" (
                set /a N+=1
                set /a FILEN+=1
            )
        )
    )
)

echo.
echo ============================================
if %N%==0 (
    echo    很干净，没有需要清理的东西
) else (
    echo    完成，共清理 %N% 项
    echo    目录 %DIRN% 个，文件 %FILEN% 个
)
echo    下次编译时 Keil 会自动重建这些文件
echo ============================================
echo.
echo 3 秒后自动关闭，按任意键立即关闭
timeout /t 3 >nul 2>nul
exit /b
