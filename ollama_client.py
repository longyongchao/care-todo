import json
import urllib.error
import urllib.request

MODEL = "qwen3.8:latest"
BASE_URL = "http://127.0.0.1:11434"

class ModelError(Exception):
    pass

class Ollama:
    def __init__(self, timeout=240):
        self.timeout = timeout
        # 不使用系统代理；固定回环地址，不接受云端地址。
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, path, payload=None, timeout=None):
        request = urllib.request.Request(BASE_URL + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=timeout or self.timeout) as response:
                result = json.load(response)
            if result.get("error"):
                raise ModelError(str(result["error"]))
            return result
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:500]
            raise ModelError(f"Ollama 返回 {exc.code}：{detail}。请用 ollama list 检查模型，修复后重试。") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ModelError("无法连接 Ollama 或生成超时。请打开 Ollama 应用或运行 ollama serve，确认本机 11434 端口可用，然后重试。" + f" ({exc})") from exc
        except (ValueError, TypeError) as exc:
            raise ModelError("Ollama 返回了无效数据，请重试。") from exc

    def health(self):
        try:
            models = self.request("/api/tags", timeout=5).get("models", [])
            model = next((m for m in models if m.get("name") == MODEL or m.get("model") == MODEL), None)
            if not model:
                raise ModelError(f"Ollama 已启动，但没有 {MODEL}。请运行 ollama list，确认已下载模型的名称完全一致；本程序不会自动改用其他模型。")
            # 禁止 Ollama 的云端代理模型，即使其标签被改为指定名称。
            if model.get("remote_host") or model.get("remote_model"):
                raise ModelError("该标签指向远程模型，请改为本地下载模型。")
            show = self.request("/api/show", {"model": MODEL}, timeout=10)
            if show.get("remote_host") or show.get("remote_model"):
                raise ModelError("该模型指向云端，本程序只允许本地模型。")
            return {"ok": True, "message": f"本机模型已就绪 · {MODEL}", "model": MODEL}
        except ModelError as exc:
            return {"ok": False, "message": str(exc), "model": MODEL}

    def chat(self, messages, schema=None):
        health = self.health()
        if not health["ok"]:
            raise ModelError(health["message"])
        payload = {"model": MODEL, "messages": messages, "stream": False,
                   "think": False, "options": {"temperature": 0 if schema else 0.65, "num_ctx": 32768, "num_predict": 4096}}
        if schema:
            payload["format"] = schema
        result = self.request("/api/chat", payload)
        content = result.get("message", {}).get("content", "").strip()
        if not content or result.get("done_reason") == "length":
            raise ModelError("模型返回空内容或输出被截断，未标记处理成功，请重试。")
        if schema:
            try:
                return json.loads(content)
            except ValueError as exc:
                raise ModelError("待办助手返回的 JSON 无效，本次结果未保存，请重试。") from exc
        return content
