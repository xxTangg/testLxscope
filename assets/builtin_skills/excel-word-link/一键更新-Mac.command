#!/bin/bash
# 双击此文件：读取 数据.xlsx + 模板.docx → 生成 输出.docx → 自动打开

cd "$(dirname "$0")"

echo "================================="
echo "  Excel → Word 一键联动填充"
echo "================================="
echo ""
echo " 数据: 数据.xlsx"
echo " 模板: 模板.docx"
echo ""
echo "正在生成 ..."
echo ""

python3 scripts/fill_word.py 数据.xlsx 模板.docx 输出.docx

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ 生成成功！正在打开 输出.docx ..."
    sleep 1
    open "输出.docx"
else
    echo ""
    echo "❌ 生成失败，请看上方提示。"
    echo "   常见原因："
    echo "     ① 没装依赖：运行  pip3 install openpyxl python-docx"
    echo "     ② 输出.docx 正在 Word 中打开：关闭后重试"
fi

echo ""
read -p "按任意键关闭窗口..." -n 1
