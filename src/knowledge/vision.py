"""Vision model client (Groq) for OCR, chart reading and image questions.

Used for scanned PDF pages, image uploads (including handwriting), charts
embedded in PDFs, and images attached to a question. Every image is
downscaled and re-encoded as JPEG (longest side 1600 px, under 4 MB) before
it is sent. Failures never raise: they return a ``VisionResult`` with
``ok=False`` so ingestion can skip the page and report it.
"""

from __future__ import annotations

import base64
import io
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.core.logging import get_logger

if TYPE_CHECKING:
    from src.core.config import Settings

logger = get_logger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"
MAX_SIDE = 1600
MAX_BYTES = 4 * 1024 * 1024


def load_prompt(name: str) -> str:
    """Prompts are versioned files (e.g. ``ocr_v1``) so changes are reviewable."""
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8").strip()


@dataclass
class VisionResult:
    ok: bool
    text: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    error: str | None = None


def prepare_image(image_bytes: bytes) -> bytes:
    """Downscale to MAX_SIDE and re-encode as JPEG under MAX_BYTES."""
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as img:
        img = img.convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        quality = 90
        while True:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            data = buf.getvalue()
            if len(data) <= MAX_BYTES or quality <= 40:
                return data
            quality -= 15


def to_png(image_bytes: bytes) -> tuple[bytes, int, int]:
    """Re-encode any supported image as PNG (for stored assets)."""
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as img:
        img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), img.width, img.height


def parse_json_reply(text: str) -> dict[str, Any] | None:
    """Parse a JSON object from a model reply, tolerating a code fence."""
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


class VisionClient:
    """Groq vision chat completions with an image data-URI content part."""

    def __init__(self, settings: Settings) -> None:
        self.model = settings.groq_vision_model
        self.enabled = bool(settings.kis_vision_enabled and settings.groq_api_key)
        self._api_key = settings.groq_api_key
        self._timeout = settings.llm_timeout_seconds
        self._sync: Any = None
        self._async: Any = None

    UNAVAILABLE = "vision OCR is disabled or GROQ_API_KEY is not set"

    @property
    def unavailable_reason(self) -> str:
        return self.UNAVAILABLE

    def _messages(self, image_bytes: bytes, prompt: str) -> list[dict[str, Any]]:
        b64 = base64.b64encode(prepare_image(image_bytes)).decode("ascii")
        return [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                ],
            }
        ]

    def _result(self, completion: Any, start: float) -> VisionResult:
        usage: Any = completion.usage
        return VisionResult(
            ok=True,
            text=(completion.choices[0].message.content or "").strip(),
            model=self.model,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
        )

    def _failure(self, exc: BaseException, start: float) -> VisionResult:
        logger.warning("kis_vision_failed", error=str(exc)[:200])
        return VisionResult(
            ok=False,
            model=self.model,
            error=f"{type(exc).__name__}: {str(exc)[:200]}",
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
        )

    def describe(self, image_bytes: bytes, prompt: str) -> VisionResult:
        """Blocking call (ingestion runs in a worker thread)."""
        if not self.enabled:
            return VisionResult(ok=False, error=self.unavailable_reason)
        start = time.perf_counter()
        try:
            if self._sync is None:
                from groq import Groq

                self._sync = Groq(
                    api_key=self._api_key, timeout=self._timeout, max_retries=1
                )
            completion = self._sync.chat.completions.create(
                model=self.model,
                messages=self._messages(image_bytes, prompt),
                temperature=0.0,
                max_tokens=1500,
            )
            return self._result(completion, start)
        except Exception as exc:
            return self._failure(exc, start)

    async def adescribe(self, image_bytes: bytes, prompt: str) -> VisionResult:
        """Non-blocking call for image questions on the request path."""
        if not self.enabled:
            return VisionResult(ok=False, error=self.unavailable_reason)
        start = time.perf_counter()
        try:
            if self._async is None:
                from groq import AsyncGroq

                self._async = AsyncGroq(
                    api_key=self._api_key, timeout=self._timeout, max_retries=1
                )
            completion = await self._async.chat.completions.create(
                model=self.model,
                messages=self._messages(image_bytes, prompt),
                temperature=0.0,
                max_tokens=1500,
            )
            return self._result(completion, start)
        except Exception as exc:
            return self._failure(exc, start)
