# config/settings.py
import os
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class BotConfig:
    token: str
    admin_id: int
    password: str

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
    admin_id_str = os.getenv("ADMIN_ID")
    bot_password = os.getenv("BOT_PASSWORD")
    api_base_url = os.getenv("API_BASE_URL")

    missing_vars = []
    if not bot_token: missing_vars.append("BOT_TOKEN")
    if not admin_id_str: missing_vars.append("ADMIN_ID")
    if not bot_password: missing_vars.append("BOT_PASSWORD")
    if not api_base_url: missing_vars.append("API_BASE_URL")

    if missing_vars:
        error_message = f"КРИТИЧЕСКАЯ ОШИБКА: Отсутствуют переменные окружения: {', '.join(missing_vars)}"
        logger.critical(error_message)
        exit(error_message)

    try:
        admin_id = int(admin_id_str)
    except ValueError:
        error_message = f"КРИТИЧЕСКАЯ ОШИБКА: Переменная окружения ADMIN_ID ('{admin_id_str}') должна быть числом."
        logger.critical(error_message)
        exit(error_message)

    logger.info(f"Загружен ADMIN_ID: {admin_id}")
    logger.info(f"Загружен API_BASE_URL: {api_base_url}")

    return Settings(
        bot=BotConfig(token=bot_token, admin_id=admin_id, password=bot_password),
        api=ApiConfig(base_url=api_base_url)
    )

try:
    settings = load_config()
    logger.info("Конфигурация успешно загружена из окружения.")
except SystemExit as e:
     # Логирование ошибки произошло в load_config
     logger.info(f"Завершение работы из-за ошибки конфигурации: {e}")
     raise # Прерываем импорт модуля