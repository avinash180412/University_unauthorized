import os
from dotenv import load_dotenv
load_dotenv() 
import asyncio
import logging
import time
import json as json_lib
import html
import re
from datetime import datetime
from typing import Dict
# ====== 1️⃣ WEB SERVER (Render needs this) ======
from flask import Flask
import threading
import os

app = Flask(__name__)

@app.route("/")
def home():
    return "Service is running 🚀"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()

import asyncio


from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# ✅ Import coupon system (as per your setup)
try:
    from coupon_system import (
        init_coupon_system,
        get_coupon_prompt_info,
        redeem_coupon,
        sync_user_from_main,
        _load_json,
        _save_json,
    )

    # 🔒 FORCE INIT USERS STORAGE (CRITICAL)
    users = _load_json("users.json", {})
    _save_json("users.json", users)

    init_coupon_system()

except Exception as e:
    logging.error(f"Storage init failed: {e}")


# ✅ Group config — verified from your channels
LOOKUP_GROUP_ID = -1003278446218  
pending_requests = {}  # {user_id: {cmd, target, group_msg_id, update}}

# ----------------------------
# CONFIG
# ----------------------------

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ Missing TELEGRAM_BOT_TOKEN in .env")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

REQUEST_COOLDOWN = 5

# ----------------------------
# USER DATA
# ----------------------------



def _ensure_data_dir():
    os.makedirs("data", exist_ok=True)

def load_user(user_id: int) -> dict:
    defaults = {
        "user_id": user_id,
        "balance": 20,
        "last_request_time": 0,
        "referred_by": None,
        "referrals_count": 0,
        "last_coupon_day": None,
        "used_one_time_coupons": [],
        "total_spent": 0,
        "verified": False,
    }

    users = _load_json("users.json", {})
    uid = str(user_id)

    user = users.get(uid, {})
    for k, v in defaults.items():
        user.setdefault(k, v)

    return user


def save_user(user_id: int, user_data: dict):
    users = _load_json("users.json", {})
    users[str(user_id)] = user_data
    _save_json("users.json", users)

# HELPERS
# ----------------------------

