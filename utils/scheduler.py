# utils/scheduler.py
import logging
import json
import os
from typing import Optional, Dict, Tuple, List, Any # Добавили нужные типы

import aiohttp
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.triggers.cron import CronTrigger
from config.settings import ApiConfig, Settings
from utils import api_client
from utils.status_tracker import update_last_status
logger = logging.getLogger(__name__)

SCHEDULE_FILE = "data/schedules.json"
DATA_DIR = "data"

async def scheduled_job_runner(
    bot: Bot,
    http_session: Optional[aiohttp.ClientSession],
    api_settings: ApiConfig,
    settings: Settings,
    process_name: str
):
    """
    Выполняет запуск процесса парсинга/синхронизации по расписанию,
    обновляет статус последнего запуска и уведомляет всех администраторов.
    Эта функция вызывается планировщиком APScheduler.
    """
    logger.info(f"[Планировщик] Запуск задачи для процесса: '{process_name}'")

    admin_ids = settings.bot.admin_ids
    if not admin_ids:
        logger.error("[Планировщик] Список ID администраторов пуст! Уведомления не будут отправлены.")
        # return

    # Проверяем наличие и состояние HTTP сессии
    if http_session is None or http_session.closed:
         logger.error(f"[Планировщик] HTTP сессия закрыта или отсутствует для задачи '{process_name}'. Невозможно выполнить API запросы.")
         success = False
         result_message = "Критическая ошибка: HTTP сессия недоступна для выполнения задачи."
         # Обновляем статус с информацией об ошибке сессии
         try: update_last_status(process_name, success, result_message)
         except Exception as status_e: logger.exception(f"[Планировщик] Ошибка обновления статуса при ошибке сессии для '{process_name}'")
         # Отправляем уведомление об ошибке сессии всем админам
         notification_text = f"❌ [Расписание] Ошибка запуска '{process_name}':\n\n{result_message}"
         for admin_id in admin_ids: # Цикл по списку админов
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

    # --- Формируем и отправляем уведомление администраторам ---
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

    logger.info(f"[Планировщик] Результат задачи '{process_name}': {'Успех' if success else 'Ошибка'}. Отправка уведомлений админам: {admin_ids}.")

    # Отправляем уведомление ВСЕМ админам из списка
    for admin_id in admin_ids: # Цикл по списку админов
        try:
            await bot.send_message(admin_id, notification_text, disable_notification=False)
            logger.debug(f"[Планировщик] Уведомление для задачи '{process_name}' отправлено админу {admin_id}.")
        except Exception as e:
            # Логируем ошибку отправки конкретному админу, но продолжаем для остальных
            logger.error(f"[Планировщик] Не удалось отправить уведомление админу {admin_id} для задачи '{process_name}': {e}")

def _ensure_data_dir():
    """Создает папку 'data', если она не существует."""
    if not os.path.exists(DATA_DIR):
        try:
            os.makedirs(DATA_DIR)
            logger.info(f"Создана директория '{DATA_DIR}' для сохранения данных.")
        except OSError as e:
            logger.error(f"Не удалось создать директорию '{DATA_DIR}': {e}")

def save_schedules(scheduler: AsyncIOScheduler, update_info: Optional[Dict[str, Optional[str]]] = None):
    """
    Сохраняет текущие активные расписания в JSON файл.
    Принимает словарь `update_info` с последним изменением для повышения надежности.
    """
    _ensure_data_dir()
    schedules_data: Dict[str, str] = {}
    # Шаг 1: Загружаем существующие данные
    if os.path.exists(SCHEDULE_FILE):
        try:
            with open(SCHEDULE_FILE, 'r', encoding='utf-8') as f: schedules_data = json.load(f)
            if not isinstance(schedules_data, dict):
                logger.error(f"Неверный формат в {SCHEDULE_FILE}, начинаем заново.")
                schedules_data = {}
            else: logger.info(f"Загружено {len(schedules_data)} существующих расписаний из {SCHEDULE_FILE}")
        except Exception as e:
            logger.exception(f"Не удалось загрузить или прочитать {SCHEDULE_FILE}, начинаем заново.")
            schedules_data = {}
    else: logger.info(f"Файл {SCHEDULE_FILE} не найден, начинаем заново.")

    # Шаг 2: Применяем информацию о последнем изменении
    if update_info is not None:
        logger.info(f"Применение информации об обновлении расписания: {update_info}")
        for job_id, time_str in update_info.items():
            if not job_id.startswith("schedule_"): continue
            if time_str is None:
                if job_id in schedules_data: del schedules_data[job_id]; logger.info(f"Удалено расписание '{job_id}' из данных.")
                else: logger.info(f"Расписание '{job_id}' уже отсутствовало (запрошено удаление).")
            else: schedules_data[job_id] = time_str; logger.info(f"Обновлено/добавлено расписание '{job_id}': {time_str}.")
    else: logger.warning("Информация об обновлении не передана в save_schedules.")

    # Шаг 3: Записываем итоговый словарь
    try:
        logger.info(f"Итоговые данные для сохранения: {schedules_data}")
        with open(SCHEDULE_FILE, 'w', encoding='utf-8') as f:
            json.dump(schedules_data, f, indent=4, ensure_ascii=False)
        logger.info(f"Успешно сохранено {len(schedules_data)} расписаний в {SCHEDULE_FILE}")
    except Exception as e:
        logger.exception(f"!!! КРИТИЧЕСКАЯ ОШИБКА: Не удалось сохранить расписания в {SCHEDULE_FILE} !!!")


