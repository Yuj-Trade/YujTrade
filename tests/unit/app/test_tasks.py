"""
P1 Tests for app/tasks.py — gap 32 (CONNECTED).

Gap 32 resolution: run_full_analysis_task / run_quick_scan_task now deliver
through deliver_task_signals(bot_token, chat_id, signals, summary) — the
chat_id that used to be log-only is consumed by the delivery path.
Static checks lock that main.py / app/telegram_bot.py still never import
app.tasks (the periodic path stays with run_scheduled_analysis).
"""

import ast
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks import (
    TaskServiceContainer,
    deliver_task_signals,
    run_full_analysis_task,
    run_quick_scan_task,
)
from app.telegram_bot import TelegramBotHandler

ROOT = Path(__file__).resolve().parents[3]

MAIN_PY = "main.py"
TELEGRAM_BOT_PY = "app/telegram_bot.py"
TASKS_PY = "app/tasks.py"


def _parse(rel_path: str) -> ast.Module:
    """Parse a project source file into an AST (no import, no side effects)."""
    return ast.parse((ROOT / rel_path).read_text(encoding="utf-8"), filename=rel_path)


def _imports_module(tree: ast.Module, target: str) -> bool:
    """True if the tree contains an import of `target` (e.g. "app.tasks"),
    including `from app import tasks` and relative `from . import tasks`."""
    top, _, rest = target.partition(".")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == target or alias.name.startswith(target + "."):
                    return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == target or module.startswith(target + "."):
                return True
            if not node.level and module == top and any(
                alias.name == rest for alias in node.names if alias.name
            ):
                return True
            if node.level:  # relative: `from . import tasks` / `from .tasks import x`
                if module == rest or any(
                    alias.name == rest for alias in node.names if alias.name
                ):
                    return True
    return False


def _make_mock_container(signals, last_errors: int = 0) -> MagicMock:
    """A TaskServiceContainer stand-in whose trading_service is fully mocked."""
    container = MagicMock(name="TaskServiceContainerMock")
    container.trading_service = MagicMock(name="TradingServiceMock")
    container.trading_service.run_analysis_for_all_symbols = AsyncMock(
        return_value=list(signals)
    )
    container.trading_service.run_quick_analysis = AsyncMock(return_value=list(signals))
    container.trading_service.last_errors = last_errors
    return container


@pytest.fixture(autouse=True)
def reset_container_singleton():
    """هر تست singleton و lock تازه می‌گیرد — قفل class-level به event loop
    تست قبلی bind می‌ماند (پرهیز از RuntimeError «different event loop»)."""
    saved_instance = TaskServiceContainer._instance
    saved_lock = TaskServiceContainer._lock
    TaskServiceContainer._instance = None
    TaskServiceContainer._lock = asyncio.Lock()
    yield
    TaskServiceContainer._instance = saved_instance
    TaskServiceContainer._lock = saved_lock


@pytest.fixture
def deliver_spy():
    """Spy روی مسیر تحویل tasks — بدون ساخت Bot واقعی."""
    with patch(
        "app.tasks.deliver_task_signals", new_callable=AsyncMock
    ) as spy_deliver:
        spy_deliver.return_value = 1
        yield spy_deliver


