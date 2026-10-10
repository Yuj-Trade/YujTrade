import asyncio
from unittest.mock import AsyncMock, MagicMock

from modeling.model_manager import ModelManager


def test_predict_without_artifact_never_trains(tmp_path):
    data_provider = MagicMock(name="ModelDataProvider")
    data_provider.get_data_for_model = AsyncMock(return_value=None)
    manager = ModelManager(
        data_provider,
        model_path=str(tmp_path / "models"),
        auto_train_on_predict=False,
    )
    manager.train_and_save_model = AsyncMock(wraps=manager.train_and_save_model)

    result = asyncio.run(
        manager.predict_with_confidence("xgboost", "BTC/USDT", "1h")
    )

    assert result is None
    manager.train_and_save_model.assert_not_called()


def test_predict_with_autotrain_disabled_keeps_config_default(tmp_path):
    data_provider = MagicMock(name="ModelDataProvider")
    manager = ModelManager(data_provider, model_path=str(tmp_path / "models"))
    assert manager.auto_train_on_predict is False
