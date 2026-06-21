"""
DeerFlow Docker Memory Monitor
实时监控 deer-flow 各容器的内存占用
"""

import asyncio
import json
import re
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

import docker
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Docker client
docker_client = docker.DockerClient(base_url="unix:///var/run/docker.sock")

# 存储历史数据（最近 5 分钟，每秒一个点 = 300 点）
MAX_HISTORY = 300
memory_history: dict[str, list[dict]] = {}
resource_events: deque[dict] = deque(maxlen=200)
resource_event_keys: deque[str] = deque(maxlen=500)
last_log_poll: dict[str, int] = {}
log_file_positions: dict[str, int] = {}
RESOURCE_EVENT_RE = re.compile(r"\b(mmkb_tool_resource_validation|assistant_resource_validation)\b")
RESOURCE_FIELD_RE = re.compile(r"\b([a-z_]+)=([^\s]+)")
LOG_TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?))")
RESOURCE_FIELDS = {
    "tool",
    "thread_id",
    "run_id",
    "resource_urls",
    "signed_media_urls",
    "structurally_valid_signed",
    "malformed_signed",
    "protected_unsigned",
    "document_page_urls",
    "structurally_valid_document_pages",
    "malformed_document_pages",
    "document_origin_matches",
    "unexpected_document_origins",
    "relative_document_pages",
    "document_pages_require_session",
}


def get_deer_flow_containers():
    """获取 deer-flow 相关的容器"""
    containers = docker_client.containers.list()
    result = []
    for c in containers:
        labels = c.labels or {}
        project = labels.get("com.docker.compose.project", "")
        if "deer-flow" in project or "deer_flow" in project or "deerflow" in project:
            result.append(c)
    # 如果没找到带标签的，尝试按名称匹配
    if not result:
        for c in containers:
            if any(kw in c.name for kw in ["deer-flow", "deer_flow", "deerflow"]):
                result.append(c)
    return result


def get_container_memory(container) -> dict | None:
    """获取单个容器的内存使用信息"""
    try:
        stats = container.stats(stream=False)
        mem_stats = stats.get("memory_stats", {})
        usage = mem_stats.get("usage", 0)
        limit = mem_stats.get("limit", 0)
        # 减去 cache（如果有的话）
        cache = mem_stats.get("stats", {}).get("cache", 0)
        actual_usage = usage - cache
        return {
            "usage": max(actual_usage, 0),
            "limit": limit,
            "timestamp": time.time(),
        }
    except Exception:
        return None


def append_resource_validation_event(line: str, source: str) -> None:
    """Retain one aggregate validation event while discarding raw log text."""
    event_match = RESOURCE_EVENT_RE.search(line)
    if event_match is None:
        return
    event_key = f"{source}:{line}"
    if event_key in resource_event_keys:
        return
    resource_event_keys.append(event_key)
    fields = {key: value for key, value in RESOURCE_FIELD_RE.findall(line) if key in RESOURCE_FIELDS}
    timestamp_match = LOG_TIMESTAMP_RE.match(line)
    resource_events.appendleft(
        {
            "timestamp": timestamp_match.group(1) if timestamp_match else "",
            "container": source,
            "event": event_match.group(1),
            "has_failures": any(
                int(fields.get(key, "0")) > 0
                for key in (
                    "malformed_signed",
                    "protected_unsigned",
                    "malformed_document_pages",
                    "unexpected_document_origins",
                )
            ),
            "fields": fields,
        }
    )


def collect_resource_validation_events(container, now: int) -> None:
    """Collect aggregate validation events from Docker stdout."""
    since = last_log_poll.get(container.name, now - 10)
    last_log_poll[container.name] = now
    try:
        output = container.logs(since=since, until=now, timestamps=True).decode("utf-8", errors="replace")
    except Exception:
        return
    for line in output.splitlines():
        append_resource_validation_event(line, container.name)


def collect_resource_validation_log_file(path: Path) -> None:
    """Tail a shared application log because the dev Gateway redirects stdout."""
    try:
        size = path.stat().st_size
        position = log_file_positions.get(str(path), size)
        if position > size:
            position = 0
        with path.open(encoding="utf-8", errors="replace") as log_file:
            log_file.seek(position)
            lines = log_file.readlines()
            log_file_positions[str(path)] = log_file.tell()
    except OSError:
        return
    for line in lines:
        append_resource_validation_event(line.rstrip(), path.name)


def collect_stats_once() -> None:
    """Run one blocking Docker/log collection pass outside the event loop."""
    containers = get_deer_flow_containers()
    now = int(time.time())
    for container in containers:
        name = container.name
        mem = get_container_memory(container)
        if mem:
            if name not in memory_history:
                memory_history[name] = []
            memory_history[name].append(mem)
            if len(memory_history[name]) > MAX_HISTORY:
                memory_history[name] = memory_history[name][-MAX_HISTORY:]
        collect_resource_validation_events(container, now)
    collect_resource_validation_log_file(Path("/logs/gateway.log"))


async def collect_stats():
    """后台任务：持续采集容器内存和资源校验数据"""
    while True:
        try:
            await asyncio.to_thread(collect_stats_once)
        except Exception:
            pass
        await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(collect_stats())
    yield
    task.cancel()


app = FastAPI(title="DeerFlow Memory Monitor", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.get("/api/containers")
async def list_containers():
    """列出当前监控的容器"""
    containers = get_deer_flow_containers()
    return [{"name": c.name, "status": c.status} for c in containers]


@app.websocket("/ws/stats")
async def websocket_stats(websocket: WebSocket):
    """WebSocket 端点：每秒推送最新内存数据"""
    await websocket.accept()
    try:
        while True:
            # 构造当前快照
            snapshot = {}
            for name, history in memory_history.items():
                if history:
                    latest = history[-1]
                    peak = max(h["usage"] for h in history)
                    snapshot[name] = {
                        "usage": latest["usage"],
                        "limit": latest["limit"],
                        "peak": peak,
                        "timestamp": latest["timestamp"],
                    }
            await websocket.send_text(json.dumps(snapshot))
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass


@app.get("/api/history/{container_name}")
async def get_history(container_name: str):
    """获取指定容器的历史内存数据"""
    return memory_history.get(container_name, [])


@app.get("/api/mmkb-resource-events")
async def get_mmkb_resource_events():
    """Return recent aggregate MMKB resource validation events."""
    return list(resource_events)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=9090)
