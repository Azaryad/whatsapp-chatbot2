from pydantic_settings import BaseSettings
from typing import Optional


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
    database_url: str = "sqlite+aiosqlite:///./dispatch.db"
    fast_timeout_seconds: int = 0  # 0 = use real 3-hour timeout

    @property
    def offer_timeout_seconds(self) -> int:
        return self.fast_timeout_seconds if self.fast_timeout_seconds > 0 else 10800  # 3 hours

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
