"""Bounded request-free cooldown; never retain SDK payloads."""
import math
import time
from . import ModelUnavailable

class ProviderCooldown:
    @property
    def available(self):
        return getattr(self, '_loaded', False) and not getattr(self, '_needs_reload', False) and time.monotonic() >= getattr(self, '_retry_at', 0)
    @available.setter
    def available(self, value):
        self._loaded = value
        self._needs_reload = False
        if not value:
            self._retry_at = 0
    @property
    def reload_due(self):
        return getattr(self, '_needs_reload', False) and time.monotonic() >= getattr(self, '_retry_at', 0)
    def unavailable(self, fallback='Model unavailable'):
        remaining = max(0, math.ceil(getattr(self, '_retry_at', 0)-time.monotonic()))
        if remaining:
            return ModelUnavailable(self.error, {'provider_status': self._provider_status, 'retry_after_sec': remaining})
        return ModelUnavailable(fallback)
    def provider_failure(self, exc, label):
        status = getattr(exc, 'code', None) or getattr(exc, 'status_code', None)
        status = status if isinstance(status, int) and 400 <= status <= 599 else None
        details = {'provider_status': status} if status else {}
        if status == 429 or status in (500, 502, 503, 504):
            delay = 60 if status == 429 else 15
            headers = getattr(getattr(exc, 'response', None), 'headers', {}) or {}
            try:
                hint = float(headers.get('Retry-After', headers.get('retry-after', delay)))
                if math.isfinite(hint):
                    delay = max(1, min(300, math.ceil(hint)))
            except (TypeError, ValueError):
                pass
            self._retry_at = time.monotonic()+delay
            self._provider_status = status
            provider = getattr(self, 'provider_name', 'AI provider')
            self.error = (f'{provider} quota or rate limit reached; retry after the cooldown.' if status == 429 else f'{provider} is temporarily unavailable; retry after the cooldown.')
            details['retry_after_sec'] = delay
            return ModelUnavailable(self.error, details)
        return ModelUnavailable(f'{label} failed; check credentials, model access, and network.', details)

def failure_details(adapter):
    return adapter.unavailable().details if hasattr(adapter, 'unavailable') else {}
