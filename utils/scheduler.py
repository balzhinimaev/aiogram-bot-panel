import logging
import json
import os
from typing import Dict, Optional
from typing import Tuple
import aiohttp
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore

from apscheduler.triggers.cron import CronTrigger
from config.settings import ApiConfig
from utils import api_client
from utils.status_tracker import update_last_status
logger = logging.getLogger(__name__)

SCHEDULE_FILE = "data/schedules.json"

async def scheduled_job_runner(
    bot: Bot,
    http_session: Optional[aiohttp.ClientSession],
    api_settings: ApiConfig,
    admin_id: int,
    process_name: str
):
    """
    Выполняет запуск процесса парсинга/синхронизации по расписанию,
    обновляет статус последнего запуска и уведомляет администратора.
    Эта функция вызывается планировщиком APScheduler.
    """
    logger.info(f"[Планировщик] Запуск задачи для процесса: '{process_name}'")

    # Проверяем наличие HTTP сессии
    if http_session is None or http_session.closed:
         logger.error(f"[Планировщик] HTTP сессия закрыта или отсутствует для задачи '{process_name}'. Невозможно выполнить API запросы.")
         success = False
         result_message = "Критическая ошибка: HTTP сессия недоступна для выполнения задачи."
         # Обновляем статус с информацией об ошибке сессии
         try:
             update_last_status(process_name, success, result_message)
             logger.info(f"[Планировщик] Статус последнего запуска для '{process_name}' обновлен (Ошибка сессии).")
         except Exception as status_e:
             logger.exception(f"[Планировщик] Ошибка обновления статуса при ошибке сессии для '{process_name}'")
         # Отправляем уведомление об ошибке сессии
         notification_text = f"❌ [Расписание] Ошибка запуска '{process_name}':\n\n{result_message}"
         try: await bot.send_message(admin_id, notification_text, disable_notification=False)
         except Exception as e: logger.error(f"[Планировщик] Не удалось отправить уведомление об ошибке сессии админу {admin_id}: {e}")
         return # Прерываем выполнение задачи

    # Если сессия есть, выполняем API вызовы
    success = False
    result_message = f"Неизвестная ошибка при запуске '{process_name}' по расписанию." # Сообщение по умолчанию

    try:
        # Вызываем соответствующую функцию API клиента
        if process_name == "Sale":
            success, result_message = await api_client.run_sale_process(http_session, api_settings)
        elif process_name == "CurrencyInfo":
            success, result_message = await api_client.run_currency_info_process(http_session, api_settings)
        elif process_name == "PackageIdPrice":
            success, result_message = await api_client.run_package_id_price_process(http_session, api_settings)
        else:
            # Обработка случая, если в планировщик попало неизвестное имя
            result_message = f"Ошибка: Неизвестный тип процесса '{process_name}' в задаче планировщика."
            logger.error(result_message)
            success = False # Явно указываем на ошибку

    except Exception as e:
        # Ловим любые другие исключения во время выполнения API вызовов
        logger.exception(f"[Планировщик] КРИТИЧЕСКАЯ ОШИБКА при выполнении задачи '{process_name}'")
        result_message = f"Критическая ошибка при выполнении '{process_name}' по расписанию. Подробности в логах сервера."
        success = False

    # --- Обновляем статус последнего запуска ---
    try:
        # Передаем имя процесса, флаг успеха и итоговое сообщение
        update_last_status(process_name, success, result_message)
        logger.info(f"[Планировщик] Статус последнего запуска для '{process_name}' обновлен (Успех: {success}).")
    except Exception as status_e:
        # Логируем ошибку сохранения статуса, но не прерываем отправку уведомления
        logger.exception(f"[Планировщик] Ошибка обновления статуса последнего запуска для '{process_name}'")
    # -----------------------------------------

    # --- Формируем и отправляем уведомление администратору ---
    status_emoji = "✅" if success else "❌"
    # Формируем базовое сообщение
    notification_text = f"{status_emoji} [Расписание] Процесс '{process_name}' завершен."
    if not success:
        max_len = 1000
        details = result_message[:max_len] + ('...' if len(result_message) > max_len else '')
        notification_text += f"\n\nРезультат:\n{details}"
    elif success and result_message and "✅" not in result_message: # Если есть доп. инфо при успехе
         max_len = 500
         details = result_message[:max_len] + ('...' if len(result_message) > max_len else '')
         notification_text += f"\n\nДетали:\n{details}"

    logger.info(f"[Планировщик] Результат задачи '{process_name}': {'Успех' if success else 'Ошибка'}. Отправка уведомления админу {admin_id}.")

    try:
        await bot.send_message(admin_id, notification_text, disable_notification=False)
        logger.info(f"[Планировщик] Уведомление для задачи '{process_name}' успешно отправлено админу {admin_id}.")
    except Exception as e:
        logger.error(f"[Планировщик] Не удалось отправить уведомление админу {admin_id} для задачи '{process_name}': {e}")

