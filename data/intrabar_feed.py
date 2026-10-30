class NullIntrabarPriceFeed:
    async def last_price(self, symbol: str) -> float | None:
        return None
