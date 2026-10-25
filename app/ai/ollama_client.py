"""Client for the local Ollama HTTP API (localhost only, no cloud)."""
from __future__ import annotations

import json
import shutil
import threading
from dataclasses import dataclass
from typing import Callable, Iterator

import requests

from app.config import is_local_url
from app.models import ChatMessage

OLLAMA_EXE_FALLBACKS = [r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"]


class OllamaError(Exception):
    """Base error with a user-friendly message."""


class OllamaUnavailable(OllamaError):
    pass


class ModelMissing(OllamaError):
    def __init__(self, model: str):
        self.model = model
        super().__init__(f"Model '{model}' is not installed. Install it with: ollama pull {model}")

    @property
    def command(self) -> str:
        return f"ollama pull {self.model}"


class OllamaTimeout(OllamaError):
    pass


class OllamaCancelled(OllamaError):
    pass


class ModelNotVision(OllamaError):
    pass


@dataclass
class ModelInfo:
    name: str
    size: int = 0
    is_cloud: bool = False


def is_cloud_model(entry: dict) -> bool:
    name = entry.get("name", "") or entry.get("model", "")
    return bool(entry.get("remote_host") or entry.get("remote_model")
                or name.endswith(":cloud") or name.endswith("-cloud"))


VISION_NAME_HINTS = ("vl", "llava", "vision", "minicpm-v", "moondream", "bakllava", "gemma3")


class OllamaClient:
    def __init__(self, base_url: str = "http://127.0.0.1:11434", timeout: int = 180):
        if not is_local_url(base_url):
            raise OllamaError("Only localhost Ollama endpoints are allowed.")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._cancel = threading.Event()
        self._resp: requests.Response | None = None

    # ---- status ----
    @staticmethod
    def find_executable() -> str | None:
        import os
        p = shutil.which("ollama")
        if p:
            return p
        for c in OLLAMA_EXE_FALLBACKS:
            c = os.path.expandvars(c)
            if os.path.isfile(c):
                return c
        return None

    def is_running(self) -> bool:
        try:
            return requests.get(self.base_url + "/api/version", timeout=3).ok
        except requests.RequestException:
            return False

    def version(self) -> str:
        try:
            r = requests.get(self.base_url + "/api/version", timeout=3)
            r.raise_for_status()
            return r.json().get("version", "?")
        except (requests.RequestException, ValueError) as e:
            raise OllamaUnavailable(self.unavailable_message()) from e

    def unavailable_message(self) -> str:
        if self.find_executable():
            return ("Ollama is installed but not running. Start it from the Start menu "
                    "or run: ollama serve")
        return "Ollama is not installed. Install it from https://ollama.com/download"

    def list_models(self, include_cloud: bool = False) -> list[ModelInfo]:
        try:
            r = requests.get(self.base_url + "/api/tags", timeout=5)
            r.raise_for_status()
            entries = r.json().get("models", [])
        except requests.RequestException as e:
            raise OllamaUnavailable(self.unavailable_message()) from e
        except ValueError as e:
            raise OllamaError("Malformed response from Ollama (/api/tags).") from e
        out = []
        for e in entries:
            cloud = is_cloud_model(e)
            if cloud and not include_cloud:
                continue  # never use cloud-hosted models: app must stay local
            out.append(ModelInfo(e.get("name") or e.get("model", ""), e.get("size", 0) or 0, cloud))
        return out

    def has_model(self, model: str) -> bool:
        names = {m.name for m in self.list_models()}
        return model in names or (":" not in model and f"{model}:latest" in names)

    def supports_vision(self, model: str) -> bool:
        try:
            r = requests.post(self.base_url + "/api/show", json={"model": model}, timeout=10)
            if r.status_code == 404:
                raise ModelMissing(model)
            r.raise_for_status()
            data = r.json()
        except OllamaError:
            raise
        except requests.RequestException as e:
            raise OllamaUnavailable(self.unavailable_message()) from e
        except ValueError:
            data = {}
        caps = data.get("capabilities")
        if isinstance(caps, list):
            return "vision" in caps
        families = (data.get("details") or {}).get("families") or []
        if any(f in ("clip", "mllama", "mllama") for f in families):
            return True
        return any(h in model.lower() for h in VISION_NAME_HINTS)

    # ---- chat ----
    @staticmethod
    def build_payload(model: str, messages: list[ChatMessage], context_length: int,
                      max_tokens: int, temperature: float, stream: bool = True) -> dict:
        msgs = []
        for m in messages:
            d = {"role": m.role, "content": m.content}
            if m.images:
                d["images"] = m.images
            msgs.append(d)
        return {
            "model": model,
            "messages": msgs,
            "stream": stream,
            "options": {"num_ctx": context_length, "num_predict": max_tokens,
                        "temperature": temperature},
        }

    def cancel(self) -> None:
        self._cancel.set()
        r = self._resp
        if r is not None:
            try:
                r.close()
            except Exception:
                pass

    def chat_stream(self, model: str, messages: list[ChatMessage], context_length: int = 4096,
                    max_tokens: int = 512, temperature: float = 0.2) -> Iterator[str]:
        self._cancel.clear()
        payload = self.build_payload(model, messages, context_length, max_tokens, temperature)
        try:
            resp = requests.post(self.base_url + "/api/chat", json=payload, stream=True,
                                 timeout=(5, self.timeout))
        except requests.ConnectionError as e:
            raise OllamaUnavailable(self.unavailable_message()) from e
        except requests.Timeout as e:
            raise OllamaTimeout(f"Ollama did not respond within {self.timeout}s.") from e
        except requests.RequestException as e:
            raise OllamaError(f"Request failed: {e}") from e
        self._resp = resp
        try:
            if resp.status_code == 404:
                raise ModelMissing(model)
            if resp.status_code >= 400:
                detail = ""
                try:
                    detail = resp.json().get("error", "")
                except ValueError:
                    detail = resp.text[:200]
                if "not found" in detail.lower():
                    raise ModelMissing(model)
                raise OllamaError(f"Ollama error ({resp.status_code}): {detail}")
            got_done = False
            for line in resp.iter_lines():
                if self._cancel.is_set():
                    raise OllamaCancelled("Cancelled.")
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError as e:
                    raise OllamaError("Malformed response from Ollama.") from e
                if "error" in obj:
                    err = str(obj["error"])
                    if "not found" in err.lower():
                        raise ModelMissing(model)
                    raise OllamaError(f"Inference error: {err}")
                chunk = (obj.get("message") or {}).get("content", "")
                if chunk:
                    yield chunk
                if obj.get("done"):
                    got_done = True
                    break
            if not got_done and not self._cancel.is_set():
                raise OllamaError("Response ended unexpectedly (incomplete reply).")
        except requests.Timeout as e:
            raise OllamaTimeout(f"Ollama timed out after {self.timeout}s without output.") from e
        except requests.RequestException as e:
            if self._cancel.is_set():
                raise OllamaCancelled("Cancelled.") from e
            raise OllamaError(f"Connection error during inference: {e}") from e
        except AttributeError as e:  # closed mid-read during cancel
            if self._cancel.is_set():
                raise OllamaCancelled("Cancelled.") from e
            raise
        finally:
            resp.close()
            self._resp = None

    def pull_stream(self, model: str) -> Iterator[tuple[str, float | None]]:
        """Download a model. ONLY call after explicit user confirmation.
        Yields (status, fraction 0..1 or None)."""
        self._cancel.clear()
        try:
            resp = requests.post(self.base_url + "/api/pull", json={"model": model, "stream": True},
                                 stream=True, timeout=(5, 120))
        except requests.RequestException as e:
            raise OllamaUnavailable(self.unavailable_message()) from e
        self._resp = resp
        try:
            for line in resp.iter_lines():
                if self._cancel.is_set():
                    raise OllamaCancelled("Download cancelled.")
                if not line:
                    continue
                obj = json.loads(line)
                if "error" in obj:
                    raise OllamaError(f"Download failed: {obj['error']}")
                total, done = obj.get("total"), obj.get("completed")
                yield obj.get("status", ""), (done / total if total and done is not None else None)
        except (requests.RequestException, ValueError, AttributeError) as e:
            if self._cancel.is_set():
                raise OllamaCancelled("Download cancelled.") from e
            raise OllamaError(f"Download interrupted: {e}") from e
        finally:
            resp.close()
            self._resp = None

    def chat(self, *args, **kwargs) -> str:
        return "".join(self.chat_stream(*args, **kwargs))
