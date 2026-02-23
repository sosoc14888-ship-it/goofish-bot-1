"""
translator.py — автоперевод с китайского
Использует Google Translate (бесплатно, без API ключа) через googletrans
"""
import logging
import asyncio
from typing import Optional

log = logging.getLogger(__name__)

_translator = None

def _get_translator():
    global _translator
    if _translator is None:
        try:
            from googletrans import Translator as GT
            _translator = GT()
        except ImportError:
            log.warning("googletrans not installed: pip install googletrans==4.0.0rc1")
    return _translator


class Translator:
    def __init__(self):
        self._cache: dict[str, str] = {}

    async def translate(self, text: str, dest: str = "ru") -> str:
        """
        Переводит текст на русский язык.
        Определяет язык автоматически.
        Кэширует результаты.
        """
        if not text or not text.strip():
            return text

        # Если текст уже латиница/кириллица без китайских символов — не переводим
        if not any('\u4e00' <= ch <= '\u9fff' for ch in text):
            return text

        if text in self._cache:
            return self._cache[text]

        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, self._do_translate, text, dest
            )
            self._cache[text] = result
            return result
        except Exception as e:
            log.debug(f"translate error: {e}")
            return text  # Возвращаем оригинал если перевод не вышел

    def _do_translate(self, text: str, dest: str) -> str:
        tr = _get_translator()
        if tr is None:
            return text
        result = tr.translate(text, dest=dest)
        return result.text if result else text
