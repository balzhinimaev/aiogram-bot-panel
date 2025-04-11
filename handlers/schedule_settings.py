import logging
import re
from typing import Dict, Optional # Для валидации времени

import aiohttp
from aiogram import Router, F, types, Bot
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.job import Job # Для проверки типа триггера
from apscheduler.triggers.cron import CronTrigger # Для создания триггера
from apscheduler.schedulers.base import JobLookupError

from keyboards.inline import get_schedule_settings_keyboard, get_main_menu_keyboard, get_cancel_keyboard
from states.user_states import UserState, ScheduleSettingsState
from handlers.auth import AdminFilter
from config.settings import ApiConfig, Settings # Импортируем Settings для доступа ко всем настройкам
from utils.scheduler import scheduled_job_runner, save_schedules # Импортируем функцию сохранения

logger = logging.getLogger(__name__)

schedule_router = Router()
# Применяем фильтры админа и состояния
schedule_router.message.filter(AdminFilter(), StateFilter("*")) # Разрешаем в любом состоянии админа
schedule_router.callback_query.filter(AdminFilter(), StateFilter("*")) # Разрешаем в любом состоянии админа

# Функция для получения актуальных расписаний из планировщика
def get_current_schedules_from_scheduler(scheduler: AsyncIOScheduler) -> dict:
    schedules = {}
    try:
        for job in scheduler.get_jobs():
            if job.id.startswith('schedule_') and isinstance(job.trigger, CronTrigger):
                 # Убедимся, что hour и minute не None (могут быть '*')
                 hour = job.trigger.fields[job.trigger.FIELD_NAMES.index('hour')]
                 minute = job.trigger.fields[job.trigger.FIELD_NAMES.index('minute')]
                 if hour is not None and minute is not None:
                     schedules[job.id] = f"{str(hour).zfill(2)}:{str(minute).zfill(2)}"
    except Exception as e:
        logging.exception("Failed to get schedules from scheduler")
    return schedules


# Обработчик кнопки "Настройки расписания" из главного меню
@schedule_router.callback_query(F.data == "schedule_settings", StateFilter(UserState.authorized))
async def show_schedule_menu(
    callback_query: types.CallbackQuery,
    state: FSMContext,
    scheduler: AsyncIOScheduler
):
    user_id = callback_query.from_user.id
    logging.info(f"Admin {user_id} accessed schedule settings menu.")
    # актуальные расписания
    current_schedules = get_current_schedules_from_scheduler(scheduler)
    await state.update_data(current_schedules=current_schedules)

    await callback_query.message.edit_text(
        "Настройте время автоматического запуска (формат ЧЧ:ММ) или введите '-' для отключения:",
        reply_markup=get_schedule_settings_keyboard(current_schedules)
    )
    await state.set_state(ScheduleSettingsState.choosing_schedule)
    await callback_query.answer()

