# 电脑跑不动本地模型时：使用官方云端 API

这份教程接续 [README](../README.md)，面向没有多少编程基础的同学。你可以把这里的修改要求交给 Vibe Coding 工具，也可以按步骤复制代码。

**先说明范围：当前项目默认仍使用 Ollama。本教程说明怎样增加云端选项；只设置地址和密钥、没有完成代码修改时，项目不会自动切换。**

只有 CPU 不等于不能运行 Ollama。例如 [Ollama 官方 macOS 说明](https://docs.ollama.com/macos)包含仅用 CPU 的运行方式。但本项目使用的模型较大，电脑内存不足、回答太慢，或操作系统不兼容时，可以把模型计算交给云端，网页和 Python 程序仍在自己的电脑上运行。

不需要安装 Ollama 或下载本地模型。先完成 README 的 **第 2 节“安装 Python”和第 4 节“下载项目、创建环境”**，然后按本教程继续。

## 1. 先选一个平台，准备三个信息

只选一家即可，不需要同时注册三家。下面使用各平台的 **OpenAI 兼容 Chat Completions 接口**；这只是共同的通信格式，不要求你购买 OpenAI 服务。

| 你需要准备的内容 | 本教程中的变量 | 含义 |
| --- | --- | --- |
| 服务基础地址，常叫 host 或 Base URL | `LLM_BASE_URL` | 请求要发到哪里，包含 `https://` 和必要路径，不只是一个域名 |
| 模型名称，常叫 model name | `LLM_MODEL` | 云端具体使用哪个模型，与 Ollama 的 `qwen3.8:latest` 是两套命名 |
| 访问密钥，常叫 API Key 或 token key | `LLM_API_KEY` | 证明你有权使用服务。不是网页登录密码，也不是计费用的 token 数量 |

另外用 `LLM_PROVIDER` 表示选择的平台，让程序知道该使用哪种参数。程序读取这四个变量后，不需要把密钥写进 Python 文件。

### 官方平台与配置对照

以下是 **2026-10-27 核对官方文档后的示例**，并非三个平台的全部模型。开通前以控制台显示的模型权限和计费规则为准。

| 平台与入口 | `LLM_PROVIDER` | `LLM_BASE_URL` | `LLM_MODEL` 示例 |
| --- | --- | --- | --- |
| [DeepSeek 开放平台](https://platform.deepseek.com/) | `deepseek` | `https://api.deepseek.com` | `deepseek-flash` |
| [智谱 GLM 开放平台](https://bigmodel.cn/) | `glm` | `https://open.bigmodel.cn/api/paas/v4` | `glm-5.2` |
| [阿里云百炼 Qwen](https://bailian.console.aliyun.com/) | `qwen` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |

配置依据：[DeepSeek 首次调用](https://api-docs.deepseek.com/zh-cn/)、[智谱 OpenAI 兼容接口](https://docs.bigmodel.cn/cn/guide/develop/openai/introduction)、[百炼 OpenAI 兼容接口](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)。

Qwen 表中使用北京地域仍受支持的地址。百炼也提供业务空间专属地址，例如 `https://你的业务空间ID.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`，可以将控制台给出的地址填入同一变量。**API Key、地址、业务空间与模型权限必须匹配，尤其不能跨地域混用。** 见[获取百炼 API Key](https://help.aliyun.com/zh/model-studio/get-api-key)。

### 注册与开通

1. 登录所选平台，按页面要求完成账号验证并开通模型 API 服务。
2. 进入“API Keys / API 密钥”页面，创建并保存密钥。Qwen 先选定地域和业务空间。
3. 确认账户有试用额度或可用余额，并能调用表中的模型。网页聊天会员和 API 用量通常是不同产品，不能假定买了会员就能调用 API。
4. GLM 选择**模型标准 API**对应的 Key 和通用地址，不要混用 Coding Plan 的密钥或专用端点。其区别见[智谱 API 指南](https://docs.bigmodel.cn/cn/api/introduction)。

云端请求可能计费，一轮照护师聊天通常有 3 次模型调用。两次观察还会携带当前患者的历史对话和已有待办，聊天越长，发送的内容通常越多。

**云端模式会将这些对话、待办和模拟患者设定发到所选平台。** 教学只使用虚构资料。密钥只放在运行 Python 的电脑上，不放进网页 JavaScript、GitHub、截图或录屏，也不用发给 AI 编程工具。

## 2. 为什么不能只改原来的 host？

现有 `ollama_client.py` 使用 Ollama 专用协议，云端平台的消息格式不同：

| 项目中的环节 | 当前 Ollama 方式 | 本教程的云端方式 |
| --- | --- | --- |
| 检查模型 | `/api/tags`、`/api/show` | 检查配置，另用两次实际请求验证连接 |
| 发出对话请求 | `/api/chat` | 基础地址后追加 `/chat/completions` |
| 身份验证 | 本机服务，不需要 Key | 请求头 `Authorization: Bearer ...` |
| 约束待办输出 | `format` 传入格式要求 | `response_format: {"type":"json_object"}`，提示词说明字段，程序继续检查 |
| 读取回答 | `message.content` | `choices[0].message.content` |
| 关闭深度思考 | `think: false` | DeepSeek / GLM 用 `thinking`，本例 Qwen 用 `enable_thinking` |

本教程选取支持 JSON 输出和关闭思考的示例模型。JSON 模式只帮助模型输出可读取的数据，**不保证责任人、证据或状态正确**，因此继续使用 `core.py` 的校验与人工确认规则。

参考：[DeepSeek JSON 输出](https://api-docs.deepseek.com/zh-cn/guides/json_mode)、[DeepSeek 思考参数](https://api-docs.deepseek.com/guides/thinking_mode/)、[GLM 结构化输出](https://docs.bigmodel.cn/cn/guide/capabilities/struct-output)、[GLM 思考参数](https://docs.bigmodel.cn/cn/guide/capabilities/thinking)、[Qwen 结构化输出](https://help.aliyun.com/zh/model-studio/qwen-structured-output)。

例如 GLM-5.3 已不接受关闭思考，某些新版 Qwen 也有不同限制。先使用表中的型号跑通，换其他型号时要再核对参数，不能只按名称新旧替换。

## 3. 应该改哪些文件？

先停止程序，并复制一份项目文件夹作为备份。

| 文件 | 修改内容 |
| --- | --- |
| 新增 `cloud_client.py` | 读取四个设置，发送云端请求，将回答交回原程序 |
| `core.py` | 改两行：导入模型选择函数，并用它创建模型 |
| `static/index.html` | 修正“只在这台电脑上”和固定模型名等提示 |
| `static/app.js` | 将就绪检查和等待提示改成同时适用于本地、云端 |
| `ollama_client.py`、`prompts.py`、`app.py` | 保留现有实现，本教程不需要修改 |

这是在原产品说明书的本地方案上增加一个可选方案。默认仍用 Ollama，只有明确选择云端才发送云端请求，失败时也不会悄悄换一家平台。

### 3.1 新增 `cloud_client.py`

在 `app.py` 所在文件夹新建名为 `cloud_client.py` 的**纯文本文件**，复制下面的完整代码。注意不要保存成 `cloud_client.py.txt`。也可以让 AI 编程工具替你创建。

它只使用 Python 自带功能，**不需要 `pip install openai`，也不需要其他新依赖**。

<details>
<summary>展开完整代码，可直接复制</summary>

```python
"""云端接入教学示例：保留本地模式，不增加第三方依赖。"""
import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from ollama_client import ModelError, Ollama

SERVICES = {
    "deepseek": ("https://api.deepseek.com", "deepseek-flash"),
    "glm": ("https://open.bigmodel.cn/api/paas/v4", "glm-5.2"),
    "qwen": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # 密钥只发往填写的地址，不跟随重定向。
        return None


class CloudModel:
    def __init__(self, provider, timeout=240):
        self.provider = provider
        default_url, default_model = SERVICES[provider]
        self.base_url = os.getenv("LLM_BASE_URL", default_url).strip().rstrip("/")
        self.model = os.getenv("LLM_MODEL", default_model).strip()
        self.api_key = os.getenv("LLM_API_KEY", "").strip()
        self.timeout = timeout
        self.opener = urllib.request.build_opener(NoRedirect())

    def health(self):
        # 只检查配置，不偷偷发出可能计费的试探请求。
        try:
            url = urlsplit(self.base_url)
        except ValueError:
            return {"ok": False, "message": "LLM_BASE_URL 地址格式有误。", "model": self.model}
        error = ""
        if not self.api_key:
            error = "未设置 LLM_API_KEY，请在启动程序的同一终端设置。"
        elif "\n" in self.api_key or "\r" in self.api_key:
            error = "API Key 中包含换行，请重新复制完整密钥。"
        elif not self.model:
            error = "未设置 LLM_MODEL。"
        elif (url.scheme != "https" or not url.hostname or url.username
              or url.password or url.query or url.fragment
              or self.base_url.endswith("/chat/completions")):
            error = "LLM_BASE_URL 应为官方 HTTPS 基础地址，不要附加 /chat/completions。"
        return {
            "ok": not error,
            "message": error or f"云端配置已读取 · {self.provider}/{self.model}，发送消息验证连接",
            "model": self.model,
        }

    def chat(self, messages, schema=None):
        check = self.health()
        if not check["ok"]:
            raise ModelError(check["message"])
        payload = {
            "model": self.model, "messages": messages, "stream": False,
            "max_tokens": 4096,
        }
        # 对应教程表中的三个模型，不代表所有型号都支持关闭思考。
        if self.provider == "qwen":
            payload["enable_thinking"] = False
        else:
            payload["thinking"] = {"type": "disabled"}
        if schema is not None:
            # core.py 已在系统提示词中提供 JSON schema。
            payload["response_format"] = {"type": "json_object"}
        request = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.api_key},
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            hints = {400: "核对模型名称、请求参数和服务地域",
                     401: "检查 API Key 与地域是否匹配",
                     402: "检查余额或可用额度", 403: "检查模型权限和地域",
                     404: "检查基础地址与模型名称", 429: "等待后再试，并检查限额"}
            hint = hints.get(exc.code, "查看平台服务状态或稍后重试")
            raise ModelError(f"云端 HTTP {exc.code}：{hint}。") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ModelError("云端连接失败或超时，请检查网络、证书和服务地址。") from None
        except (ValueError, UnicodeError):
            raise ModelError("云端没有返回有效的 JSON 响应。") from None
        try:
            choice = result["choices"][0]
            content = choice["message"]["content"]
            if choice.get("finish_reason") != "stop":
                raise ModelError("云端输出未正常结束，可能被截断或拦截，本次未保存。")
            if not isinstance(content, str) or not content.strip():
                raise ModelError("云端返回空内容，本次未保存。")
        except (KeyError, IndexError, TypeError, AttributeError):
            raise ModelError("云端响应格式不符合 Chat Completions 约定。") from None
        if schema is None:
            return content.strip()
        try:
            parsed = json.loads(content)
        except ValueError:
            raise ModelError("观察员没有返回有效 JSON，请重试失败步骤。") from None
        if not isinstance(parsed, dict) or not isinstance(parsed.get("changes"), list):
            raise ModelError("观察员返回的待办清单格式有误，本次未保存。")
        # 字段、证据归属、责任人和允许状态仍由 core.py 检查。
        return parsed


def create_model():
    provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
    if provider == "ollama":
        return Ollama()
    if provider not in SERVICES:
        raise ModelError("LLM_PROVIDER 只能是 ollama、deepseek、glm 或 qwen。")
    return CloudModel(provider)


if __name__ == "__main__":
    from prompts import CHANGE_SCHEMA
    client = create_model()
    if not isinstance(client, CloudModel):
        raise ModelError("请先按教程设置云端 LLM_PROVIDER。")
    print(client.chat([{"role": "user", "content": "请只回复：连接成功。"}]))
    result = client.chat([
        {"role": "system", "content": "只返回 JSON 对象 {\"changes\":[]}，不创建待办。"},
        {"role": "user", "content": "好的，谢谢。"},
    ], CHANGE_SCHEMA)
    if result != {"changes": []}:
        raise ModelError("JSON 检查未通过，请核对返回内容与模型设置。")
    print("PASS: 云端文本回复与 JSON 输出检查通过。")
```

</details>

`health()` 只检查有没有填配置，不验证密钥、余额或远端可用性，所以页面写的是“云端配置已读取”，不会假装已经联网成功。第 5 节才会发出真实请求。

### 3.2 修改 `core.py` 的两行

找到文件开头：

```python
from ollama_client import ModelError, Ollama
```

替换为：

```python
from cloud_client import ModelError, create_model
```

再在 `CareApp.__init__` 中找到：

```python
self.model = model or Ollama()
```

替换为：

```python
self.model = model or create_model()
```

第二处要保留原来的行首空格。修改后，同一个待办流程会根据 `LLM_PROVIDER` 选择本地或云端模型；已有的测试模型注入方式也保留。

### 3.3 修正网页提示

在 `static/index.html` 中：

- 将 `● 本机运行 · 虚构资料` 改为 `● 教学演示 · 虚构资料`。
- 将 `正在检查 Ollama 和本机模型…` 改为 `正在检查模型服务…`。
- 找到以 `<div class="privacy">` 开始、以 `</div>` 结束的整段侧栏说明，将这一段替换成：

```html
<div class="privacy">
  <strong>运行方式与资料范围</strong>
  <p>对话与待办保存在本地。本地模式由 Ollama 处理，云端模式会将对话和待办发送到所选平台。仅使用虚构资料，不提供诊断或用药建议。</p>
  <code>当前模型见页面顶部</code>
</div>
```

在 `static/app.js` 中，将 `正在检查 Ollama 和本机模型…` 改为 `正在检查模型服务…`，将 `等待本机模型` 改为 `等待模型服务`。

网页顶部之后会显示模型客户端返回的状态，例如 `deepseek/deepseek-flash`，不再把云端说成本地模型。

## 4. 填写地址、模型名和密钥

打开终端并进入项目目录。**以下三组选一家执行，不要全部执行。** 它们设置的是当前终端里的“环境变量”，相当于在启动程序前填一张配置表。

### 4.1 平台设置

**DeepSeek**

macOS：

```bash
export LLM_PROVIDER="deepseek"
export LLM_BASE_URL="https://api.deepseek.com"
export LLM_MODEL="deepseek-flash"
```

Windows PowerShell：

```powershell
$env:LLM_PROVIDER = "deepseek"
$env:LLM_BASE_URL = "https://api.deepseek.com"
$env:LLM_MODEL = "deepseek-flash"
```

**智谱 GLM**

macOS：

```bash
export LLM_PROVIDER="glm"
export LLM_BASE_URL="https://open.bigmodel.cn/api/paas/v4"
export LLM_MODEL="glm-5.2"
```

Windows PowerShell：

```powershell
$env:LLM_PROVIDER = "glm"
$env:LLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
$env:LLM_MODEL = "glm-5.2"
```

**阿里云百炼 Qwen，北京地域示例**

macOS：

```bash
export LLM_PROVIDER="qwen"
export LLM_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export LLM_MODEL="qwen-plus"
```

Windows PowerShell：

```powershell
$env:LLM_PROVIDER = "qwen"
$env:LLM_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
$env:LLM_MODEL = "qwen-plus"
```

如果使用百炼其他地域或业务空间地址，替换 `LLM_BASE_URL`，同时使用对应地域和业务空间的 Key。基础地址后**不要自行补上 `/chat/completions`**，代码会添加。

### 4.2 输入你所选平台的 API Key

macOS 默认的 zsh 终端中，先执行第一行，按提示粘贴 Key 并回车，再执行第二行。输入时不显示密钥：

```zsh
read -s "LLM_API_KEY?请粘贴 API Key，按回车确认："
export LLM_API_KEY
```

Windows PowerShell 复制以下一行，再按提示输入 Key：

```powershell
$env:LLM_API_KEY = [System.Net.NetworkCredential]::new('', (Read-Host '请输入 API Key' -AsSecureString)).Password
```

Key 只需粘贴平台发给你的那一串字符，不要自己添加 `Bearer`。代码会为请求头添加它。

后续检查和启动命令都要在**同一个终端窗口**执行。关闭窗口后需要重新设置这四项；修改设置后也需要停止并重启 `app.py`。本示例不会自动读取 `.env` 文件。

## 5. 先验证 API，再打开网页

### 5.1 单独验证文本回复和 JSON 输出

在刚设置好环境变量的终端执行：

macOS：

```bash
./.venv/bin/python cloud_client.py
```

Windows：

```powershell
.\.venv\Scripts\python.exe cloud_client.py
```

这条命令会发出 **2 次真实云端请求，可能计费**，输入都是代码中的虚构测试文字。成功时先看到模型回复，最后显示：

```text
PASS: 云端文本回复与 JSON 输出检查通过。
```

这只验证基本通信与 JSON 输出，还没有验证完整的待办判断。报错时先看第 7 节。

### 5.2 启动云端演示

仍在同一个终端中运行。这里使用单独的 `cloud-demo` 文件夹保存数据，避免把以前的本地对话带入云端演示。

macOS：

```bash
./.venv/bin/python app.py --data-dir ./cloud-demo --open
```

Windows：

```powershell
.\.venv\Scripts\python.exe app.py --data-dir ./cloud-demo --open
```

浏览器仍打开 **http://127.0.0.1:8765**，不用修改网页地址，也不需要运行 Ollama。若旧程序还在运行，先在旧终端按 `Ctrl + C` 停止它。`cloud-demo` 是你的演示数据文件夹，分享或上传项目时不要包含它。

选择林晓雨，输入：

```text
请把上周的记录发给我，我收到后核对是否齐全，再回复您。
```

等本轮处理结束，检查患者回复和双方待办。然后继续做 [README 第 7 节的案例](../README.md#step-7)，重点确认不会把承诺当成完成，最终完成仍由你点击按钮决定。

### 5.3 再运行原有的固定对话检查

改过 `core.py` 后，原来的脚本也会读取云端设置：

macOS：

```bash
./.venv/bin/python -u tests/live_acceptance.py
```

Windows：

```powershell
.\.venv\Scripts\python.exe -u tests/live_acceptance.py
```

虽然文件中的说明最初写的是 Ollama，此时它会使用你选择的云端平台。它会发送多次 API 请求并可能计费，使用临时数据库，不改动网页数据。先等网页处理结束再运行，观察三类 `PASS`，不要将失败当作成功。

本教程的示例代码做了离线请求格式、异常处理和原有待办规则检查。**没有使用真实平台 API Key 完成三家服务的在线验收。** 原 `TEST_REPORT.md` 也只代表原先的本地模型验收，云端效果需要按上述步骤另行验证。

## 6. 如何切回 Ollama？

先在运行网页的终端按 `Ctrl + C`。然后设置：

macOS：

```bash
export LLM_PROVIDER="ollama"
unset LLM_API_KEY
./.venv/bin/python app.py --open
```

Windows：

```powershell
$env:LLM_PROVIDER = "ollama"
Remove-Item Env:LLM_API_KEY -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe app.py --open
```

这时需要重新满足 README 的本地条件：Ollama 已启动，模型 `qwen3.8:latest` 已下载。本地客户端会忽略云端的地址和模型变量。普通启动命令使用原来的 `data` 文件夹，`cloud-demo` 仍保留在磁盘上。

## 7. 云端常见问题

| 现象 | 优先检查什么 |
| --- | --- |
| 设置完仍显示 Ollama | 是否修改了 `core.py` 两行？是否在设置变量的同一终端重启？`LLM_PROVIDER` 是否拼写正确？ |
| 提示没有 `cloud_client` 模块 | 是否创建了 `cloud_client.py`，且与 `core.py` 在同一文件夹？文件是否误存为 `.py.txt`？ |
| `IndentationError` | 修改 `core.py` 时保留原来的行首空格，完整代码也不要混入代码框标记 |
| “云端配置已读取”，但发消息失败 | 配置检查没有调用 API，不代表密钥或余额有效。先运行第 5.1 节的检查 |
| HTTP 401 / 403 | Key 是否属于当前平台、地域和业务空间？是否已开通模型权限？是否误用了编程套餐的 Key？ |
| HTTP 402 或额度不足 | 到平台控制台查看 API 余额、额度和账单。不同平台的错误码可能不同 |
| HTTP 404 | Base URL 是否误填成网页地址或完整 `/chat/completions` 地址？模型名是否属于这个平台？ |
| HTTP 400 | 型号是否与教程一致？是否支持关闭思考和 JSON 模式？Qwen 是否正确使用 `enable_thinking`？不要照搬 Ollama 的 `format`、`options`、`num_ctx` 等参数 |
| HTTP 429 | 限流或额度限制，等待后重试，查看控制台的请求频率与额度 |
| 连接失败、证书错误或超时 | 检查网络、系统时间、代理和官方服务状态。macOS 官方 Python 安装目录通常提供 `Install Certificates.command`，可按安装说明修复证书，不要关闭 HTTPS 证书校验 |
| 观察员返回空内容、无效 JSON 或截断 | 程序不会把它当成成功。先检查型号和思考设置，再点击“重试失败步骤”。反复截断时需评估输出上限，不能直接删掉校验 |
| JSON 可读取，但责任人或状态错误 | 格式正确不等于意思正确。通过“查看依据”和测试案例检查，保留人工修改、取消与完成确认 |

按本教程切换平台时，**地址、模型、Key 要一起更换**。排查时可以提供错误码、模型名和基础地址，但不要提供真实 API Key。账号权限和具体服务错误仍以官方控制台为准。

## 8. 交给 Vibe Coding 工具的说明

不想手动修改文件，可以把以下要求和本教程一起交给工具。实际密钥由你在运行时输入：

```text
请按 docs/CLOUD_API.md 给 care-todo 增加可选云端模型模式。
保留 Ollama 作为默认方式，使用 LLM_PROVIDER 选择 ollama / deepseek / glm / qwen。
新增 cloud_client.py，按教程修改 core.py 的两处模型创建代码和网页提示。
host、模型名称和密钥分别从 LLM_BASE_URL、LLM_MODEL、LLM_API_KEY 读取。
普通患者回复和待办 JSON 输出都要支持；本教程中的三个示例型号关闭思考。
保留原有字段与证据校验、人工确认完成、数据隔离和失败重试。
不要把 API Key 写入代码、日志或网页；缺少配置时给出明确错误。
不要把“配置已读取”说成“远端验证成功”，也不要自动改用其他平台。
运行现有程序测试与离线模拟检查，说明尚未验证的在线部分。
```

这份补充教程新增的是模型连接方式，待办助手的使用目标和人工确认边界保持一致。
