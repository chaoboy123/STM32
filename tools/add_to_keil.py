#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把源文件加入 Keil 工程组（等价于 uVision 里右键 Add Existing Files to Group）。

用法：
    python add_to_keil.py <工程目录或uvprojx> <要添加的文件> [--group 组名] [--dry-run]

示例：
    python add_to_keil.py "C:/Users/liu/Desktop/STM32/6-3 PWM驱动LED呼吸灯" "C:/Users/liu/Desktop/STM32/6-3 PWM驱动LED呼吸灯/Hardware/Motor.c"

组的推断规则：文件所在目录名 == 工程里的 GroupName 就直接用，否则报错并列出现有组。
"""

import argparse
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET

# Keil 的 FileType 编码
FTYPE = {
    ".c": 1,
    ".s": 2,
    ".asm": 2,
    ".o": 3,
    ".obj": 3,
    ".lib": 4,
    ".h": 5,
    ".txt": 5,
    ".cpp": 8,
    ".cc": 8,
}


def find_uvprojx(path):
    path = os.path.abspath(path)
    if os.path.isfile(path) and path.lower().endswith((".uvprojx", ".uvproj")):
        return path
    if not os.path.isdir(path):
        sys.exit("错误：路径不存在 -> %s" % path)
    cands = [f for f in os.listdir(path) if f.lower().endswith((".uvprojx", ".uvproj"))]
    if not cands:
        sys.exit("错误：目录里没有 .uvprojx 工程文件 -> %s" % path)
    if len(cands) > 1:
        sys.exit("错误：目录里有多个工程文件，请直接指定其中一个：%s" % ", ".join(cands))
    return os.path.join(path, cands[0])


def groups_of(text):
    return re.findall(r"<GroupName>([^<]*)</GroupName>", text)


def group_block(text, group):
    """返回 (组起始, 组结束) 的字符区间。"""
    idx = text.find("<GroupName>%s</GroupName>" % group)
    if idx < 0:
        return None, None
    gstart = text.rfind("<Group>", 0, idx)
    gend = text.find("</Group>", idx)
    return gstart, gend + len("</Group>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project", help="工程目录或 .uvprojx 路径")
    ap.add_argument("file", help="要添加的源文件路径")
    ap.add_argument("--group", default=None, help="指定组名，默认按文件所在目录名推断")
    ap.add_argument("--dry-run", action="store_true", help="只演示，不写入文件")
    a = ap.parse_args()

    uvprojx = find_uvprojx(a.project)
    projdir = os.path.dirname(uvprojx)
    srcfile = os.path.abspath(a.file)

    if not os.path.isfile(srcfile):
        sys.exit("错误：文件不存在 -> %s" % srcfile)

    ext = os.path.splitext(srcfile)[1].lower()
    if ext not in FTYPE:
        sys.exit("错误：不认识的文件类型 %s（支持 %s）" % (ext, ", ".join(sorted(FTYPE))))

    text = open(uvprojx, encoding="utf-8", newline="").read()
    existing_groups = groups_of(text)

    group = a.group or os.path.basename(os.path.dirname(srcfile))
    if group not in existing_groups:
        sys.exit(
            "错误：工程里没有名为「%s」的组。\n现有组：%s\n可以用 --group 手动指定，"
            "或先在 Keil 里建好这个组。" % (group, ", ".join(existing_groups))
        )

    rel = os.path.relpath(srcfile, projdir).replace("/", "\\")
    if not rel.startswith("\\"):
        rel = ".\\" + rel
    filename = os.path.basename(srcfile)

    gstart, gend = group_block(text, group)
    seg = text[gstart:gend]

    if ("<FilePath>%s</FilePath>" % rel) in seg or ("<FileName>%s</FileName>" % filename) in seg:
        print("已在工程组「%s」中，无需重复添加：%s" % (group, filename))
        return

    # 检测该组现有 <File> 的缩进，保持一致
    m = re.search(r"\n([ \t]+)<File>", seg)
    ind = m.group(1) if m else "            "
    ind2 = ind + "  "

    block = (
        "%s<File>\n"
        "%s<FileName>%s</FileName>\n"
        "%s<FileType>%d</FileType>\n"
        "%s<FilePath>%s</FilePath>\n"
        "%s</File>\n"
        % (ind, ind2, filename, ind2, FTYPE[ext], ind2, rel, ind)
    )

    if "</File>" in seg:
        pos = gstart + seg.rfind("</File>") + len("</File>") + 1
        new_text = text[:pos] + block + text[pos:]
    else:
        pos = gstart + seg.find("</Files>")
        new_text = text[:pos] + block + text[pos:]

    # 校验 XML 仍然合法
    try:
        ET.fromstring(new_text)
    except ET.ParseError as e:
        sys.exit("错误：修改后 XML 不合法，已中止（未写入）。%s" % e)

    print("工程：%s" % uvprojx)
    print("文件：%s" % filename)
    print("组  ：%s    FileType=%d" % (group, FTYPE[ext]))
    print("路径：%s" % rel)

    if a.dry_run:
        print("\n--dry-run，未写入文件。")
        return

    shutil.copy2(uvprojx, uvprojx + ".bak")
    open(uvprojx, "w", encoding="utf-8", newline="").write(new_text)
    print("\n已加入工程。备份：%s.bak" % os.path.basename(uvprojx))
    print("回到 Keil / VS Code 后重新编译即可；若 VS Code 面板没刷新，点一次 Rebuild 或重载窗口。")


if __name__ == "__main__":
    main()
