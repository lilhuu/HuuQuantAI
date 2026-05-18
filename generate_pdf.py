#!/usr/bin/env python3
"""将 AI_Agent_学习路线.md 转换为 PDF 并保存到桌面"""

import os
import sys

# 获取桌面路径
def get_desktop():
    if sys.platform == "win32":
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        desktop = winreg.QueryValueEx(key, "Desktop")[0]
        key.Close()
        # 处理环境变量
        desktop = os.path.expandvars(desktop)
    else:
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    return desktop


def main():
    try:
        from fpdf import FPDF
    except ImportError:
        print("正在安装 fpdf2...")
        os.system(f"{sys.executable} -m pip install fpdf2 -q")
        from fpdf import FPDF

    import re

    md_path = os.path.join(os.path.dirname(__file__), "AI_Agent_学习路线.md")
    if not os.path.exists(md_path):
        print(f"错误: 找不到 {md_path}")
        sys.exit(1)

    with open(md_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    desktop = get_desktop()
    pdf_path = os.path.join(desktop, "AI_Agent_学习路线.pdf")

    pdf = FPDF()
    pdf.add_page()
    pdf.add_font("NotoSansSC", "", os.path.join(os.path.dirname(__file__), "NotoSansSC-Regular.ttf"), uni=True)
    pdf.add_font("NotoSansSC", "B", os.path.join(os.path.dirname(__file__), "NotoSansSC-Bold.ttf"), uni=True)
    pdf.set_auto_page_break(auto=True, margin=20)

    pdf.set_font("NotoSansSC", "B", 18)
    pdf.cell(0, 15, "AI Agent 系统性学习路线", ln=True, align="C")
    pdf.ln(3)
    pdf.set_font("NotoSansSC", "", 9)
    pdf.cell(0, 6, "目标：从零基础到能够独立设计、开发和部署 AI Agent 系统", ln=True, align="C")
    pdf.cell(0, 6, "预计周期：3-6 个月（每天 1-2 小时投入）", ln=True, align="C")
    pdf.ln(5)

    # 解析 Markdown 行
    for line in lines:
        line_stripped = line.rstrip()

        # 分隔线
        if line_stripped.startswith("---"):
            pdf.ln(2)
            continue

        # 一级标题
        if line_stripped.startswith("# ") and not line_stripped.startswith("##"):
            pdf.ln(4)
            pdf.set_font("NotoSansSC", "B", 14)
            # 去除 markdown 标记和内联代码
            text = re.sub(r'# ', '', line_stripped)
            text = re.sub(r'`([^`]+)`', r'\1', text)
            pdf.cell(0, 10, text, ln=True)
            continue

        # 二级标题
        if line_stripped.startswith("## ") and not line_stripped.startswith("### "):
            pdf.ln(3)
            pdf.set_font("NotoSansSC", "B", 12)
            text = re.sub(r'## ', '', line_stripped)
            text = re.sub(r'`([^`]+)`', r'\1', text)
            pdf.cell(0, 8, text, ln=True)
            continue

        # 三级标题
        if line_stripped.startswith("### "):
            pdf.ln(2)
            pdf.set_font("NotoSansSC", "B", 10.5)
            text = re.sub(r'### ', '', line_stripped)
            text = re.sub(r'`([^`]+)`', r'\1', text)
            pdf.cell(0, 7, text, ln=True)
            continue

        # 引用块
        if line_stripped.startswith(">"):
            pdf.set_font("NotoSansSC", "", 9)
            text = re.sub(r'^> ', '', line_stripped)
            text = re.sub(r'`([^`]+)`', r'\1', text)
            pdf.set_text_color(80, 80, 80)
            pdf.multi_cell(0, 5, text)
            pdf.set_text_color(0, 0, 0)
            continue

        # 代码块（跳过）
        if line_stripped.startswith("```"):
            continue

        # 列表项
        if line_stripped.startswith("- ") or line_stripped.startswith("  - "):
            pdf.set_font("NotoSansSC", "", 9)
            text = re.sub(r'`([^`]+)`', r'\1', line_stripped)
            pdf.multi_cell(0, 5, text)
            continue

        # 数字列表
        if re.match(r'^\d+\. ', line_stripped):
            pdf.set_font("NotoSansSC", "", 9)
            text = re.sub(r'`([^`]+)`', r'\1', line_stripped)
            pdf.multi_cell(0, 5, text)
            continue

        # 表格（简化处理）
        if "|" in line_stripped and line_stripped.startswith("|"):
            if "---" in line_stripped:
                continue  # 表头分隔线
            pdf.set_font("NotoSansSC", "", 8.5)
            cells = [c.strip() for c in line_stripped.split("|")[1:-1]]
            row_text = "  |  ".join(cells)
            pdf.multi_cell(0, 5, row_text)
            continue

        # 空行
        if not line_stripped:
            pdf.ln(1)
            continue

        # 普通段落
        if not line_stripped.startswith("#") and not line_stripped.startswith(">"):
            pdf.set_font("NotoSansSC", "", 9)
            text = re.sub(r'\*\*([^*]+)\*\*', r'\1', line_stripped)
            text = re.sub(r'`([^`]+)`', r'\1', text)
            text = re.sub(r'^\* ', '', text)
            if text.strip():
                pdf.multi_cell(0, 5, text)

    pdf.output(pdf_path)
    print(f"PDF 已生成: {pdf_path}")


if __name__ == "__main__":
    main()
