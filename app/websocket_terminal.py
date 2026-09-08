import asyncio
import fcntl
import json
import os
import pty
import struct
import termios

from fastapi import WebSocket, WebSocketDisconnect

_SEND_TIMEOUT = 15.0        # declare connection dead if a single send blocks longer than this
_KEEPALIVE_INTERVAL = 20.0  # ping interval to detect silently-dropped connections
_QUEUE_MAXSIZE = 512        # ~2 MB at 4096 bytes/chunk; chunks dropped when full to prevent OOM


def _resize(fd: int, cols: int, rows: int) -> None:
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except OSError:
        pass


def _write(fd: int, data: bytes) -> None:
    try:
        os.write(fd, data)
    except OSError:
        pass


async def _run_io_loop(websocket: WebSocket, master_fd: int) -> None:
    """Bridge PTY master_fd <-> WebSocket. Caller must close slave_fd before calling this."""
    loop = asyncio.get_running_loop()
    out_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
    done = asyncio.Event()

    def _on_readable() -> None:
        try:
            data = os.read(master_fd, 4096)
            if data:
                try:
                    loop.call_soon_threadsafe(out_q.put_nowait, data)
                except asyncio.QueueFull:
                    pass  # drop chunk rather than OOM when browser is too slow
            else:
                loop.call_soon_threadsafe(done.set)
        except OSError:
            loop.call_soon_threadsafe(done.set)

    loop.add_reader(master_fd, _on_readable)

    async def _sender() -> None:
        while not done.is_set():
            try:
                data = await asyncio.wait_for(out_q.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            try:
                await asyncio.wait_for(websocket.send_bytes(data), timeout=_SEND_TIMEOUT)
            except asyncio.TimeoutError:
                done.set()  # connection is stuck — declare dead
                break
            except Exception:
                done.set()
                break

    async def _receiver() -> None:
        while not done.is_set():
            try:
                msg = await asyncio.wait_for(websocket.receive(), timeout=0.5)
                kind = msg.get("type")
                if kind == "websocket.disconnect":
                    done.set()
                    break
                raw_bytes = msg.get("bytes")
                raw_text = msg.get("text")
                if raw_bytes:
                    _write(master_fd, raw_bytes)
                elif raw_text:
                    try:
                        ctrl = json.loads(raw_text)
                        if ctrl.get("type") == "resize":
                            _resize(master_fd, int(ctrl.get("cols", 220)), int(ctrl.get("rows", 50)))
                        # silently ignore {"type": "ping"} keepalive acks from the client
                    except (json.JSONDecodeError, ValueError):
                        _write(master_fd, raw_text.encode())
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                done.set()
                break
            except Exception:
                done.set()
                break

    async def _keepalive() -> None:
        while not done.is_set():
            try:
                await asyncio.sleep(_KEEPALIVE_INTERVAL)
                if not done.is_set():
                    # Empty binary frame — xterm.js writes nothing for zero-length data
                    await asyncio.wait_for(websocket.send_bytes(b""), timeout=5.0)
            except Exception:
                done.set()
                break

    try:
        await asyncio.gather(_sender(), _receiver(), _keepalive(), return_exceptions=True)
    finally:
        try:
            loop.remove_reader(master_fd)
        except Exception:
            pass


async def handle_terminal_websocket(
    websocket: WebSocket,
    tmux_session_name: str,
    cols: int = 220,
    rows: int = 50,
) -> None:
    await websocket.accept()

    master_fd, slave_fd = pty.openpty()
    _resize(master_fd, cols, rows)

    def _preexec() -> None:
        os.setsid()
        try:
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
        except OSError:
            pass

    proc = await asyncio.create_subprocess_exec(
        "tmux", "attach-session", "-t", tmux_session_name,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        preexec_fn=_preexec,
        env={**os.environ, "TERM": "xterm-256color"},
    )
    os.close(slave_fd)

    try:
        await _run_io_loop(websocket, master_fd)
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass
        if proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass


async def handle_direct_websocket(
    websocket: WebSocket,
    command: list[str],
    cwd: str,
    cols: int = 220,
    rows: int = 50,
    extra_env: dict | None = None,
) -> None:
    """Spawn a process directly via PTY — no tmux involved."""
    await websocket.accept()

    master_fd, slave_fd = pty.openpty()
    _resize(master_fd, cols, rows)

    def _preexec() -> None:
        os.setsid()
        try:
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
        except OSError:
            pass

    proc = await asyncio.create_subprocess_exec(
        *command,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=cwd,
        preexec_fn=_preexec,
        env={**os.environ, "TERM": "xterm-256color", **(extra_env or {})},
    )
    os.close(slave_fd)

    try:
        await _run_io_loop(websocket, master_fd)
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass
        if proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
