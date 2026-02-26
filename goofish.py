"""
goofish.py — парсер Goofish (闲鱼)
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

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.goofish.com/",
        "Origin": "https://www.goofish.com",
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
        try:
            item_id = str(
                raw.get("itemId") or
                raw.get("id") or
                raw.get("data", {}).get("itemId", "")
            )
            if not item_id:
                return None

            title = (
                raw.get("title") or
                raw.get("data", {}).get("title") or
                raw.get("name", "")
            )

            price = 0.0
            for key in ["price", "soldPrice", "currentPrice"]:
                val = raw.get(key) or raw.get("data", {}).get(key)
                if val:
                    try:
                        price = float(str(val).replace("¥", "").replace(",", "").strip())
                        break
                    except Exception:
                        pass

            image_url = ""
            for key in ["picUrl", "img", "image", "pic"]:
                val = raw.get(key) or raw.get("data", {}).get(key)
                if val:
                    if isinstance(val, list):
                        val = val[0]
                    image_url = str(val)
                    if not image_url.startswith("http"):
                        image_url = "https:" + image_url
                    break

            seller = str(
                raw.get("userNick") or
                raw.get("seller") or
                raw.get("data", {}).get("userNick", "")
            )

            date_str = ""
            for key in ["gmtModified", "soldTime", "time", "createTime"]:
                ts = raw.get(key) or raw.get("data", {}).get(key)
                if ts:
                    try:
                        from datetime import datetime
                        t = int(str(ts)[:10])
                        date_str = datetime.fromtimestamp(t).strftime("%d.%m.%Y %H:%M")
                        break
                    except Exception:
                        pass

            url = f"https://www.goofish.com/item?id={item_id}"

            return {
                "id": item_id,
                "title": title,
                "price": price,
                "image_url": image_url,
                "seller": seller,
                "date": date_str,
                "url": url,
                "description": raw.get("desc") or raw.get("data", {}).get("desc", ""),
            }
        except Exception as e:
            log.debug(f"parse_item error: {e}")
            return None

    async def search(self, query: str, price_min: int = 0,
                     price_max: int = 0) -> list[dict]:
        result = await self._search_v1(query, price_min, price_max)
        if result:
            return result
        result = await self._search_taobao(query, price_min, price_max)
        if result:
            return result
        return await self._search_v3(query, price_min, price_max)

    async def _search_v1(self, query: str, price_min: int,
                         price_max: int) -> list[dict]:
        session = await self._session_get()
        params = {
            "q": query,
            "isp": 1,
            "oss": 1,
            "from": "pc",
        }
        if price_min:
            params["priceLow"] = price_min
        if price_max:
            params["priceHigh"] = price_max

        endpoints = [
            "https://www.goofish.com/search",
            "https://www.goofish.com/api/search",
        ]

        for url in endpoints:
            try:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        continue
                    text = await resp.text()
                    if not text or not text.strip().startswith("{"):
                        continue
                    data = json.loads(text)
                    items = (
                        data.get("data", {}).get("items", []) or
                        data.get("items", []) or []
                    )
                    result = [a for a in [self._parse_item(i) for i in items] if a]
                    if result:
                        log.info(f"v1 found {len(result)} for '{query}'")
                        return result
            except Exception as e:
                log.debug(f"v1 error {url}: {e}")
        return []

    async def _search_taobao(self, query: str, price_min: int,
                              price_max: int) -> list[dict]:
        session = await self._session_get()
        t = str(int(time.time() * 1000))
        app_key = "12574478"

        data_obj = {
            "keyword": query,
            "sortType": "1",
            "pageNumber": 1,
            "priceStart": price_min if price_min else "",
            "priceEnd": price_max if price_max else "",
        }
        data_str = json.dumps(data_obj, ensure_ascii=False, separators=(",", ":"))

        token = ""
        if GOOFISH_COOKIE and "_m_h5_tk" in GOOFISH_COOKIE:
            for part in GOOFISH_COOKIE.split(";"):
                part = part.strip()
                if part.startswith("_m_h5_tk="):
                    token = part.split("=", 1)[1].split("_")[0]
                    break

        sign_str = f"{token}&{t}&{app_key}&{data_str}"
        sign = hashlib.md5(sign_str.encode()).hexdigest()

        params = {
            "jsv": "2.7.2",
            "appKey": app_key,
            "t": t,
            "sign": sign,
            "api": "mtop.taobao.idlefish.search.api",
            "v": "1.0",
            "data": data_str,
        }

        try:
            async with session.get(
                "https://h5api.m.taobao.com/h5/mtop.taobao.idlefish.search.api/1.0/",
                params=params
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json(content_type=None)
                items = (
                    data.get("data", {}).get("items", []) or
                    data.get("data", {}).get("resultList", []) or []
                )
                result = [a for a in [self._parse_item(i) for i in items] if a]
                if result:
                    log.info(f"taobao found {len(result)} for '{query}'")
                return result
        except Exception as e:
            log.debug(f"taobao error: {e}")
            return []

    async def _search_v3(self, query: str, price_min: int,
                          price_max: int) -> list[dict]:
        session = await self._session_get()
        try:
            params = {"keyword": query, "page": 1}
            if price_min:
                params["priceMin"] = price_min
            if price_max:
                params["priceMax"] = price_max

            async with session.get(
                "https://api.goofish.com/api/search",
                params=params
            ) as resp:
                if resp.status != 200:
                    return []
                text = await resp.text()
                if not text.strip().startswith("{"):
                    return []
                data = json.loads(text)
                items = data.get("data", {}).get("items", []) or []
                result = [a for a in [self._parse_item(i) for i in items] if a]
                log.info(f"v3 found {len(result)} for '{query}'")
                return result
        except Exception as e:
            log.debug(f"v3 error: {e}")
            return []

    async def search_all_tags(self, tags: list[str], price_min: int = 0,
                               price_max: int = 0) -> list[dict]:
        all_ads: dict[str, dict] = {}
        for tag in tags:
            ads = await self.search(tag, price_min=price_min, price_max=price_max)
            for ad in ads:
                if ad["id"] not in all_ads:
                    all_ads[ad["id"]] = ad
            await asyncio.sleep(1.0)

        result = list(all_ads.values())
        result.sort(key=lambda x: x.get("date", ""), reverse=True)
        return result

    async def search_by_embedding(self, embedding: list[float],
                                   limit: int = 10) -> list[dict]:
        queries = ["品牌", "潮牌", "正品", "二手服装"]
        all_ads: dict[str, dict] = {}

        for q in queries:
            ads = await self.search(q)
            for ad in ads:
                if ad["id"] not in all_ads and ad.get("image_url"):
                    all_ads[ad["id"]] = ad
            await asyncio.sleep(0.5)

        scored = []
        for ad in list(all_ads.values())[:50]:
            sim = await image_ai.compare_url(embedding, ad["image_url"])
            if sim > 0.20:
                ad["similarity"] = sim
                scored.append(ad)

        scored.sort(key=lambda x: x["similarity"], reverse=True)
        return scored[:limit]