# --- Функции сохранения/загрузки расписания ---
def _ensure_data_dir():
    """Создает папку 'data', если она не существует."""
    if not os.path.exists("data"):
        try:
            os.makedirs("data")
            logging.info("Created 'data' directory for schedule persistence.")
        except OSError as e:
            logging.error(f"Failed to create 'data' directory: {e}")

SCHEDULE_FILE = "data/schedules.json"
def save_schedules(scheduler: AsyncIOScheduler, update_info: Optional[Dict[str, Optional[str]]] = None):
    """
    Сохраняет текущие активные расписания в JSON файл.
    Принимает словарь `update_info` с последним изменением для повышения надежности.

    Args:
        scheduler: Экземпляр AsyncIOScheduler (технически не используется в этой версии,
                   но оставлен для совместимости интерфейса, если понадобится сверка).
        update_info: Словарь вида {'job_id': 'ЧЧ:ММ' или None}. None означает удаление.
                     Если None, функция попытается прочитать текущий файл.
    """
    _ensure_data_dir()
    schedules_data: Dict[str, str] = {}

    # Шаг 1: Загружаем существующие данные из файла, если он есть
    if os.path.exists(SCHEDULE_FILE):
        try:
            with open(SCHEDULE_FILE, 'r', encoding='utf-8') as f:
                schedules_data = json.load(f)
            if not isinstance(schedules_data, dict):
                logging.error(f"Invalid format in {SCHEDULE_FILE}. Expected a dictionary, got {type(schedules_data)}. Starting fresh.")
                schedules_data = {}
            else:
                logging.info(f"Loaded {len(schedules_data)} existing schedule(s) from {SCHEDULE_FILE}")
        except (json.JSONDecodeError, IOError, FileNotFoundError) as e:
            logging.exception(f"Failed to load or parse existing schedule file {SCHEDULE_FILE}. Starting fresh.")
            schedules_data = {}
    else:
        logging.info(f"Schedule file {SCHEDULE_FILE} not found. Starting fresh.")

    # Шаг 2: Применяем информацию о последнем изменении, если она передана
    if update_info is not None:
        logging.warning(f"!!! Applying update info to schedules: {update_info}")
        for job_id, time_str in update_info.items():
            if not job_id.startswith("schedule_"):
                 logging.warning(f"Skipping update for invalid job_id format: {job_id}")
                 continue

            if time_str is None:
                if job_id in schedules_data:
                    del schedules_data[job_id]
                    logging.info(f"Removed '{job_id}' from schedule data based on update_info.")
                else:
                    logging.info(f"Job '{job_id}' was already absent from schedule data (requested removal).")
            else:
                schedules_data[job_id] = time_str
                logging.info(f"Updated/Added '{job_id}' with time '{time_str}' in schedule data based on update_info.")
    else:
         logging.warning("!!! No update_info provided to save_schedules. Saving currently loaded data.")


    # Шаг 3: Записываем итоговый словарь schedules_data обратно в файл
    try:
        logging.warning(f"!!! Final schedule data to save: {schedules_data}")
        with open(SCHEDULE_FILE, 'w', encoding='utf-8') as f:
            json.dump(schedules_data, f, indent=4, ensure_ascii=False)
        logging.info(f"Successfully saved {len(schedules_data)} schedule(s) to {SCHEDULE_FILE}")
    except IOError as e:
        logging.exception(f"!!! IOError: FAILED TO SAVE SCHEDULES to {SCHEDULE_FILE} !!!")
    except TypeError as e:
         logging.exception(f"!!! TypeError: FAILED TO SAVE SCHEDULES due to JSON serialization error !!! Data: {schedules_data}")
    except Exception as e:
        logging.exception(f"!!! UNEXPECTED ERROR: FAILED TO SAVE SCHEDULES to {SCHEDULE_FILE} !!!")
        
