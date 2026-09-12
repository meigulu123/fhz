#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
下载离线 TTS 语音模型文件 → static/tts/
来源: HuggingFace csukuangfj/vits-zh-aishell3
运行: python download_tts_models.py
"""

import os
import sys
import io
import urllib.request
import time

# 修复 Windows 编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 目标目录
TT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'tts')

# 国内镜像（直连超时则自动切换）或直接使用 hf-mirror.com
USE_MIRROR = True  # 设为 False 用官方源

HF_OFFICIAL = 'https://huggingface.co'
HF_MIRROR   = 'https://hf-mirror.com'

BASE_URL = HF_MIRROR if USE_MIRROR else HF_OFFICIAL

# 模型文件列表（文件名, 路径）
FILES = [
    ('vits-aishell3.onnx', '/csukuangfj/vits-zh-aishell3/resolve/main/vits-aishell3.onnx'),
    ('tokens.txt',         '/csukuangfj/vits-zh-aishell3/resolve/main/tokens.txt'),
    ('lexicon.txt',        '/csukuangfj/vits-zh-aishell3/resolve/main/lexicon.txt'),
]

SIZES = {
    'vits-aishell3.onnx': 51 * 1024 * 1024,   # ~51 MB
    'tokens.txt':          2 * 1024 * 1024,   # ~2 MB
    'lexicon.txt':         3 * 1024 * 1024,   # ~3 MB
}


def format_size(n):
    if n < 1024:
        return f'{n} B'
    elif n < 1024 * 1024:
        return f'{n/1024:.0f} KB'
    else:
        return f'{n/(1024*1024):.0f} MB'


def download(url, dest, expected_size=0):
    """下载单个文件，显示进度条"""
    if os.path.exists(dest):
        actual = os.path.getsize(dest)
        if expected_size and actual >= expected_size * 0.95:
            print(f'  [OK] 已存在 ({format_size(actual)})，跳过')
            return True
        else:
            print(f'  [WARN] 文件不完整 ({format_size(actual)})，重新下载...')

    print(f'  => 下载中... {format_size(expected_size) if expected_size else "未知大小"}')

    def report(block_num, block_size, total_size):
        downloaded = block_num * block_size
        if total_size > 0:
            pct = min(downloaded / total_size, 1.0)
            bar_len = 30
            filled = int(bar_len * pct)
            bar = '#' * filled + '.' * (bar_len - filled)
            sys.stdout.write(
                f'\r    [{bar}] {pct*100:5.1f}%  '
                f'{format_size(downloaded)} / {format_size(total_size)}'
            )
            sys.stdout.flush()

    try:
        urllib.request.urlretrieve(url, dest, reporthook=report)
        print()
        actual = os.path.getsize(dest)
        print(f'  [OK] 下载完成 ({format_size(actual)})')
        return True
    except Exception as e:
        print(f'\n  [FAIL] 下载失败: {e}')
        return False


def main():
    os.makedirs(TT_DIR, exist_ok=True)

    print('=' * 60)
    print('  陪优佳 — 离线 TTS 模型下载工具')
    print(f'  目标目录: {TT_DIR}')
    print('  来源: HuggingFace csukuangfj/vits-zh-aishell3')
    print('=' * 60)
    print()

    total = len(FILES)
    ok = 0

    for i, (filename, path) in enumerate(FILES, 1):
        url = BASE_URL + path
        dest = os.path.join(TT_DIR, filename)
        expected = SIZES.get(filename, 0)
        print(f'[{i}/{total}] {filename}')
        if download(url, dest, expected):
            ok += 1
        print()

    print('=' * 60)
    print(f'  完成: {ok}/{total} 个文件下载成功')
    if ok == total:
        print(f'  模型文件已就绪 → {TT_DIR}')
        print('  重启 python server.py 即可使用离线 TTS')
    else:
        print('  [WARN] 部分文件下载失败，请检查网络后重试')
    print('=' * 60)


if __name__ == '__main__':
    main()
    input('\n按 Enter 退出...')
