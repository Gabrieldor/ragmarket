from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./market_intel.db"
    poll_interval_seconds: int = 600
    raw_retention_days: int = 30
    server_type: str = "FREYA"
    store_type: str = "BUY"
    headless: bool = True
    browser_timeout_ms: int = 30_000

    # Throttling, mirrors the original scraper's rule_delay -- inserted between each item's
    # scrape (item_delay_seconds) and between each location-modal click within an item
    # (location_click_delay_seconds), to avoid hammering the site and triggering HTTP 429s.
    item_delay_seconds: float = 8.0
    location_click_delay_seconds: float = 2.5

    # How long a vending listing stays up in-game before it's expected to expire on its
    # own, regardless of whether everything sold. Used by "my sales" tracking to decide
    # whether a disappeared listing was a likely sellout (well before this window) or a
    # natural expiry (at/after it).
    my_listing_window_hours: float = 24.0


settings = Settings()
