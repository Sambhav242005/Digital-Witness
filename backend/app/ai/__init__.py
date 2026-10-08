"""Model boundaries. Importing these modules never downloads weights."""

class ModelUnavailable(RuntimeError):
    """A real model cannot currently perform inference."""
