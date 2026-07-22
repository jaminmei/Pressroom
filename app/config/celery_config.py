from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class CelerySettings(BaseSettings):
    # Local imports and unit tests use in-memory transports. Compose always
    # overrides both values with authenticated Redis URLs.
    celery_broker_url: str = "memory://"
    celery_result_backend: str = "cache+memory://"
    celery_task_serializer: str = "json"
    celery_result_serializer: str = "json"
    celery_accept_content: str = "json"
    celery_timezone: str = "UTC"
    celery_enable_utc: bool = True
    celery_task_acks_late: bool = True
    celery_task_reject_on_worker_lost: bool = True
    celery_worker_prefetch_multiplier: int = 1

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend

    @property
    def task_serializer(self) -> str:
        return self.celery_task_serializer

    @property
    def result_serializer(self) -> str:
        return self.celery_result_serializer

    @property
    def accept_content(self) -> tuple[str, ...]:
        values = tuple(
            token.strip() for token in self.celery_accept_content.split(",") if token.strip()
        )
        return values if values else ("json",)

    @property
    def timezone(self) -> str:
        return self.celery_timezone

    @property
    def enable_utc(self) -> bool:
        return self.celery_enable_utc


@lru_cache
def get_celery_settings() -> CelerySettings:
    return CelerySettings()
