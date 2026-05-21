import os
import json
import time
import threading
import urllib.request
import urllib.parse
import config
from kite_auth_manager import check_kite_auth
from kite_telemetry import get_kite_margin, get_kite_positions, get_kite_orders
from kite_order_manager import panic_square_off

PENDING_SIGNALS_FILE = os.path.join(config.DATA_DIR, "pending_signals.json")

def load_pending_signals():
    """
    Loads all pending trade signals from the persistent JSON file.
    """
    if not os.path.exists(PENDING_SIGNALS_FILE):
        return {}
    try:
        with open(PENDING_SIGNALS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_pending_signals(signals):
    """
    Saves the pending trade signals cache atomically.
    """
    temp_file = PENDING_SIGNALS_FILE + ".tmp"
    try:
        with open(temp_file, "w") as f:
            json.dump(signals, f, indent=4)
        os.replace(temp_file, PENDING_SIGNALS_FILE)
    except Exception as e:
        print(f"❌ Error saving pending signals: {e}")
        if os.path.exists(temp_file):
            os.remove(temp_file)

def send_telegram_message(text, reply_markup=None):
    """
    Sends an HTML message to NJ's configured Telegram Chat ID.
    Supports inline keyboard markup for approvals.
    """
    token = config.TELEGRAM_BOT_TOKEN
    chat_id = config.TELEGRAM_CHAT_ID
    if not token or not chat_id or "your_telegram" in token:
        print(f"⚠️ Telegram credentials not configured. Message: {text}")
        return None
    
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
            
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, 
            data=data, 
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as res:
            return json.loads(res.read().decode("utf-8"))
    except Exception as e:
        print(f"❌ Telegram send failed: {e}")
        return None

def edit_telegram_message(message_id, text, reply_markup=None):
    """
    Edits a previously sent Telegram message to show updated status.
    Clears inline buttons upon action completion.
    """
    token = config.TELEGRAM_BOT_TOKEN
    chat_id = config.TELEGRAM_CHAT_ID
    if not token or not chat_id or "your_telegram" in token:
        return None
        
    try:
        url = f"https://api.telegram.org/bot{token}/editMessageText"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML"
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
            
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as res:
            return json.loads(res.read().decode("utf-8"))
    except Exception as e:
        print(f"❌ Telegram edit failed: {e}")
        return None

def answer_callback_query(callback_query_id, text):
    """
    Sends callback query answers to prevent loading spinner on the Telegram UI.
    """
    token = config.TELEGRAM_BOT_TOKEN
    if not token or "your_telegram" in token:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
        payload = {
            "callback_query_id": callback_query_id,
            "text": text
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as res:
            res.read()
    except Exception:
        pass

def send_signal_approval_request(symbol, direction, qty, price, sl, target, strategy, dry_run=True):
    """
    Formats and pushes a trade signal with inline Accept/Reject buttons.
    Saves the signal configuration parameters in the pending queue.
    """
    signals = load_pending_signals()
    sig_id = f"sig_{int(time.time())}"
    signals[sig_id] = {
        "symbol": symbol,
        "direction": direction,
        "qty": qty,
        "price": price,
        "sl": sl,
        "target": target,
        "strategy": strategy,
        "dry_run": dry_run,
        "timestamp": time.time()
    }
    save_pending_signals(signals)
    
    mode_tag = "🟡 [SIMULATION]" if dry_run else "🔴 [LIVE CAPITAL]"
    text = (
        f"🚨 <b>{mode_tag} TRADE SIGNAL</b>\n\n"
        f"<b>Stock:</b> {symbol}\n"
        f"<b>Strategy:</b> {strategy}\n"
        f"<b>Direction:</b> {direction}\n"
        f"<b>Quantity:</b> {qty}\n"
        f"<b>Trigger Price:</b> ₹{price:.2f}\n"
        f"<b>Stop Loss:</b> ₹{sl:.2f}\n"
        f"<b>Target:</b> ₹{target:.2f}\n\n"
        f"Do you want to execute this trade?"
    )
    
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ Approve", "callback_data": f"approve:{sig_id}"},
                {"text": "❌ Reject", "callback_data": f"reject:{sig_id}"}
            ]
        ]
    }
    
    send_telegram_message(text, reply_markup=reply_markup)
    print(f"✉️ Telegram approval request pushed: {symbol} ({direction})")