async def is_user_in_channels(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    channels = [
        "@shadow_officia",      # Main channel (88 members)
        "@intellegence_back",      # Backup (1 member)
        "@Shadow_updat",       # Coupons (37 subscribers)
    ]

    for channel in channels:
        try:
            member = await context.bot.get_chat_member(channel, user_id)
            if member.status in ("left", "kicked"):
                return False
        except Exception as e:
            logger.error(f"Verification failed for {channel}: {e}")
            return False
    return True

def credit_footer(user_id: int) -> str:
    balance = load_user(user_id)["balance"]
    return f"\n\n🔖 Credits: <code>{balance}</code>"

def can_make_request(user_id: int) -> bool:
    user = load_user(user_id)
    return (time.time() - user["last_request_time"]) >= REQUEST_COOLDOWN

def deduct_credits(user_id: int, amount: int = 2) -> bool:
    user = load_user(user_id)
    if user["balance"] < amount:
        return False
    user["balance"] -= amount
    user["total_spent"] = user.get("total_spent", 0) + amount
    user["last_request_time"] = time.time()
    save_user(user_id, user)
    try:
        sync_user_from_main(user_id, user["balance"], user["total_spent"])
    except:
        pass
    return True

def add_credits(user_id: int, amount: int):
    user = load_user(user_id)
    user["balance"] += amount
    save_user(user_id, user)
    try:
        sync_user_from_main(user_id, user["balance"], user.get("total_spent", 0))
    except:
        pass

def generate_referral_link(user_id: int) -> str:
    return f"https://t.me/Shadow_int_kosmic_bot?start=ref_{user_id}"

def safe_edit(query, text: str, markup=None):
    try:
        return query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
    except Exception as e:
        if "message is not modified" in str(e).lower():
            return query.edit_message_text(text + '\u200b', reply_markup=markup, parse_mode=ParseMode.HTML)
        raise

def is_error_reply(text: str) -> bool:
    if not text:
        return True
    text = text.lower()
    return any(kw in text for kw in [
        "error", "failed", "not found", "no data", "timeout", "502", "503", "504", "404", "invalid"
    ])

# ----------------------------
# MAIN MENU
# ----------------------------
HELP_TEXT = (
    "📘 <b>SHADOW OSINT — HELP GUIDE</b>\n"
    "──────────────────────────\n\n"

    "📱 <b>Mobile Number Search</b>\n"
    "<code> 9876543210</code>\n"
    "Search comprehensive details using mobile number\n\n"

    "⚡ <b>Power Mobile Search</b>\n"
    "<code>9876543210</code>\n"
    "Advanced mobile number search with more details\n\n"

    "💳 <b>Aadhaar V2 Search</b>\n"
    "<code> 123456789012</code>\n"
    "Get Aadhaar card information\n\n"

    "🏠 <b>Rashan Card Details</b>\n"
    "<code> 123456789012</code>\n"
    "Get family members and rashan card information\n\n"

    "💳 <b>UPI Information</b>\n"
    "<code>username@paytm</code>\n"
    "Fetch UPI account holder details\n\n"

    "🏥 <b>ICMR Database</b>\n"
    "<code> 9876543210</code>\n"
    "Search ICMR medical records database\n\n"

    "🚗 <b>Vehicle RC Information</b>\n"
    "<code> UP32JM0855</code>\n"
    "Get vehicle registration, owner and challan details\n\n"

    "🚘 <b>Vehicle Info V2</b>\n"
    "<code> UP32JM0855</code>\n"
    "Get combined vehicle information from multiple sources\n\n"

    "👤 <b>Telegram User Info</b>\n"
    "<code>/ username</code>\n"
    "Get Telegram user information\n\n"

    "🏢 <b>GST Number Lookup</b>\n"
    "<code> 07AABCU9603R1ZX</code>\n"
    "Get GST business information\n\n"

    "🏦 <b>IFSC Code Lookup</b>\n"
    "<code> SBIN0000001</code>\n"
    "Get bank branch details\n\n"

    "📄 <b>PAN Card Information</b>\n"
    "<code> ABCDE1234F</code>\n"
    "Get PAN card details and verification\n\n"

    "💡 <b>Tips</b>\n"
    "• Rate limit: 1 request per 5 seconds\n"
    "• Large results are sent as files\n"
    "• Use responsibly and ethically\n"
    "──────────────────────────"
)

PRICING_TEXT = (
    "💳 <b>RECHARGE & ACCESS PLANS</b>\n"
    "──────────────────────────\n\n"

    "🔎 <b>2 Credit = 1 Search</b>\n\n"

    "⚡ <b>Credit-Based Plans</b>\n"
    "<i>🔥 50% OFF — Welcome Offer</i>\n\n"

    "₹<s>99</s>  <b>₹49</b>  → <b>25 Credits</b>\n"
    "₹<s>199</s> <b>₹99</b>  → <b>50 Credits</b>\n"
    "₹<s>299</s> <b>₹199</b> → <b>110 Credits</b>\n"
    "₹<s>399</s> <b>₹299</b> → <b>150 Credits</b>\n"
    "₹<s>499</s> <b>₹399</b> → <b>190 Credits</b>\n"
    "₹<s>699</s> <b>₹499</b> → <b>250 Credits</b>\n"
    "₹<s>999</s> <b>₹699</b> → <b>450 Credits</b>\n"
    "₹<s>1499</s> <b>₹999</b> → <b>1000 Credits</b>\n\n"

    "🎁 <i>Credits include bonus (Double + 5)</i>\n\n"

    "🔒 <b>Unlimited Search Plans</b>\n"
    "<i>🔥 50% OFF — Welcome Offer</i>\n\n"

    "🚀 <b>7 Days</b>   ₹<s>1399</s>  <b>₹699</b>\n"
    "🚀 <b>15 Days</b>  ₹<s>2599</s>  <b>₹1299</b>\n"
    "🚀 <b>30 Days</b>  ₹<s>4999</s>  <b>₹2499</b>\n"
    "🚀 <b>1 Year</b>   ₹<s>13999</s> <b>₹6999</b>\n\n"

    "📩 <b>Need more credits?</b>\n"
    "Just Message the <b>Admin</b> 💬\n\n"

    "⚠️ <i>Use responsibly & ethically.</i>\n"
    "──────────────────────────"
)

PROTECT_TEXT = (
    "🛡 <b>PROTECT ME — PRIVACY MODE</b>\n"
    "──────────────────────────\n\n"
    "🔐 Hide your activity footprint\n"
    "🚫 YOUR NUMBER BECOME UNSEARCHABLE \n"
    "👁 Monitor suspicious lookups\n"
    "📢 Your Number will Be completly removed  from our Database\n\n"
    "💡 <i>This feature helps protect your digital identity.</i>\n\n"
    "📩 Contact <b>Admin</b> to activate protection.\n"
    "──────────────────────────"
)

def is_protected_value(value: str) -> bool:
    data = _load_json("protect.json", {})
    protected = data.get("numbers", [])

    value = value.strip().lower()

    return value in {str(x).lower() for x in protected}

PROTECTED_MSG = (
    "🚫 <b>Access Restricted</b>\n\n"
    "This number is <b>protected under VIP plans</b> 🔐\n"
    "You are not authorized to search this data.\n\n"
    "📩 Contact <b>Admin</b> for access."
)




MAIN_MENU_KEYBOARD = [
    [InlineKeyboardButton("📱 Mobile Search", callback_data="cmd_num"),
     InlineKeyboardButton("⚡ Advanced Mobile", callback_data="cmd_num2")],
    [InlineKeyboardButton("🆔 Aadhaar Search", callback_data="cmd_aadh"),
     InlineKeyboardButton("🏠 Rashan Card", callback_data="cmd_rashan")],
    [InlineKeyboardButton("💳 UPI Lookup", callback_data="cmd_upi"),
     InlineKeyboardButton("🏦 IFSC Lookup", callback_data="cmd_ifsc")],
    [InlineKeyboardButton("🏢 GST Lookup", callback_data="cmd_gst"),
     InlineKeyboardButton("🚗 Vehicle RC", callback_data="cmd_vehicle")],
    [InlineKeyboardButton("🏥 ICMR", callback_data="cmd_icmr"),
     InlineKeyboardButton("👤 Telegram User", callback_data="cmd_tguser")],
    [InlineKeyboardButton("💣 OTP Bomb", callback_data="info_otp")],
    [InlineKeyboardButton("🎟️ Redeem Coupon", callback_data="redeem_coupon")],
    [InlineKeyboardButton("📊 Balance", callback_data="info_balance"),
     InlineKeyboardButton("🔗 Referral", callback_data="info_ref")],
    [InlineKeyboardButton("💰 Pricing", callback_data="info_pricing"),
     InlineKeyboardButton("🛡 Protect Me", callback_data="info_protect")],
    [InlineKeyboardButton("❓ Help", callback_data="info_help")],
]

def back_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]])

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, edit=False):
    user = update.effective_user
    user_id = user.id
    ud = load_user(user_id)

    status = "✅ ACTIVE" if ud.get("verified", False) else "⚠️ PENDING"
    username = f"@{user.username}" if user.username else "None"
    
    text = (
        "🟦🟦🟦 <b>SHADOW OSINT</b>🟦🟦🟦 \n"
        f"👤 <b>User:</b> {html.escape(user.first_name)}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"🔗 <b>Username:</b> {username}\n"
        f"💰 <b>Credits:</b> <code>{ud['balance']:.1f}</code>\n"
        f"👥 <b>Referrals:</b> {ud.get('referrals_count', 0)}\n\n"
        f"📌 <b>Status:</b> {status}\n\n"
        "🔹 <i>Select a service from the menu below:</i>\n"
    )

    markup = InlineKeyboardMarkup(MAIN_MENU_KEYBOARD)

    if edit and update.callback_query:
        await safe_edit(update.callback_query, text, markup)
    else:
        effective_msg = update.effective_message
        if effective_msg:
            await effective_msg.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                reply_markup=markup,
                parse_mode=ParseMode.HTML
            )

