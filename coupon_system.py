# coupon_system.py
import os
import json
import time
import hashlib
import base64
import requests
from dotenv import load_dotenv
load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")

def _github_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

def github_load_json(path, default):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}?ref={GITHUB_BRANCH}"
    r = requests.get(url, headers=_github_headers())
    if r.status_code != 200:
        return default

    data = r.json()
    content = base64.b64decode(data.get("content", "")).decode("utf-8").strip()

    if not content:
        return default

    try:
        return json.loads(content)
    except Exception:
        return default


def github_save_json(path, data):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"

    content = base64.b64encode(
        json.dumps(data, indent=2, ensure_ascii=False).encode()
    ).decode()

    sha = None
    r = requests.get(url, headers=_github_headers())
    if r.status_code == 200:
        sha = r.json().get("sha")

    payload = {
        "message": f"update {path}",
        "content": content,
        "branch": GITHUB_BRANCH
    }
    if sha:
        payload["sha"] = sha

    requests.put(url, headers=_github_headers(), json=payload)


# 🔐 CONFIG — Edit these. Changing ANY value forces reset.
COUPON_CODE = "WELCOME50"       # ← Change this to rotate
COUPON_CREDITS = 15
MAX_USES = 50
VALID_HOURS = 24

USERS_FILE = "users.json"
COUPONS_FILE = "coupons.json"


def _load_json(path, default):
    return github_load_json(path, default)


def _save_json(path, data):
    github_save_json(path, data)


# ✅ Generate config fingerprint
def _get_config_hash():
    config_str = f"{COUPON_CODE}|{COUPON_CREDITS}|{MAX_USES}|{VALID_HOURS}"
    return hashlib.md5(config_str.encode()).hexdigest()[:8]

def init_coupon_system():
    coupons = _load_json(COUPONS_FILE, {})
    code = COUPON_CODE.upper()
    current_hash = _get_config_hash()

    # ✅ Force reset if hash changed (i.e., you updated config)
    should_reset = (
        code not in coupons
        or coupons[code].get("_config_hash") != current_hash
    )

    if should_reset:
        coupons[code] = {
            "used_by": [],
            "created_at": time.time(),
            "config": {
                "credits": COUPON_CREDITS,
                "max_uses": MAX_USES,
                "valid_hours": VALID_HOURS,
            },
            "_config_hash": current_hash,  # ← Critical: track version
            "_reset_time": time.time(),
        }
        _save_json(COUPONS_FILE, coupons)
        print(f"✅ Coupon '{code}' activated (v{current_hash})")

def get_coupon_prompt_info():
    coupons = _load_json(COUPONS_FILE, {})
    code = COUPON_CODE.upper()
    coupon = coupons.get(code)
    if not coupon:
        return None
    cfg = coupon["config"]
    used = len(coupon["used_by"])
    expires_at = coupon["created_at"] + cfg["valid_hours"] * 3600
    remaining = max(0, int(expires_at - time.time()))
    hours = remaining // 3600
    mins = (remaining % 3600) // 60
    return {
        "credits": cfg["credits"],
        "used": used,
        "max": cfg["max_uses"],
        "expires_in": f"{hours}h {mins}m"
    }

def redeem_coupon(user_id: int):
    coupons = _load_json(COUPONS_FILE, {})
    users = _load_json(USERS_FILE, {})
    code = COUPON_CODE.upper()
    coupon = coupons.get(code)
    if not coupon:
        return {"success": False, "message": "❌ No active coupon."}

    cfg = coupon["config"]
    used_by = coupon.get("used_by", [])
    created_at = coupon.get("created_at", time.time())
    expires_at = created_at + cfg["valid_hours"] * 3600

    if time.time() > expires_at:
        return {"success": False, "message": "🕒 Coupon expired. Check channel for new code."}
    if len(used_by) >= cfg["max_uses"]:
        return {"success": False, "message": "🚫 Slots full!"}
    if user_id in used_by:
        return {"success": False, "message": "🎫 Already redeemed."}

    # ✅ Success
    used_by.append(user_id)
    coupons[code]["used_by"] = used_by
    _save_json(COUPONS_FILE, coupons)

    uid = str(user_id)
    user = users.get(uid, {"user_id": user_id, "balance": 20, "joined_at": time.time()})
    user.setdefault("credits_used", 0)
    user.setdefault("redeemed_coupons", [])
    user.setdefault("joined_at", time.time())
    user["balance"] = user.get("balance", 20) + COUPON_CREDITS
    user["redeemed_coupons"].append(COUPON_CODE)
    users[uid] = user
    _save_json(USERS_FILE, users)

    return {
        "success": True,
        "message": f"🎉 <b>Congratulations!</b>\n+{COUPON_CREDITS} credits added!",
        "credits_added": COUPON_CREDITS
    }

def sync_user_from_main(user_id: int, balance: int, credits_used: int):
    users = _load_json(USERS_FILE, {})
    uid = str(user_id)
    user = users.get(uid, {"user_id": user_id, "joined_at": time.time()})
    user["balance"] = balance
    user["credits_used"] = credits_used
    user.setdefault("redeemed_coupons", [])
    users[uid] = user

    _save_json(USERS_FILE, users)
