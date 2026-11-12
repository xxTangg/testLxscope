@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo =================================
echo   Excel 到 Word 一键联动填充
echo =================================
echo.
echo  数据: 数据.xlsx
echo  模板: 模板.docx
echo.
echo 正在生成 ...
echo.

python scripts\fill_word.py 数据.xlsx 模板.docx 输出.docx
if errorlevel 1 (
    echo.
    echo X 生成失败，请看上方提示。
    echo   常见原因：
    echo     1) 没装 Python：到 python.org 下载安装，安装时勾选 Add to PATH
    echo     2) 没装依赖：命令行运行  pip install openpyxl python-docx
    echo     3) 输出.docx 正在 Word 中打开：关闭后重试
    echo.
    pause
    exit /b 1
)

echo.
echo √ 生成成功！正在打开 输出.docx ...
timeout /t 1 >nul
start "" "输出.docx"
echo.
pause
