import logging
import aiohttp
from io import BytesIO

from aiogram import Router, F, types
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext

from keyboards.inline import get_view_logs_keyboard, get_main_menu_keyboard
from states.user_states import UserState
from handlers.auth import AdminFilter
from utils import api_client
from config.settings import ApiConfig

view_logs_router = Router()

view_logs_router.message.filter(AdminFilter(), StateFilter(UserState.authorized))
view_logs_router.callback_query.filter(AdminFilter(), StateFilter(UserState.authorized))

# Обработчик нажатия кнопки "Просмотр логов" из главного меню (callback_data="view_logs")
@view_logs_router.callback_query(F.data == "view_logs")
async def show_view_logs_menu(callback_query: types.CallbackQuery):
    """Отображает подменю для выбора лога."""
    user_id = callback_query.from_user.id
    logging.info(f"Admin {user_id} accessed view logs menu.")
    try:
        await callback_query.message.edit_text(
            "Выберите лог для просмотра:",
            reply_markup=get_view_logs_keyboard()
        )
    except Exception as e:
        logging.error(f"Error editing message for view logs menu (user {user_id}): {e}")
        await callback_query.answer("Не удалось обновить меню.", show_alert=True)
        return
    await callback_query.answer()

# Обработчик нажатия кнопки "Назад" в меню просмотра логов (callback_data="main_menu")
@view_logs_router.callback_query(F.data == "main_menu")
async def back_to_main_menu_from_logs(callback_query: types.CallbackQuery):
    """Возвращает пользователя в главное меню."""
    user_id = callback_query.from_user.id
    logging.info(f"Admin {user_id} returned to main menu from logs.")
    try:
        await callback_query.message.edit_text(
            "Главное меню:",
            reply_markup=get_main_menu_keyboard() 
        )
    except Exception as e:
        logging.error(f"Error editing message for main menu from logs (user {user_id}): {e}")
        await callback_query.answer("Не удалось вернуться в главное меню.", show_alert=True)
        return
    await callback_query.answer()

# Обработчик нажатия кнопок просмотра конкретного лога
@view_logs_router.callback_query(F.data.startswith("view_log:"))
async def handle_view_log(
    callback_query: types.CallbackQuery,
    http_session: aiohttp.ClientSession,
    api_settings: ApiConfig
):
    """
    Запрашивает и отображает лог для выбранного парсера.
    Длинные логи отправляет файлом.
    """
    try:
        parser_name = callback_query.data.split(":")[-1]
        if not parser_name:
            raise IndexError("Parser name is empty")
    except IndexError:
        logging.error(f"Invalid callback_data format received: {callback_query.data}")
        await callback_query.answer("Ошибка: Некорректные данные кнопки.", show_alert=True)
        return

    user_id = callback_query.from_user.id
    logging.info(f"Admin {user_id} requested log for '{parser_name}'.")

    # 1. Уведомляем пользователя о начале запроса
    await callback_query.answer(f"Запрашиваю лог '{parser_name}'...")
    try:
        await callback_query.message.edit_text(
            f"⏳ Запрашиваю лог для '{parser_name}'...",
            reply_markup=None
        )
    except Exception as e:
        logging.warning(f"Could not edit message before requesting log '{parser_name}': {e}")

    # 2. Запрашиваем лог через API клиент
    success, log_content = await api_client.get_parser_logs(http_session, api_settings, parser_name)

    # 3. Обрабатываем и отображаем результат
    final_text = ""
    document_to_send = None

    if success:
        logging.info(f"Log for '{parser_name}' received successfully for user {user_id}.")
        if log_content:
            max_length = 4000
            if len(log_content) > max_length:
                logging.warning(f"Log for '{parser_name}' is too long ({len(log_content)} chars). Preparing file.")
                try:

                    log_file = BytesIO(log_content.encode('utf-8'))
                    document_to_send = types.BufferedInputFile(log_file.getvalue(), filename=f"{parser_name}_log.txt")
                    final_text = f"📄 Лог для '{parser_name}' слишком длинный и отправлен файлом."
                except Exception as e:
                    logging.exception(f"Error preparing log file for '{parser_name}'")
                    final_text = f"⚠️ Ошибка подготовки файла лога для '{parser_name}'. Показана часть:\n\n```\n{log_content[:max_length]}...\n```"
            else:
                 final_text = f"📄 Лог для '{parser_name}':\n\n```\n{log_content}\n```"
        else:
            # Если API вернуло успех, но лог пуст
            final_text = f"ℹ️ Лог для '{parser_name}' пуст."
    else:
        logging.error(f"Failed to retrieve log for '{parser_name}' for user {user_id}. Reason: {log_content}")
        final_text = f"❌ Не удалось получить лог для '{parser_name}'.\n\n{log_content}"

    # 4. Отправляем результат пользователю
    try:
        if document_to_send:
            await callback_query.message.delete()
            await callback_query.message.answer_document(
                document=document_to_send,
                caption=final_text,
                reply_markup=get_view_logs_keyboard()
            )
        else:
            await callback_query.message.edit_text(
                final_text,
                reply_markup=get_view_logs_keyboard(),
                parse_mode="Markdown"
            )
    except Exception as e:
        logging.error(f"Failed to send/edit message with log result for '{parser_name}' (user {user_id}): {e}")
        try:
             await callback_query.message.answer(
                 f"Не удалось обновить предыдущее сообщение.\nРезультат для '{parser_name}':\n{log_content if success else 'Ошибка получения лога.'}",
                 reply_markup=get_view_logs_keyboard()
                 )
        except Exception as final_e:
            logging.error(f"Failed even to send plain text result for log '{parser_name}': {final_e}")
            await callback_query.answer("Произошла ошибка при отображении лога.", show_alert=True)
