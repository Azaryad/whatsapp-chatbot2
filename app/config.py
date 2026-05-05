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
    # Public base URL of THIS server — used in HMAC-signed approval links
    approval_base_url: str = "http://localhost:8000"
    # Long random secret used to sign approval URLs. Generate with secrets.token_urlsafe(32)
    approval_link_secret: str = ""
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
        # Time allowed to click the approval link after saying yes on WhatsApp
        return self.fast_timeout_seconds if self.fast_timeout_seconds > 0 else 3600  # 1h

    @property
    def approval_link_ttl_seconds(self) -> int:
        # How long a signed approval URL stays valid. Covers batch + approval timeout windows.
        if self.fast_timeout_seconds > 0:
            return self.fast_timeout_seconds * 2
        return self.driver_offer_timeout_seconds + self.approval_timeout_seconds + 1800  # +30min buffer

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
