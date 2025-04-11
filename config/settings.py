import os
import logging
from dataclasses import dataclass, field
from typing import List

logger = logging.getLogger(__name__)

@dataclass
class BotConfig:
    token: str
    password: str
    admin_ids: List[int] = field(default_factory=list)

@dataclass
class ApiConfig:
    base_url: str

@dataclass
class Settings:
    bot: BotConfig
    api: ApiConfig

def load_config() -> Settings:
    logger.info("Загрузка конфигурации из переменных окружения...")
    bot_token = os.getenv("BOT_TOKEN")
    admin_ids_str = os.getenv("ADMIN_IDS")
    bot_password = os.getenv("BOT_PASSWORD")
    api_base_url = os.getenv("API_BASE_URL")

    missing_vars = []
    if not bot_token: missing_vars.append("BOT_TOKEN")
    if not admin_ids_str: missing_vars.append("ADMIN_IDS")
    if not bot_password: missing_vars.append("BOT_PASSWORD")
    if not api_base_url: missing_vars.append("API_BASE_URL")

    if missing_vars:
        error_message = f"КРИТИЧЕСКАЯ ОШИБКА: Отсутствуют переменные окружения: {', '.join(missing_vars)}"
        logger.critical(error_message)
        exit(error_message)

    # --- ADMIN_IDS ---
    admin_ids: List[int] = []
    try:
        admin_ids = [int(admin_id.strip()) for admin_id in admin_ids_str.split(',') if admin_id.strip()]
        if not admin_ids:
            raise ValueError("Список ADMIN_IDS пуст или содержит некорректные значения.")
    except ValueError as e:
        error_message = f"КРИТИЧЕСКАЯ ОШИБКА: Переменная окружения ADMIN_IDS ('{admin_ids_str}') должна быть списком чисел, разделенных запятыми. Ошибка: {e}"
        logger.critical(error_message)
        exit(error_message)
    # -------------------------

    logger.info(f"Загружены ADMIN_IDS: {admin_ids}")
    logger.info(f"Загружен API_BASE_URL: {api_base_url}")

    return Settings(
        bot=BotConfig(token=bot_token, admin_ids=admin_ids, password=bot_password),
        api=ApiConfig(base_url=api_base_url)
    )

try:
    settings = load_config()
    logger.info("Конфигурация успешно загружена из окружения.")
except SystemExit as e:
     # Логирование ошибки произошло в load_config
     logger.info(f"Завершение работы из-за ошибки конфигурации: {e}")
     raise # Прерываем импорт модуля