# pdf2mineru.py
import os
import time
import yaml
import shutil
import zipfile
import requests
import argparse
import re
from pathlib import Path
from io import BytesIO
from pypdf import PdfReader, PdfWriter
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==================== 基础配置 ====================
BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "default.yaml"
API_BASE = "https://mineru.net/api/v4"

IMG_PATTERN = re.compile(r"!\[\]\(images/([^)]+)\)")
MAX_WORKERS = 8

def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def load_config():
    if not CONFIG_FILE.exists():
        log(f"❌ 配置文件不存在: {CONFIG_FILE.absolute()}")
        exit(1)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    if not config.get("api_token"):
        log("❌ default.yaml 中缺少 api_token")
        exit(1)
    return config

def clean_temp_dir(temp_dir: Path):
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)
    log("🧹 临时目录已准备/清理完毕")

# ==================== PDF 分割与合并核心 ====================
def split_pdf_by_pages(file_path: Path, safe_stem: str, TEMP_DIR: Path, max_pages=200):
    try:
        reader = PdfReader(file_path)
        total = len(reader.pages)
        if total <= max_pages:
            shutil.copy(file_path, TEMP_DIR / f"{safe_stem}.pdf")
            return total
        for i in range(0, total, max_pages):
            w = PdfWriter()
            part = str((i // max_pages) + 1).zfill(3)
            end = min(i + max_pages, total)
            for p in range(i, end):
                w.add_page(reader.pages[p])
            out = TEMP_DIR / f"{safe_stem}_part{part}.pdf"
            with open(out, "wb") as f:
                w.write(f)
        return total
    except Exception as e:
        # 核心防弹衣：捕获坏文件，跳过并继续
        log(f"❌ 警告: 无法读取或切分 PDF [{file_path.name}]，可能文件已损坏。错误详情: {e}")
        return -1

def split_pdf_by_size(file_path: Path, TEMP_DIR: Path, max_mb=150):
    reader = PdfReader(file_path)
    safe_stem = file_path.stem
    total = len(reader.pages)
    w = PdfWriter()
    sub = 1
    for i in range(total):
        w.add_page(reader.pages[i])
        buf = BytesIO()
        w.write(buf)
        mb = buf.tell() / 1024 / 1024
        if mb > max_mb and len(w.pages) > 1:
            w2 = PdfWriter()
            for p in w.pages[:-1]:
                w2.add_page(p)
            out = TEMP_DIR / f"{safe_stem}_part{str(sub).zfill(3)}.pdf"
            with open(out, "wb") as f:
                w2.write(f)
            sub += 1
            last = w.pages[-1]
            w = PdfWriter()
            w.add_page(last)
    if len(w.pages) > 0:
        out = TEMP_DIR / f"{safe_stem}_part{str(sub).zfill(3)}.pdf"
        with open(out, "wb") as f:
            w.write(f)
    os.remove(file_path)

def merge_markdown_files(OUTPUT_DIR: Path):
    parts = sorted(OUTPUT_DIR.rglob("*_part*.md"))
    bases = set()
    for p in parts:
        # 核心修复：消除历史幽灵碎片和带空格的文件名带来的截断 Bug
        base_name = p.stem.split("_part")[0].strip()
        base_path = p.parent / base_name
        bases.add(base_path)

    for base_path in bases:
        pattern = f"{base_path.name}_part*.md"
        part_files = sorted(base_path.parent.glob(pattern))
        if not part_files: continue

        final_md = base_path.with_suffix(".md")
        final_img = base_path.parent / base_path.name / "images"
        all_md = []

        for p in part_files:
            with open(p, "r", encoding="utf-8") as f:
                content = f.read()
            content = content.replace(f"![]({p.stem}/images/", f"![]({base_path.name}/images/")
            all_md.append(content)

            src_img = p.parent / p.stem / "images"
            if src_img.exists():
                final_img.mkdir(parents=True, exist_ok=True)
                for img in src_img.glob("*"):
                    if img.is_file():
                        shutil.copy2(img, final_img)
                shutil.rmtree(src_img.parent)
            os.remove(p)

        with open(final_md, "w", encoding="utf-8") as f:
            f.write("\n\n".join(all_md))
        log(f"✅ 合并完成: {final_md.name}")

# ==================== API 请求核心 ====================
def request_upload_batch(files: list[str], config: dict):
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {config['api_token']}",
        "Content-Type": "application/json"
    })
    body = {
        "files": [{"name": n, "data_id": n} for n in files],
        "is_ocr": config.get('is_ocr', True),
        "enable_formula": config.get('enable_formula', True),
        "enable_table": config.get('enable_table', True),
        "language": config.get('language', "ch")
    }
    r = s.post(f"{API_BASE}/file-urls/batch", json=body)
    r.raise_for_status()
    data = r.json()
    return data["data"]["batch_id"], data["data"]["file_urls"]