def handle_text_command(text):
    """
    Processes incoming text instructions from NJ.
    Supports /status, /positions, /orders, and /panic.
    """
    text = text.strip()
    if text == "/start":
        return "🤖 <b>Kite Quant Terminal Remote Control Active</b>\nUse /status, /positions, /orders, or /panic."
    
    elif text == "/status":
        needs_login, _ = check_kite_auth()
        auth_status = "⚠️ Authenticate Required" if needs_login else "✅ Connected to Zerodha"
        
        margin_info = ""
        if not needs_login:
            try:
                margin = get_kite_margin()
                cash = margin.get("equity", {}).get("net", 0.0)
                margin_info = f"\n<b>Available Cash:</b> ₹{cash:,.2f}"
            except Exception:
                pass
                
        return (
            f"💻 <b>System Telemetry</b>\n"
            f"<b>Auth Status:</b> {auth_status}{margin_info}\n"
            f"<b>Platform Time:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
    elif text == "/positions":
        try:
            positions_data = get_kite_positions()
            net = positions_data.get("net", [])
            active = [p for p in net if int(p.get("quantity", 0)) != 0]
            if not active:
                return "ℹ️ No open positions."
            
            lines = ["📈 <b>Open Net Positions:</b>"]
            for p in active:
                sym = p["tradingsymbol"]
                qty = p["quantity"]
                ltp = p["last_price"]
                avg = p["average_price"]
                pnl = p["pnl"]
                dir_tag = "BUY" if qty > 0 else "SELL"
                lines.append(f"• <b>{sym}</b> ({dir_tag}): {abs(qty)} @ ₹{avg:.2f} (LTP: ₹{ltp:.2f}) P&L: <b>₹{pnl:,.2f}</b>")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ Error retrieving positions: {e}"
            
    elif text == "/orders":
        try:
            orders_data = get_kite_orders()
            open_orders = [o for o in orders_data if o.get("status") in ["OPEN", "TRIGGER PENDING"]]
            if not open_orders:
                return "ℹ️ No open pending orders."
            
            lines = ["📋 <b>Pending Bracket Orders:</b>"]
            for o in open_orders:
                sym = o["tradingsymbol"]
                qty = o["quantity"]
                price = o["price"]
                trigger = o["trigger_price"]
                otype = o["order_type"]
                tx = o["transaction_type"]
                lines.append(f"• {tx} {sym} ({otype}) Qty: {qty} Price: ₹{price} (Trigger: ₹{trigger}) Status: {o['status']}")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ Error retrieving orders: {e}"
            
    elif text == "/panic":
        res = panic_square_off()
        if res.get("status") == "success":
            return f"🚨 <b>PANIC SQUARE-OFF COMPLETE</b>\n{res['message']}"
        else:
            return f"❌ <b>PANIC SQUARE-OFF FAILED</b>\n{res.get('message')}"
            
    return None

def execute_signal_trade(sig_id):
    """
    Performs trade entry and bracket setup for approved signals.
    """
    signals = load_pending_signals()
    sig = signals.get(sig_id)
    if not sig:
        return "❌ Signal not found or already executed."
        
    symbol = sig["symbol"]
    direction = sig["direction"]
    qty = sig["qty"]
    price = sig["price"]
    sl = sig["sl"]
    target = sig["target"]
    strategy = sig["strategy"]
    dry_run = sig["dry_run"]
    
    from kite_execution_core import KiteExecutionCore
    core = KiteExecutionCore(dry_run=dry_run)
    
    try:
        if dry_run:
            core.trigger_mock_order_placement(symbol, direction, qty, price, sl, target, strategy)
        else:
            core.execute_live_order_placement(symbol, direction, qty, price, sl, target, strategy)
        
        if sig_id in signals:
            del signals[sig_id]
        save_pending_signals(signals)
        return "success"
    except Exception as e:
        return f"❌ Execution Exception: {e}"

def telegram_polling_loop():
    """
    Main long-polling runtime loop pulling queries from Telegram.
    """
    token = config.TELEGRAM_BOT_TOKEN
    if not token or "your_telegram" in token:
        print("⚠️ Telegram polling bypassed: credentials not configured in .env")
        return
        
    print("🤖 Telegram Bot long-polling daemon active.")
    last_update_id = 0
    
    while True:
        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates"
            # Encode request parameter dictionary
            params = urllib.parse.urlencode({"offset": last_update_id + 1, "timeout": 20})
            req_url = f"{url}?{params}"
            
            req = urllib.request.Request(req_url, method="GET")
            with urllib.request.urlopen(req, timeout=25) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                
            updates = res_data.get("result", [])
            for update in updates:
                last_update_id = update["update_id"]
                
                # Inline action queries
                if "callback_query" in update:
                    cb = update["callback_query"]
                    cb_id = cb["id"]
                    data = cb["data"]
                    msg = cb.get("message", {})
                    msg_id = msg.get("message_id")
                    orig_text = msg.get("text", "")
                    
                    if not msg_id:
                        continue
                        
                    sender_chat_id = str(cb.get("from", {}).get("id", ""))
                    if sender_chat_id != str(config.TELEGRAM_CHAT_ID):
                        answer_callback_query(cb_id, "Unauthorized.")
                        continue
                        
                    if data.startswith("approve:"):
                        sig_id = data.split(":")[1]
                        answer_callback_query(cb_id, "Executing Trade...")
                        
                        status = execute_signal_trade(sig_id)
                        if status == "success":
                            new_text = f"{orig_text}\n\n✅ <b>APPROVED & EXECUTED</b> at {time.strftime('%H:%M:%S')}"
                            edit_telegram_message(msg_id, new_text, reply_markup={"inline_keyboard": []})
                        else:
                            new_text = f"{orig_text}\n\n❌ <b>EXECUTION FAILED:</b> {status}"
                            edit_telegram_message(msg_id, new_text, reply_markup={"inline_keyboard": []})
                            
                    elif data.startswith("reject:"):
                        sig_id = data.split(":")[1]
                        answer_callback_query(cb_id, "Rejected.")
                        
                        signals = load_pending_signals()
                        if sig_id in signals:
                            del signals[sig_id]
                            save_pending_signals(signals)
                            
                        new_text = f"{orig_text}\n\n❌ <b>REJECTED & DISMISSED</b> at {time.strftime('%H:%M:%S')}"
                        edit_telegram_message(msg_id, new_text, reply_markup={"inline_keyboard": []})
                
                # Plain commands
                elif "message" in update:
                    msg = update["message"]
                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    text = msg.get("text")
                    
                    if not text or chat_id != str(config.TELEGRAM_CHAT_ID):
                        continue
                        
                    response_text = handle_text_command(text)
                    if response_text:
                        send_telegram_message(response_text)
                        
        except Exception as e:
            # Prevent loop crashing on network failures
            time.sleep(5)
        
        # Idle resolution sleep
        time.sleep(0.5)

def start_telegram_polling():
    """
    Forks long-polling loop to standard daemon thread.
    """
    thread = threading.Thread(target=telegram_polling_loop, daemon=True)
    thread.start()
    return thread
