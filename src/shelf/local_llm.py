"""A built-in writer for the DJ: a small language model run by Shelf itself, on the processor,
so the DJ can talk without any account, key or outside service.

It uses llama.cpp (a small program for running language models on ordinary processors) and a
compact model, both downloaded from the admin dashboard when wanted:
- standard: Llama 3.2 3B, natural and chatty (2 GB; about 3 GB of memory while it runs)
- small: Llama 3.2 1B, quicker on slow machines, plainer (0.8 GB; about 1.5 GB of memory)

The model runs as a helper process (llama-server) started when the DJ needs a line, and
stopped again after ten minutes without one, so the memory goes back to everything else.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import socket
import subprocess
import tarfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import procs
from . import __version__

log = logging.getLogger("shelf.local_llm")
AGENT = f"Shelf/{__version__} (self-hosted music server)"
HF = "https://huggingface.co/bartowski"
MODELS = {
    "standard": {"name": "Llama 3.2 3B", "file": "Llama-3.2-3B-Instruct-Q4_K_M.gguf", "size": 2_019_377_696,
                 "url": f"{HF}/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf",
                 "note": "Natural and chatty. 2 GB download, about 3 GB of memory while the DJ talks."},
    "small": {"name": "Llama 3.2 1B", "file": "Llama-3.2-1B-Instruct-Q4_K_M.gguf", "size": 807_694_464,
              "url": f"{HF}/Llama-3.2-1B-Instruct-GGUF/resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf",
              "note": "Quicker on slow machines, plainer lines. 0.8 GB download, about 1.5 GB of memory."},
}
FALLBACK_BUILD = "b12211"
_ASSET = re.compile(r"^llama-b\d+-bin-ubuntu-x64\.tar\.gz$")
IDLE_SECONDS = 600


def _get(url: str, timeout: float = 30):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": AGENT}), timeout=timeout)


class LocalLLM:
    def __init__(self, root: Path):
        self.root = root
        self.state: dict = {"installing": None, "done": 0, "total": 0, "error": None}
        self._proc: subprocess.Popen | None = None
        self._port = 0
        self._model: str | None = None
        self._last = 0.0
        self._lock = threading.Lock()
        threading.Thread(target=self._idle_loop, name="shelf-llm-idle", daemon=True).start()

    # ---------- what's here ----------

    @property
    def server(self) -> Path | None:
        hits = sorted((self.root / "bin").glob("**/llama-server")) if (self.root / "bin").exists() else []
        return hits[0] if hits else None

    def model_path(self, key: str) -> Path | None:
        m = MODELS.get(key)
        p = self.root / "models" / m["file"] if m else None
        return p if p and p.exists() else None

    def installed(self) -> list[str]:
        return [k for k in MODELS if self.model_path(k)] if self.server else []

    def info(self) -> dict:
        return {"models": {k: {**{x: v[x] for x in ("name", "note", "size")}, "installed": k in self.installed()}
                           for k, v in MODELS.items()},
                "running": self._proc is not None and self._proc.poll() is None, **self.state}

    # ---------- installing ----------

    def install(self, key: str) -> None:
        if key not in MODELS:
            raise ValueError("No such model")
        if self.state["installing"]:
            raise ValueError("Already downloading")
        self.state.update(installing=key, done=0, total=0, error=None)
        threading.Thread(target=self._install, args=(key,), name="shelf-llm-install", daemon=True).start()

    def _download(self, url: str, dest: Path, expected: int = 0) -> None:
        part = dest.with_name(dest.name + ".part")
        with _get(url, timeout=60) as r, open(part, "wb") as out:
            self.state["total"] = int(r.headers.get("Content-Length") or expected or 0)
            self.state["done"] = 0
            while chunk := r.read(1 << 20):
                out.write(chunk)
                self.state["done"] += len(chunk)
        part.rename(dest)

    def _build_url(self) -> str:
        """The newest CPU build of llama.cpp for x86-64 Linux (or a known one)."""
        try:
            with _get("https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=10") as r:
                for rel in json.loads(r.read()):
                    for a in rel.get("assets", []):
                        if _ASSET.match(a["name"]):
                            return a["browser_download_url"]
        except (urllib.error.URLError, OSError, ValueError):
            pass
        return (f"https://github.com/ggml-org/llama.cpp/releases/download/{FALLBACK_BUILD}/"
                f"llama-{FALLBACK_BUILD}-bin-ubuntu-x64.tar.gz")

    def _install(self, key: str) -> None:
        try:
            (self.root / "models").mkdir(parents=True, exist_ok=True)
            if not self.server:
                tgz = self.root / "llama-cpp.tar.gz"
                self._download(self._build_url(), tgz)
                shutil.rmtree(self.root / "bin", ignore_errors=True)
                with tarfile.open(tgz) as t:
                    t.extractall(self.root / "bin", filter="data")
                tgz.unlink(missing_ok=True)
                if not self.server:
                    raise OSError("The llama.cpp download didn't contain llama-server")
                self.server.chmod(0o755)
            m = MODELS[key]
            dest = self.root / "models" / m["file"]
            if not dest.exists():
                self._download(m["url"], dest, m["size"])
            log.info("The DJ's built-in writer (%s) is ready", m["name"])
        except (urllib.error.URLError, OSError, tarfile.TarError) as e:
            log.warning("Installing the built-in writer failed: %s", e)
            self.state["error"] = f"The download failed: {e}"
        finally:
            self.state["installing"] = None

    def remove(self, key: str) -> None:
        if self._model and self.model_path(key) and str(self.model_path(key)) == self._model:
            self.stop()
        p = self.model_path(key)
        if p:
            p.unlink()

    # ---------- running ----------

    def _start(self, key: str) -> None:
        model = self.model_path(key)
        if not model or not self.server:
            raise OSError("The built-in writer isn't downloaded yet")
        self.stop()
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self._port = s.getsockname()[1]
        threads = max(2, min(8, (os.cpu_count() or 4) - 1))
        env = {**os.environ, "LD_LIBRARY_PATH": f"{self.server.parent}:{os.environ.get('LD_LIBRARY_PATH', '')}"}
        self._proc = subprocess.Popen(
            [str(self.server), "-m", str(model), "--host", "127.0.0.1", "--port", str(self._port),
             "-c", "2048", "-np", "1", "-t", str(threads)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, **procs.low_priority(5),
        )
        self._model = str(model)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise OSError("The built-in writer stopped as it started (not enough memory?)")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self._port}/health", timeout=2) as r:
                    if r.status == 200:
                        return
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(0.5)
        raise OSError("The built-in writer took too long to start")

    def chat(self, key: str, system: str, prompt: str, max_tokens: int = 160, json_mode: bool = False,
             schema: dict | None = None) -> str:
        with self._lock:
            want = self.model_path(key)
            if self._proc is None or self._proc.poll() is not None or self._model != str(want):
                self._start(key)
            self._last = time.monotonic()
            # cache_prompt: the fixed opening (persona and examples) stays loaded between lines.
            body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                    "max_tokens": max_tokens, "temperature": 0.9, "top_p": 0.95, "cache_prompt": True}
            if schema:  # the answer is forced into exactly this shape
                body["response_format"] = {"type": "json_object", "schema": schema}
            elif json_mode:
                body["response_format"] = {"type": "json_object"}
            req = urllib.request.Request(f"http://127.0.0.1:{self._port}/v1/chat/completions",
                                         data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                out = json.loads(r.read())
            self._last = time.monotonic()
            return out["choices"][0]["message"]["content"]

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
        self._model = None

    def _idle_loop(self) -> None:
        while True:
            time.sleep(30)
            if self._proc and time.monotonic() - self._last > IDLE_SECONDS and not self._lock.locked():
                log.info("Stopping the DJ's built-in writer (idle)")
                self.stop()
