from __future__ import annotations

import asyncio
import queue
import threading
from typing import Any, Callable

from config import get_logger

log = get_logger("finance.async_utils")

# 后台任务强引用集合。asyncio.create_task 返回的 Task 若不被任何变量持有，
# CPython 可能在完成前将其回收，导致缓存刷新等后台任务静默失败。
# 这里集中持有引用，完成后自动移除并记录异常。
_bg_tasks: set[asyncio.Task] = set()


def spawn_background_task(coro, label: str = "bg") -> asyncio.Task | None:
    # 提交后台任务并持有强引用，避免被 GC 中途回收。无运行中事件循环时安全跳过。
    try:
        task = asyncio.create_task(coro)
    except RuntimeError:
        log.warning("spawn_background_task(%s): no running loop, skip", label)
        coro.close()
        return None
    _bg_tasks.add(task)

    def _on_done(t: asyncio.Task) -> None:
        _bg_tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            log.warning("background task %s failed: %s: %s", label, type(exc).__name__, exc)

    task.add_done_callback(_on_done)
    log.debug("spawn_background_task(%s) queued", label)
    return task


def call_with_timeout(func: Callable, timeout: float, *args, **kwargs) -> Any:
    # 在 daemon 线程中执行同步阻塞调用，超时返回 None。用于 akshare 这类无内部
    # 超时、可能挂起的网络调用，防止拖垮事件循环。signal.alarm 只能在主线程使用，
    # 此方案可在任意线程（含 executor worker）中调用。
    # 注意：超时后 daemon 线程会继续运行直到自然结束（无法强制杀线程），因此
    # 仅用于低频调用；高频路径应配合有界 ThreadPoolExecutor + asyncio.wait_for。
    q: "queue.Queue" = queue.Queue()

    def _worker():
        try:
            q.put(("ok", func(*args, **kwargs)))
        except Exception as exc:
            q.put(("err", exc))

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    try:
        kind, val = q.get(timeout=timeout)
    except queue.Empty:
        log.warning("call_with_timeout: %.1fs timeout, abandoning worker", timeout)
        return None
    if kind == "err":
        raise val
    return val
