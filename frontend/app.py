"""
frontend/app.py
───────────────────────────────────────────────────────────────────────────────
SQL Validator Web 前端服务（与功能代码完全解耦，可整体删除 frontend/ 目录）

额外依赖（项目已有则无需重装）：
  uv add fastapi "uvicorn[standard]"

运行方式（在项目根目录执行）：
  uv run uvicorn frontend.app:app --reload --port 8000

然后浏览器访问 http://localhost:8000
"""
from __future__ import annotations

import asyncio
import io
import json
import queue
import sys
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

# ── 将项目根目录追加到 sys.path，使 sql_validator 包可被导入 ──────────────────
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sql_validator.entrypoint import run_validation          # noqa: E402
from sql_validator.schemas.inputs import SQLFile, ValidationRequest  # noqa: E402

app = FastAPI(title="SQL Validator UI", docs_url=None, redoc_url=None)

# ── 内存任务状态（单进程，重启即清空） ─────────────────────────────────────────
_tasks: dict[str, dict] = {}
_DONE_SENTINEL = object()

# 防止多并发请求同时修改 sys.stdout
_stdout_lock = threading.Lock()


# ─────────────────────────────────────────────────────────────────────────────
# 请求模型
# ─────────────────────────────────────────────────────────────────────────────

class _SQLFileInput(BaseModel):
    filename: str
    content: str
    developer: str = ""


class _FetchRequest(BaseModel):
    coding_numbers: list[str]   # 如 ["#2590", "5775"]


class _ValidateRequest(BaseModel):
    sql_files: list[_SQLFileInput]
    change_description: str


# ─────────────────────────────────────────────────────────────────────────────
# 实时日志捕获器
# ─────────────────────────────────────────────────────────────────────────────

class _LineCapture(io.TextIOBase):
    """
    替换 sys.stdout，将打印内容按行推入 queue，同时转发到原始 stdout。
    非线程安全，由 _stdout_lock 保证同一时刻只有一个捕获器激活。
    """

    def __init__(self, log_queue: queue.Queue, original):
        self._q = log_queue
        self._orig = original
        self._buf = ""

    def write(self, text: str) -> int:
        self._orig.write(text)
        self._orig.flush()
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self._q.put(line)
        return len(text)

    def flush(self):
        self._orig.flush()

    def isatty(self) -> bool:
        return False

    def readable(self) -> bool:
        return False

    def writable(self) -> bool:
        return True


# ─────────────────────────────────────────────────────────────────────────────
# 后台验证线程
# ─────────────────────────────────────────────────────────────────────────────

def _run_task(task_id: str, payload: dict) -> None:
    task = _tasks[task_id]
    log_q: queue.Queue = task["log_queue"]

    with _stdout_lock:
        original = sys.stdout
        sys.stdout = _LineCapture(log_q, original)
        try:
            sql_files = [SQLFile(**f) for f in payload["sql_files"]]
            req = ValidationRequest(
                sql_files=sql_files,
                change_description=payload["change_description"],
            )
            result = run_validation(req)

            # 读取生成的 Markdown 报告文件
            change_md = ""
            syntax_md = ""
            if result.report_path and Path(result.report_path).exists():
                change_md = Path(result.report_path).read_text(encoding="utf-8")
            if result.syntax_report_path and Path(result.syntax_report_path).exists():
                syntax_md = Path(result.syntax_report_path).read_text(encoding="utf-8")

            task["status"] = "done"
            task["result"] = {
                "verdict": result.verdict,
                "risk_level": result.risk_level,
                "summary": result.summary,
                "report_path": str(result.report_path),
                "syntax_report_path": str(result.syntax_report_path or ""),
                "change_report_md": change_md,
                "syntax_report_md": syntax_md,
            }

        except Exception as exc:
            err_str = str(exc)
            task["status"] = "error"
            task["error"] = err_str
            # 提取人类可读的错误类型标签，方便前端识别
            if "429" in err_str or "insufficient_quota" in err_str or "exceeded" in err_str.lower():
                task["error_type"] = "quota_exceeded"
            elif "401" in err_str or "Authentication" in err_str or "api_key" in err_str.lower():
                task["error_type"] = "auth_error"
            elif "timeout" in err_str.lower() or "Timeout" in err_str:
                task["error_type"] = "timeout"
            else:
                task["error_type"] = "unknown"
            log_q.put(f"[ERROR] {exc}")
        finally:
            sys.stdout = original
            log_q.put(_DONE_SENTINEL)