def load_schedules(
    scheduler: AsyncIOScheduler,
    bot: Bot,
    http_session: aiohttp.ClientSession,
    api_settings: ApiConfig,
    admin_id: int
) -> Dict[str, str]:
    """Загружает расписания из JSON файла и добавляет их в планировщик."""
    _ensure_data_dir()
    loaded_schedules = {}
    if not os.path.exists(SCHEDULE_FILE):
        logging.warning(f"Schedule file {SCHEDULE_FILE} not found. No schedules loaded.")
        return loaded_schedules

    try:
        with open(SCHEDULE_FILE, 'r', encoding='utf-8') as f:
            schedules_data = json.load(f)

        if not isinstance(schedules_data, dict):
             logging.error(f"Invalid format in {SCHEDULE_FILE}. Expected a dictionary.")
             return loaded_schedules

        count = 0
        for job_id, time_str in schedules_data.items():
            try:
                hour, minute = map(int, time_str.split(':'))
                process_name = job_id.split('_')[-1]
                if process_name not in ["Sale", "CurrencyInfo", "PackageIdPrice"]:
                     logging.warning(f"Skipping job with invalid ID format: {job_id}")
                     continue

                scheduler.add_job(
                    scheduled_job_runner,
                    trigger='cron',
                    hour=hour,
                    minute=minute,
                    id=job_id,
                    replace_existing=True,
                    kwargs={
                        "bot": bot,
                        "http_session": http_session,
                        "api_settings": api_settings,
                        "admin_id": admin_id,
                        "process_name": process_name
                    }
                )
                loaded_schedules[job_id] = time_str # Сохраняем загруженное время
                count += 1
                logging.info(f"Loaded and scheduled job '{job_id}' for {time_str}")
            except (ValueError, KeyError, TypeError) as e:
                logging.error(f"Failed to load job '{job_id}' with time '{time_str}': {e}")

        logging.info(f"Successfully loaded {count} schedules from {SCHEDULE_FILE}")
        return loaded_schedules
    except (json.JSONDecodeError, IOError) as e:
        logging.exception(f"Failed to load schedules from {SCHEDULE_FILE}")
        return loaded_schedules


# --- Функция инициализации планировщика ---
async def setup_scheduler(
    bot: Bot,
    http_session: aiohttp.ClientSession,
    api_settings: ApiConfig,
    admin_id: int
) -> Tuple[AsyncIOScheduler, Dict[str, str]]:
    """Инициализирует, настраивает и загружает задачи для планировщика."""
    logging.info("Initializing scheduler...")
    # JSON файл для сохранения/загрузки.
    jobstores = {
        'default': MemoryJobStore()
    }
    executors = {
        'default': {'type': 'threadpool', 'max_workers': 5}
    }
    job_defaults = {
        'coalesce': True,
        'max_instances': 1
    }
    scheduler = AsyncIOScheduler(
        jobstores=jobstores,
        job_defaults=job_defaults,
        timezone='Europe/Moscow'
    )

    current_schedules = load_schedules(scheduler, bot, http_session, api_settings, admin_id)

    logging.info("Scheduler configured.")
    return scheduler, current_schedules