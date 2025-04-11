import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

STATUS_FILE = "data/last_status.json"
DATA_DIR = "data"

def _ensure_data_dir():
    """Создает папку 'data', если она не существует."""
    if not os.path.exists(DATA_DIR):
        try:
            os.makedirs(DATA_DIR)
            logger.info(f"Создана директория '{DATA_DIR}' для хранения данных.")
        except OSError as e:
            logger.error(f"Не удалось создать директорию '{DATA_DIR}': {e}")

def update_last_status(process_name: str, success: bool, message: str):
    """
    Сохраняет информацию о последнем завершенном запуске в JSON-файл.

    Args:
        process_name: Имя запущенного процесса ('Sale', 'CurrencyInfo', etc.).
        success: True, если процесс завершился успешно, False иначе.
        message: Итоговое сообщение о результате (или ошибка).
    """
    _ensure_data_dir()
    timestamp = datetime.now(timezone.utc).isoformat() # Используем UTC ISO формат

    status_data = {
        "process_name": process_name,
        "timestamp_utc": timestamp,
        "success": success,
        "message": message # Сохраняем полное сообщение о результате
    }

    try:
        with open(STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump(status_data, f, indent=4, ensure_ascii=False)
        logger.info(f"Статус последнего запуска ({process_name}) сохранен в {STATUS_FILE}")
    except IOError as e:
        logger.exception(f"Ошибка записи статуса в файл {STATUS_FILE}: {e}")
    except Exception as e:
        logger.exception(f"Неожиданная ошибка при сохранении статуса в {STATUS_FILE}")

def get_last_status() -> Optional[Dict[str, Any]]:
    """
    Читает информацию о последнем запуске из JSON-файла.

    Returns:
        Словарь со статусом или None, если файл не найден или пуст/некорректен.
    """
    if not os.path.exists(STATUS_FILE):
        logger.warning(f"Файл статуса {STATUS_FILE} не найден.")
        return None

    try:
        with open(STATUS_FILE, 'r', encoding='utf-8') as f:
            status_data = json.load(f)
        if isinstance(status_data, dict) and "process_name" in status_data: # Простая проверка
            return status_data
        else:
            logger.error(f"Некорректный формат данных в файле статуса {STATUS_FILE}")
            return None
    except (json.JSONDecodeError, IOError) as e:
        logger.exception(f"Ошибка чтения или парсинга файла статуса {STATUS_FILE}: {e}")
        return None
    except Exception as e:
        logger.exception(f"Неожиданная ошибка при чтении статуса из {STATUS_FILE}")
        return None