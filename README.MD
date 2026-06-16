# 🦆 MALLARD

## 本地数据仓库 · 数据精炼版

![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square&logo=python)
![DuckDB](https://img.shields.io/badge/DuckDB-1.2.2-yellow?style=flat-square)
![Streamlit](https://img.shields.io/badge/Streamlit-1.45.1-red?style=flat-square&logo=streamlit)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey?style=flat-square&logo=windows)

> 拖入你的 CSV、Excel、Parquet 或 JSON，让鸭子完成剩下的工作。

MALLARD 是一款**100% 本地、无需服务器的数据工具**，基于 DuckDB + Streamlit 构建。上传杂乱的数据集，自动清洗，通过交互式图表探索，运行自定义 SQL，并导出精炼后的结果 —— 全程不触碰云端。

<p align="center">
  <img src="assets/welcome.png" width="700"/>
  <img src="assets/dashboard.png" width="700"/>
</p>

---

## 🎬 演示

<p align="center">
  <img src="assets/demo.gif" width="700" alt="MALLARD 演示"/>
</p>

---

## ✨ 功能特性

- **多格式导入** —— 支持 CSV、Excel（.xlsx/.xls）、Parquet、JSON。
- **零 Pandas 内存占用** —— 使用 DuckDB 原生 SQL 下推，处理超大内存数据集而不发生 OOM 崩溃。
- **自动深度清洗** —— 去重、删除空列、智能类型修复（无硬编码逻辑）。
- **智能摘要** —— 在数据库引擎内即时完成自动化洞察和缺失值检测。
- **分析探索器** —— 通过智能 SQL 采样和原生聚合后再渲染图表，保持浏览器极速响应。
- **自定义 SQL** —— 直接对表运行任意 DuckDB 查询。
- **直接落盘导出** —— 使用 DuckDB 原生 `COPY` 命令实现超快下载（CSV、Parquet、JSON），绕过 Python 内存。
- **100% 本地** —— 数据永远不会离开你的电脑，无需云端上传。
- **独立 .exe** —— 可分发 Windows 可执行文件，接收方无需安装 Python。

---

## 🚀 快速开始

### 方式一 —— 从源码运行

```bash
# 1. 克隆仓库
git clone https://github.com/KMoex-HZ/mallard.git
cd mallard

# 2. 安装依赖
pip install -r requirements.txt

# 3. 运行
streamlit run mallard.py
```

### 方式二 —— Windows .exe（无需 Python）

1. 从 [Releases](../../releases) 下载 `MALLARD.zip`
2. 解压 zip
3. 双击 `MALLARD.exe`
4. 浏览器会自动打开 `http://localhost:8501`

---

## 📦 环境要求

```
streamlit==1.45.1
duckdb==1.2.2
pandas==2.2.3
plotly==6.0.1
openpyxl==3.1.5
pyarrow==19.0.1
xlrd==2.0.1
psutil==6.1.1
```

推荐使用 Python 3.10+。

---

## 🛠️ 从源码构建 .exe

```bash
pip install pyinstaller pyinstaller-hooks-contrib
python setup_exe.py
```

输出：`dist/MALLARD/MALLARD.exe`  
发布时将整个 `dist/MALLARD/` 文件夹打包为 zip。

---

## 🧹 深度清洗工作原理

- **去重**：通过 SQL `DISTINCT` 删除完全重复的行。
- **删除空列**：统计每列非空值数量，即时删除全空列。
- **智能数值修复**：使用 `TRY_CAST` 检测并转换脏的 VARCHAR 数字为 DOUBLE，无需硬编码列名。
- **宽格式检测**：自动将日期作为列标题的透视表 melt 为长格式。

---

## 📁 项目结构

```
mallard/
├── mallard.py          # Streamlit 主应用
├── launcher.py         # .exe 打包入口
├── setup_exe.py        # PyInstaller 构建脚本
├── requirements.txt
└── data/               # 自动创建，放入文件即可自动导入
```

---

## 🦆 为什么选择 MALLARD？

大多数数据工具要么太重（完整的 BI 平台），要么太简陋（仅 CSV 查看器）。MALLARD 处于中间地带 —— 一个快速、有主见、能在分析前真正修复数据的本地仓库。

借助 DuckDB 的进程内 OLAP 引擎，它可以处理通常会让标准 pandas/Streamlit 应用崩溃的数据集。

无需 Tableau 许可证。无需云端上传。只要一只鸭子和 DuckDB。

---

## 作者

Khairunnisa Maharani

## 许可证

MIT
