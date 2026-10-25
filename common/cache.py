from enum import Enum


class CacheCategory(Enum):
    OHLCV = "ohlcv"
    MACRO = "macro"
    NEWS = "news"
    SENTIMENT = "sentiment"
    FEAR_GREED = "fear_greed"
    TRENDING = "trending"
    DERIVATIVES = "derivatives"
    FUNDAMENTAL = "fundamental"
    METRICS = "metrics"
    PROFILE = "profile"
    GENERIC = "generic"
    INDICES = "indices"
    YIELD = "yield"
    COIN_LIST = "coin_list"


class CacheKeyBuilder:
    PREFIX = "cache"

    @staticmethod
    def build(
        category: CacheCategory,
        source: str,
        parts: list[str],
        symbol: str | None = None,
    ) -> str:
        safe_symbol = symbol.lower().replace("/", "_").replace("\\", "") if symbol else "global"
        key_parts = [
            CacheKeyBuilder.PREFIX,
            category.value,
            source.lower(),
            safe_symbol,
        ] + [str(p).lower() for p in parts]
        return ":".join(key_parts)

    @staticmethod
    def ohlcv_key(source: str, symbol: str, timeframe: str) -> str:
        return CacheKeyBuilder.build(CacheCategory.OHLCV, source, [timeframe], symbol)

    @staticmethod
    def generic_key(source: str, identifier: str, symbol: str | None = None) -> str:
        return CacheKeyBuilder.build(CacheCategory.GENERIC, source, [identifier], symbol)

    @staticmethod
    def derivatives_key(source: str, metric: str, symbol: str) -> str:
        return CacheKeyBuilder.build(CacheCategory.DERIVATIVES, source, [metric], symbol)

    @staticmethod
    def macro_key(source: str, identifier: str) -> str:
        return CacheKeyBuilder.build(CacheCategory.MACRO, source, [identifier])

    @staticmethod
    def indices_key(source: str, identifier: str) -> str:
        return CacheKeyBuilder.build(CacheCategory.INDICES, source, [identifier])
