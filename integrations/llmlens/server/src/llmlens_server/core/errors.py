"""Error taxonomy."""


class LLMLensError(Exception):
    """Base for deliberate errors."""


class ConfigError(LLMLensError):
    """Invalid or missing configuration."""


class StorageError(LLMLensError):
    """A storage backend failed or is unreachable."""


class IngestError(LLMLensError):
    """A telemetry payload could not be accepted."""


class AuthError(LLMLensError):
    """Authentication / authorization failure."""
