class TradingBotException(Exception):
    pass


class NetworkError(TradingBotException):
    pass


class DataError(TradingBotException):
    pass


class ValidationError(DataError):
    pass


class APIRateLimitError(NetworkError):
    pass


class InvalidSymbolError(ValidationError):
    pass


class InsufficientDataError(DataError):
    pass


class ModelError(TradingBotException):
    pass


class ConfigurationError(TradingBotException):
    pass


class IndicatorError(DataError):
    pass


class ObjectClosedError(TradingBotException):
    pass


class UpstreamUnavailableError(TradingBotException):
    pass


class ArtifactIntegrityError(ModelError):
    pass
