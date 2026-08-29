class FXScannerError(Exception):
    """Base project exception."""


class ConfigurationError(FXScannerError):
    """Configuration failed validation."""


class DataContractError(FXScannerError):
    """Incoming market data violates a hard contract."""


class MissingOptionalDependency(FXScannerError):
    """Optional runtime dependency is unavailable."""


class CollectorUnavailable(FXScannerError):
    """Configured market-data collector cannot be used."""
