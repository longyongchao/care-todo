#!/usr/bin/env python3
"""Python 3.10+，零第三方依赖。运行：python3 app.py"""
import argparse
import json
import secrets
import os
import threading
import webbrowser
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from core import CareApp

ROOT = Path(__file__).resolve().parent


def make_handler(app):
    csrf = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # 不把消息内容写入日志。
            if args and isinstance(args[0], str) and "/api/state" in args[0]:
                return
            super().log_message(fmt, *args)

        def send(self, status, body, content_type="application/json; charset=utf-8"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def local_request(self):
            expected = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.headers.get("Host") not in expected:
                self.send(403, {"error": "只允许本机访问"})
                return False
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://" + host for host in expected}:
                self.send(403, {"error": "拒绝跨站请求"})
                return False
            return True

        def do_GET(self):
            if not self.local_request():
                return
            path = urlsplit(self.path).path
            if path == "/api/state":
                self.send(200, {**app.state(), "csrf": csrf})
            elif path == "/api/health":
                self.send(200, app.model.health())
            else:
                files = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/style.css": ("style.css", "text/css; charset=utf-8")}
                if path not in files:
                    self.send(404, {"error": "页面不存在"})
                    return
                name, mime = files[path]
                self.send(200, (ROOT / "static" / name).read_bytes(), mime)

        def do_POST(self):
            if not self.local_request():
                return
            if not secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), csrf):
                self.send(403, {"error": "页面会话已失效，请刷新后重试"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 32000:
                    raise ValueError("请求内容过大或为空")
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError("请求格式错误")
                path = urlsplit(self.path).path
                if path == "/api/send":
                    if type(data.get("patient_id")) is not int or not isinstance(data.get("content", ""), str):
                        raise ValueError("患者或消息格式错误")
                    result = app.submit(data["patient_id"], data.get("content", ""), data.get("proactive") is True, data.get("request_id"))
                elif path == "/api/retry":
                    app.retry(data.get("job_id"))
                    result = {"ok": True}
                elif path == "/api/task":
                    if type(data.get("id")) is not int:
                        raise ValueError("事项编号无效")
                    app.edit_task(data["id"], data.get("action"), data)
                    result = {"ok": True}
                elif path == "/api/reset":
                    app.reset(data.get("confirmation"))
                    result = {"ok": True}
                else:
                    self.send(404, {"error": "接口不存在"})
                    return
                self.send(200, result)
            except (ValueError, TypeError, KeyError) as exc:
                self.send(400, {"error": str(exc)})
            except Exception as exc:
                print(f"请求失败：{type(exc).__name__}: {exc}", file=sys.stderr)
                self.send(500, {"error": "本地保存失败，请检查终端和磁盘空间；不要重复发送，先刷新核对。"})
    return Handler


def lock_data(directory):
    """同一数据目录只允许一个程序进程；退出时操作系统自动释放锁。"""
    directory.mkdir(parents=True, exist_ok=True)
    handle = (directory / "app.lock").open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            if handle.seek(0, 2) == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError("该数据目录已有程序在运行。请使用已打开的程序，或先关闭它。")
    return handle


def main():
    parser = argparse.ArgumentParser(description="共同照护待办助手 · 本机演示")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--open", action="store_true", help="启动后打开浏览器")
    args = parser.parse_args()
    try:
        data_lock = lock_data(args.data_dir)
    except RuntimeError as exc:
        parser.exit(1, str(exc) + "\n")
    app = CareApp(args.data_dir / "care.sqlite3")
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(app))
    except OSError as exc:
        parser.exit(1, f"无法启动：{exc}\n若端口被占用，请运行 python3 app.py --port 8766\n")
    app.start_worker()
    print(f"\n共同照护待办助手：http://127.0.0.1:{args.port}\n数据保存在：{args.data_dir.resolve()}\n仅虚构资料演示。按 Ctrl+C 停止。\n", flush=True)
    if args.open:
        threading.Timer(0.5, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}")).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在退出；处理中步骤将在下次启动时提示重试。")
    finally:
        app.stop.set()
        app.wake.set()
        server.server_close()
        data_lock.close()


if __name__ == "__main__":
    main()
