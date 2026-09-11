"""Energy sampling.

Per-request energy attribution uses the power draw during the request:

1. **NVML mode** - if ``pynvml`` is installed and an NVIDIA GPU is present,
   the instantaneous GPU power draw (watts) is sampled right before and
   after the request and averaged. This is the honest number.
2. **Static mode** - otherwise the configured ``load_watts`` is assumed for
   the duration of the request (documented approximation; the idle draw is
   *not* charged to a request, since it would run anyway).

Both modes go through :class:`PowerSampler` so the rest of the code never
cares which one is active.
"""

from __future__ import annotations

from typing import Optional


class PowerSampler:
    """Samples GPU power draw, falling back to a configured static value."""

    def __init__(self, load_watts: float = 300.0, idle_watts: float = 20.0):
        self.load_watts = float(load_watts)
        self.idle_watts = float(idle_watts)
        self._nvml = None
        self._nvml_handle = None
        try:
            import pynvml  # type: ignore

            pynvml.nvmlInit()
            self._nvml = pynvml
            index = pynvml.nvmlDeviceGetCount()
            if index > 0:
                self._nvml_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        except Exception:  # noqa: BLE001 - any failure => static mode
            self._nvml = None
            self._nvml_handle = None

    @property
    def mode(self) -> str:
        return "nvml" if self._nvml_handle is not None else "static"

    def sample_watts(self) -> float:
        """Current GPU draw in watts (or the static load assumption)."""
        if self._nvml_handle is not None:
            try:
                return float(self._nvml.nvmlDeviceGetPowerUsage(self._nvml_handle)) / 1000.0
            except Exception:  # noqa: BLE001
                pass
        return self.load_watts

    def request_watts(self, before: Optional[float] = None, after: Optional[float] = None) -> float:
        """Average draw attributed to one request."""
        if before is None:
            before = self.sample_watts()
        if after is None:
            after = self.sample_watts()
        return (before + after) / 2.0

    def kwh_for(self, seconds: float, watts: float) -> float:
        """kWh consumed by ``seconds`` at ``watts``."""
        if seconds <= 0 or watts <= 0:
            return 0.0
        return watts * seconds / 3_600_000.0

    def gpu_name(self) -> Optional[str]:
        if self._nvml_handle is not None:
            try:
                return self._nvml.nvmlDeviceGetName(self._nvml_handle)
            except Exception:  # noqa: BLE001
                return None
        return None

    def close(self) -> None:
        if self._nvml is not None:
            try:
                self._nvml.nvmlShutdown()
            except Exception:  # noqa: BLE001
                pass
        self._nvml = None
        self._nvml_handle = None
