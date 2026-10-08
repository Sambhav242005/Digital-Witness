"""Model boundaries, with sanitized failures."""
class ModelUnavailable(RuntimeError):
    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details or {}
