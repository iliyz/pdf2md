# pdfmerge.py
import os
import re
import shutil
from pathlib import Path

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    print("❌ 缺少必要的 pypdf 库，请在终端运行：pip install pypdf")
    exit(1)

# =====================================================================
# ==================== 【用户自定义可配置参数】 ====================
# =====================================================================

INPUT_DIR = "./input"    # 输入目录（存放待合并的碎片 PDF）
OUTPUT_DIR = "./output"  # 输出目录（存放合并后的完整 PDF）

# 匹配切片后缀的正则表达式规则列表（脚本会从上到下依次尝试匹配）
# 提示：
# - r'_part\d+$' 会匹配文件名末尾的 _part1, _part02, _part003 等
# - r'_\d+$'     会匹配文件名末尾的 _1, _2, _10 等
# - $ 符号在正则中代表“字符串末尾”，确保不会误伤文件名中间的数字
RULES = [
    r'_part\d+$',  # 对应 "part1、part2……" 规则
    r'_\d+$',      # 对应 "_1、_2……" 规则
    r'-part\d+$',  # 扩展：对应 "-part1、-part2……" 规则
    r'-\d+$'       # 扩展：对应 "-1、-2……" 规则
]

# =====================================================================


def log(msg):
    import time
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def extract_part_info(stem: str):
    """
    根据用户定义的 RULES 规则，识别文件名是否为碎片文件。
    如果是，返回 (基准文件名, 碎片数字序号)；如果不是，返回 (None, None)
    """
    for rule in RULES:
        match = re.search(rule, stem, re.IGNORECASE)
        if match:
            suffix = match.group()  # 匹配到的后缀，如 "_part1" 或 "_3"
            base_name = stem[:match.start()].strip()  # 剥离后缀后的干净文件名
            
            # 从后缀中提取出纯数字，用于精准的数学排序 (防止出现 10 排在 2 前面)
            digits = re.findall(r'\d+', suffix)
            part_num = int(digits[0]) if digits else 0
            
            return base_name, part_num
    return None, None


def main():
    log("🚀 PDF 智能组装合并脚本启动")
    log("=" * 50)

    input_path = Path(INPUT_DIR)
    output_path = Path(OUTPUT_DIR)

    if not input_path.exists():
        log(f"⚠️ 输入目录不存在，已自动创建: {input_path.absolute()}")
        input_path.mkdir(parents=True, exist_ok=True)
        log("请将需要合并的 PDF 碎片放入 input 文件夹后重新运行。")
        return

    output_path.mkdir(parents=True, exist_ok=True)

    # 1. 递归扫描所有的 PDF 文件
    all_pdfs = list(input_path.rglob("*.pdf"))
    if not all_pdfs:
        log(f"⚠️ 在 {input_path.absolute()} 中未找到任何 PDF 文件。")
        return

    # 2. 对文件进行归类分组
    # 数据结构：{(相对父目录, 基准文件名): [(碎片序号, 文件绝对路径), ...]}
    pdf_groups = {}
    standalone_files = [] # 存放不需要合并的独立完整 PDF

    for pdf in all_pdfs:
        rel_parent = pdf.relative_to(input_path).parent  # 保持原有的子文件夹层级
        base_name, part_num = extract_part_info(pdf.stem)

        if base_name is not None:
            group_key = (rel_parent, base_name)
            if group_key not in pdf_groups:
                pdf_groups[group_key] = []
            pdf_groups[group_key].append((part_num, pdf))
        else:
            # 没有匹配到任何切片规则，说明是个独立的完整 PDF
            standalone_files.append((rel_parent, pdf))

    # 3. 开始执行合并与组装
    log(f"📦 扫描完毕：发现 {len(pdf_groups)} 组待合并的碎片文件，{len(standalone_files)} 个独立文档。")
    log("-" * 50)

    merged_count = 0
    for (rel_parent, base_name), parts_list in pdf_groups.items():
        # 核心：根据碎片数字序号进行正向数学排序 (1 -> 2 -> 3 -> 10)
        parts_list.sort(key=lambda x: x[0])

        # 确定最终输出的目录和文件名
        target_dir = output_path / rel_parent
        target_dir.mkdir(parents=True, exist_ok=True)
        final_pdf_path = target_dir / f"{base_name}.pdf"

        # 如果只有单薄的一个碎片，没法合并，直接拷贝过去
        if len(parts_list) == 1:
            shutil.copy2(parts_list[0][1], final_pdf_path)
            log(f"ℹ️ 只有单个碎片，已直接复制: {final_pdf_path.name}")
            continue

        log(f"🔄 正在缝合组装 [{base_name}] (共 {len(parts_list)} 个碎片)...")
        
        writer = PdfWriter()
        success = True
        
        for part_num, file_path in parts_list:
            try:
                reader = PdfReader(file_path)
                # 兼容可能存在的加密流
                for page in reader.pages:
                    writer.add_page(page)
            except Exception as e:
                log(f"❌ 读取碎片失败 [{file_path.name}]: {e}")
                success = False
                break

        if success:
            try:
                with open(final_pdf_path, "wb") as f:
                    writer.write(f)
                log(f"✅ 缝合成功 -> {final_pdf_path.name}")
                merged_count += 1
            except Exception as e:
                log(f"❌ 写入最终文件失败 [{final_pdf_path.name}]: {e}")

    # 4. 捎带处理独立文件（可选：直接拷贝到 output 目录，保持结构）
    if standalone_files:
        log("-" * 50)
        log("📂 正在原样迁移无需合并的独立 PDF 文件...")
        for rel_parent, pdf in standalone_files:
            target_dir = output_path / rel_parent
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pdf, target_dir / pdf.name)
            log(f"⏩ 已迁移: {pdf.name}")

    log("=" * 50)
    log(f"🎉 大功告成！完美合并组装了 {merged_count} 份文档。")


if __name__ == "__main__":
    main()