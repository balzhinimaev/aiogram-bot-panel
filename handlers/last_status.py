import logging
from datetime import datetime

from aiogram import Router, F, types
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext

from keyboards.inline import get_main_menu_keyboard
from states.user_states import UserState
from handlers.auth import AdminFilter
from utils.status_tracker import get_last_status

logger = logging.getLogger(__name__)
last_status_router = Router()
last_status_router.message.filter(AdminFilter(), StateFilter("*"))
last_status_router.callback_query.filter(AdminFilter(), StateFilter("*"))

@last_status_router.callback_query(F.data == "last_status", StateFilter(UserState.authorized))
async def show_last_status(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает нажатие кнопки 'Статус последнего парсинга'.
    Читает статус из файла и отправляет пользователю.
    """
    user_id = callback_query.from_user.id
    logger.info(f"Администратор {user_id} запросил статус последнего запуска.")
    await callback_query.answer("Получение статуса...") # Краткий ответ на кнопку

    status_data = get_last_status()
    message_text = ""

    if status_data is None:
        message_text = "ℹ️ Информация о последнем запуске отсутствует."
        logger.warning(f"Статус последнего запуска не найден для запроса от {user_id}.")
    else:
        try:
            process_name = status_data.get("process_name", "Неизвестный процесс")
            timestamp_str = status_data.get("timestamp_utc", "Неизвестное время")
            success = status_data.get("success", False)
            result_msg = status_data.get("message", "Нет деталей.")

            # Форматируем время для отображения
            try:
                dt_utc = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                formatted_time = dt_utc.strftime('%Y-%m-%d %H:%M:%S %Z')
            except Exception:
                formatted_time = timestamp_str

            status_text = "✅ Успешно" if success else "❌ Ошибка"

            max_msg_len = 3500
            if len(result_msg) > max_msg_len:
                 result_msg_short = result_msg[:max_msg_len] + "..."
            else:
                 result_msg_short = result_msg

            message_text = (
                f"📊 **Статус последнего запуска:**\n\n"
                f"🔹 **Процесс:** {process_name}\n"
                f"🕒 **Время завершения (UTC):** {formatted_time}\n"
                f"🚦 **Статус:** {status_text}\n\n"
                f"📝 **Результат:**\n```\n{result_msg_short}\n```"
            )
            logger.info(f"Отображен статус для {user_id}: Процесс={process_name}, Успех={success}")

        except Exception as e:
            logger.exception(f"Ошибка форматирования статуса для {user_id}")
            message_text = "❌ Произошла ошибка при обработке данных о статусе."

    # Отправляем сообщение со статусом и возвращаем главное меню
    try:
        await callback_query.message.edit_text(
            message_text,
            reply_markup=get_main_menu_keyboard(),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Не удалось отредактировать сообщение со статусом для {user_id}: {e}")
        try:
            await callback_query.message.answer(
                 message_text,
                 reply_markup=get_main_menu_keyboard(),
                 parse_mode="Markdown"
                 )
        except Exception as e2:
             logger.error(f"Не удалось отправить сообщение со статусом для {user_id}: {e2}")
             await callback_query.answer("Не удалось отобразить статус.", show_alert=True)