# ----------------------------
# HANDLERS
# ----------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_member = await is_user_in_channels(context, user_id)
    
    if is_member:
        if context.args and context.args[0].startswith("ref_"):
            try:
                ref_id = int(context.args[0].split("_")[1])
                if ref_id != user_id:
                    ref_user = load_user(ref_id)
                    referred_user = load_user(user_id)
                    if referred_user.get("referred_by") is None:
                        referred_user["referred_by"] = ref_id
                        save_user(user_id, referred_user)
                        add_credits(ref_id, 5)
                        ref_user = load_user(ref_id)
                        ref_user["referrals_count"] = ref_user.get("referrals_count", 0) + 1
                        save_user(ref_id, ref_user)
            except Exception as e:
                logger.error(f"Referral error: {e}")
        await show_main_menu(update, context)
    else:
        buttons = [
            [InlineKeyboardButton("🔹 Official Channel", url="https://t.me/shadow_officia")],
            [InlineKeyboardButton("🔹 Backup", url="https://t.me/intellegence_back")],
            [InlineKeyboardButton("🔹 Movies and fun", url="https://t.me/Shadow_updat")],
            [InlineKeyboardButton("✅ Verify Now", callback_data="verify_membership")],
        ]
        await update.message.reply_text(
            "🔐 <b>Access Required</b>\n\n"
            "Please join all channels to use the bot:\n"
            "• Official announcements \n"
            "• Backup channel \n"
            "• Daily coupon codes\n\n"
            "After joining, tap <b>✅ Verify Now</b>.",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.HTML
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    try:
        if data == "verify_membership":
            is_member = await is_user_in_channels(context, user_id)
            if is_member:
                user = load_user(user_id)
                user["verified"] = True
                save_user(user_id, user)
                await query.answer("✅ Verified!", show_alert=True)
                await show_main_menu(update, context, edit=False)
            else:
                await query.answer("❌ Not all channels joined.", show_alert=True)
                buttons = [
                    [InlineKeyboardButton("🔹 Official Channel", url="https://t.me/shadow_officia")],
                    [InlineKeyboardButton("🔹 Backup", url="https://t.me/intellegence_back")],
                    [InlineKeyboardButton("🔹 Fun", url="https://t.me/Shadow_updat")],
                    [InlineKeyboardButton("🔁 Try Again", callback_data="verify_membership")],
                ]
                await safe_edit(query,
                    "❌ Please join all channels first.\n\nAfter joining, tap <b>🔁 Try Again</b>.",
                    InlineKeyboardMarkup(buttons)
                )
            return

        if data == "main_menu":
            context.user_data.pop("awaiting_input_for", None)
            await show_main_menu(update, context, edit=True)
            return

        if data == "redeem_coupon":
            info = get_coupon_prompt_info()
            if not info:
                text = "❌ No active coupon." + credit_footer(user_id)
            else:
                text = (
                    "🎟️ <b>Redeem Today’s Coupon</b>\n\n"
                    f"👥 Claimed: {info['used']}/{info['max']}\n"
                    f"⏳ Ends in: {info['expires_in']}\n"
                    "❓ <a href=\"https://t.me/Shadow_updat\">Get code from channel</a>\n\n"
                    "<i>Enter the code below:</i>" + credit_footer(user_id)
                )
            context.user_data["awaiting_input_for"] = "coupon"
            await query.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=back_button())
            return

        info_map = {
            "info_balance": lambda: f"📊 <b>Balance</b>: <code>{load_user(user_id)['balance']}</code> credits",
            "info_ref": lambda: (
                f"🔗 <b>Referral Link</b>\n<code>{html.escape(generate_referral_link(user_id))}</code>\n"
                f"👥 Referred: {load_user(user_id).get('referrals_count', 0)}"
            ),
            "info_help": lambda: HELP_TEXT,
            "info_pricing": lambda: PRICING_TEXT,
            "info_protect": lambda: PROTECT_TEXT,
            "info_otp": lambda: "💣 <b>OTP Bombing</b>\n❌ Disabled for ethical reasons.",
        }

        
        if data in info_map:
            await safe_edit(query, info_map[data]() + credit_footer(user_id), back_button())
            return

        cmd_map = {
            "cmd_num": ("📱 Enter 10-digit mobile number(without +91):\n<b>Cost: 2 credits</b>", "num"),
            "cmd_num2": ("⚡ Enter 10-digit mobile number(without +91):\n<b>Cost: 2 credits</b>", "num2"),
            "cmd_aadh": ("🆔 Enter 12-digit Aadhaar number:\n<b>Cost: 2 credits</b>", "aadh"),
            "cmd_rashan": ("🏠 Enter Rashan Card ID (e.g., DEL1234):\n<b>Cost: 2 credits</b>", "rashan"),
            "cmd_upi": ("💳 Enter UPI ID (e.g., user@oksbi):\n<b>Cost: 2 credits</b>", "upi"),
            "cmd_ifsc": ("🏦 Enter 11-character IFSC code:\n<b>Cost: 2 credits</b>", "ifsc"),
            "cmd_gst": ("🏢 Enter 15-character GSTIN:\n<b>Cost: 2 credits</b>", "gst"),
            "cmd_vehicle": ("🚗 Enter Vehicle Reg. No. (e.g., UP32JM0855):\n<b>Cost: 2 credits</b>", "vehicle"),
            "cmd_icmr": ("🏥 Enter 10-digit mobile number:\n<b>Cost: 2 credits</b>", "icmr"),
            "cmd_tguser": ("👤 Enter Telegram username (without @):\n<b>Cost: 2 credits</b>", "tguser"),
        }

        if data in cmd_map:
            prompt, cmd = cmd_map[data]
            context.user_data["awaiting_input_for"] = cmd
            await query.message.reply_text(f"{prompt}", parse_mode=ParseMode.HTML)
            return

    except Exception as e:
        logger.exception("Button handler error")
        await query.message.reply_text("❌ An error occurred. Returning to menu.", parse_mode=ParseMode.HTML)
        await show_main_menu(update, context, edit=False)

