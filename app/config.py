from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str
    wa_phone_number_id: str
    wa_access_token: str
    wa_verify_token: str
    google_maps_api_key: str
    supplier_api_base: str = "https://ridecontrolapi.tlv-transfers.com/rest/default/supplier"
    supplier_api_token: str = ""
    michel_phone: str = "0526084230"
    app_deeplink_base: str = "https://example.com/trip"
    # Ride Control web URL for supplier approval links — update when confirmed
    ride_control_base_url: str = "https://ridecontrol.tlv-transfers.com/booking"
    rc_callback_token: str = ""
    database_url: str = "sqlite+aiosqlite:///./dispatch.db"
    fast_timeout_seconds: int = 0

    @property
    def driver_offer_timeout_seconds(self) -> int:
        return self.fast_timeout_seconds if self.fast_timeout_seconds > 0 else 3600  # 1h

    @property
    def supplier_offer_timeout_seconds(self) -> int:
        return self.fast_timeout_seconds if self.fast_timeout_seconds > 0 else 21600  # 6h

    @property
    def approval_timeout_seconds(self) -> int:
        # Time allowed to click the Ride Control link after saying yes on WhatsApp
        return self.fast_timeout_seconds if self.fast_timeout_seconds > 0 else 3600  # 1h

    def ride_control_link(self, booking_id: str) -> str:
        return f"{self.ride_control_base_url}/{booking_id}"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