class TestTaskServiceContainer:
    """Container lifecycle: direct init forbidden, singleton, composition root."""

    def test_direct_init_raises_runtime_error(self):
        with pytest.raises(RuntimeError, match=r"Call instance\(\) instead"):
            TaskServiceContainer()

    @pytest.mark.asyncio
    async def test_instance_returns_same_singleton(self):
        """instance() یکتا است — دو فراخوانی، یک شیء (قاعده ۱۸: همان Composition
        Root اصلی، بدون graph موازی)."""
        fake_stack = (MagicMock(), MagicMock(), MagicMock(), MagicMock())
        with patch(
            "services.trading_service.create_trading_stack",
            new=AsyncMock(return_value=fake_stack),
        ):
            first = await TaskServiceContainer.instance()
            second = await TaskServiceContainer.instance()

        assert first is second
        assert TaskServiceContainer._instance is first
        assert first.trading_service is fake_stack[3]

    @pytest.mark.asyncio
    async def test_initialize_uses_shared_composition_root(self):
        """_initialize باید create_trading_stack را با ConfigManager خودش صدا
        بزند و ۴ مؤلفه را به همان ترتیب composition root بگیرد."""
        inst = TaskServiceContainer.__new__(TaskServiceContainer)
        cm, rm, provider, ts = MagicMock(), MagicMock(), MagicMock(), MagicMock()
        # ConfigManager و BackgroundTaskManager هم باید patch شوند — وگرنه
        # _initialize یک ConfigManager واقعی می‌سازد و create_trading_stack با
        # آن (نه با mock) صدا زده می‌شود.
        with patch("app.tasks.SecretsManager") as mock_secrets, patch(
            "app.tasks.ConfigManager", return_value=cm
        ), patch("app.tasks.BackgroundTaskManager"), patch(
            "services.trading_service.create_trading_stack",
            new=AsyncMock(return_value=(cm, rm, provider, ts)),
        ) as mock_stack_fn:
            mock_secrets.TELEGRAM_BOT_TOKEN = "fake_token:fake"
            await inst._initialize()

        mock_stack_fn.assert_awaited_once_with(cm)
        assert inst.config_manager is cm
        assert inst.resource_manager is rm
        assert inst.market_data_provider is provider
        assert inst.trading_service is ts

    @pytest.mark.asyncio
    async def test_initialize_missing_token_raises_value_error(self):
        inst = TaskServiceContainer.__new__(TaskServiceContainer)
        with patch("app.tasks.SecretsManager") as mock_secrets:
            mock_secrets.TELEGRAM_BOT_TOKEN = ""
            with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN is not configured"):
                await inst._initialize()

    @pytest.mark.asyncio
    async def test_cleanup_gathers_all_components(self):
        inst = TaskServiceContainer.__new__(TaskServiceContainer)
        inst.background_tasks = MagicMock()
        inst.background_tasks.cancel_all = AsyncMock()
        inst.trading_service = MagicMock()
        inst.trading_service.cleanup = AsyncMock()
        inst.market_data_provider = MagicMock()
        inst.market_data_provider.close = AsyncMock()
        inst.resource_manager = MagicMock()
        inst.resource_manager.cleanup = AsyncMock()

        await inst.cleanup()

        inst.background_tasks.cancel_all.assert_awaited_once()
        inst.trading_service.cleanup.assert_awaited_once()
        inst.market_data_provider.close.assert_awaited_once()
        inst.resource_manager.cleanup.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cleanup_tolerates_missing_components(self):
        """background_tasks فقط None-check است (نه hasattr)؛ بقیه با hasattr
        محافظت می‌شوند — None برای background_tasks کافی است."""
        inst = TaskServiceContainer.__new__(TaskServiceContainer)
        inst.background_tasks = None
        await inst.cleanup()  # باید بدون خطا کامل شود