# ----------------------------
# INPUT HANDLER
# ----------------------------

async def handle_user_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if "awaiting_input_for" not in context.user_data:
        await update.message.reply_text(
            "❌ Invalid input.\n\n🔹 Please select a service from the menu first.",
            parse_mode=ParseMode.HTML
        )
        return

    cmd = context.user_data.pop("awaiting_input_for", None)
    if not cmd:
        return

    # Validate
    valid = False
    target = text

    if cmd == "num" and text.isdigit() and len(text) == 10:
        valid = True
    elif cmd == "num2" and text.isdigit() and len(text) == 10:
        valid = True
    elif cmd == "aadh" and text.isdigit() and len(text) == 12:
        valid = True
    elif cmd == "rashan" and len(text) >= 4 and text[:3].isalpha() and text[3:].isdigit():
        valid = True
    elif cmd == "upi" and "@" in text and 5 < len(text) < 50 and text.count("@") == 1:
        valid = True
    elif cmd == "ifsc" and len(text) == 11 and text[:4].isalpha() and text[4:].isalnum():
        valid = True
    elif cmd == "gst" and len(text) == 15 and text[:2].isdigit() and text[2:12].isalnum() and text[12].isdigit():
        valid = True
    elif cmd == "vehicle" and 6 <= len(text) <= 12 and re.match(r"^[A-Z]{2}\d{1,2}[A-Z]{1,2}\d{1,4}$", text.upper().replace(' ', '')):
        valid = True
        target = text.upper().replace(' ', '')
    elif cmd == "icmr" and text.isdigit() and len(text) == 10:
        valid = True
    elif cmd == "tguser" and 3 <= len(text) <= 32 and text.replace('_', '').isalnum() and not text[0].isdigit():
        valid = True
    elif cmd == "coupon":
        expected = "Welcome50"
        if text.upper() == expected:
            result = redeem_coupon(user_id)
            msg = result["message"]
        else:
            msg = "❌ Invalid coupon code."
        await update.message.reply_text(msg + credit_footer(user_id), parse_mode=ParseMode.HTML)
        await show_main_menu(update, context, edit=False)
        return

    # ❌ INVALID INPUT
    if not valid:
        await update.message.reply_text(
        f"❌ Invalid input for <b>{cmd.upper()}</b>.\n\n"
        "🔹 Please enter a valid value.",
        parse_mode=ParseMode.HTML
        )
        await show_main_menu(update, context, edit=False)
        return

