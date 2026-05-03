"""
AppIntegration ABC + in-memory stub.

The real implementation requires the driver app team to expose:
  - Deep-link scheme for opening a specific trip
  - Push pending trip to driver's app view
  - Webhook when driver accepts/declines inside app
  - Cancel pending trip

See docs/app_integration_spec.md for the full spec.
"""
from abc import ABC, abstractmethod
from app.config import settings


class AppIntegration(ABC):
    @abstractmethod
    async def get_trip_link(self, trip_id: int) -> str:
        """Return a deep-link URL that opens the trip in the driver app."""

    @abstractmethod
    async def push_pending_trip(self, trip_id: int, driver_code: str) -> bool:
        """Notify the driver app that a trip is pending for this driver."""

    @abstractmethod
    async def cancel_pending_trip(self, trip_id: int, driver_code: str) -> bool:
        """Remove the pending trip from the driver's app view."""


class StubAppIntegration(AppIntegration):
    """In-memory stub used for tests and until real app endpoints are available."""

    _pending: dict[tuple[int, str], bool] = {}

    async def get_trip_link(self, trip_id: int) -> str:
        return f"{settings.app_deeplink_base}/{trip_id}"

    async def push_pending_trip(self, trip_id: int, driver_code: str) -> bool:
        self._pending[(trip_id, driver_code)] = True
        return True

    async def cancel_pending_trip(self, trip_id: int, driver_code: str) -> bool:
        self._pending.pop((trip_id, driver_code), None)
        return True


# Singleton — swap with real implementation when app team is ready
app_integration: AppIntegration = StubAppIntegration()