class TestTaskDeliveryGap32Connected:
    """قاعده ۳۲ (وصل شد): سیگنال تولیدشده به chat_id تحویل داده می‌شود."""

    SIGNALS = [
        {"symbol": "BTC/USDT", "timeframe": "1h", "signal_type": "BUY"},
        {"symbol": "ETH/USDT", "timeframe": "1d", "signal_type": "SELL"},
    ]

    @pytest.mark.asyncio
    async def test_gap32_full_analysis_delivers_to_chat_id(self, deliver_spy):
        container = _make_mock_container(self.SIGNALS, last_errors=0)
        container.bot_token = "fake_token:fake"
        with patch.object(
            TaskServiceContainer, "instance", new=AsyncMock(return_value=container)
        ):
            result = await run_full_analysis_task(chat_id=123, message_id=456)

        # سیگنال تولید شده (TradingService صدا زده شده)
        container.trading_service.run_analysis_for_all_symbols.assert_awaited_once()

        # قاعده ۳۲ (وصل شد): تحویل با همان chat_id انجام شده است
        deliver_spy.assert_awaited_once()
        call = deliver_spy.await_args
        assert call.args[0] == "fake_token:fake"
        assert call.args[1] == 123
        assert list(call.args[2]) == self.SIGNALS
        assert result == self.SIGNALS

    @pytest.mark.asyncio
    async def test_gap32_quick_scan_delivers_to_chat_id(self, deliver_spy):
        container = _make_mock_container(self.SIGNALS, last_errors=0)
        container.bot_token = "fake_token:fake"
        with patch.object(
            TaskServiceContainer, "instance", new=AsyncMock(return_value=container)
        ):
            result = await run_quick_scan_task(chat_id=789, message_id=101)

        container.trading_service.run_quick_analysis.assert_awaited_once()

        deliver_spy.assert_awaited_once()
        call = deliver_spy.await_args
        assert call.args[1] == 789
        assert result == self.SIGNALS

    @pytest.mark.asyncio
    async def test_gap32_analysis_failure_swallowed(self, deliver_spy):
        """هر Exception ای در task swallow می‌شود (try/except کامل) و چیزی
        تحویل داده نمی‌شود."""
        container = _make_mock_container([])
        container.trading_service.run_analysis_for_all_symbols = AsyncMock(
            side_effect=RuntimeError("pipeline exploded")
        )
        with patch.object(
            TaskServiceContainer, "instance", new=AsyncMock(return_value=container)
        ):
            # نباید exception به بیرون نشت کند
            result = await run_full_analysis_task(chat_id=1, message_id=2)

        assert result == []
        deliver_spy.assert_not_called()

    @pytest.mark.asyncio
    async def test_gap32_instance_failure_swallowed(self, deliver_spy):
        with patch.object(
            TaskServiceContainer,
            "instance",
            new=AsyncMock(side_effect=RuntimeError("init failed")),
        ):
            result = await run_quick_scan_task(chat_id=1, message_id=2)  # بدون raise

        assert result == []
        deliver_spy.assert_not_called()

    @pytest.mark.asyncio
    async def test_gap32_delivery_failure_swallowed(self, deliver_spy):
        """خطای تحویل هم کل task را نمی‌شکند — [] برمی‌گردد."""
        container = _make_mock_container(self.SIGNALS)
        container.bot_token = "fake_token:fake"
        deliver_spy.side_effect = RuntimeError("telegram down")
        with patch.object(
            TaskServiceContainer, "instance", new=AsyncMock(return_value=container)
        ):
            result = await run_full_analysis_task(chat_id=1, message_id=2)

        assert result == []


class TestStaticImportGraph32:
    """قاعده ۳۲ (بخش a): مسیر دوره‌ای از bot_handler.run_scheduled_analysis
    می‌گذرد؛ app.tasks هرگز از main.py یا app/telegram_bot.py import نمی‌شود."""

    def test_main_never_imports_app_tasks(self):
        tree = _parse(MAIN_PY)
        assert not _imports_module(tree, "app.tasks"), (
            "Gap 32: main.py must not import app.tasks — the periodic path "
            "belongs to TelegramBotHandler.run_scheduled_analysis."
        )

    def test_telegram_bot_never_imports_app_tasks(self):
        tree = _parse(TELEGRAM_BOT_PY)
        assert not _imports_module(tree, "app.tasks"), (
            "Gap 32: app/telegram_bot.py must not import app.tasks."
        )

    def test_periodic_path_goes_through_run_scheduled_analysis(self):
        main_tree = _parse(MAIN_PY)
        assert any(
            isinstance(node, ast.Attribute) and node.attr == "run_scheduled_analysis"
            for node in ast.walk(main_tree)
        ), "main.py should call bot_handler.run_scheduled_analysis for the periodic path"

        bot_tree = _parse(TELEGRAM_BOT_PY)
        assert any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "send_signals_to_telegram"
            for node in ast.walk(bot_tree)
        ), "TelegramBotHandler must define send_signals_to_telegram (the real delivery path)"

    def test_tasks_module_wires_delivery(self):
        """قفل ماژولی قاعده ۳۲ (وصل شد): app/tasks.py مسیر تحویل
        deliver_task_signals را تعریف می‌کند و هر دو task آن را صدا می‌زنند —
        chat_id دیگر فقط لاگ نمی‌شود."""
        tree = _parse(TASKS_PY)
        func_names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert "deliver_task_signals" in func_names

        for task_name in ("run_full_analysis_task", "run_quick_scan_task"):
            task_node = next(
                node
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == task_name
            )
            called = {
                node.func.id
                for node in ast.walk(task_node)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
            }
            assert "deliver_task_signals" in called, (
                f"{task_name} must call deliver_task_signals (gap 32 wiring)"
            )