# 🔒 VIP PROTECTION CHECK (AFTER VALIDATION, BEFORE CREDITS)
    if is_protected_value(target):
        await update.message.reply_text(
            PROTECTED_MSG,
            parse_mode=ParseMode.HTML
        )
        await show_main_menu(update, context, edit=False)
        return


    if not can_make_request(user_id):
        w = max(1, int(REQUEST_COOLDOWN - (time.time() - load_user(user_id)["last_request_time"])))
        await update.message.reply_text(f"⏳ Wait {w}s.", parse_mode=ParseMode.HTML)
        await show_main_menu(update, context, edit=False)
        return

    if not deduct_credits(user_id, 2):
        await update.message.reply_text("❌ Insufficient credits.", parse_mode=ParseMode.HTML)
        await show_main_menu(update, context, edit=False)
        return

    try:
        sent = await context.bot.send_message(
            chat_id=LOOKUP_GROUP_ID,
            text=f"/{cmd} {target}",
            disable_notification=True
        )

        pending_requests[user_id] = {
            "group_msg_id": sent.message_id,
            "update": update,
            "cmd": cmd,
            "target": target,
        }

        await update.message.reply_text("🔍 Request sent to SHADOW network. Awaiting response...", parse_mode=ParseMode.HTML)

        # 90s timeout
        async def timeout_task():
            await asyncio.sleep(90)
            if user_id in pending_requests:
                pending_requests.pop(user_id, None)
                add_credits(user_id, 2)
                await update.message.reply_text(
                    "⏱️ Request timed out (50s).\n💰 2 credits refunded.",
                    parse_mode=ParseMode.HTML
                )
                await show_main_menu(update, context, edit=False)

        asyncio.create_task(timeout_task())

    except Exception as e:
        logger.error(f"Failed to send to group: {e}")
        add_credits(user_id, 2)
        await update.message.reply_text("❌ Server Down. Credits refunded.", parse_mode=ParseMode.HTML)
        await show_main_menu(update, context, edit=False)

def parse_mobile_json(raw_text: str, target: str):
    """
    Returns a LIST of parsed result dicts.
    """
    import re

    results = []

    try:
        json_match = re.search(r'(\{.*\}|\[.*\])', raw_text, re.DOTALL)
        if not json_match:
            return results

        data = json_lib.loads(json_match.group(1))

        # Find result array
        records = None
        if isinstance(data, dict):
            if "result" in data:
                records = data["result"]
            elif "data" in data and "result" in data["data"]:
                records = data["data"]["result"]
        elif isinstance(data, list):
            records = data

        if not records or not isinstance(records, list):
            return results

        for rec in records:
            if not isinstance(rec, dict):
                continue

            addr = str(rec.get("address", "") or "")
            addr = re.sub(r"[!]+", ", ", addr)
            addr = re.sub(r"\s+", " ", addr)
            addr = re.sub(r",\s*,", ", ", addr)

            results.append({
                "mobile": str(rec.get("mobile", target)),
                "name": str(rec.get("name", "") or ""),
                "father_name": str(rec.get("father_name", "") or ""),
                "address": addr.strip(" ,."),
                "alt_mobile": str(rec.get("alt_mobile", "") or ""),
                "circle": str(rec.get("circle", "") or ""),
                "id_number": str(rec.get("id_number", target)),
                "source": str(data.get("source", "/mobile")),
                "email": str(rec.get("email", "") or ""),
            })

    except Exception as e:
        logger.error(f"JSON parse error: {e}")

    return results


