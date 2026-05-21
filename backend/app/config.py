"""Application configuration via Pydantic Settings."""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Shopify
    shopify_shop_name: str = Field(default="demo-store.myshopify.com", alias="SHOPIFY_SHOP_NAME")
    shopify_api_key: str = Field(default="demo_key", alias="SHOPIFY_API_KEY")
    shopify_api_secret: str = Field(default="demo_secret", alias="SHOPIFY_API_SECRET")
    shopify_access_token: str = Field(default="demo_token", alias="SHOPIFY_ACCESS_TOKEN")
    shopify_webhook_secret: str = Field(default="demo_webhook_secret", alias="SHOPIFY_WEBHOOK_SECRET")

    # Facebook Ads
    facebook_app_id: str = Field(default="", alias="FACEBOOK_APP_ID")
    facebook_app_secret: str = Field(default="", alias="FACEBOOK_APP_SECRET")
    facebook_access_token: str = Field(default="", alias="FACEBOOK_ACCESS_TOKEN")
    facebook_ad_account_id: str = Field(default="", alias="FACEBOOK_AD_ACCOUNT_ID")
    facebook_page_id: str = Field(default="", alias="FACEBOOK_PAGE_ID")

    # Ollama / LLM
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="llama3.2", alias="OLLAMA_MODEL")

    # SMS Gateway
    sms_gateway_base_url: str = Field(default="http://localhost:8080", alias="SMS_GATEWAY_BASE_URL")
    sms_gateway_device_id: str = Field(default="demo_device", alias="SMS_GATEWAY_DEVICE_ID")
    # Telegram Notifications (replaces SMS gateway)
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")
    owner_phone_number: str = Field(default="+1234567890", alias="OWNER_PHONE_NUMBER")

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://dropship:dropship@localhost:5432/dropship",
        alias="DATABASE_URL",
    )

    # App
    app_secret_key: str = Field(default="demo_secret_key_change_me", alias="APP_SECRET_KEY")
    app_env: str = Field(default="development", alias="APP_ENV")

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    @property
    def is_demo_mode(self) -> bool:
        """Return True if running in demo mode (default credentials)."""
        return (
            self.shopify_access_token in ("demo_token", "your_admin_api_token")
            or self.shopify_api_key == "your_api_key"
        )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()

