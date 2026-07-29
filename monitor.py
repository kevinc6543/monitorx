import os
import json
import re
import yaml
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright

STATE_FILE = Path("state.json")
CONFIG_FILE = Path("config.yaml")
HKT = timezone(timedelta(hours=8))

def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def now_hkt():
    return datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S")

def send_telegram(token: str, chat_id: str, message: str):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        print(f"Telegram 回應: {resp.status_code}")
        return resp.status_code == 200
    except Exception as e:
        print(f"Telegram 發送失敗: {e}")
        return False

def check_target(page, target):
    method = target.get("method", "text").lower()
    value = target.get("value", "")
    must_have = target.get("must_have", [])
    must_not_have = target.get("must_not_have", [])

    try:
        content = page.content()

        # 基本檢測
        if method == "text":
            base_found = value in content if value else True
        elif method == "css":
            base_found = page.locator(value).count() > 0
        elif method == "xpath":
            base_found = page.locator(f"xpath={value}").count() > 0
        elif method == "regex":
            base_found = bool(re.search(value, content, re.IGNORECASE | re.DOTALL))
        else:
            base_found = False

        if not base_found:
            print(f"  → 基本條件唔符合")
            return "LOST"

        # must_have 檢查
        for kw in must_have:
            if kw not in content:
                print(f"  → 缺少必須字眼: {kw}")
                return "LOST"

        # must_not_have 檢查
        for kw in must_not_have:
            if kw in content:
                print(f"  → 出現禁止字眼: {kw}")
                return "LOST"

        print(f"  → 所有條件通過 → FOUND")
        return "FOUND"

    except Exception as e:
        print(f"  → 檢查出錯: {e}")
        return "ERROR"

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        raise ValueError("缺少 TELEGRAM secrets")

    config = load_config()
    settings = config.get("settings", {})
    targets = config.get("targets", [])
    only_notify_found = settings.get("only_notify_found", True)
    failure_threshold = settings.get("failure_threshold", 3)

    state = load_state()
    changed = False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
            locale="zh-HK"
        )
        page = context.new_page()
        page.set_default_timeout(settings.get("timeout", 30000))

        for target in targets:
            tid = target["id"]
            name = target.get("name", tid)
            url = target["url"]

            # 初始化 state
            if tid not in state:
                state[tid] = {"status": "LOST", "failures": 0}

            print(f"\n正在檢查: {name}")
            print(f"網址: {url}")

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(settings.get("wait_after_load", 3000))
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)

                current_status = check_target(page, target)
            except Exception as e:
                print(f"  → 載入失敗: {e}")
                current_status = "ERROR"

            prev_status = state[tid].get("status", "LOST")
            failures = state[tid].get("failures", 0)

            print(f"  → 上次狀態: {prev_status} | 今次: {current_status}")

            # 處理失敗計數
            if current_status == "ERROR":
                failures += 1
                state[tid]["failures"] = failures
                changed = True

                if failures == failure_threshold:
                    msg = (
                        f"<b>⚠️ 檢查異常通知</b>\n\n"
                        f"商品：<b>{name}</b>\n"
                        f"已連續失敗 <b>{failures}</b> 次\n"
                        f"時間：{now_hkt()}\n"
                        f"連結：{url}"
                    )
                    send_telegram(token, chat_id, msg)
                    print("→ 已發送連續失敗通知")
            else:
                # 成功檢查，重置失敗次數
                if failures > 0:
                    state[tid]["failures"] = 0
                    changed = True

                # 狀態有變化
                if current_status != prev_status:
                    state[tid]["status"] = current_status
                    changed = True

                    # 只在變成 FOUND 時通知
                    if current_status == "FOUND" and only_notify_found:
                        msg = (
                            f"<b>有貨通知！</b>\n\n"
                            f"商品：<b>{name}</b>\n"
                            f"狀態：<b>FOUND</b>\n"
                            f"時間：{now_hkt()}\n"
                            f"連結：{url}"
                        )
                        send_telegram(token, chat_id, msg)
                        print("→ 已發送有貨通知")

        browser.close()

    if changed:
        save_state(state)
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write("changed=true\n")
    else:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write("changed=false\n")

    print("\n監控完成")

if __name__ == "__main__":
    main()
