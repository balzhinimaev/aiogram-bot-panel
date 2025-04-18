import logging
import aiohttp
import asyncio

from aiogram import Router, F, types
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext

from keyboards.inline import get_manual_start_keyboard, get_main_menu_keyboard
from states.user_states import UserState
from handlers.auth import AdminFilter
from utils import api_client
from config.settings import ApiConfig
from utils.status_tracker import update_last_status

logger = logging.getLogger(__name__)
manual_start_router = Router()

PARSER_EXECUTION_LOCK = asyncio.Lock()

manual_start_router.message.filter(AdminFilter(), StateFilter(UserState.authorized))
manual_start_router.callback_query.filter(AdminFilter(), StateFilter(UserState.authorized))

@manual_start_router.callback_query(F.data == "manual_start")
async def show_manual_start_menu(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    logger.info(f"Admin {user_id} opened manual start menu.")
    try:
        if PARSER_EXECUTION_LOCK.locked():
            await callback_query.message.edit_text(
                "⏳ В данный момент выполняется другой процесс. Меню ручного запуска временно недоступно.\n\nПожалуйста, подождите...",
                reply_markup=None
            )
            await callback_query.answer("Выполняется другой процесс, подождите.", show_alert=True)
        else:
            await callback_query.message.edit_text(
                "Выберите процесс для ручного запуска:",
                reply_markup=get_manual_start_keyboard()
            )
            await callback_query.answer()
    except Exception as e:
        logger.error(f"Error editing message for manual start menu (user {user_id}): {e}")
        await callback_query.answer("Failed to update menu.", show_alert=True)

@manual_start_router.callback_query(F.data == "main_menu")
async def back_to_main_menu(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    logger.info(f"Admin {user_id} returned to main menu from manual start.")
    try:
        if PARSER_EXECUTION_LOCK.locked():
             await callback_query.message.edit_text(
                "Главное меню:\n\n_(Внимание: в данный момент выполняется процесс ручного запуска)_",
                reply_markup=get_main_menu_keyboard()
            )
        else:
             await callback_query.message.edit_text(
                "Главное меню:",
                reply_markup=get_main_menu_keyboard()
            )
        await state.set_state(UserState.authorized)
    except Exception as e:
        logger.error(f"Error editing message for main menu (user {user_id}): {e}")
        await callback_query.answer("Failed to return to main menu.", show_alert=True)
    await callback_query.answer()

@manual_start_router.callback_query(F.data.startswith("run_parser:"))
async def handle_run_parser(
    callback_query: types.CallbackQuery,
    http_session: aiohttp.ClientSession,
    api_settings: ApiConfig
):
    try:
        process_name = callback_query.data.split(":", 1)[-1]
        if not process_name:
             raise IndexError("Process name is empty")
    except IndexError:
        logger.error(f"Invalid callback_data format: {callback_query.data}")
        await callback_query.answer("Error: Invalid button data.", show_alert=True)
        return

    user_id = callback_query.from_user.id
    logger.info(f"Admin {user_id} requested manual start for '{process_name}'. Attempting to acquire lock...")

    if PARSER_EXECUTION_LOCK.locked():
        logger.warning(f"'{process_name}' start for {user_id} delayed: lock is busy.")
        await callback_query.answer(f"Another process is running. Your request '{process_name}' is queued.", show_alert=True)

    async with PARSER_EXECUTION_LOCK:
        logger.info(f"Admin {user_id} acquired lock for '{process_name}'.")

        try:
            await callback_query.message.edit_text(
                f"⏳ Выполняю процесс '{process_name}'... Пожалуйста, подождите.\n\n(Другие запуски временно невозможны)",
                reply_markup=None
            )
            await callback_query.answer(f"Starting '{process_name}'...")
        except Exception as e:
            logger.warning(f"Failed to edit message before starting '{process_name}' (user {user_id}): {e}")

        success = False
        api_status_code = None
        result_message = "Unknown error occurred when calling the API client."

        try:
            if process_name == "Sale":
                success, result_message, api_status_code = await api_client.run_sale_process(http_session, api_settings)
            elif process_name == "CurrencyInfo":
                success, result_message, api_status_code = await api_client.run_currency_info_process(http_session, api_settings)
            elif process_name == "PackageIdPrice":
                success, result_message, api_status_code = await api_client.run_package_id_price_process(http_session, api_settings)
            else:
                logger.error(f"Unknown process name '{process_name}' requested by {user_id}")
                result_message = f"Error: Unknown process type '{process_name}'."
                success = False

        except Exception as e:
            logger.exception(f"Critical error during API client call for '{process_name}' (user {user_id}): {e}")
            result_message = f"Critical error during '{process_name}' execution. See server logs."
            success = False

        try:
            update_last_status(process_name, success, result_message)
            logger.info(f"Last run status for '{process_name}' updated (API Success: {success}).")
        except Exception as status_e:
            logger.exception(f"Error updating last run status for '{process_name}': {status_e}")

        final_text = ""
        status_emoji = "✅" if success else "❌"
        status_text = "успешно завершен" if success else "завершен с ошибкой"

        final_text = f"{status_emoji} Процесс '{process_name}' {status_text}.\n\n"
        final_text += result_message
        if not success and api_status_code:
            final_text += f"\n(Код ответа последнего шага: {api_status_code})"

        if success:
             logger.info(f"Manual run '{process_name}' (user {user_id}) completed successfully (API OK).")
        else:
             logger.error(f"Manual run '{process_name}' (user {user_id}) failed. API Success: {success}. Status: {api_status_code}. Message: {result_message}")

        try:
            await callback_query.message.edit_text(
                final_text,
                reply_markup=get_manual_start_keyboard()
            )
        except Exception as e:
            logger.error(f"Failed to edit message after '{process_name}' completion (user {user_id}): {e}. Sending new message.")
            try:
                await callback_query.message.answer(
                    final_text,
                    reply_markup=get_manual_start_keyboard()
                )
            except Exception as e2:
                logger.error(f"Failed to send new message after '{process_name}' completion (user {user_id}): {e2}")
                try:
                    await callback_query.answer("Process finished, but failed to display result.", show_alert=True)
                except Exception:
                    pass

    logger.info(f"Lock released after handling '{process_name}' for user {user_id}.")