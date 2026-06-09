#!/usr/bin/env python3
"""BonDownloader Pro - Flask 后端（跨平台：macOS + Windows）"""

import os, re, json, hashlib, secrets, datetime, sqlite3, asyncio, subprocess, threading, time, sys, platform
from pathlib import Path
from functools import wraps
from flask import Flask, request, jsonify, g, send_file

IS_MAC = platform.system() == "Darwin"
IS_WIN = platform.system() == "Windows"

# ── 跨平台路径 ──
if IS_MAC:
    DATA_DIR = Path.home() / "Library" / "Application Support" / "BonDownloaderPro"
    CACHE_DIR = Path.home() / "Library" / "Caches" / "ms-playwright"
elif IS_WIN:
    DATA_DIR = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "BonDownloaderPro"
    CACHE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "ms-playwright"
else:
    DATA_DIR = Path.home() / ".bon-downloader-pro"
    CACHE_DIR = Path.home() / ".cache" / "ms-playwright"

DOWNLOAD_DIR = str(Path.home() / "Downloads" / "DouyinVideos")
DATA_DIR.mkdir(parents=True, exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

DB_PATH = str(DATA_DIR / "data.db")

# ── Chromium 路径：优先用 App 内置的 ──
def _get_chromium_path():
    import glob
    if getattr(sys, 'frozen', False):
        bundle_root = Path(sys._MEIPASS)
        chromium_dir = bundle_root / "chromium"
        if chromium_dir.exists():
            return str(chromium_dir)
    if glob.glob(str(CACHE_DIR / "chromium_headless_shell-*" / "chrome-headless-shell"*)):
        return str(CACHE_DIR)
    return str(CACHE_DIR)

PLAYWRIGHT_CACHE = _get_chromium_path()
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = PLAYWRIGHT_CACHE


def _find_chromium_exe():
    """跨平台查找 Chromium 可执行文件"""
    import glob
    # App 内置
    if getattr(sys, 'frozen', False):
        bundle = Path(sys._MEIPASS) / "chromium"
        if bundle.exists():
            patterns = [
                bundle / "chromium_headless_shell-*" / "chrome-headless-shell-mac-arm64" / "chrome-headless-shell",
                bundle / "chromium_headless_shell-*" / "chrome-headless-shell-win64" / "chrome-headless-shell.exe",
            ]
            for p in patterns:
                found = sorted(glob.glob(str(p)), reverse=True)
                if found: return found[0]

    # 缓存目录
    patterns = [
        CACHE_DIR / "chromium_headless_shell-*" / "chrome-headless-shell-mac-arm64" / "chrome-headless-shell",
        CACHE_DIR / "chromium_headless_shell-*" / "chrome-headless-shell-win64" / "chrome-headless-shell.exe",
    ]
    for p in patterns:
        found = sorted(glob.glob(str(p)), reverse=True)
        if found: return found[0]
    return None


app = Flask(__name__)
app.config["SECRET_KEY"] = secrets.token_hex(32)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db: db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS download_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            phone TEXT NOT NULL,
            url TEXT NOT NULL,
            title TEXT DEFAULT '',
            author TEXT DEFAULT '',
            resolution TEXT DEFAULT '',
            file_size INTEGER DEFAULT 0,
            status TEXT DEFAULT 'success',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    """)
    admin = db.execute("SELECT id FROM users WHERE is_admin=1").fetchone()
    if not admin:
        pw = hashlib.sha256("admin888".encode()).hexdigest()
        db.execute("INSERT OR IGNORE INTO users (phone,password_hash,is_admin) VALUES (?,?,1)",
                   ("00000000000", pw))
    db.commit()
    db.close()


def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()


def require_auth(f):
    @wraps(f)
    def wrap(*a, **kw):
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not token: return jsonify({"error": "未登录"}), 401
        db = get_db()
        s = db.execute("SELECT user_id FROM sessions WHERE token=*** (token,)).fetchone()
        if not s: return jsonify({"error": "登录已过期"}), 401
        g.user_id = s["user_id"]
        g.user = db.execute("SELECT * FROM users WHERE id=?", (g.user_id,)).fetchone()
        return f(*a, **kw)
    return wrap


def require_admin(f):
    @wraps(f)
    def wrap(*a, **kw):
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not token: return jsonify({"error": "未登录"}), 401
        db = get_db()
        s = db.execute("SELECT user_id FROM sessions WHERE token=*** (token,)).fetchone()
        if not s: return jsonify({"error": "登录已过期"}), 401
        u = db.execute("SELECT * FROM users WHERE id=?", (s["user_id"],)).fetchone()
        if not u or not u["is_admin"]: return jsonify({"error": "无管理员权限"}), 403
        g.user_id = u["id"]
        g.user = u
        return f(*a, **kw)
    return wrap


@app.route("/api/ping")
def ping():
    return jsonify({"ok": True})


@app.route("/api/register", methods=["POST"])
def register():
    d = request.get_json(force=True)
    phone = (d.get("phone") or "").strip()
    pw = (d.get("password") or "").strip()
    if not re.match(r"^1[3-9]\d{9}$", phone):
        return jsonify({"error": "请输入正确的手机号"}), 400
    if len(pw) < 6:
        return jsonify({"error": "密码至少6位"}), 400
    db = get_db()
    if db.execute("SELECT id FROM users WHERE phone=?", (phone,)).fetchone():
        return jsonify({"error": "该手机号已注册"}), 409
    db.execute("INSERT INTO users (phone,password_hash) VALUES (?,?)", (phone, hash_pw(pw)))
    db.commit()
    return jsonify({"ok": True, "message": "注册成功"})


@app.route("/api/login", methods=["POST"])
def login():
    d = request.get_json(force=True)
    phone = (d.get("phone") or "").strip()
    pw = (d.get("password") or "").strip()
    if not phone or not pw:
        return jsonify({"error": "请输入手机号和密码"}), 400
    db = get_db()
    u = db.execute("SELECT * FROM users WHERE phone=?", (phone,)).fetchone()
    if not u or u["password_hash"] != hash_pw(pw):
        return jsonify({"error": "手机号或密码错误"}), 401
    token = secrets.token_hex(32)
    db.execute("INSERT INTO sessions (user_id,token) VALUES (?,?)", (u["id"], token))
    db.commit()
    return jsonify({"ok": True, "token": token, "user": {
        "id": u["id"], "phone": u["phone"], "is_admin": bool(u["is_admin"])
    }})


@app.route("/api/log_download", methods=["POST"])
@require_auth
def log_download():
    d = request.get_json(force=True)
    db = get_db()
    db.execute("""
        INSERT INTO download_logs (user_id,phone,url,title,author,resolution,file_size,status)
        VALUES (?,?,?,?,?,?,?,?)
    """, (g.user_id, g.user["phone"], d.get("url",""), d.get("title",""),
          d.get("author",""), d.get("resolution",""), d.get("file_size",0),
          d.get("status","success")))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/my_logs")
@require_auth
def my_logs():
    db = get_db()
    page = request.args.get("page", 1, type=int)
    per = request.args.get("per_page", 20, type=int)
    off = (page - 1) * per
    total = db.execute("SELECT COUNT(*) FROM download_logs WHERE user_id=?", (g.user_id,)).fetchone()[0]
    logs = db.execute(
        "SELECT * FROM download_logs WHERE user_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (g.user_id, per, off)).fetchall()
    return jsonify({"total": total, "page": page, "logs": [dict(r) for r in logs]})


@app.route("/api/admin/all_logs")
@require_admin
def admin_all_logs():
    db = get_db()
    page = request.args.get("page", 1, type=int)
    per = request.args.get("per_page", 50, type=int)
    phone = request.args.get("phone", "").strip()
    off = (page - 1) * per
    if phone:
        total = db.execute("SELECT COUNT(*) FROM download_logs WHERE phone LIKE ?",
                           (f"%{phone}%",)).fetchone()[0]
        logs = db.execute(
            "SELECT * FROM download_logs WHERE phone LIKE ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (f"%{phone}%", per, off)).fetchall()
    else:
        total = db.execute("SELECT COUNT(*) FROM download_logs").fetchone()[0]
        logs = db.execute(
            "SELECT * FROM download_logs ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (per, off)).fetchall()
    return jsonify({"total": total, "page": page, "logs": [dict(r) for r in logs]})


@app.route("/api/admin/users")
@require_admin
def admin_users():
    db = get_db()
    users = db.execute("SELECT id,phone,is_admin,created_at FROM users ORDER BY created_at DESC").fetchall()
    return jsonify({"users": [dict(r) for r in users]})


@app.route("/api/admin/stats")
@require_admin
def admin_stats():
    db = get_db()
    total_users = db.execute("SELECT COUNT(*) FROM users WHERE is_admin=0").fetchone()[0]
    total_dl = db.execute("SELECT COUNT(*) FROM download_logs").fetchone()[0]
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    today_dl = db.execute("SELECT COUNT(*) FROM download_logs WHERE date(created_at)=?", (today,)).fetchone()[0]
    return jsonify({"total_users": total_users, "total_downloads": total_dl, "today_downloads": today_dl})


# ============================================================
# 下载 API
# ============================================================
download_tasks = {}


@app.route("/api/download", methods=["POST"])
@require_auth
def api_download():
    d = request.get_json(force=True)
    url = (d.get("url") or "").strip()
    task_id = str(int(time.time() * 1000))
    download_tasks[task_id] = {"status": "starting", "progress": 0}
    threading.Thread(target=_do_download, args=(task_id, url), daemon=True).start()
    return jsonify({"task_id": task_id})


def _do_download(task_id, url):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        res = loop.run_until_complete(_async_download(task_id, url))
        download_tasks[task_id].update(res)
    except Exception as e:
        download_tasks[task_id] = {"status": "error", "error": str(e)}
    finally:
        loop.close()


async def _async_download(task_id, url):
    download_tasks[task_id] = {"status": "parsing", "progress": 0}
    m = re.search(r"https?://(?:v\.douyin\.com|www\.douyin\.com)\S+", url)
    if m: url = m.group(0).rstrip("/")
    else: return {"status": "error", "error": "未识别到抖音链接"}

    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        launch_kwargs = {"headless": True}
        exe = _find_chromium_exe()
        if exe: launch_kwargs["executable_path"] = exe
        browser = await p.chromium.launch(**launch_kwargs)

        if "v.douyin.com" in url:
            ctx = await browser.new_context(user_agent="Mozilla/5.0", viewport={"width": 1440, "height": 900})
            page = await ctx.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)
            final = page.url; await ctx.close()
            vm = re.search(r"/video/(\d+)", final)
            url = f"https://www.douyin.com/video/{vm.group(1)}" if vm else final

        ctx = await browser.new_context(user_agent="Mozilla/5.0", viewport={"width": 1440, "height": 900})
        page = await ctx.new_page()
        data = {}

        async def on_resp(resp):
            if "aweme/v1/web/aweme/detail" in resp.url:
                try:
                    body = await resp.json()
                    item = body.get("aweme_detail", {})
                    if not item: return
                    a = item.get("author", {})
                    v = item.get("video", {})
                    brs = v.get("bit_rate", [])
                    if brs:
                        best = max(brs, key=lambda x: x.get("bit_rate", 0))
                        urls = best.get("play_addr", {}).get("url_list", [])
                        if urls: data["url"] = urls[0]; data["bitrate"] = best.get("bit_rate", 0)
                    if not data.get("url"):
                        for u in v.get("download_addr", {}).get("url_list", []):
                            if "aweme/v1/play/" in u:
                                nw = re.sub(r"watermark=\d+", "watermark=0", u)
                                nw = re.sub(r"improve_bitrate=\d+", "improve_bitrate=1", nw)
                                data["url"] = nw; break
                    data["desc"] = item.get("desc", "")
                    data["author"] = a.get("nickname", "")
                    data["aweme_id"] = item.get("aweme_id", "")
                    data["w"] = v.get("width", 0); data["h"] = v.get("height", 0)
                except: pass

        page.on("response", on_resp)
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)
        if not data: await asyncio.sleep(5)
        await ctx.close(); await browser.close()

    if not data.get("url"): return {"status": "error", "error": "未能获取视频地址"}

    import aiohttp
    async with aiohttp.ClientSession() as s:
        hdrs = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.douyin.com/"}
        async with s.get(data["url"], headers=hdrs) as r:
            total = int(r.headers.get("content-length", 0))
            dl = 0
            author = re.sub(r'[\\/:*?"<>|]', '_', data.get("author", "未知作者"))[:40]
            desc = re.sub(r'[\\/:*?"<>|]', '_', data.get("desc", data.get("aweme_id", "video")))[:60]
            fname = f"{author} - {desc}.mp4"
            out = os.path.join(DOWNLOAD_DIR, fname)
            if os.path.exists(out):
                aid = data.get("aweme_id", "")
                out = os.path.join(DOWNLOAD_DIR, f"{author} - {desc}_{aid}.mp4")
            with open(out, "wb") as f:
                async for chunk in r.content.iter_chunked(65536):
                    f.write(chunk); dl += len(chunk)
                    if total > 0: download_tasks[task_id].update({"status": "downloading", "progress": int(dl/total*100)})

    return {"status": "done", "progress": 100, "output_path": out, "filename": os.path.basename(out), "file_size": os.path.getsize(out)}


@app.route("/api/status/<task_id>")
def api_status(task_id):
    return jsonify(download_tasks.get(task_id, {"status": "not_found"}))


@app.route("/api/file/<task_id>")
def api_file(task_id):
    t = download_tasks.get(task_id)
    if not t or t.get("status") != "done": return jsonify({"error": "not ready"}), 404
    return send_file(t["output_path"], mimetype="video/mp4")


def run_server(port=5199):
    init_db()
    print(f"🚀 BonDownloader Pro 后端: http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    run_server()
