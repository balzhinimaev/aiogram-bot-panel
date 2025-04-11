# keyboards/inline.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import Optional, Dict
# 1. Клавиатура главного меню
def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру главного меню."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="▶️ Запуск парсеров вручную", callback_data="manual_start")
    )
    builder.row(
        InlineKeyboardButton(text="⚙️ Настройки расписания", callback_data="schedule_settings") # Пока не реализуем
    )
    builder.row(
        InlineKeyboardButton(text="📄 Просмотр логов", callback_data="view_logs")
    )
    builder.row(
        InlineKeyboardButton(text="📊 Статус последнего парсинга", callback_data="last_status") # Пока не реализуем
    )
    builder.row(
        InlineKeyboardButton(text="🚪 Выход", callback_data="logout")
    )
    return builder.as_markup()

# 2. Клавиатура отмены для FSM (например, при вводе пароля)
def get_cancel_keyboard() -> InlineKeyboardMarkup:
     """Создает клавиатуру с кнопкой 'Отмена'."""
     builder = InlineKeyboardBuilder()
     builder.add(InlineKeyboardButton(text="Отмена", callback_data="cancel_fsm"))
     return builder.as_markup()

# 3. Клавиатура для выбора парсера для ручного запуска (!!! ВОТ ОНА !!!)
def get_manual_start_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру для выбора парсера для ручного запуска."""
    builder = InlineKeyboardBuilder()
    # Используем префикс 'run_parser:' для callback_data
    builder.row(InlineKeyboardButton(text="📊 Sale", callback_data="run_parser:Sale"))
    builder.row(InlineKeyboardButton(text="🏦 CurrencyInfo", callback_data="run_parser:CurrencyInfo"))
    builder.row(InlineKeyboardButton(text="📦 PackageIdPrice", callback_data="run_parser:PackageIdPrice"))
    # Кнопка "Назад" ведет в главное меню (используем callback_data="main_menu")
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu"))
    return builder.as_markup()

# 4. Клавиатура для выбора лога для просмотра
def get_view_logs_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру для выбора лога для просмотра."""
    builder = InlineKeyboardBuilder()
    # Используем префикс 'view_log:'
    builder.row(InlineKeyboardButton(text="📄 Лог Sale", callback_data="view_log:Sale"))
    builder.row(InlineKeyboardButton(text="📄 Лог CurrencyInfo", callback_data="view_log:CurrencyInfo"))
    builder.row(InlineKeyboardButton(text="📄 Лог PackageIdPrice", callback_data="view_log:PackageIdPrice"))
    # Кнопка "Назад" также ведет в главное меню
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu"))
    return builder.as_markup()

# 5. Клавиатура для меню настроек расписания
def get_schedule_settings_keyboard(current_schedules: Optional[Dict[str, str]] = None) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для меню настроек расписания.
    Отображает текущее установленное время рядом с кнопкой, если оно есть.

    Args:
        current_schedules: Словарь вида {'schedule_Sale': '10:30', ...}
    """
    builder = InlineKeyboardBuilder()
    if current_schedules is None:
        current_schedules = {}

    # Получаем текущее время для каждой задачи или '(-) не задано'
    sale_time = current_schedules.get('schedule_Sale', '(-) не задано')
    currency_time = current_schedules.get('schedule_CurrencyInfo', '(-) не задано')
    package_time = current_schedules.get('schedule_PackageIdPrice', '(-) не задано')

    # Используем префикс 'set_schedule:' для callback_data
    builder.row(InlineKeyboardButton(
        text=f"⏰ Расписание Sale [{sale_time}]",
        callback_data="set_schedule:Sale"
    ))
    builder.row(InlineKeyboardButton(
        text=f"⏰ Расписание CurrencyInfo [{currency_time}]",
        callback_data="set_schedule:CurrencyInfo"
    ))
    builder.row(InlineKeyboardButton(
        text=f"⏰ Расписание PackageIdPrice [{package_time}]",
        callback_data="set_schedule:PackageIdPrice"
    ))
    # Кнопка "Назад" ведет в главное меню
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu"))
    return builder.as_markup()