# MinerU PDF 批量 OCR to Markdown 及正则处理

- pdf2mineru.py 通过 MinerU 精准解析 API，将 PDF 批量 OCR 并转换为 Markdown。
- md_regex_pipeline.py 根据正则表达式规则集，将 Markdown 批量格式化。

## 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10 / 11 |
| Python | >= 3.10（推荐 3.12 或 3.13） |

## 安装依赖

```bash
pip install pyyaml requests pypdf regex
```

## 目录结构

```
minerupy/
├─input                   # 放入待处理 pdf
├─output                  # mineru 处理后的 .md 文件及附件出现的地方
├─reput                  # 正则排版后的 .md 文件及附件出现的地方
├─src 
│  └─regex               # regex pipeline 规则集              
│  │  ├─排版              
│  │  └─消除多余换行    
├─temp                     # 自动生成，存放分割后的临时文件
├─default.yaml             # mineru 配置，请在此填入 mineru API
├─md_regex_pipeline.py     # 对 output 中的 .md 批量正则处理
└─pdf2mineru_better.py     # 主脚本
```


## 配置

在 [MinerU 官网](https://mineru.net/apiManage) 申请 API Token，填入 `default.yaml`：

```yaml
api_token: "你的API Token"

model_version: "pipeline"   # pipeline（快速）或 vlm（更精准）
is_ocr: true                # 启用 OCR（扫描件必须开启）
enable_formula: true        # 公式识别
enable_table: true          # 表格识别
language: "ch"              # 中文文档设为 ch

max_pages: 200              # 单文件最大页数（超出自动分页）
max_size_mb: 200            # 单文件最大体积 MB（超出自动分割）
split_size_mb: 150          # 体积分割时每块目标大小 MB
batch_size: 50              # 每批上传文件数上限
poll_interval: 15           # 轮询间隔（秒）

process_mode_threshold: 15   # 当 input 中 PDF 数量 ≥ 此值时，自动激活 【逐本串行模式】 安全处理
```

## 使用

1. 将 PDF 文件放入 `input/` 文件夹
2. 运行脚本：
   ```bash
   python pdf2mineru.py
   ```
3. 等待脚本完成，最终 `.md` 文件及图片附件在 `output/` 文件夹中


## 处理流程说明

`pdf2mineru.py` 会遍历输入目录，在输出目录建立相同目录结构，然后执行：

```
阶段一：页数检查 → 页数 ≤ 200 直接存入 temp，> 200 按 200 页分割
阶段二：体积检查 → 体积 > 200MB 的文件按 150MB 分割
阶段三：批量上传到 MinerU → 实时显示解析进度 → 下载结果
阶段四：自动合并碎片 → 输出完整的 .md 文件及图片
阶段五：自动清理 temp 中的过程文件

```

`pdf2mineru.py` 会根据 `default.yaml` 中 `process_mode_threshold` 的值选择处理模式，默认值 15。

1. 批量处理：当输入的 pdf 总数 ＜ 15 时，先对全部 pdf 文件执行阶段一，再对全部文件执行阶段二 …… 处理时更快；
2. 逐本处理：当输入的 pdf 总数 ≥ 15 时，逐本执行阶段一至阶段五，处理大量文件时更安全；

## 显式指定路径运行

`pdf2mineru.py` 支持选择输入和输出的目录，如：

```bash
python pdf2mineru.py -i "C:\我的图书\原始PDF" -o "C:\我的图书\OCR结果"
```

如果没有指定输入文件夹 `-i "C:\我的图书\原始PDF"` ，默认选择脚本所在目录下的 `input` 文件夹。没有指定输出文件夹同理。


## 正则流水线脚本

`md_regex_pipeline.py` 的功能是读取 `./src/regex`目录下的规则文件，批量格式化 output 目录中的 .md 文件，并在 reput 目录输出格式化后的 .md 文件及其附件。

规则文件可以直接复制 Obsidian 插件 [regex pipeline](https://github.com/No3371/obsidian-regex-pipeline) 的规则文件。regex pipeline 的规则文件为每行一个正则规则：

```
"SEARCH"->"REPLACE"
```

- regex pipeline 的一个特殊语法：由于 Obsidian 的限制，"REPLACE" 中用 Enter 换行，而不是`\n`。例如将超过三个的空行换为一个空行的规则：

```
"\n{3,}"->"

"
```

- `"SEARCH"` 和 `"REPLACE"` 内可以有多个`"`；
- 每个规则文件包含一系列规则，每行一个，从上至下依次执行；
- 由于正则表达式的规则顺序会影响格式化的效率和可行性，因此请关注规则文件中规则的顺序；
- 由于正则表达式的规则顺序会影响格式化的效率和可行性，因此请关注规则文件的顺序；regex 下的规则按文件名的字母/数字顺序执行，可以给规则文件加上数字前缀如 `01_`、`_02` 以显式地控制格式化顺序；
- `md_regex_pipeline.py`只会读取 `/src/regex` 单层目录下的规则文件，不会读取子文件夹中的文件，可以根据这个特点设计不同的规则集；

## 组合执行

pdf2mineru 脚本（pdf→md，input→output）和 md_regex_pipeline 脚本（md→regex md，output→reput）通过管道符顺序执行，如：

```bash
python pdf2mineru.py && python md_regex_pipeline.py
```

## 报错

### pypdf.errors.DependencyError…

pdf 被加密了，需要解密。安装 `cryptography`：

```bash
pip install cryptography
```

再次运行

```bash
python pdf2mineru.py
```

如果解密不了，请把加密的 pdf 移出输入文件夹。







