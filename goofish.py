"""
goofish.py — парсер Goofish через веб API
Использует cookie из твоего браузера (без Selenium, без эмулятора)
"""
import asyncio
import hashlib
import json
import logging
import time
from typing import Optional
import aiohttp
from config import GOOFISH_COOKIE
from image_ai import ImageAI

log = logging.getLogger(__name__)
image_ai = ImageAI()


class GoofishParser:
    """
    Парсер Goofish (闲鱼) через официальный веб API.
    
    Goofish использует тот же API, что и мобильное приложение:
    https://www.goofish.com / https://h5api.m.taobao.com
    
    Cookie берётся из браузера после входа в аккаунт.
    """

    SEARCH_URL = "https://www.goofish.com/api/search"
    # Альтернативный endpoint (Taobao API, используется мобильным приложением)
    TAOBAO_URL = "https://h5api.m.taobao.com/h5/mtop.taobao.idlefish.search.api/1.0/"

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 12; Pixel 6) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Mobile Safari/537.36"
        ),
        "Referer": "https://www.goofish.com/",
        "Origin":  "https://www.goofish.com",
        "Accept":  "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def _session_get(self) -> aiohttp.ClientSession:
        if not self._session or self._session.closed:
            headers = dict(self.HEADERS)
            if GOOFISH_COOKIE:
                headers["Cookie"] = GOOFISH_COOKIE
            self._session = aiohttp.ClientSession(
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20)
            )
        return self._session

    def _parse_item(self, raw: dict) -> Optional[dict]:
        """Нормализует сырой ответ API в удобный формат"""
        try:
            # Goofish возвращает вложенные данные
            data   = raw.get("data", raw)
            item   = data.get("item", data)
            main   = item.get("main", {})
            info   = main.get("clickParam", {}).get("args", {})

            item_id = (
                str(data.get("itemId", ""))
                or str(item.get("itemId", ""))
                or str(info.get("id", ""))
            )
            if not item_id:
                return None

            # Заголовок
            title = (
                main.get("title", "")
                or data.get("title", "")
                or info.get("title", "")
            )

            # Цена
            price_info = main.get("price", {}) or data.get("price", {}) or {}
            price_str = (
                price_info.get("price", "")
                or price_info.get("standardPrice", "")
                or str(data.get("price", "0"))
            )
            try:
                price = float(str(price_str).replace("¥", "").replace(",", "").strip())
            except Exception:
                price = 0.0

            # Фото
            pics = (
                main.get("picUrl", [])
                or data.get("picUrl", [])
                or []
            )
            if isinstance(pics, str):
                pics = [pics]
            image_url = pics[0] if pics else ""
            if image_url and not image_url.startswith("http"):
                image_url = "https:" + image_url

            # Продавец
            seller_info = main.get("userNick", "") or data.get("userNick", "")

            # Дата
            date_ts = data.get("soldTime") or data.get("gmtModified") or ""
            date_str = ""
            if date_ts:
                try:
                    from datetime import datetime
                    ts = int(str(date_ts)[:10])
                    date_str = datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")
                except Exception:
                    pass

            # Ссылка
            url = (
                f"https://www.goofish.com/item?id={item_id}"
            )

            return {
                "id":          item_id,
                "title":       title,
                "price":       price,
                "image_url":   image_url,
                "seller":      seller_info,
                "date":        date_str,
                "url":         url,
                "description": data.get("desc", ""),
            }
        except Exception as e:
            log.debug(f"parse_item error: {e}")
            return None

    async def search(
        self,
        query: str,
        price_min: int = 0,
        price_max: int = 0,
        page: int = 1,
        sort: str = "time",   # time | price
    ) -> list[dict]:
        """Поиск по одному запросу"""
        session = await self._session_get()

        params = {
            "q":        query,
            "page":     page,
            "sortType": "time" if sort == "time" else "price_asc",
        }
        if price_min > 0:
            params["priceStart"] = price_min
        if price_max > 0:
            params["priceEnd"] = price_max

        try:
            async with session.get(self.SEARCH_URL, params=params) as resp:
                if resp.status != 200:
                    log.warning(f"Goofish search status {resp.status} for '{query}'")
                    # Пробуем запасной метод
                    return await self._search_taobao_api(query, price_min, price_max)
                
                data = await resp.json(content_type=None)
                
                # Разные структуры ответа
                items = (
                    data.get("data", {}).get("items", [])
                    or data.get("items", [])
                    or data.get("result", {}).get("items", [])
                    or []
                )
                
                result = []
                for raw in items:
                    ad = self._parse_item(raw)
                    if ad:
                        result.append(ad)
                return result

        except Exception as e:
            log.error(f"search error '{query}': {e}")
            return await self._search_taobao_api(query, price_min, price_max)

    async def _search_taobao_api(
        self, query: str, price_min: int = 0, price_max: int = 0
    ) -> list[dict]:
        """
        Запасной метод — Taobao H5 API (используется мобильным приложением Xianyu/Goofish).
        Требует валидный cookie с _m_h5_tk токеном.
        """
        session = await self._session_get()
        t = str(int(time.time() * 1000))
        
        # Параметры запроса
        app_key = "12574478"
        data_obj = {
            "keyword": query,
            "sortType": "1",  # 1=по дате, 2=по цене
            "pageNumber": 1,
            "priceStart": price_min if price_min else "",
            "priceEnd":   price_max if price_max else "",
        }
        data_str = json.dumps(data_obj, ensure_ascii=False, separators=(',', ':'))

        # Подпись (token из cookie _m_h5_tk)
        token = ""
        if GOOFISH_COOKIE and "_m_h5_tk" in GOOFISH_COOKIE:
            for part in GOOFISH_COOKIE.split(";"):
                if "_m_h5_tk=" in part:
                    token = part.split("=")[1].split("_")[0].strip()
                    break

        sign_str = f"{token}&{t}&{app_key}&{data_str}"
        sign = hashlib.md5(sign_str.encode()).hexdigest()

        params = {
            "jsv":    "2.7.2",
            "appKey": app_key,
            "t":      t,
            "sign":   sign,
            "api":    "mtop.taobao.idlefish.search.api",
            "v":      "1.0",
            "data":   data_str,
        }

        try:
            async with session.get(self.TAOBAO_URL, params=params) as resp:
                raw = await resp.json(content_type=None)
                items = (
                    raw.get("data", {}).get("items", [])
                    or raw.get("data", {}).get("resultList", [])
                    or []
                )
                result = []
                for item in items:
                    ad = self._parse_item(item)
                    if ad:
                        result.append(ad)
                return result
        except Exception as e:
            log.error(f"Taobao API error: {e}")
            return []

    async def search_all_tags(
        self,
        tags: list[str],
        price_min: int = 0,
        price_max: int = 0,
    ) -> list[dict]:
        """
        Поиск по всем тегам одновременно.
        Результаты объединяются, дубликаты удаляются, сортируются по дате.
        """
        all_ads: dict[str, dict] = {}

        for tag in tags:
            ads = await self.search(tag, price_min=price_min, price_max=price_max)
            for ad in ads:
                if ad["id"] not in all_ads:
                    all_ads[ad["id"]] = ad
            await asyncio.sleep(1.0)  # пауза между запросами

        # Сортировка по дате (новые первыми)
        result = list(all_ads.values())
        result.sort(key=lambda x: x.get("date", ""), reverse=True)
        return result

    async def search_by_embedding(
        self, embedding: list[float], limit: int = 10
    ) -> list[dict]:
        """
        Поиск похожих объявлений по AI-эмбеддингу изображения.
        
        Логика:
        1. Ищем объявления по общим популярным запросам (брендвые вещи)
        2. Для каждого сравниваем фото через CLIP
        3. Возвращаем самые похожие
        """
        # Базовые запросы для получения пула объявлений
        general_queries = ["品牌", "潮牌", "正品", "二手"]
        all_ads: dict[str, dict] = {}
        
        for q in general_queries:
            ads = await self.search(q)
            for ad in ads:
                if ad["id"] not in all_ads and ad.get("image_url"):
                    all_ads[ad["id"]] = ad
            await asyncio.sleep(0.5)

        # Сравниваем фото
        scored = []
        for ad in list(all_ads.values())[:50]:
            sim = await image_ai.compare_url(embedding, ad["image_url"])
            if sim > 0.20:
                ad["similarity"] = sim
                scored.append(ad)

        scored.sort(key=lambda x: x["similarity"], reverse=True)
        return scored[:limit]