def upload_one(sess, path: Path, url):
    with open(path, "rb") as f:
        sess.put(url, data=f, timeout=30)

def poll_batch(batch_id: str, config: dict, count: int):
    s = requests.Session()
    s.headers = {"Authorization": f"Bearer {config['api_token']}"}
    interval = config.get('poll_interval', 15)
    results = {}

    while len(results) < count:
        try:
            r = s.get(f"{API_BASE}/extract-results/batch/{batch_id}", timeout=20)
            data = r.json()
            items = data.get("data", {}).get("extract_result", [])

            for item in items:
                name = item.get("file_name")
                state = item.get("state")
                if state == "done" and name not in results:
                    results[name] = item.get("full_zip_url")
                elif state == "failed":
                    results[name] = None

            log(f"⏳ 解析进度: {len(results)}/{count}")
            time.sleep(interval)
        except Exception as e:
            time.sleep(5)
    return results

def download_extract_one(fname: str, url: str, OUTPUT_DIR: Path):
    try:
        r = requests.get(url, stream=True, timeout=60)
        r.raise_for_status()

        with zipfile.ZipFile(BytesIO(r.content)) as zf:
            mdfiles = [n for n in zf.namelist() if n.endswith(".md")]
            if not mdfiles: return None
            md = zf.read(mdfiles[0]).decode("utf-8")

        stem = Path(fname).stem 
        parts = stem.split("___")
        rel_parent = Path(*parts[:-1]) if len(parts) > 1 else Path("")
        true_stem = parts[-1] 

        out_folder = OUTPUT_DIR / rel_parent
        out_folder.mkdir(parents=True, exist_ok=True)
        img_folder = out_folder / true_stem / "images"
        img_folder.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(BytesIO(r.content)) as zf:
            for info in zf.infolist():
                if info.filename.startswith("images/") and info.filename.lower().endswith((".jpg", ".jpeg", ".png", ".gif")):
                    zf.extract(info, out_folder / true_stem)

        md = IMG_PATTERN.sub(f"![]({true_stem}/images/\\1)", md)
        with open(out_folder / f"{true_stem}.md", "w", encoding="utf-8") as f:
            f.write(md)
        return fname
    except Exception as e:
        log(f"❌ 下载失败: {fname} {e}")
        return None

def process_batch(files: list[Path], config: dict, OUTPUT_DIR: Path):
    if not files: return 0
    names = [f.name for f in files]
    batch_id, urls = request_upload_batch(names, config)

    s = requests.Session()
    with ThreadPoolExecutor(MAX_WORKERS) as pool:
        for f, u in zip(files, urls):
            pool.submit(upload_one, s, f, u)

    log("☁️ 上传完成，MinerU 引擎解析中...")
    res = poll_batch(batch_id, config, len(files))

    tasks = []
    with ThreadPoolExecutor(MAX_WORKERS) as pool:
        for fname, url in res.items():
            if url:
                tasks.append(pool.submit(download_extract_one, fname, url, OUTPUT_DIR))

    ok = sum(1 for t in as_completed(tasks) if t.result())
    return ok

# ==================== 两种运行策略 ====================

def run_global_batch_mode(pdfs: list[Path], config: dict, TEMP_DIR: Path, OUTPUT_DIR: Path, INPUT_DIR: Path):
    """策略 A：全局批处理（适合少量文件，速度极快）"""
    log("⚡ 启动【全局并发】模式 (阶段处理)")
    
    total_pages = 0
    for pdf in pdfs:
        # 清理多余空格防报错
        clean_parts = [p.strip() for p in pdf.relative_to(INPUT_DIR).parts[:-1]]
        clean_stem = pdf.stem.strip()
        safe_stem = "___".join(clean_parts + [clean_stem])
        
        pages = split_pdf_by_pages(pdf, safe_stem, TEMP_DIR, max_pages=config.get('max_pages', 200))
        if pages == -1: 
            continue
            
        total_pages += pages
        log(f"🔪 已排队: {clean_stem} ({pages}页)")

    for f in sorted(TEMP_DIR.glob("*.pdf")):
        if os.path.getsize(f) / 1024 / 1024 > 200:
            split_pdf_by_size(f, TEMP_DIR, 150)

    all_pdfs = sorted(TEMP_DIR.glob("*.pdf"))
    batches = [all_pdfs[i:i+8] for i in range(0, len(all_pdfs), 8)]
    for b in batches:
        process_batch(b, config, OUTPUT_DIR)

    merge_markdown_files(OUTPUT_DIR)
    return total_pages

