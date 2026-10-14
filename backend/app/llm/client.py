import base64
import hashlib
import io
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, TypeVar

from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError
from PIL import Image
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.llm.prompts import PROMPT_VERSION

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger("claimgraph.llm")


class RedactingFilter(logging.Filter):
    """Ensures LLM keys and sensitive document texts are redacted from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            if settings.LLM_API_KEY and settings.LLM_API_KEY in record.msg:
                record.msg = record.msg.replace(settings.LLM_API_KEY, "[REDACTED_KEY]")
            # Redact prompt texts if they contain document content
            if "Document text:" in record.msg:
                record.msg = re.sub(r"Document text:.*", "Document text: [REDACTED]", record.msg)
        return True


logger.addFilter(RedactingFilter())


class LLMCacheMissError(RuntimeError):
    """Raised when an LLM call is attempted in replay mode and no cache entry exists."""
    pass

def to_strict_json_schema(model_cls: type[BaseModel]) -> dict[str, Any]:
    """Ensures Pydantic JSON schema conforms to OpenAI / Groq strict structured outputs rules:
    - additionalProperties: False on every object
    - required: list of all property keys on every object
    """
    schema = model_cls.model_json_schema()

    def fix_node(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                node["additionalProperties"] = False
                if "properties" in node:
                    node["required"] = list(node["properties"].keys())
            for v in node.values():
                if isinstance(v, dict | list):
                    fix_node(v)
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, dict | list):
                    fix_node(item)

    fix_node(schema)
    return schema


class LLMClient:
    def __init__(self) -> None:
        self.semaphore = threading.Semaphore(settings.LLM_MAX_CONCURRENCY)
        self._client: OpenAI | None = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            api_key = settings.LLM_API_KEY.strip() or "mock-key"
            self._client = OpenAI(
                base_url=settings.LLM_BASE_URL,
                api_key=api_key,
                max_retries=0,  # We handle retries and 429 explicitly
            )
        return self._client

    def _get_cache_dir(self) -> Path:
        cache_dir = Path(settings.STORAGE_DIR) / "llm_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    def _get_synthetic_cache_dir(self) -> Path:
        # Check standard locations for data/synthetic/_llm_cache
        candidates = [
            Path("/data/synthetic/_llm_cache"),
            Path(__file__).resolve().parents[3] / "data" / "synthetic" / "_llm_cache",
            Path("data/synthetic/_llm_cache").resolve(),
        ]
        for c in candidates:
            if c.exists():
                return c
        candidates[1].mkdir(parents=True, exist_ok=True)
        return candidates[1]

    def _get_cache_key(
        self, doc_hash: str, page_range: str, model: str, prompt_version: str = PROMPT_VERSION
    ) -> str:
        safe_model = model.replace("/", "_").replace(":", "_")
        return f"{doc_hash}_{page_range}_{prompt_version}_{safe_model}.json"

    def read_cache(self, cache_key: str) -> dict[str, Any] | None:
        # 1. Check primary storage cache
        storage_path = self._get_cache_dir() / cache_key
        if storage_path.exists():
            try:
                with open(storage_path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read cache at {storage_path}: {e}")

        # 2. Check committed synthetic cache
        synthetic_path = self._get_synthetic_cache_dir() / cache_key
        if synthetic_path.exists():
            try:
                with open(synthetic_path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read synthetic cache at {synthetic_path}: {e}")

        return None

    def write_cache(self, cache_key: str, data: dict[str, Any]) -> None:
        storage_path = self._get_cache_dir() / cache_key
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        with open(storage_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def complete_json(
        self,
        system: str,
        user: str,
        pydantic_model: type[T],
        model: str | None = None,
        doc_hash: str | None = None,
        page_range: str = "1",
    ) -> T | None:
        target_model = model or settings.LLM_EXTRACT_MODEL or "openai/gpt-oss-120b"
        effective_doc_hash = doc_hash or hashlib.sha256(user.encode("utf-8")).hexdigest()
        cache_key = self._get_cache_key(
            doc_hash=effective_doc_hash,
            page_range=page_range,
            model=target_model,
        )

        # 1. Check cache
        cached_data = self.read_cache(cache_key)
        if cached_data is not None:
            try:
                return pydantic_model.model_validate(cached_data)
            except ValidationError as e:
                logger.warning(f"Cached data invalid for {pydantic_model.__name__}: {e}")
                if settings.LLM_MODE == "replay":
                    raise

        # If in replay mode and not cached, error out clearly
        if settings.LLM_MODE == "replay":
            raise LLMCacheMissError(
                f"LLM cache miss for key '{cache_key}' (model={target_model}, pages={page_range}) "
                f"while LLM_MODE=replay. Live API calls are prohibited in replay mode."
            )

        # In live mode, call API
        if not settings.LLM_API_KEY.strip():
            logger.warning("LLM_API_KEY is empty. Skipping live LLM call.")
            return None

        with self.semaphore:
            return self._call_with_retry_and_validation(
                system=system,
                user=user,
                pydantic_model=pydantic_model,
                model=target_model,
                cache_key=cache_key,
            )

    def complete_vision_json(
        self,
        system: str,
        user: str,
        image_bytes_or_path: bytes | str | Path,
        pydantic_model: type[T],
        model: str | None = None,
        doc_hash: str | None = None,
        page_no: int = 1,
    ) -> T | None:
        target_model = model or settings.LLM_VISION_MODEL or "llama-3.2-11b-vision-preview"

        # Read image bytes
        if isinstance(image_bytes_or_path, str | Path):
            with open(image_bytes_or_path, "rb") as f:
                img_bytes = f.read()
        else:
            img_bytes = image_bytes_or_path

        effective_doc_hash = doc_hash or hashlib.sha256(img_bytes).hexdigest()
        cache_key = self._get_cache_key(
            doc_hash=f"{effective_doc_hash}_vision_page_{page_no}",
            page_range=str(page_no),
            model=target_model,
        )

        # 1. Check cache
        cached_data = self.read_cache(cache_key)
        if cached_data is not None:
            try:
                return pydantic_model.model_validate(cached_data)
            except ValidationError as e:
                logger.warning(f"Cached vision data invalid for {pydantic_model.__name__}: {e}")
                if settings.LLM_MODE == "replay":
                    raise

        if settings.LLM_MODE == "replay":
            raise LLMCacheMissError(
                f"LLM vision cache miss for key '{cache_key}' (model={target_model}, page={page_no}) "
                f"while LLM_MODE=replay. Live API calls are prohibited in replay mode."
            )

        if not settings.LLM_API_KEY.strip():
            logger.warning("LLM_API_KEY is empty. Skipping live vision LLM call.")
            return None

        # Downscale image to max 1280px to respect limits
        try:
            pil_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            pil_img.thumbnail((1280, 1280))
            buf = io.BytesIO()
            pil_img.save(buf, format="JPEG", quality=85)
            downscaled_bytes = buf.getvalue()
        except Exception as e:
            logger.warning(f"Failed to downscale image for vision: {e}. Using raw bytes.")
            downscaled_bytes = img_bytes

        base64_img = base64.b64encode(downscaled_bytes).decode("utf-8")
        data_uri = f"data:image/jpeg;base64,{base64_img}"

        user_content: list[dict[str, Any]] = [
            {"type": "text", "text": user},
            {
                "type": "image_url",
                "image_url": {"url": data_uri},
            },
        ]
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]

        with self.semaphore:
            raw_content = self._call_chat_completion(
                messages=messages, model=target_model, pydantic_model=pydantic_model
            )
            if raw_content is None:
                return None
            try:
                parsed_json = json.loads(raw_content)
                validated = pydantic_model.model_validate(parsed_json)
                self.write_cache(cache_key, validated.model_dump(mode="json"))
                return validated
            except (json.JSONDecodeError, ValidationError) as err:
                logger.warning(f"Vision response failed validation ({err}). Retrying once...")
                retry_messages = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                    {"role": "assistant", "content": raw_content},
                    {
                        "role": "user",
                        "content": (
                            f"Your previous output failed schema validation: {str(err)}.\n"
                            f"Please fix and output valid JSON conforming to requested schema."
                        ),
                    },
                ]
                retry_raw = self._call_chat_completion(
                    messages=retry_messages, model=target_model, pydantic_model=pydantic_model
                )
                if retry_raw is None:
                    return None
                try:
                    retry_json = json.loads(retry_raw)
                    validated = pydantic_model.model_validate(retry_json)
                    self.write_cache(cache_key, validated.model_dump(mode="json"))
                    return validated
                except (json.JSONDecodeError, ValidationError) as final_err:
                    logger.error(f"Retry vision validation failed: {final_err}")
                    return None

    def _call_with_retry_and_validation(
        self,
        system: str,
        user: str,
        pydantic_model: type[T],
        model: str,
        cache_key: str,
    ) -> T | None:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        raw_content = self._call_chat_completion(messages=messages, model=model, pydantic_model=pydantic_model)
        if raw_content is None:
            return None

        # Validate with Pydantic
        try:
            parsed_json = json.loads(raw_content)
            validated = pydantic_model.model_validate(parsed_json)
            # Save to cache
            self.write_cache(cache_key, validated.model_dump(mode="json"))
            return validated
        except (json.JSONDecodeError, ValidationError) as err:
            logger.warning(f"Initial LLM response failed validation ({err}). Retrying once with error message...")
            # Retry once with error feedback
            retry_messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
                {"role": "assistant", "content": raw_content},
                {
                    "role": "user",
                    "content": (
                        f"Your previous output failed schema validation with error: {str(err)}.\n"
                        f"Please fix the error and output valid JSON conforming strictly to the requested schema."
                    ),
                },
            ]
            retry_raw = self._call_chat_completion(
                messages=retry_messages, model=model, pydantic_model=pydantic_model
            )
            if retry_raw is None:
                return None
            try:
                retry_json = json.loads(retry_raw)
                validated = pydantic_model.model_validate(retry_json)
                self.write_cache(cache_key, validated.model_dump(mode="json"))
                return validated
            except (json.JSONDecodeError, ValidationError) as final_err:
                logger.error(f"Retry validation failed as well: {final_err}. Marking for human review.")
                return None

    def _call_chat_completion(
        self,
        messages: list[dict[str, str]],
        model: str,
        pydantic_model: type[BaseModel],
    ) -> str | None:
        max_attempts = 4
        backoff = 2.0

        for attempt in range(max_attempts):
            try:
                try:
                    strict_schema = to_strict_json_schema(pydantic_model)
                    response = self.client.chat.completions.create(
                        model=model,
                        messages=messages,  # type: ignore
                        temperature=0,
                        response_format={
                            "type": "json_schema",
                            "json_schema": {
                                "name": pydantic_model.__name__,
                                "strict": True,
                                "schema": strict_schema,
                            },
                        },
                    )
                    return response.choices[0].message.content or "{}"
                except APIStatusError as e:
                    if e.status_code == 400 and "response_format" in str(e).lower():
                        logger.info(f"Model {model} does not support json_schema, falling back to json_object.")
                        response = self.client.chat.completions.create(
                            model=model,
                            messages=messages,  # type: ignore
                            temperature=0,
                            response_format={"type": "json_object"},
                        )
                        return response.choices[0].message.content or "{}"
                    raise

            except RateLimitError as rle:
                retry_after = backoff
                # Attempt to extract retry-after from error or headers
                if hasattr(rle, "response") and rle.response and "retry-after" in rle.response.headers:
                    try:
                        retry_after = float(rle.response.headers["retry-after"])
                    except ValueError:
                        pass
                logger.warning(
                    f"Rate limited (429) on model {model}. Attempt {attempt + 1}/{max_attempts}. "
                    f"Backing off for {retry_after:.1f}s."
                )
                time.sleep(retry_after)
                backoff *= 2.0
            except APIConnectionError as ace:
                logger.warning(f"Connection error to LLM API: {ace}. Backing off for {backoff:.1f}s.")
                time.sleep(backoff)
                backoff *= 2.0
            except Exception as e:
                logger.error(f"LLM API call error: {e}")
                return None

        logger.error(f"Exhausted {max_attempts} attempts for LLM call.")
        return None

    def sync_cache_to_synthetic(self) -> int:
        """Copies all cached LLM responses from storage to data/synthetic/_llm_cache."""
        src_dir = self._get_cache_dir()
        dst_dir = self._get_synthetic_cache_dir()
        dst_dir.mkdir(parents=True, exist_ok=True)
        count = 0
        if src_dir.exists():
            for f in src_dir.glob("*.json"):
                with open(f, encoding="utf-8") as rf:
                    content = rf.read()
                with open(dst_dir / f.name, "w", encoding="utf-8") as wf:
                    wf.write(content)
                count += 1
        return count

    def sync_synthetic_to_storage(self) -> int:
        """Loads cached LLM responses from data/synthetic/_llm_cache into storage."""
        src_dir = self._get_synthetic_cache_dir()
        dst_dir = self._get_cache_dir()
        dst_dir.mkdir(parents=True, exist_ok=True)
        count = 0
        if src_dir.exists():
            for f in src_dir.glob("*.json"):
                with open(f, encoding="utf-8") as rf:
                    content = rf.read()
                with open(dst_dir / f.name, "w", encoding="utf-8") as wf:
                    wf.write(content)
                count += 1
        return count


llm_client = LLMClient()
