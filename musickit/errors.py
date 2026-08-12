"""Error types for musickit."""


class MusicKitError(Exception):
    """Raised for any recoverable failure in a musickit operation.

    All public functions raise this (and only this) on failure so callers
    -- including the CLI and the GUI -- have a single exception to catch and
    can present a clean message instead of a raw traceback.
    """
