"""
自动截图脚本：打开 demo.html 并截取页面图片。
依赖：pip install playwright
用法：python capture_demo.py
输出：capture_demo_full.png / capture_demo_1.png / capture_demo_2.png
"""
import importlib
import sys
import time
import os

# 自动安装 playwright（仅首次）
try:
    importlib.import_module("playwright.sync_api")
except ImportError:
    print("正在安装 playwright ...")
    os.system(f'"{sys.executable}" -m pip install playwright -q')
    os.system(f'"{sys.executable}" -m playwright install chromium')

from playwright.sync_api import sync_playwright

HTML_PATH = os.path.join(os.path.dirname(__file__), "demo.html")
URL = "file:///" + HTML_PATH.replace("\\", "/")

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(URL, wait_until="networkidle")
        time.sleep(1)

        # 1) 全页截图
        page.screenshot(path="capture_demo_full.png", full_page=True)

        # 2) 配置翻译器区域
        config_card = page.locator("section.card").nth(1)
        config_card.screenshot(path="capture_demo_1.png")

        # 3) 协议翻译器区域
        proto_card = page.locator("section.card").nth(2)
        proto_card.screenshot(path="capture_demo_2.png")

        browser.close()
    print("截图完成：")
    print(" - capture_demo_full.png")
    print(" - capture_demo_1.png")
    print(" - capture_demo_2.png")

if __name__ == "__main__":
    main()