# Обработчик кнопки "Назад" из меню настроек расписания
@schedule_router.callback_query(F.data == "main_menu", StateFilter(ScheduleSettingsState.choosing_schedule))
async def back_to_main_from_schedule(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    logging.info(f"Admin {user_id} returned to main menu from schedule settings.")
    await callback_query.message.edit_text(
        "Главное меню:",
        reply_markup=get_main_menu_keyboard()
    )
    await state.set_state(UserState.authorized)
    await callback_query.answer()


# Обработчик кнопок выбора конкретного расписания (set_schedule:...)
@schedule_router.callback_query(F.data.startswith("set_schedule:"), StateFilter(ScheduleSettingsState.choosing_schedule))
async def ask_for_schedule_time(callback_query: types.CallbackQuery, state: FSMContext):
    try:
        process_name = callback_query.data.split(":")[-1]
        job_id = f"schedule_{process_name}"
    except IndexError:
        logging.error(f"Invalid callback_data in schedule settings: {callback_query.data}")
        await callback_query.answer("Ошибка: Некорректные данные кнопки.", show_alert=True)
        return

    user_id = callback_query.from_user.id
    logging.info(f"Admin {user_id} requested to set schedule for '{process_name}' (Job ID: {job_id}).")

    await state.update_data(current_job_id=job_id, current_process_name=process_name)

    await callback_query.message.edit_text(
        f"Введите время для '{process_name}' в формате ЧЧ:ММ (например, 09:30 или 18:05) или введите '-' для отключения:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(ScheduleSettingsState.waiting_for_time)
    await callback_query.answer()


# Обработчик ввода времени или символа '-'
@schedule_router.message(StateFilter(ScheduleSettingsState.waiting_for_time), F.text)
async def process_schedule_time_input(
    message: types.Message,
    state: FSMContext,
    scheduler: AsyncIOScheduler,
    bot: Bot,
    http_session: aiohttp.ClientSession,
    settings: Settings
):
    """
    Обрабатывает ввод пользователя (время ЧЧ:ММ или '-'),
    обновляет задачу в планировщике и вызывает сохранение расписания.
    """
    user_input = message.text.strip()
    user_id = message.from_user.id
    fsm_data = await state.get_data()
    job_id = fsm_data.get("current_job_id")
    process_name = fsm_data.get("current_process_name")

    if not job_id or not process_name:
        logging.error(f"Job ID or process name not found in FSM state for user {user_id}")
        await message.reply("Произошла ошибка состояния. Пожалуйста, начните настройку расписания заново из главного меню.")
        await state.clear()
        return
    
    time_pattern = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
    schedule_changed = False
    schedule_update_info: Dict[str, Optional[str]] = {}

    # --- Обработка ввода пользователя ---
    if user_input == "-":
        try:
            # Пытаемся удалить задачу из планировщика
            scheduler.remove_job(job_id, jobstore='default')
            logging.info(f"Removed job '{job_id}' by admin {user_id}.")
            await message.reply(f"Расписание для '{process_name}' успешно отключено.")
            schedule_changed = True
            schedule_update_info[job_id] = None # Помечаем как удаленное для сохранения
        except JobLookupError:
            # Если задачи с таким ID не было - это не ошибка
            logging.warning(f"Job '{job_id}' not found when trying to remove by admin {user_id}.")
            await message.reply(f"Расписание для '{process_name}' не было установлено.")
            schedule_update_info[job_id] = None
            schedule_changed = True # Считаем изменением для файла
        except Exception as e:
            # Ловим другие ошибки при удалении
            logging.exception(f"Error removing job '{job_id}' for user {user_id}")
            await message.reply(f"Произошла ошибка при отключении расписания для '{process_name}'.")
            schedule_changed = False # Изменение не удалось

    elif time_match := time_pattern.match(user_input):
        # --- Установка / Обновление задачи ---
        hour = int(time_match.group(1))
        minute = int(time_match.group(2))
        # Формируем строку времени ЧЧ:ММ
        new_time_str = f"{str(hour).zfill(2)}:{str(minute).zfill(2)}"
        logging.info(f"--- Preparing to add/update job '{job_id}' with hour={hour}, minute={minute}")
        try:
            # Добавляем или заменяем задачу в планировщике
            scheduler.add_job(
                func=scheduled_job_runner, # Функция, которая будет выполняться
                trigger='cron',          # Запуск по времени (cron)
                hour=hour,               # Час
                minute=minute,           # Минута
                id=job_id,               # Уникальный идентификатор задачи
                replace_existing=True,   # Заменить задачу, если она уже существует
                kwargs={                 # Аргументы, которые будут переданы в scheduled_job_runner
                    "bot": bot,
                    "http_session": http_session,
                    "api_settings": settings.api,       # Настройки API
                    "settings": settings,  # ID админа для уведомлений
                    "process_name": process_name        # Имя процесса для запуска
                }
            )
            logging.info(f"Successfully Added/Updated job '{job_id}' for {new_time_str} by admin {user_id}.")
            await message.reply(f"Расписание для '{process_name}' установлено на {new_time_str} ежедневно.")
            schedule_changed = True
            schedule_update_info[job_id] = new_time_str
        except Exception as e:
            logging.exception(f"Error adding/updating job '{job_id}' for user {user_id}")
            await message.reply(f"Произошла ошибка при установке расписания для '{process_name}'.")
            schedule_changed = False

    else:
        await message.reply("Неверный формат. Введите время как ЧЧ:ММ (например, 14:00) или '-' для отключения.")
        return

    # --- Сохранение изменений в файл ---
    if schedule_changed:
        logging.warning(f"!!! Schedule update info: {schedule_update_info}. Attempting to save...")
        try:
            save_schedules(scheduler, update_info=schedule_update_info)
        except Exception as save_e:
             logging.exception(f"Failed to save schedules after update by user {user_id}")
             await message.answer("⚠️ Не удалось сохранить изменения расписания в файл.")
    else:
        logging.warning("!!! Schedule not successfully changed, skipping save.")

    # --- Возвращаемся в меню выбора расписания ---
    try:
        await state.set_state(ScheduleSettingsState.choosing_schedule)
        current_schedules = get_current_schedules_from_scheduler(scheduler)
        await message.answer(
            "Настройте время автоматического запуска:",
            reply_markup=get_schedule_settings_keyboard(current_schedules)
        )
    except Exception as e:
         logging.exception(f"Error returning to schedule menu for user {user_id}")
         await state.clear()
         await message.answer("Произошла ошибка при обновлении меню. Пожалуйста, вернитесь в главное меню /start")


# Обработчик кнопки "Отмена" во время ввода времени
@schedule_router.callback_query(F.data == "cancel_fsm", StateFilter(ScheduleSettingsState.waiting_for_time))
async def cancel_time_input(
    callback_query: types.CallbackQuery,
    state: FSMContext,
    scheduler: AsyncIOScheduler
):
    user_id = callback_query.from_user.id
    logger.info(f"Администратор {user_id} отменил ввод времени.")
    await state.set_state(ScheduleSettingsState.choosing_schedule)
    current_schedules = get_current_schedules_from_scheduler(scheduler)
    await callback_query.message.edit_text(
        "Ввод времени отменен. Настройте время автоматического запуска:",
        reply_markup=get_schedule_settings_keyboard(current_schedules)
    )
    await callback_query.answer("Отменено.")