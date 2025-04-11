# main.py
import asyncio
import logging
from typing import Optional, Dict  # Добавляем импорт Optional и Dict

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Импортируем настройки
from config.settings import settings
# Импортируем все роутеры
from handlers import auth, common, last_status, manual_start, view_logs, schedule_settings
# Импортируем утилиты планировщика
from utils.scheduler import setup_scheduler, save_schedules

try:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S' # Формат времени
    )
    logging.info("--- Логирование успешно настроено ---")
except Exception as e:
    # Этот print сработает, только если сам basicConfig вызовет ошибку
    print(f"КРИТИЧЕСКАЯ ОШИБКА НАСТРОЙКИ ЛОГИРОВАНИЯ: {e}")
    exit(1)

logger = logging.getLogger(__name__)
async def main():
    """Основная асинхронная функция запуска бота."""
    logger.info("Инициализация бота...")

    # Загружаем настройки
    bot_settings = settings.bot
    api_settings = settings.api

    # Инициализация хранилища FSM
    storage = MemoryStorage()

    # Инициализация бота и диспетчера
    bot = Bot(token=bot_settings.token)
    dp = Dispatcher(storage=storage)

    # --- Настройка планировщика ---
    scheduler: Optional[AsyncIOScheduler] = None
    current_schedules: Dict[str, str] = {} # Словарь для хранения текущих расписаний
    try:
        # Инициализируем планировщик ДО создания HTTP сессии,
        scheduler, current_schedules = await setup_scheduler(
            bot=bot,
            http_session=None, # Сессию передадим позже
            api_settings=api_settings,
            settings=settings
        )
        logger.info("Планировщик инициализирован.")
    except Exception as e:
        logger.exception("КРИТИЧЕСКАЯ ОШИБКА: Не удалось инициализировать планировщик!")
        # Можно раскомментировать exit, если бот не должен работать без планировщика
        # exit("Scheduler initialization failed.")
    # -----------------------------------------

    # Передаем статические зависимости и настройки в контекст диспетчера,
    # чтобы они были доступны во всех хэндлерах.
    if scheduler:
        dp["scheduler"] = scheduler
    dp["current_schedules"] = current_schedules # Даже если пустой, он нужен для клавиатуры
    dp["settings"] = settings # Передаем все настройки целиком
    dp["api_settings"] = api_settings # Передаем настройки API для хэндлеров

    logger.info("Зависимости (планировщик, настройки) переданы в диспетчер.")

    # Создаем HTTP сессию, которая будет жить в течение всего времени работы бота
    async with aiohttp.ClientSession() as http_session:
        # Передаем HTTP сессию в контекст диспетчера
        dp["http_session"] = http_session
        logger.info("aiohttp ClientSession created and added to dispatcher context.")

        # Обновляем задачи планировщика, добавляя им созданную HTTP сессию
        if scheduler:
            logger.info("Попытка обновления задач планировщика HTTP сессией...")
            updated_jobs_count = 0
            try:
                jobs = scheduler.get_jobs(jobstore='default')
                for job in jobs:
                    # Проверяем, что у задачи есть kwargs и сессия еще не установлена
                    if hasattr(job, 'kwargs') and isinstance(job.kwargs, dict) and \
                       ("http_session" not in job.kwargs or job.kwargs["http_session"] is None):

                        # Создаем копию kwargs и добавляем сессию
                        new_kwargs = job.kwargs.copy()
                        new_kwargs["http_session"] = http_session
                        try:
                            # Модифицируем задачу с новыми kwargs
                            scheduler.modify_job(job.id, jobstore='default', kwargs=new_kwargs)
                            updated_jobs_count += 1
                            logger.debug(f"Successfully modified job '{job.id}' with http_session.")
                        except Exception as mod_e:
                            logger.error(f"Failed to modify job '{job.id}' with http_session: {mod_e}")
                if updated_jobs_count > 0:
                     logger.info(f"Successfully updated {updated_jobs_count} scheduler jobs with http_session.")
                else:
                     logger.info("No scheduler jobs required http_session update.")
            except Exception as e:
                logger.exception("Error occurred while updating scheduler jobs with http_session.")


        # --- Регистрация роутеров ---
        # Порядок важен: сначала более специфичные, потом общие
        logger.info("Регистрация роутеров...")
        dp.include_router(auth.auth_router)             # Авторизация
        dp.include_router(manual_start.manual_start_router) # Ручной запуск
        dp.include_router(view_logs.view_logs_router)       # Просмотр логов
        dp.include_router(schedule_settings.schedule_router) # Настройки расписания
        dp.include_router(last_status.last_status_router) #
        dp.include_router(common.common_router)             # Общие команды (logout, неизвестные) - в конце
        logger.info("Обработчики зарегистрированы")
        # ---------------------------

        # --- Запуск планировщика ---
        if scheduler:
            try:
                scheduler.start()
                logger.info("Планировщик успешно запущен.")
            except Exception as start_e:
                logger.exception("КРИТИЧЕСКАЯ ОШИБКА: Планировщик не запустился!")
        else:
            logger.warning("Планировщик не инициализирован, запуск пропущен.")
        # ---------------------------

        # --- Запуск бота (polling) ---
        try:
            # на случай, если он был установлен ранее
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("Starting polling...")
            # Запускаем бесконечный цикл получения обновлений
            await dp.start_polling(
                bot,
                allowed_updates=dp.resolve_used_update_types() # Оптимизация: получаем только нужные типы апдейтов
            )
        finally:
            logger.warning("Polling stopped. Завершение работы...")

            # --- Корректное завершение работы ---
            # Останавливаем планировщик и сохраняем расписания
            if scheduler and scheduler.running:
                logger.info("Остановка планировщика и сохранение расписаний...")
                try:
                    save_schedules(scheduler) # Сохраняем перед остановкой
                    scheduler.shutdown()
                    logger.info("Планировщик остановлен, расписания сохранены.")
                except Exception as e:
                    logger.exception("Ошибка при остановке планировщика или сохранении.")

            # Сессия aiohttp закроется автоматически благодаря 'async with'
            logger.info("Бот успешно остановлен.")
            # -----------------------------------

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен вручную (Ctrl+C).")
    except Exception as e:
        # Ловим и логируем любые необработанные исключения на верхнем уровне
        logger.critical(f"Необработанное исключение верхнего уровня: {e}", exc_info=True)