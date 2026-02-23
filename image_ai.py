"""
image_ai.py — AI поиск по фото через CLIP (OpenAI)
Полностью бесплатно, работает локально.
"""
import logging
import asyncio
from io import BytesIO
from typing import Optional
import aiohttp
import numpy as np

log = logging.getLogger(__name__)

# CLIP загружается лениво при первом использовании
_model = None
_preprocess = None
_device = None


def _load_clip():
    global _model, _preprocess, _device
    if _model is not None:
        return
    try:
        import clip
        import torch
        _device = "cuda" if torch.cuda.is_available() else "cpu"
        _model, _preprocess = clip.load("ViT-B/32", device=_device)
        log.info(f"✅ CLIP loaded on {_device}")
    except ImportError:
        log.warning("⚠️ CLIP not installed. pip install git+https://github.com/openai/CLIP.git")
        _model = None


def _cosine_similarity(a: list, b: list) -> float:
    """Косинусное сходство двух векторов"""
    a, b = np.array(a), np.array(b)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


class ImageAI:
    def __init__(self):
        self._http: Optional[aiohttp.ClientSession] = None

    async def _get_http(self) -> aiohttp.ClientSession:
        if not self._http or self._http.closed:
            self._http = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            )
        return self._http

    async def _download_image(self, url: str) -> Optional[BytesIO]:
        try:
            session = await self._get_http()
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
                return BytesIO(data)
        except Exception as e:
            log.debug(f"download error {url}: {e}")
            return None

    async def get_embedding_from_url(self, url: str) -> Optional[list[float]]:
        """Скачивает фото и возвращает CLIP эмбеддинг"""
        img_bytes = await self._download_image(url)
        if not img_bytes:
            return None
        return await asyncio.get_event_loop().run_in_executor(
            None, self._embed_bytes, img_bytes
        )

    def _embed_bytes(self, img_bytes: BytesIO) -> Optional[list[float]]:
        _load_clip()
        if _model is None:
            return None
        try:
            from PIL import Image
            import torch
            img = Image.open(img_bytes).convert("RGB")
            tensor = _preprocess(img).unsqueeze(0).to(_device)
            with torch.no_grad():
                features = _model.encode_image(tensor)
                features = features / features.norm(dim=-1, keepdim=True)
            return features[0].cpu().tolist()
        except Exception as e:
            log.error(f"embed error: {e}")
            return None

    async def compare_url(self, embedding: list[float], image_url: str) -> float:
        """Сравнивает эмбеддинг с фото по URL, возвращает схожесть 0..1"""
        if not embedding or not image_url:
            return 0.0
        other = await self.get_embedding_from_url(image_url)
        if not other:
            return 0.0
        return max(0.0, _cosine_similarity(embedding, other))

    async def compare_with_ad(self, embedding: list[float], ad: dict) -> float:
        """Сравнивает эмбеддинг с фото объявления"""
        return await self.compare_url(embedding, ad.get("image_url", ""))