def load_schedules(
    scheduler: AsyncIOScheduler,
    bot: Bot,
    http_session: Optional[aiohttp.ClientSession], # Сессия может быть None при инициализации
    api_settings: ApiConfig,
    settings: Settings # Передаем весь объект настроек
) -> Dict[str, str]:
    """Загружает расписания из JSON файла и добавляет их в планировщик."""
    _ensure_data_dir()
    loaded_schedules: Dict[str, str] = {}
    if not os.path.exists(SCHEDULE_FILE):
        logger.warning(f"Файл {SCHEDULE_FILE} не найден. Расписания не загружены.")
        return loaded_schedules
    try:
        with open(SCHEDULE_FILE, 'r', encoding='utf-8') as f: schedules_data = json.load(f)
        if not isinstance(schedules_data, dict):
            logger.error(f"Неверный формат в {SCHEDULE_FILE}. Ожидался словарь.")
            return loaded_schedules

        count = 0
        for job_id, time_str in schedules_data.items():
            try:
                if not job_id.startswith("schedule_"): continue
                process_name = job_id.split('_')[-1]
                if process_name not in ["Sale", "CurrencyInfo", "PackageIdPrice"]: continue
                hour, minute = map(int, time_str.split(':'))

                # Формируем kwargs для передачи в scheduled_job_runner
                job_kwargs = {
                    "bot": bot,
                    "http_session": http_session, # Передаем сессию (может быть None)
                    "api_settings": api_settings,
                    "settings": settings, # Передаем весь объект settings
                    "process_name": process_name
                }
                if http_session is None:
                    logger.warning(f"HTTP сессия не доступна при загрузке задачи '{job_id}', она может не выполниться корректно до передачи сессии.")
                    job_kwargs["http_session"] = None # Явно

                scheduler.add_job(
                    scheduled_job_runner, trigger='cron', hour=hour, minute=minute,
                    id=job_id, replace_existing=True, kwargs=job_kwargs
                )
                loaded_schedules[job_id] = time_str
                count += 1
                logger.info(f"Загружено и добавлено расписание '{job_id}' на {time_str}")
            except Exception as e:
                logger.error(f"Ошибка загрузки задачи '{job_id}' ({time_str}): {e}", exc_info=True)
        logger.info(f"Успешно загружено {count} расписаний из {SCHEDULE_FILE}")
        return loaded_schedules
    except Exception as e:
        logger.exception(f"Не удалось загрузить расписания из {SCHEDULE_FILE}")
        return loaded_schedules


async def setup_scheduler(
    bot: Bot,
    http_session: Optional[aiohttp.ClientSession], # Сессия может быть None
    api_settings: ApiConfig,
    settings: Settings # Принимаем settings
) -> Tuple[AsyncIOScheduler, Dict[str, str]]:
    """Инициализирует, настраивает и загружает задачи для планировщика."""
    logger.info("Инициализация планировщика...")
    scheduler = AsyncIOScheduler(timezone='Europe/Moscow') # Укажите ваш часовой пояс!
    # Передаем settings в load_schedules
    current_schedules = load_schedules(scheduler, bot, http_session, api_settings, settings)
    logger.info("Планировщик настроен.")
    return scheduler, current_schedules