def run_sequential_mode(pdfs: list[Path], config: dict, TEMP_DIR: Path, OUTPUT_DIR: Path, INPUT_DIR: Path):
    """策略 B：逐本串行处理（适合大量文件，不挤占内存和临时空间）"""
    log("🛡️ 启动【逐本串行】模式 (文件数量超过阈值)")
    
    total_pages = 0
    for index, pdf in enumerate(pdfs, 1):
        clean_parts = [p.strip() for p in pdf.relative_to(INPUT_DIR).parts[:-1]]
        clean_stem = pdf.stem.strip()
        safe_stem = "___".join(clean_parts + [clean_stem])
        
        log(f"\n▶ 开始处理第 {index}/{len(pdfs)} 本: {clean_stem}")
        clean_temp_dir(TEMP_DIR)
        
        pages = split_pdf_by_pages(pdf, safe_stem, TEMP_DIR, max_pages=config.get('max_pages', 200))
        
        # 遇到损坏文件跳过
        if pages == -1:
            log(f"⏭️ 已跳过损坏的文档: {clean_stem}")
            continue
            
        total_pages += pages
        for f in TEMP_DIR.glob("*.pdf"):
            if os.path.getsize(f) / 1024 / 1024 > 200:
                split_pdf_by_size(f, TEMP_DIR, 150)
                
        current_pdfs = sorted(TEMP_DIR.glob("*.pdf"))
        batches = [current_pdfs[i:i+8] for i in range(0, len(current_pdfs), 8)]
        for b in batches:
            process_batch(b, config, OUTPUT_DIR)
            
        merge_markdown_files(OUTPUT_DIR)
        
    return total_pages

# ==================== 主入口 ====================
def main():
    parser = argparse.ArgumentParser(description="MinerU PDF 批量 OCR (自适应策略引擎)")
    parser.add_argument("-i", "--input", type=str, help="输入文件夹绝对路径")
    parser.add_argument("-o", "--output", type=str, help="输出文件夹绝对路径")
    args = parser.parse_args()

    log("🚀 终极版 MinerU PDF OCR 管道启动 (搭载双引擎自适应)")
    log("="*60)
    config = load_config()

    TEMP_DIR = BASE_DIR / "temp"
    
    if args.input:
        INPUT_DIR = Path(args.input)
    else:
        default_input = BASE_DIR / "input"
        if default_input.exists():
            INPUT_DIR = default_input
            log(f"✅ 自动选中输入目录: {INPUT_DIR.absolute()}")
        else:
            print("\n" + "="*50)
            while True:
                input_path = input("未检测到默认 input 目录，请输入 PDF 文件夹的绝对路径：\n> ").strip().strip('"')
                path = Path(input_path)
                if path.exists() and path.is_dir():
                    INPUT_DIR = path
                    break
                log("❌ 路径无效，请重新输入。")

    if args.output:
        OUTPUT_DIR = Path(args.output)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    else:
        OUTPUT_DIR = BASE_DIR / "output"
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        log(f"✅ 自动选定输出目录: {OUTPUT_DIR.absolute()}")

    clean_temp_dir(TEMP_DIR)
    pdfs = sorted(INPUT_DIR.rglob("*.pdf"))
    
    if not pdfs:
        log("⚠ 输入目录及其子目录均未找到 PDF 文件")
        return

    log(f"📄 共扫描到 {len(pdfs)} 个待处理 PDF 文件")
    
    threshold = config.get("process_mode_threshold", 15)
    
    if len(pdfs) < threshold:
        total_pages = run_global_batch_mode(pdfs, config, TEMP_DIR, OUTPUT_DIR, INPUT_DIR)
    else:
        total_pages = run_sequential_mode(pdfs, config, TEMP_DIR, OUTPUT_DIR, INPUT_DIR)

    clean_temp_dir(TEMP_DIR)
    
    log("\n" + "="*60)
    log("🎉 全部任务完美收工！")
    log(f"📂 输出已保存至：{OUTPUT_DIR.absolute()}")
    log(f"📊 本次处理统计：处理文档 {len(pdfs)} 份，累计消耗约 {total_pages} 页额度")
    log("="*60)

if __name__ == "__main__":
    main()