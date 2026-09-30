"""P1 source fixes — applied via script because git-checked-out sources are CRLF
and the edit tool cannot match them. Each replacement is asserted to occur
exactly once. Line-ending style of each file is preserved."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def apply(path: str, replacements: list):
    p = ROOT / path
    raw = p.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")
    for i, (old, new) in enumerate(replacements):
        count = text.count(old)
        if count != 1:
            print(f"FAIL {path} #{i}: found {count} occurrences (expected 1)")
            print("---- search snippet head ----")
            print(old[:200])
            sys.exit(1)
        text = text.replace(old, new)
    if crlf:
        text = text.replace("\n", "\r\n")
    p.write_bytes(text.encode("utf-8"))
    print(f"OK {path}: {len(replacements)} replacement(s)")


# ── 1) data/data_provider.py — inverted has_gaps contract (found by P1 test) ──

apply(
    "data/data_provider.py",
    [
        (
            """        try:
            no_gaps, _ = self.data_quality_checker.detect_data_gaps(df)
            if no_gaps is False:
                score -= 30.0
        except ValueError:
            return 0.0
""",
            """        # قرارداد detect_data_gaps (عنصر اول) «has_gaps» است — همان
        #‌گونه که calculate_overall_quality_score آن را مصرف می‌کند. قبلاً
        # برعکس خوانده می‌شد: داده بدون گپ -۳۰ می‌گرفت و داده گپ‌دار
        # جریمه نمی‌شد (Regression P1 — تست‌های فاز ۸ آن را آشکار کردند).
        try:
            has_gaps, _ = self.data_quality_checker.detect_data_gaps(df)
            if has_gaps:
                score -= 30.0
        except ValueError:
            return 0.0
""",
        ),
    ],
)

# ── 2) common/utils.py — detect_market_regime UnboundLocalError (P1/Phase 12) ──

apply(
    "common/utils.py",
    [
        (
            """    try:
        from ..analysis.market_analyzer import MarketConditionAnalyzer

        analyzer = MarketConditionAnalyzer()
        hurst = analyzer._calculate_hurst_exponent(recent_data["close"])

        if hurst:
""",
            """    # Regression (P1/فاز ۱۲): import نسبی «..» از ماژول top-level همیشه
    # ImportError می‌داد → except خام آن را می‌خورد → hurst هرگز تعریف
    # نمی‌شد → UnboundLocalError در سطر return، یعنی crash مسیر زنده
    # SignalGenerator.generate_signal. import مطلق + مقداردهی اولیه
    # hurst=None؛ fallback رفتاری بدون تغییر می‌ماند.
    hurst = None
    try:
        from analysis.market_analyzer import MarketConditionAnalyzer

        analyzer = MarketConditionAnalyzer()
        hurst = analyzer._calculate_hurst_exponent(recent_data["close"])

        if hurst:
""",
        ),
        (
            """        else:
            trend_persistence = "unknown"
    except:
        trend_persistence = "unknown"
""",
            """        else:
            trend_persistence = "unknown"
    except Exception:
        trend_persistence = "unknown"
        hurst = None
""",
        ),
    ],
)

# ── 3) modeling/model_manager.py — train_model closing the just-trained model ──

apply(
    "modeling/model_manager.py",
    [
        (
            """                async with self._lock:
                    key = f"{model_type}-{symbol}-{timeframe}"
                    # Ensure the newly trained model is in the cache
                    if key in self._cache:
                        self._cache[key].cleanup()
                    self._cache[key] = model
""",
            """                async with self._lock:
                    key = f"{model_type}-{symbol}-{timeframe}"
                    # Ensure the newly trained model is in the cache.
                    # Regression (P1): وقتی get_model همان نمونه کش‌شده را
                    # برگرداند، cleanup نمونه‌ی کش یعنی بستن مدلی که همین
                    # الان fit شد و گذاشتن نسخه بسته در cache (وزن‌های
                    # آموزش‌دیده دور ریخته می‌شد). فقط نمونه متفاوت
                    # جایگزین/بسته می‌شود.
                    existing = self._cache.get(key)
                    if existing is not None and existing is not model:
                        existing.cleanup()
                    self._cache[key] = model
""",
        ),
    ],
)

print("ALL SOURCE FIXES APPLIED")