# ─────────────────────────────────────────────────────────────────────────────
# 路由
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    html = (Path(__file__).parent / "index.html").read_text(encoding="utf-8")
    return html


@app.post("/api/fetch-scripts")
async def fetch_scripts(req: _FetchRequest):
    """
    从 CODING 仓库拉取匹配指定 Coding 编号的 SQL 脚本。

    Returns:
        {
          "date_folders": ["20260428", ...],   # 按日期排序
          "files": {
            "20260428": [
              {"filename": "...", "content": "...", "developer": "..."},
              ...
            ]
          }
        }
    """
    from sql_validator.config.settings import get_settings
    from sql_validator.fetcher import fetch_scripts_by_coding

    if not req.coding_numbers:
        raise HTTPException(status_code=400, detail="Coding 编号列表不能为空")

    settings = get_settings()

    try:
        results = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: fetch_scripts_by_coding(
                settings.coding_repo_url,
                settings.coding_branch,
                settings.coding_token,
                req.coding_numbers,
            ),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    date_folders = list(results.keys())
    files = {
        date: [
            {"filename": f.filename, "content": f.content, "developer": f.developer}
            for f in flist
        ]
        for date, flist in results.items()
    }
    return {"date_folders": date_folders, "files": files}


@app.post("/api/validate")
async def start_validate(req: _ValidateRequest):
    """创建验证任务，在后台线程中执行，立即返回 task_id。"""
    task_id = str(uuid.uuid4())
    _tasks[task_id] = {
        "status": "running",
        "log_queue": queue.Queue(),
        "result": None,
        "error": None,
    }
    t = threading.Thread(
        target=_run_task,
        args=(task_id, req.model_dump()),
        daemon=True,
    )
    t.start()
    return {"task_id": task_id}


@app.get("/api/stream/{task_id}")
async def stream_logs(task_id: str):
    """SSE 接口：实时推送验证日志，任务结束后发送 done 事件关闭流。"""
    if task_id not in _tasks:
        raise HTTPException(status_code=404, detail="任务不存在")

    task = _tasks[task_id]
    log_q: queue.Queue = task["log_queue"]

    async def _gen():
        loop = asyncio.get_event_loop()
        while True:
            try:
                item = await loop.run_in_executor(
                    None, lambda: log_q.get(block=True, timeout=0.5)
                )
                if item is _DONE_SENTINEL:
                    payload = json.dumps({
                        "type": "done",
                        "status": task["status"],
                        "error": task.get("error", ""),
                        "error_type": task.get("error_type", ""),
                    })
                    yield f"data: {payload}\n\n"
                    break
                text = str(item)
                payload = json.dumps({"type": "log", "text": text})
                yield f"data: {payload}\n\n"
            except Exception:
                # queue.Empty (timeout) 或其他异常 → 发心跳保活
                yield 'data: {"type":"heartbeat"}\n\n'

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/report/{task_id}")
async def get_report(task_id: str):
    """返回已完成任务的完整报告数据（含 Markdown 原文）。"""
    if task_id not in _tasks:
        raise HTTPException(status_code=404, detail="任务不存在")
    task = _tasks[task_id]
    if task["status"] == "running":
        raise HTTPException(status_code=202, detail="任务仍在运行中，请稍后重试")
    if task["status"] == "error":
        raise HTTPException(status_code=500, detail=task.get("error", "未知错误"))
    return task["result"]


# ─────────────────────────────────────────────────────────────────────────────
# 直接运行入口
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        app_dir=str(Path(__file__).parent),
    )
