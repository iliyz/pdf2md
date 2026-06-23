# md_regex_pipeline.py
import os
import argparse
import shutil
from pathlib import Path

try:
    import regex as re
except ImportError:
    print("❌ 缺少必要的 regex 库，请在终端运行：pip install regex")
    exit(1)

# ==================== 默认目录配置 ====================
BASE_DIR = Path(__file__).parent
DEFAULT_INPUT = BASE_DIR / "output"  
DEFAULT_OUTPUT = BASE_DIR / "reput"  
DEFAULT_REGEX_BASE = BASE_DIR / "src" / "regex"  # 默认规则库基准路径

def resolve_regex_dir(raw_path: str) -> Path:
    """智能解析规则文件夹路径，支持绝对路径、相对路径和简写模式"""
    if not raw_path:
        return DEFAULT_REGEX_BASE

    if raw_path.startswith('/') or raw_path.startswith('\\'):
        folder_name = raw_path.lstrip('/\\')
        return DEFAULT_REGEX_BASE / folder_name

    potential_shorthand = DEFAULT_REGEX_BASE / raw_path
    if not Path(raw_path).exists() and potential_shorthand.exists():
        return potential_shorthand

    return Path(raw_path).resolve()

def load_pipeline_rules(regex_dir: Path):
    """解析指定目录下的规则文件，严格按照数字/字母顺序加载"""
    rules = []
    if not regex_dir.exists():
        print(f"⚠️ 规则文件夹不存在: {regex_dir.absolute()}")
        if regex_dir == DEFAULT_REGEX_BASE:
            regex_dir.mkdir(parents=True, exist_ok=True)
            print("已自动创建了默认规则文件夹。")
        return rules

    # 核心：确保排序读取
    for filepath in sorted(regex_dir.iterdir()):
        if not filepath.is_file():
            continue

        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        current_search = None
        current_replace = []

        for line in lines:
            clean_line = line.rstrip('\r\n')
            if '"->"' in clean_line:
                if current_search is not None:
                    repl_str = '\n'.join(current_replace)
                    if repl_str.endswith('"'): 
                        repl_str = repl_str[:-1]
                    rules.append((current_search, repl_str))
                
                parts = clean_line.split('"->"', 1)
                search_str = parts[0][1:] if parts[0].startswith('"') else parts[0]
                replace_str = parts[1][1:] if parts[1].startswith('"') else parts[1]
                
                current_search = search_str
                current_replace = [replace_str]
            else:
                if current_search is not None:
                    current_replace.append(clean_line)

        if current_search is not None:
            repl_str = '\n'.join(current_replace)
            if repl_str.endswith('"'): 
                repl_str = repl_str[:-1]
            rules.append((current_search, repl_str))

    return rules

def process_markdown_files(rules, input_dir, output_dir):
    """执行正则替换，递归子文件夹保持结构，安全迁移对应图片"""
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    
    # 核心：rglob 递归寻找
    md_files = list(input_path.rglob("*.md"))
    if not md_files:
        print(f"⚠️ 在 {input_path} 及其所有子目录下均未找到 .md 文件。")
        return

    for md_file in md_files:
        relative_path = md_file.relative_to(input_path)
        out_file = output_path / relative_path

        out_file.parent.mkdir(parents=True, exist_ok=True)

        with open(md_file, 'r', encoding='utf-8') as f:
            text = f.read()

        for search_pattern, replace_pattern in rules:
            try:
                py_replace = re.sub(r'\$(\d+)', r'\\\1', replace_pattern)
                regex_obj = re.compile(search_pattern, flags=re.MULTILINE)
                text = regex_obj.sub(py_replace, text)
            except Exception as e:
                print(f"❌ 规则执行出错 [文件: {relative_path}, 匹配: {search_pattern[:20]}...]: {e}")

        with open(out_file, 'w', encoding='utf-8') as f:
            f.write(text)
            
        img_folder_src = md_file.parent / md_file.stem / "images"
        if img_folder_src.exists():
            img_folder_dst = out_file.parent / md_file.stem / "images"
            
            if img_folder_dst.exists():
                shutil.rmtree(img_folder_dst)
                
            shutil.copytree(img_folder_src, img_folder_dst)
            print(f"✅ 排版完成，并成功迁移图片: {relative_path}")
        else:
            print(f"✅ 排版完成 (无图片): {relative_path}")

def main():
    parser = argparse.ArgumentParser(description="Obsidian Regex Pipeline 批量递归排版工具")
    parser.add_argument("-i", "--input", type=str, default=str(DEFAULT_INPUT), help="待处理 .md 文件的输入目录")
    parser.add_argument("-o", "--output", type=str, default=str(DEFAULT_OUTPUT), help="排版后 .md 文件的保存目录")
    parser.add_argument("-r", "--regex", type=str, default="", help="规则文件夹路径 (支持绝对/相对/简写模式)")
    args = parser.parse_args()

    print("🚀 Markdown 批量正则流水线启动")
    
    target_regex_dir = resolve_regex_dir(args.regex)
    
    rules = load_pipeline_rules(target_regex_dir)
    if not rules:
        print("⚠️ 规则列表为空或路径无效，已终止。")
        return
        
    print(f"📁 当前应用规则库: {target_regex_dir.absolute()}")
    print(f"✅ 成功加载 {len(rules)} 条正则排版规则")
    
    process_markdown_files(rules, args.input, args.output)
    
    print("🎉 全部文档及其附件格式化与迁移完成！")

if __name__ == "__main__":
    main()