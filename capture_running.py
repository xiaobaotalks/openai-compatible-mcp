"""
截图脚本：截取 wizard 和 proxy 的运行状态。
"""
import time
import os
from playwright.sync_api import sync_playwright

def screenshot(name, url, wait_ms=1500):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(url, wait_until="networkidle")
        time.sleep(wait_ms / 1000)
        page.screenshot(path=name, full_page=False)
        browser.close()
    print(f"screenshot saved: {name}")

if __name__ == "__main__":
    screenshot("wizard_running.png", "http://127.0.0.1:8989")
    screenshot("proxy_running.png", "http://127.0.0.1:7878/v1/models")