# ----------------------------
# FORMATTERS
# ----------------------------

def format_mobile_report(fields: dict, cmd: str, target: str) -> str:
    now = datetime.now().strftime("%d-%b-%Y %H:%M IST")
    title = "Advanced Mobile Lookup" if cmd == "num2" else "Mobile Lookup"

    lines = [
        "🟦 <b>SHADOW OSINT — MOBILE REPORT</b> 🟦",
        "──────────────────────────",
        f"🔍 <b>{title}</b>",
        f"🎯 Target: <code>{html.escape(target)}</code>",
        f"🔍 <b>Source:</b> <code>{html.escape(fields['source'])}</code>",
        "",
        f"📱 <b>Mobile:</b> <code>{html.escape(fields['mobile'])}</code>",
        "──────────────────────────",
    ]

    if fields["name"]:
        lines.append(f"👤 <b>Name:</b> {html.escape(fields['name'])}")
    if fields["father_name"]:
        lines.append(f"👨 <b>Father:</b> {html.escape(fields['father_name'])}")
    if fields["address"]:
        lines.append(f"🏠 <b>Address:</b> {html.escape(fields['address'])}")
    if fields["alt_mobile"]:
        lines.append(f"📞 <b>Alt Number:</b> <code>{html.escape(fields['alt_mobile'])}</code>")
    if fields["circle"]:
        lines.append(f"🌐 <b>Circle:</b> {html.escape(fields['circle'])}")
    if fields["id_number"]:
        lines.append(f"🆔 <b>ID Number:</b> <code>{html.escape(fields['id_number'])}</code>")

    lines.extend([
        "",
        "──────────────────────────",
        f"🕒 <i>Report generated: {now}</i>",
        "",
        "⚠️ <i>This data is for educational & authorized cybersecurity research only.</i>"
        "🚫 <i>Illegal or unethical use is your sole responsibility.</i>",
        "──────────────────────────",
    ])

    return "\n".join(lines)

def format_generic_report(raw_text: str, cmd: str, target: str) -> str:
    now = datetime.now().strftime("%d-%b-%Y %H:%M IST")
    names = {
        "aadh": "Aadhaar Search", "rashan": "Rashan Card", "upi": "UPI Lookup",
        "ifsc": "IFSC Lookup", "gst": "GST Search", "vehicle": "Vehicle RC",
        "tguser": "Telegram User", "icmr": "ICMR Search",
    }
    title = names.get(cmd, "OSINT Query")
    clean = html.escape(raw_text)
    body = "\n".join(
        (line if line.startswith(("•", "-", "✅", "❌")) else f"• {line}")
        for line in clean.splitlines() if line.strip()
    ) or "• No details available."

    return (
        "🟦 <b>SHADOW OSINT — REPORT</b> 🟦\n"
        "──────────────────────────\n"
        f"🔍 <b>{title}</b>\n"
        f"🎯 Target: <code>{html.escape(target)}</code>\n\n"
        f"{body}\n\n"
        "──────────────────────────\n"
        f"🕒 <i>Report generated: {now}</i>\n"
        "──────────────────────────"
    )

