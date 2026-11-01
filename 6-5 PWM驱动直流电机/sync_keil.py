#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_keil.py —— 把工程目录下所有源文件一次性登记进 Keil 工程

用法（任选一种）：
    双击工程目录里的「同步到工程.bat」
    VS Code: Ctrl+Shift+P -> Tasks: Run Task -> Keil: 同步全部源文件到工程
    命令行: python sync_keil.py [工程目录] [--dry-run] [--no-create-group]

做的事：
    1. 扫描工程目录下所有 .c / .h / .s / .asm / .cpp（跳过 Objects、Listings、.git、.vscode 等）
    2. 按「文件所在的第一级目录名」匹配工程里已有的组
    3. 组里没有的文件补进去；目录没有对应组时自动新建一个组
    4. 改完先校验 XML，再备份 Project.uvprojx.bak，最后才写盘
    5. 重复运行是安全的：已登记的文件不会重复添加

退出码：0 正常（含"无需变更"），1 出错。
"""

import argparse
import difflib
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

# 扫描时跳过的目录（小写比较）
EXCLUDE_DIRS = {
    "objects", "listings", "debugconfig", "rte", "backup",
    ".git", ".vscode", ".vs", ".idea", "__pycache__", "node_modules",
}

# 支持的源文件扩展名 -> Keil FileType
FTYPE = {
    ".c": 1,
    ".s": 2,
    ".asm": 2,
    ".h": 5,
    ".cpp": 8,
    ".cc": 8,
}

# 会被自动同步的扩展名。故意不含 .s/.asm：
# 启动文件一个工程只能用其中一个，全加进去必然大量重复定义，必须人工选。
SCAN_EXT = {".c", ".h", ".cpp", ".cc"}

# 参与"同名重复定义"检查的扩展名（头文件同名不算冲突）
CODE_EXT = {".c", ".cpp", ".cc"}


def find_uvprojx(path):
    path = os.path.abspath(path)
    if os.path.isfile(path) and path.lower().endswith((".uvprojx", ".uvproj")):
        return path
    if not os.path.isdir(path):
        sys.exit("错误：路径不存在 -> %s" % path)
    cands = sorted(f for f in os.listdir(path) if f.lower().endswith((".uvprojx", ".uvproj")))
    if not cands:
        sys.exit("错误：这个目录里没有 .uvprojx 工程文件 -> %s" % path)
    if len(cands) > 1:
        sys.exit("错误：目录里有多个工程文件，请指定其中一个：%s" % ", ".join(cands))
    return os.path.join(path, cands[0])


def scan_sources(root):
    """扫描所有源文件，返回按路径排序的绝对路径列表。"""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in EXCLUDE_DIRS]
        for fn in filenames:
            if fn.startswith("~") or fn.endswith(".bak"):
                continue
            if os.path.splitext(fn)[1].lower() in SCAN_EXT:
                found.append(os.path.join(dirpath, fn))
    return sorted(found)


def group_spans(block):
    """返回 [(组名, 起始, 结束)]，区间覆盖整个 <Group>...</Group>。"""
    out = []
    for m in re.finditer(r"<GroupName>([^<]*)</GroupName>", block):
        gstart = block.rfind("<Group>", 0, m.start())
        if gstart < 0:
            continue
        gend = block.find("</Group>", m.end())
        if gend < 0:
            continue
        out.append((m.group(1), gstart, gend + len("</Group>")))
    return out


def match_group(directory, groups):
    """把目录名映射到工程里已有的组名。返回 (组名, 匹配方式) 或 (None, None)。"""
    if directory in groups:
        return directory, "exact"

    lower_map = {}
    for g in groups:
        lower_map.setdefault(g.lower(), g)
    if directory.lower() in lower_map:
        return lower_map[directory.lower()], "case"

    cand = difflib.get_close_matches(directory, groups, n=1, cutoff=0.7)
    if cand:
        return cand[0], "fuzzy"
    return None, None


def insert_into_group(block, gname, items):
    """把 items 插到指定组内最后一个 </File> 之后。items 为 [(文件名, FileType, 相对路径)]。"""
    for name, gs, ge in group_spans(block):
        if name != gname:
            continue

        seg = block[gs:ge]
        m = re.search(r"\n([ \t]+)<File>", seg)
        ind = m.group(1) if m else "            "
        ind2 = ind + "  "

        chunks = "".join(
            "%s<File>\n%s<FileName>%s</FileName>\n%s<FileType>%d</FileType>\n%s<FilePath>%s</FilePath>\n%s</File>\n"
            % (ind, ind2, fn, ind2, ft, ind2, rp, ind)
            for fn, ft, rp in items
        )

        files_end = block.rfind("</Files>", gs, ge)
        if files_end >= 0:
            line_start = block.rfind("\n", gs, files_end) + 1
            return block[:line_start] + chunks + block[line_start:]

        # 组里还没有 <Files>（空组），补一个
        anchor = block.find("</GroupName>", gs, ge) + len("</GroupName>")
        return (
            block[:anchor]
            + "\n%s<Files>\n" % ind2
            + chunks
            + "%s</Files>" % ind2
            + block[anchor:]
        )
    return block


def create_group(block, gname, items):
    """在 </Groups> 之前新建一个组，并放入 items。"""
    m = re.search(r"\n([ \t]+)<Group>", block)
    ind = m.group(1) if m else "        "
    ind2 = ind + "  "
    ind3 = ind2 + "  "
    ind4 = ind3 + "  "

    files = "".join(
        "%s<File>\n%s<FileName>%s</FileName>\n%s<FileType>%d</FileType>\n%s<FilePath>%s</FilePath>\n%s</File>\n"
        % (ind3, ind4, fn, ind4, ft, ind4, rp, ind3)
        for fn, ft, rp in items
    )
    new_group = (
        "%s<Group>\n"
        "%s<GroupName>%s</GroupName>\n"
        "%s<Files>\n"
        "%s"
        "%s</Files>\n"
        "%s</Group>\n" % (ind, ind2, gname, ind2, files, ind2, ind)
    )

    pos = block.rfind("</Groups>")
    if pos < 0:
        return block
    line_start = block.rfind("\n", 0, pos) + 1
    return block[:line_start] + new_group + block[line_start:]


def keil_running():
    try:
        r = subprocess.run(
            ["tasklist", "/nh", "/fi", "imagename eq UV4.exe"],
            capture_output=True, timeout=8,
        )
        return b"UV4.exe" in r.stdout
    except Exception:
        return False


def main():
    here = os.path.dirname(os.path.abspath(__file__))

    ap = argparse.ArgumentParser(description="把工程目录下所有源文件同步进 Keil 工程")
    ap.add_argument("project", nargs="?", default=here, help="工程目录（默认：脚本所在目录）")
    ap.add_argument("--dry-run", action="store_true", help="只显示会做什么，不写文件")
    ap.add_argument("--no-create-group", action="store_true", help="不自动新建组，组不存在就跳过")
    a = ap.parse_args()

    uvprojx = find_uvprojx(a.project)
    projdir = os.path.dirname(uvprojx)

    if not a.dry_run and keil_running():
        sys.exit("错误：Keil uVision 正在运行。请先关闭它，否则保存工程时会覆盖本次修改。")

    sources = scan_sources(projdir)
    if not sources:
        sys.exit("错误：%s 下没有找到任何 .c/.h 文件" % projdir)

    asm_files = []
    for dirpath, dirnames, filenames in os.walk(projdir):
        dirnames[:] = [d for d in dirnames if d.lower() not in EXCLUDE_DIRS]
        for fn in filenames:
            if fn.lower().endswith((".s", ".asm")):
                asm_files.append(fn)

    text = open(uvprojx, encoding="utf-8", errors="surrogateescape", newline="").read()

    # 工程里已登记的路径（用于去重），以及已登记的代码文件主名（用于查重复定义）
    registered = set()
    reg_code_stems = {}
    for p in re.findall(r"<FilePath>([^<]*)</FilePath>", text):
        norm = os.path.normcase(p.replace("\\", "/").lstrip("./"))
        registered.add(norm)
        base = os.path.basename(norm)
        if os.path.splitext(base)[1].lower() in CODE_EXT:
            reg_code_stems.setdefault(os.path.splitext(base)[0].lower(), (os.path.dirname(norm), p))

    # 现存的组名（取第一个 Groups 块，用于判断是否需要新建）
    all_groups = []
    for m in re.finditer(r"<Groups>.*?</Groups>", text, re.S):
        for name, _, _ in group_spans(m.group(0)):
            if name not in all_groups:
                all_groups.append(name)

    # 规划：目录 -> 要补的文件
    plan = {}           # 目标组名 -> [(文件名, FileType, 相对路径)]
    new_groups = []     # 需要新建的组
    skipped = []        # (相对路径, 原因)
    fuzzy_notes = []    # 模糊匹配的提示
    already = 0

    for src in sources:
        rel_win = os.path.relpath(src, projdir).replace("/", "\\")
        rel_cfg = ".\\" + rel_win if not rel_win.startswith("\\") else rel_win
        key = os.path.normcase(rel_win)
        filename = os.path.basename(src)
        ftype = FTYPE[os.path.splitext(src)[1].lower()]

        if key in registered:
            already += 1
            continue

        # 同名模块已在别的目录登记过：再加会符号重复定义，或让同名头文件版本打架
        stem = os.path.splitext(filename)[0].lower()
        if stem in reg_code_stems:
            other_dir, other_path = reg_code_stems[stem]
            if other_dir != os.path.dirname(key):
                skipped.append(
                    (rel_win, "同名模块已登记在 %s，此副本会造成重复定义或头文件版本不一致" % other_path)
                )
                continue

        parts = os.path.relpath(src, projdir).split(os.sep)
        if len(parts) < 2:
            skipped.append((rel_win, "文件直接放在工程根目录，没有对应的组"))
            continue

        directory = parts[0]
        gname, how = match_group(directory, all_groups)
        if gname:
            if how == "fuzzy":
                fuzzy_notes.append((directory, gname))
        elif a.no_create_group:
            skipped.append((rel_win, "目录「%s」在工程里没有对应的组" % directory))
            continue
        else:
            gname = directory
            if gname not in new_groups:
                new_groups.append(gname)

        plan.setdefault(gname, []).append((filename, ftype, rel_cfg))

    total_add = sum(len(v) for v in plan.values())

    # ---- 输出计划 ----
    print("工程：%s" % uvprojx)
    print("扫描：%s 下共 %d 个源文件（.c/.h）" % (os.path.basename(projdir), len(sources)))
    if len(asm_files) > 1:
        print("说明：目录里有 %d 个汇编启动文件，不会自动添加——一个工程只能用其中一个，全加会大量重复定义。" % len(asm_files))
    print()

    if not plan:
        print("工程已是最新，没有需要添加的文件。")
        if skipped:
            print("\n跳过 %d 个：" % len(skipped))
            for r, why in skipped:
                print("   - %s    (%s)" % (r, why))
        return

    print("需要添加 %d 个文件：" % total_add)
    for gname in sorted(plan):
        tag = "  [新建组]" if gname in new_groups else ""
        print("  %s%s" % (gname, tag))
        for fn, ft, rp in plan[gname]:
            print("      + %s" % rp)
    print()
    print("已登记、无需处理：%d 个" % already)

    if fuzzy_notes:
        print()
        for directory, g in dict(fuzzy_notes).items():
            print("  注意：目录「%s」没有同名组，已自动匹配到「%s」（疑似拼写差异）" % (directory, g))

    if skipped:
        print("\n跳过 %d 个：" % len(skipped))
        for r, why in skipped:
            print("   - %s    (%s)" % (r, why))

    # 死链提示：工程里登记了但磁盘上不存在的文件
    dead = []
    for p in re.findall(r"<FilePath>([^<]*)</FilePath>", text):
        real = os.path.normpath(os.path.join(projdir, p.replace("\\", os.sep)))
        if not os.path.exists(real):
            dead.append(p)
    if dead:
        print("\n提示：工程里有 %d 条记录指向磁盘上不存在的文件（本次未改动，需要的话在 Keil 里移除）：" % len(dead))
        for p in dead[:6]:
            print("   ! %s" % p)
        if len(dead) > 6:
            print("   ... 另有 %d 条" % (len(dead) - 6))

    if a.dry_run:
        print("\n--dry-run：未写入任何文件。")
        return

    # ---- 逐 Target 修改 ----
    spans = [(m.start(), m.end()) for m in re.finditer(r"<Groups>.*?</Groups>", text, re.S)]
    if not spans:
        sys.exit("错误：工程文件里没找到 <Groups> 结构，可能不是标准 Keil5 工程。")

    new_text = text
    for s0, e0 in reversed(spans):
        block = new_text[s0:e0]
        for gname in sorted(plan):
            existing = [n for n, _, _ in group_spans(block)]
            if gname in existing:
                block = insert_into_group(block, gname, plan[gname])
            else:
                block = create_group(block, gname, plan[gname])
        new_text = new_text[:s0] + block + new_text[e0:]

    # ---- 校验 ----
    try:
        ET.fromstring(new_text)
    except ET.ParseError as e:
        sys.exit("错误：修改后 XML 不合法，已中止（未写入任何文件）。\n  %s" % e)

    shutil.copy2(uvprojx, uvprojx + ".bak")
    open(uvprojx, "w", encoding="utf-8", errors="surrogateescape", newline="").write(new_text)

    print("\n完成：新增 %d 个文件%s" % (total_add, "，新建 %d 个组" % len(new_groups) if new_groups else ""))
    print("备份：%s.bak" % os.path.basename(uvprojx))
    print("回到 Keil / VS Code 后重新编译即可。")


if __name__ == "__main__":
    main()
