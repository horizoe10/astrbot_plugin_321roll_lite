"""Pure validation of a world's optional economy block; usable by offline pack tools."""
import re
from typing import Any

KEYS = ("currency", "initial", "prices", "sell", "wage", "storyLimit", "autoOutfit", "kitMoney", "shops")
SHOP_KEYS = ("id", "name", "kind", "place", "items", "text")
MAX_SHOPS, MAX_WARES = 12, 30
_KEY = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,100}")


def validate(value: Any, pack: dict[str, Any]) -> None:
    """Raise ValueError when a world's optional 'economy' block is malformed (pure; offline tools use it too)."""
    def require(ok: Any, message: str) -> None:
        if not ok:
            raise ValueError("economy：" + message)

    def integer(key: str, low: int, high: int, default: int) -> None:
        v = value.get(key, default)
        require(type(v) is int and low <= v <= high, f"{key} 是 {low}–{high} 的整数")

    require(isinstance(value, dict) and set(value) <= set(KEYS), "只能包含 " + "、".join(KEYS))
    require(isinstance(value.get("currency"), str) and 1 <= len(value["currency"].strip()) <= 8, "currency 是 1–8 字的货币名")
    integer("initial", 0, 100000, 0)
    integer("sell", 0, 100, 50)
    integer("wage", 0, 10000, 0)
    integer("storyLimit", 1, 100000, 20)
    integer("kitMoney", 0, 100000, 0)
    require(type(value.get("autoOutfit", False)) is bool, "autoOutfit 是 true 或 false")
    items = {i["id"] for i in pack["items"]}
    prices = value.get("prices") or {}
    require(isinstance(prices, dict) and all(k in items and type(v) is int and 1 <= v <= 100000 for k, v in prices.items()),
            "prices 是“物品 id → 1–100000 的价格”")
    shops = value.get("shops") or []
    require(isinstance(shops, list) and len(shops) <= MAX_SHOPS, f"shops 最多 {MAX_SHOPS} 家")
    entries = {e["id"] for e in pack["entries"]}
    seen: set[str] = set()
    for shop in shops:
        require(isinstance(shop, dict) and set(shop) <= set(SHOP_KEYS), "每家店只写 " + "、".join(SHOP_KEYS))
        require(isinstance(shop.get("id"), str) and _KEY.fullmatch(shop["id"]) and shop["id"] not in seen, "店的 id 无效或重复")
        seen.add(shop["id"])
        name = shop.get("name")
        require(isinstance(name, str) and 1 <= len(name.strip()) <= 20, f"店 {shop['id']} 的 name 是 1–20 字")
        require(isinstance(shop.get("kind", ""), str) and len(shop.get("kind", "")) <= 8, f"店“{name}”的 kind 最多 8 字")
        require(shop.get("place") in (None, "") or shop["place"] in entries, f"店“{name}”的 place 要写设定条目的 id，或留空表示随处可买")
        wares = shop.get("items")
        require(isinstance(wares, list) and 1 <= len(wares) <= MAX_WARES and len(set(wares)) == len(wares)
                and all(i in prices for i in wares), f"店“{name}”的 items 是 1–{MAX_WARES} 个已定价的物品 id")
        require(isinstance(shop.get("text", ""), str) and len(shop.get("text", "")) <= 80, f"店“{name}”的 text 最多 80 字")
    for origin in (pack.get("creation") or {}).get("origins") or []:
        if isinstance(origin, dict) and "money" in origin:
            require(type(origin["money"]) is int and -100000 <= origin["money"] <= 100000,
                    f"出身“{origin.get('name', '')}”的 money 是 -100000–100000 的整数")
