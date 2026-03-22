import asyncio
import hashlib
import os
import random
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from .exceptions import EmbeddingException


class EmbeddingProvider(Protocol):
    @property
    def dimension(self) -> int: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def aembed(self, texts: list[str]) -> list[list[float]]: ...


def _float32(x: float) -> float:
    return float(f"{x:.7g}")


def _stable_int_hash(s: str) -> int:
    h = hashlib.sha256(s.encode("utf-8")).digest()
    return int.from_bytes(h[:8], "little", signed=False)


@dataclass(frozen=True)
class StubProvider:
    dimension: int = 1536
    seed: int = 1337

    def _rng_for_text(self, text: str) -> random.Random:
        return random.Random(self.seed ^ _stable_int_hash(text))

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for t in texts:
            rng = self._rng_for_text(t)
            vec = [_float32(rng.uniform(-1.0, 1.0)) for _ in range(self.dimension)]
            vectors.append(vec)
        return vectors

    async def aembed(self, texts: list[str]) -> list[list[float]]:
        return self.embed(texts)


@dataclass(frozen=True)
class OpenAIProvider:
    model: str
    api_key: str
    dimension: int = 1536
    batch_size: int = 128
    timeout_seconds: int = 30
    concurrency: int = 8
    base_url: str = "https://api.openai.com/v1"
    max_retries: int = 5

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _embed_batch_sync(self, client: httpx.Client, batch: list[str]) -> list[list[float]]:
        payload = {"model": self.model, "input": batch}
        for attempt in range(self.max_retries):
            try:
                r = client.post(
                    f"{self.base_url}/embeddings",
                    headers=self._headers(),
                    json=payload,
                    timeout=self.timeout_seconds,
                )
                if r.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError("retryable", request=r.request, response=r)
                r.raise_for_status()
                data = r.json()
                items = data.get("data", [])
                vectors = [[_float32(x) for x in item["embedding"]] for item in items]
                return vectors
            except Exception as e:
                if attempt >= self.max_retries - 1:
                    raise EmbeddingException("openai_embed_failed") from e
                time.sleep(min(2**attempt, 10))
        raise EmbeddingException("openai_embed_failed")

    async def _embed_batch_async(self, client: httpx.AsyncClient, batch: list[str]) -> list[list[float]]:
        payload = {"model": self.model, "input": batch}
        for attempt in range(self.max_retries):
            try:
                r = await client.post(
                    f"{self.base_url}/embeddings",
                    headers=self._headers(),
                    json=payload,
                    timeout=self.timeout_seconds,
                )
                if r.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError("retryable", request=r.request, response=r)
                r.raise_for_status()
                data = r.json()
                items = data.get("data", [])
                vectors = [[_float32(x) for x in item["embedding"]] for item in items]
                return vectors
            except Exception as e:
                if attempt >= self.max_retries - 1:
                    raise EmbeddingException("openai_embed_failed") from e
                await asyncio.sleep(min(2**attempt, 10))
        raise EmbeddingException("openai_embed_failed")

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            with httpx.Client() as client:
                out: list[list[float]] = []
                for i in range(0, len(texts), self.batch_size):
                    out.extend(self._embed_batch_sync(client, texts[i : i + self.batch_size]))
                return out
        except EmbeddingException:
            raise
        except Exception as e:
            raise EmbeddingException("openai_embed_failed") from e

    async def aembed(self, texts: list[str]) -> list[list[float]]:
        sem = asyncio.Semaphore(self.concurrency)

        async def run_one(batch: list[str]) -> list[list[float]]:
            async with sem:
                async with httpx.AsyncClient() as client:
                    return await self._embed_batch_async(client, batch)

        try:
            tasks = []
            for i in range(0, len(texts), self.batch_size):
                tasks.append(run_one(texts[i : i + self.batch_size]))
            parts = await asyncio.gather(*tasks)
            out: list[list[float]] = []
            for p in parts:
                out.extend(p)
            return out
        except EmbeddingException:
            raise
        except Exception as e:
            raise EmbeddingException("openai_embed_failed") from e


def provider_from_model_row(model_id: str, provider_type: str, dimension: int, config: dict[str, Any]) -> EmbeddingProvider:
    if provider_type == "stub":
        seed = int(config.get("seed", 1337))
        dim = int(config.get("dimension", dimension))
        return StubProvider(dimension=dim, seed=seed)

    if provider_type == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise EmbeddingException("OPENAI_API_KEY_not_set")
        model = str(config.get("model", "text-embedding-3-small"))
        return OpenAIProvider(
            model=model,
            api_key=api_key,
            dimension=int(config.get("dimension", dimension)),
            batch_size=int(config.get("batch_size", 128)),
            timeout_seconds=int(config.get("timeout_seconds", 30)),
            concurrency=int(config.get("concurrency", 8)),
            base_url=str(config.get("base_url", "https://api.openai.com/v1")),
        )

    raise EmbeddingException(f"unknown_provider_type:{provider_type}")
