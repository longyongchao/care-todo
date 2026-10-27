import json
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from ollama_client import ModelError, Ollama
from prompts import CHANGE_SCHEMA, EXTRACT_SYSTEM, PATIENT_SYSTEM, PATIENTS


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def normalize(text):
    return re.sub(r"[\W_]+", "", text).lower()


class CareApp:
    def __init__(self, db_path, model=None):
        self.db_path = str(db_path)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.model = model or Ollama()
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.stop = threading.Event()
        with self.db() as con:
            con.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER NOT NULL,
                    role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER NOT NULL,
                    owner TEXT NOT NULL, title TEXT NOT NULL, due TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending', signal TEXT NOT NULL DEFAULT 'pending',
                    reason TEXT NOT NULL DEFAULT '', remaining TEXT NOT NULL DEFAULT '',
                    evidence TEXT NOT NULL DEFAULT '[]', dismissed TEXT NOT NULL DEFAULT '[]',
                    suggestion TEXT NOT NULL DEFAULT '[]', manual_title INTEGER NOT NULL DEFAULT 0,
                    manual_due INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, patient_id INTEGER NOT NULL, kind TEXT NOT NULL,
                    stage TEXT NOT NULL, message_id INTEGER, status TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS analyses (message_id INTEGER PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL,
                    action TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
            ''')
            con.execute("UPDATE jobs SET status='failed', error='程序在处理中退出；已保存的步骤仍在，请点击重试。' WHERE status='running'")

    @contextmanager
    def db(self):
        con = sqlite3.connect(self.db_path, timeout=15)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()

    @staticmethod
    def patient(patient_id):
        return next((p for p in PATIENTS if p["id"] == patient_id), None)

    @staticmethod
    def task_dict(row):
        task = dict(row)
        for key in ("evidence", "dismissed", "suggestion"):
            task[key] = json.loads(task[key])
        return task

    def state(self):
        with self.db() as con:
            return {"patients": [{k: v for k, v in p.items() if k != "persona"} for p in PATIENTS],
                    "messages": [dict(r) for r in con.execute("SELECT * FROM messages ORDER BY id")],
                    "tasks": [self.task_dict(r) for r in con.execute("SELECT * FROM tasks ORDER BY id DESC")],
                    "jobs": [dict(r) for r in con.execute("SELECT * FROM jobs WHERE status != 'done' ORDER BY created_at")],
                    "audit": [dict(r) for r in con.execute("SELECT * FROM audit ORDER BY id")]}

    def submit(self, patient_id, content="", proactive=False, request_id=None):
        if not self.patient(patient_id):
            raise ValueError("患者不存在")
        content = content.strip()
        if not proactive and not 1 <= len(content) <= 4000:
            raise ValueError("消息应为 1–4000 字")
        job_id = request_id or str(uuid.uuid4())
        if not isinstance(job_id, str) or not 8 <= len(job_id) <= 100:
            raise ValueError("请求编号无效")
        with self.lock, self.db() as con:
            previous = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if previous:
                return dict(previous)
            if con.execute("SELECT 1 FROM jobs WHERE patient_id=? AND status!='done'", (patient_id,)).fetchone():
                raise ValueError("该患者仍有处理中的消息或失败步骤，请等待或重试。")
            message_id = None
            if not proactive:
                message_id = con.execute("INSERT INTO messages(patient_id,role,content,created_at) VALUES(?,?,?,?)", (patient_id, "caregiver", content, now())).lastrowid
            con.execute("INSERT INTO jobs(id,patient_id,kind,stage,message_id,status,created_at) VALUES(?,?,?,?,?,'queued',?)", (job_id, patient_id, "proactive" if proactive else "chat", "reply" if proactive else "analyze_user", message_id, now()))
        self.wake.set()
        return {"id": job_id}

    def retry(self, job_id):
        with self.lock, self.db() as con:
            row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row["status"] != "failed":
                raise ValueError("找不到可重试步骤")
            con.execute("UPDATE jobs SET status='queued',error='' WHERE id=?", (job_id,))
        self.wake.set()

    def analyze(self, patient_id, message_id):
        with self.db() as con:
            if con.execute("SELECT 1 FROM analyses WHERE message_id=?", (message_id,)).fetchone():
                return
            messages = [dict(r) for r in con.execute("SELECT * FROM messages WHERE patient_id=? AND id<=? ORDER BY id", (patient_id, message_id))]
            tasks = [self.task_dict(r) for r in con.execute("SELECT * FROM tasks WHERE patient_id=?", (patient_id,))]
        if not messages or messages[-1]["id"] != message_id:
            raise ValueError("消息不存在或属于其他患者")
        # 明确限制上下文；超过限制时报错，不能静默遗忘后继续处理。
        context = json.dumps({"latest_message_id": message_id, "messages": messages, "existing_tasks": tasks}, ensure_ascii=False)
        if len(context) > 42000:
            raise ModelError("这位患者的演示对话已超过安全上下文长度。请先备份 data 文件夹，再重新开始演示。已有内容仍保留。")
        result = self.model.chat([
            {"role": "system", "content": EXTRACT_SYSTEM + "\nJSON schema: " + json.dumps(CHANGE_SCHEMA, ensure_ascii=False)},
            {"role": "user", "content": context}], CHANGE_SCHEMA)
        self.apply_analysis(patient_id, message_id, result)

    def apply_analysis(self, patient_id, message_id, result):
        """全量校验后在同一事务应用；模型永远没有写入 completed 的能力。"""
        with self.lock, self.db() as con:
            if con.execute("SELECT 1 FROM analyses WHERE message_id=?", (message_id,)).fetchone():
                return
            valid_ids = {r[0] for r in con.execute("SELECT id FROM messages WHERE patient_id=? AND id<=?", (patient_id, message_id))}
            if message_id not in valid_ids:
                raise ValueError("消息不属于当前患者")
            if not isinstance(result, dict) or set(result) != {"changes"} or not isinstance(result["changes"], list) or len(result["changes"]) > 30:
                raise ModelError("待办结果结构无效，本次结果未保存，请重试。")
            for change in result["changes"]:
                self.validate_change(change, valid_ids, message_id)
                old = None
                if change["id"] is not None:
                    old = con.execute("SELECT * FROM tasks WHERE id=? AND patient_id=?", (change["id"], patient_id)).fetchone()
                    if not old or old["owner"] != change["owner"]:
                        raise ModelError("模型引用了不存在或责任人不符的事项，本次未保存，请重试。")
                else:
                    for row in con.execute("SELECT * FROM tasks WHERE patient_id=? AND owner=?", (patient_id, change["owner"])):
                        if normalize(row["title"]) == normalize(change["title"]):
                            old = row
                            break
                if old is None:
                    task_id = con.execute("INSERT INTO tasks(patient_id,owner,title,due,updated_at) VALUES(?,?,?,?,?)", (patient_id, change["owner"], change["title"].strip(), change["due"], now())).lastrowid
                    old = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                task = self.task_dict(old)
                incoming = sorted(set(change["evidence"]))
                signal = change["signal"]
                # 取消事项不自动恢复；已完成只可出现核实提醒，完成状态由人控制。
                if task["status"] == "cancelled" or (task["status"] == "completed" and signal != "contradiction"):
                    continue
                fresh = set(incoming) - set(task["dismissed"])
                if signal == "possible" and not fresh:
                    continue
                status = task["status"]
                if status != "completed":
                    if signal == "possible":
                        status = "possible"
                    elif signal in {"contradiction", "partial", "uncertain"}:
                        status = "pending"
                    # 普通提醒不抹去已提出但未确认的完成建议。
                if signal == "pending" and task["status"] == "possible":
                    signal = task["signal"]
                    reason, remaining, suggestion = task["reason"], task["remaining"], task["suggestion"]
                else:
                    reason, remaining = change["reason"], change["remaining"]
                    suggestion = incoming if signal in {"possible", "contradiction", "uncertain", "partial"} else []
                title = task["title"] if task["manual_title"] else change["title"].strip()
                due = task["due"] if task["manual_due"] else change["due"]
                con.execute("UPDATE tasks SET title=?,due=?,status=?,signal=?,reason=?,remaining=?,evidence=?,suggestion=?,updated_at=? WHERE id=?", (
                    title, due, status, signal, reason, remaining, json.dumps(sorted(set(task["evidence"]) | set(incoming))), json.dumps(suggestion), now(), task["id"]))
                con.execute("INSERT INTO audit(task_id,action,detail,created_at) VALUES(?,?,?,?)", (task["id"], "assistant", json.dumps(change, ensure_ascii=False), now()))
            con.execute("INSERT INTO analyses(message_id) VALUES(?)", (message_id,))

    @staticmethod
    def validate_change(change, valid_ids, message_id):
        keys = set(CHANGE_SCHEMA["properties"]["changes"]["items"]["required"])
        if not isinstance(change, dict) or set(change) != keys:
            raise ModelError("模型返回的待办字段无效，请重试。")
        if change["id"] is not None and type(change["id"]) is not int:
            raise ModelError("事项编号无效")
        if change["owner"] not in {"caregiver", "patient"} or change["signal"] not in {"pending", "possible", "partial", "contradiction", "uncertain"}:
            raise ModelError("模型返回了不允许的责任人或状态")
        for key in ("title", "due", "reason", "remaining"):
            if not isinstance(change[key], str) or len(change[key]) > 2000:
                raise ModelError("待办文字字段无效")
        if not change["title"].strip():
            raise ModelError("待办标题不能为空")
        evidence = change["evidence"]
        if not isinstance(evidence, list) or any(type(e) is not int or e not in valid_ids for e in evidence) or message_id not in evidence:
            raise ModelError("模型给出的依据不属于当前对话或不包含新消息，未保存，请重试。")

    def edit_task(self, task_id, action, data=None):
        data = data or {}
        with self.lock, self.db() as con:
            row = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise ValueError("事项不存在")
            task = self.task_dict(row)
            if con.execute("SELECT 1 FROM jobs WHERE patient_id=? AND status IN ('queued','running')", (task["patient_id"],)).fetchone():
                raise ValueError("该患者的消息正在处理，请稍后再修改事项。")
            status, signal = task["status"], task["signal"]
            dismissed = set(task["dismissed"])
            if action == "edit":
                title = str(data.get("title", "")).strip()
                due = str(data.get("due", "")).strip()
                owner = data.get("owner")
                if not title or len(title) > 500 or len(due) > 200 or owner not in {"caregiver", "patient"}:
                    raise ValueError("请填写有效的事项、责任人和时间")
                con.execute("UPDATE tasks SET title=?,due=?,owner=?,manual_title=1,manual_due=1,updated_at=? WHERE id=?", (title, due, owner, now(), task_id))
            else:
                if action == "confirm":
                    status, signal = "completed", "pending"
                elif action in {"reject", "reopen"}:
                    status, signal = "pending", "pending"
                elif action == "cancel":
                    status, signal = "cancelled", "pending"
                else:
                    raise ValueError("未知操作")
                dismissed.update(task["suggestion"])
                con.execute("UPDATE tasks SET status=?,signal=?,reason='',suggestion='[]',dismissed=?,updated_at=? WHERE id=?", (status, signal, json.dumps(sorted(dismissed)), now(), task_id))
            con.execute("INSERT INTO audit(task_id,action,detail,created_at) VALUES(?,?,?,?)", (task_id, action, json.dumps(data, ensure_ascii=False), now()))

    def reset(self, confirmation):
        if confirmation != "重新开始":
            raise ValueError("请先确认重新开始")
        with self.lock, self.db() as con:
            if con.execute("SELECT 1 FROM jobs WHERE status IN ('queued','running')").fetchone():
                raise ValueError("请等当前模型处理结束后再重新开始")
            for table in ("messages", "tasks", "jobs", "analyses", "audit"):
                con.execute(f"DELETE FROM {table}")

    def run_job(self, job_id):
        try:
            with self.lock, self.db() as con:
                job = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
                if not job or job["status"] not in {"queued", "running"}:
                    return
                con.execute("UPDATE jobs SET status='running',error='' WHERE id=?", (job_id,))
            while True:
                with self.db() as con:
                    job = dict(con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
                if job["stage"] in {"analyze_user", "analyze_patient"}:
                    self.analyze(job["patient_id"], job["message_id"])
                    with self.db() as con:
                        if job["stage"] == "analyze_patient":
                            con.execute("UPDATE jobs SET status='done',stage='done' WHERE id=?", (job_id,))
                            return
                        con.execute("UPDATE jobs SET stage='reply' WHERE id=?", (job_id,))
                elif job["stage"] == "reply":
                    with self.db() as con:
                        history = [dict(r) for r in con.execute("SELECT * FROM messages WHERE patient_id=? ORDER BY id", (job["patient_id"],))]
                    context = [{"role": "system", "content": PATIENT_SYSTEM + self.patient(job["patient_id"])["persona"]}]
                    context.extend({"role": "user" if m["role"] == "caregiver" else "assistant", "content": m["content"]} for m in history)
                    if job["kind"] == "proactive":
                        context.append({"role": "user", "content": "[演示控制] 请以患者身份主动提出一个与资料、记录或日程有关的自然问题，不要重复已经解决的问题。"})
                    if len(json.dumps(context, ensure_ascii=False)) > 42000:
                        raise ModelError("对话超过演示上下文限制，请备份数据后重新开始。")
                    reply = self.model.chat(context)
                    with self.lock, self.db() as con:
                        mid = con.execute("INSERT INTO messages(patient_id,role,content,created_at) VALUES(?,?,?,?)", (job["patient_id"], "patient", reply, now())).lastrowid
                        con.execute("UPDATE jobs SET stage='analyze_patient',message_id=? WHERE id=?", (mid, job_id))
                else:
                    raise ValueError("任务步骤无效")
        except Exception as exc:
            with self.db() as con:
                con.execute("UPDATE jobs SET status='failed',error=? WHERE id=?", (str(exc) or type(exc).__name__, job_id))

    def start_worker(self):
        def loop():
            while not self.stop.is_set():
                with self.db() as con:
                    row = con.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
                if row:
                    self.run_job(row[0])
                else:
                    self.wake.wait(1)
                    self.wake.clear()
        thread = threading.Thread(target=loop, daemon=True, name="local-ollama-worker")
        thread.start()
        return thread