# ----------------------------
async def monitor_group_replies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not (
        msg.reply_to_message and
        msg.reply_to_message.from_user.id == context.bot.id and
        msg.chat.id == LOOKUP_GROUP_ID
    ):
        return

    reply_to_id = msg.reply_to_message.message_id
    raw_reply = (msg.text or "").strip()

    matched_user_id = None
    matched_req = None
    for user_id, req in list(pending_requests.items()):
        if req.get("group_msg_id") == reply_to_id:
            matched_user_id = user_id
            matched_req = req
            break

    if not matched_user_id or not matched_req:
        return

    pending_requests.pop(matched_user_id, None)

    update_obj = matched_req["update"]
    cmd = matched_req["cmd"]
    target = matched_req["target"]

    try:
        # =========================
        # MOBILE LOOKUPS (UNCHANGED)
        # =========================
        if cmd in ("num", "num2"):
            records = parse_mobile_json(raw_reply, target)

            if not records:
                add_credits(matched_user_id, 2)
                await update_obj.message.reply_text(
                    "❌ <b>Incomplete Result</b>\n"
                    "🔍 Unable to fetch Details.\n"
                    "💰 <b>2 credits refunded.</b>",
                    parse_mode=ParseMode.HTML
                )
                return

            if cmd == "num":
                rec = records[0]
                core_missing = (
                    not rec.get("name", "").strip() and
                    not rec.get("father_name", "").strip() and
                    not rec.get("address", "").strip()
                )

                if core_missing:
                    add_credits(matched_user_id, 2)
                    await update_obj.message.reply_text(
                        "❌ <b>Incomplete Result</b>\n"
                        "🔍 Unable to fetch Details.\n"
                        "💰 <b>2 credits refunded.</b>",
                        parse_mode=ParseMode.HTML
                    )
                else:
                    report = format_mobile_report(rec, cmd, target)
                    await update_obj.message.reply_text(
                        report, parse_mode=ParseMode.HTML
                    )

            else:
                valid_records = []
                for rec in records:
                    if (
                        rec.get("name", "").strip() or
                        rec.get("father_name", "").strip() or
                        rec.get("address", "").strip()
                    ):
                        valid_records.append(rec)

                if not valid_records:
                    add_credits(matched_user_id, 2)
                    await update_obj.message.reply_text(
                        "❌ <b>Incomplete Result</b>\n"
                        "🔍 Unable to fetch Details.\n"
                        "💰 <b>2 credits refunded.</b>",
                        parse_mode=ParseMode.HTML
                    )
                    return

                # top result normal
                await update_obj.message.reply_text(
                    format_mobile_report(valid_records[0], cmd, target),
                    parse_mode=ParseMode.HTML
                )

                combined = []
                for i, rec in enumerate(valid_records, start=1):
                    combined.append(
                        f"\nRESULT {i}\n" + format_mobile_report(rec, cmd, target)
                    )

                full_report = "\n\n".join(combined)

                if len(full_report) <= 3800:
                    await update_obj.message.reply_text(
                        full_report,
                        parse_mode=ParseMode.HTML
                    )
                else:
                    file_name = f"num2_{target}.txt"
                    with open(file_name, "w", encoding="utf-8") as f:
                        f.write(
                            full_report
                            .replace("<b>", "")
                            .replace("</b>", "")
                            .replace("<i>", "")
                            .replace("</i>", "")
                        )
                    await update_obj.message.reply_document(
                        document=open(file_name, "rb"),
                        caption="📄 Full mobile lookup report"
                    )

        # =========================
        # VEHICLE LOOKUP (TXT FALLBACK ADDED)
        # =========================
        elif cmd == "vehicle":
            if is_error_reply(raw_reply):
                add_credits(matched_user_id, 2)
                await update_obj.message.reply_text(
                    "❌ <b>Lookup Failed</b>\n"
                    "🔍 No result or service error.\n"
                    "💰 <b>2 credits refunded.</b>",
                    parse_mode=ParseMode.HTML
                )
            else:
                report = format_generic_report(raw_reply, cmd, target)

                if len(report) <= 3800:
                    await update_obj.message.reply_text(
                        report, parse_mode=ParseMode.HTML
                    )
                else:
                    await update_obj.message.reply_text(
                        "⚠️ <b>Data too long</b>\n📄 Full vehicle report sent as file.",
                        parse_mode=ParseMode.HTML
                    )

                    file_name = f"vehicle_{target}.txt"
                    with open(file_name, "w", encoding="utf-8") as f:
                        f.write(
                            report
                            .replace("<b>", "")
                            .replace("</b>", "")
                            .replace("<i>", "")
                            .replace("</i>", "")
                        )

                    await update_obj.message.reply_document(
                        document=open(file_name, "rb"),
                        caption="🚗 Vehicle full report"
                    )

        # =========================
        # ALL OTHER COMMANDS (UNCHANGED)
        # =========================
        else:
            if is_error_reply(raw_reply):
                add_credits(matched_user_id, 2)
                await update_obj.message.reply_text(
                    "❌ <b>Lookup Failed</b>\n"
                    "🔍 No result or service error.\n"
                    "💰 <b>2 credits refunded.</b>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await update_obj.message.reply_text(
                    format_generic_report(raw_reply, cmd, target),
                    parse_mode=ParseMode.HTML
                )

    except Exception:
        logger.exception("Group reply processing error")
        add_credits(matched_user_id, 2)
        await update_obj.message.reply_text(
            "⚠️ <b>Processing Error</b>\n💰 Credits refunded.",
            parse_mode=ParseMode.HTML
        )

    await show_main_menu(update_obj, context, edit=False)




# ----------------------------
# COMMAND HANDLERS
# ----------------------------

async def forward_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE, cmd: str, validator=None):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text(f"UsageId: <code>/{cmd} &lt;value&gt;</code>", parse_mode=ParseMode.HTML)
        return

    target = context.args[0].strip()
    if validator and not validator(target):
        await update.message.reply_text(f"❌ Invalid input for <b>{cmd}</b>.", parse_mode=ParseMode.HTML)
        return

    if not can_make_request(user_id):
        w = max(1, int(REQUEST_COOLDOWN - (time.time() - load_user(user_id)["last_request_time"])))
        await update.message.reply_text(f"⏳ Wait {w}s.", parse_mode=ParseMode.HTML)
        return

    if not deduct_credits(user_id, 2):
        await update.message.reply_text("❌ Insufficient credits.", parse_mode=ParseMode.HTML)
        return

    try:
        sent = await context.bot.send_message(
            chat_id=LOOKUP_GROUP_ID,
            text=f"/{cmd} {target}",
            disable_notification=True
        )
        pending_requests[user_id] = {
            "group_msg_id": sent.message_id,
            "update": update,
            "cmd": cmd,
            "target": target,
        }
        await update.message.reply_text("🔍 Forwarded to processing group.", parse_mode=ParseMode.HTML)

        async def timeout_task():
            await asyncio.sleep(50)
            if user_id in pending_requests:
                pending_requests.pop(user_id, None)
                add_credits(user_id, 2)
                await update.message.reply_text(
                    "⏱️ Timed out (50s). Credits refunded.", parse_mode=ParseMode.HTML
                )
        asyncio.create_task(timeout_task())

    except Exception as e:
        add_credits(user_id, 2)
        await update.message.reply_text("❌ Failed to forward. Credits refunded.", parse_mode=ParseMode.HTML)

# Command wrappers
async def num_handler(u, c): await forward_to_group(u, c, "num", lambda x: x.isdigit() and len(x) == 10)
async def num2_handler(u, c): await forward_to_group(u, c, "num2", lambda x: x.isdigit() and len(x) == 10)
async def aadh_handler(u, c): await forward_to_group(u, c, "aadh", lambda x: x.isdigit() and len(x) == 12)
async def rashan_handler(u, c): await forward_to_group(u, c, "rashan", lambda x: len(x) >= 4 and x[:3].isalpha() and x[3:].isdigit())
async def upi_handler(u, c): await forward_to_group(u, c, "upi", lambda x: "@" in x and 5 < len(x) < 50)
async def ifsc_handler(u, c): await forward_to_group(u, c, "ifsc", lambda x: len(x) == 11 and x[:4].isalpha() and x[4:].isalnum())
async def gst_handler(u, c): await forward_to_group(u, c, "gst", lambda x: len(x) == 15)
async def vehicle_handler(u, c): await forward_to_group(u, c, "vehicle", lambda x: bool(re.match(r"^[A-Z]{2}\d{1,2}[A-Z]{1,2}\d{1,4}$", x.upper().replace(' ', ''))))
async def icmr_handler(u, c): await forward_to_group(u, c, "icmr", lambda x: x.isdigit() and len(x) == 10)
async def tguser_handler(u, c): await forward_to_group(u, c, "tguser", lambda x: 3 <= len(x) <= 32 and x.replace('_', '').isalnum() and not x[0].isdigit())
async def boom_handler(u, c): await u.message.reply_text("💣 <b>OTP Bomb</b>\n❌ Disabled for ethical reasons.", parse_mode=ParseMode.HTML)
async def balance_handler(u, c): await u.message.reply_text("📊 " + credit_footer(u.effective_user.id).strip(), parse_mode=ParseMode.HTML)
async def ref_handler(u, c):
    uid = u.effective_user.id
    link = generate_referral_link(uid)
    await u.message.reply_text(f"🔗 <code>{html.escape(link)}</code>" + credit_footer(uid), parse_mode=ParseMode.HTML)

# ----------------------------
# MAIN
# ----------------------------

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    cmds = ["num", "num2", "aadh", "rashan", "upi", "ifsc", "gst", "vehicle", "icmr", "tguser"]
    for cmd in cmds:
        app.add_handler(CommandHandler(cmd, globals()[f"{cmd}_handler"]))
    app.add_handler(CommandHandler("boom", boom_handler))
    app.add_handler(CommandHandler("balance", balance_handler))
    app.add_handler(CommandHandler("ref", ref_handler))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_user_input))
    app.add_handler(MessageHandler(filters.REPLY & filters.Chat(chat_id=LOOKUP_GROUP_ID), monitor_group_replies))

    logger.info("✅ Bot started — .")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        timeout=30,
    )

if __name__ == "__main__":

    main()
