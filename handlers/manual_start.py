import logging
import aiohttp

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

manual_start_router.message.filter(AdminFilter(), StateFilter(UserState.authorized))
manual_start_router.callback_query.filter(AdminFilter(), StateFilter(UserState.authorized))

# Обработчик нажатия кнопки "Запуск парсеров вручную" из главного меню
@manual_start_router.callback_query(F.data == "manual_start")
async def show_manual_start_menu(callback_query: types.CallbackQuery):
    """
    Отображает подменю с кнопками для ручного запуска парсеров.
    """
    user_id = callback_query.from_user.id
    logger.info(f"Администратор {user_id} открыл меню ручного запуска.")
    try:
        await callback_query.message.edit_text(
            "Выберите процесс для ручного запуска:",
            reply_markup=get_manual_start_keyboard() # Показываем клавиатуру выбора
        )
    except Exception as e:
        logger.error(f"Ошибка редактирования сообщения для меню ручного запуска (user {user_id}): {e}")
        await callback_query.answer("Не удалось обновить меню.", show_alert=True)
        return
    await callback_query.answer()

# Обработчик нажатия кнопки "Назад" в меню ручного запуска
@manual_start_router.callback_query(F.data == "main_menu")
async def back_to_main_menu(callback_query: types.CallbackQuery, state: FSMContext): # Добавили state
    """
    Возвращает пользователя в главное меню из подменю ручного запуска.
    """
    user_id = callback_query.from_user.id
    logger.info(f"Администратор {user_id} вернулся в главное меню из ручного запуска.")
    try:
        await callback_query.message.edit_text(
            "Главное меню:",
            reply_markup=get_main_menu_keyboard()
        )
        await state.set_state(UserState.authorized)
    except Exception as e:
        logger.error(f"Ошибка редактирования сообщения для главного меню (user {user_id}): {e}")
        await callback_query.answer("Не удалось вернуться в главное меню.", show_alert=True)
        return
    await callback_query.answer()


# Обработчик нажатия кнопок запуска конкретных процессов
@manual_start_router.callback_query(F.data.startswith("run_parser:"))
async def handle_run_parser(
    callback_query: types.CallbackQuery,
    http_session: aiohttp.ClientSession,
    api_settings: ApiConfig
):
    """
    Запускает выбранный процесс парсинга/синхронизации через API-клиент.
    Показывает статус выполнения, результат пользователю и обновляет статус последнего запуска.
    """
    try:
        process_name = callback_query.data.split(":")[-1]
        if not process_name: # Проверка на пустую строку после двоеточия
             raise IndexError("Имя процесса пустое")
    except IndexError:
        logger.error(f"Неверный формат callback_data для запуска парсера: {callback_query.data}")
        await callback_query.answer("Ошибка: Некорректные данные кнопки.", show_alert=True)
        return

    user_id = callback_query.from_user.id
    logger.info(f"Администратор {user_id} запросил ручной запуск процесса '{process_name}'.")

    # 1. Отправляем предварительное сообщение пользователю
    try:
        await callback_query.message.edit_text(
            f"⏳ Запускаю процесс '{process_name}'... Пожалуйста, подождите.",
            reply_markup=None  # Убираем клавиатуру на время выполнения
        )
        await callback_query.answer(f"Запуск '{process_name}'...")
    except Exception as e:
        logger.error(f"Ошибка редактирования сообщения перед запуском '{process_name}' (user {user_id}): {e}")

    # 2. Выполняем сам процесс через API
    success = False
    result_message = "Произошла неизвестная ошибка при обращении к API."

    try:
        if process_name == "Sale":
            success, result_message = await api_client.run_sale_process(http_session, api_settings)
        elif process_name == "CurrencyInfo":
            success, result_message = await api_client.run_currency_info_process(http_session, api_settings)
        elif process_name == "PackageIdPrice":
            success, result_message = await api_client.run_package_id_price_process(http_session, api_settings)
        else:
            logger.error(f"Получено неизвестное имя процесса '{process_name}' от {user_id}")
            result_message = f"Ошибка: Неизвестный тип процесса '{process_name}'."
            success = False

    except Exception as e:
        logger.exception(f"Критическая ошибка при выполнении процесса '{process_name}' для {user_id}")
        result_message = f"Критическая ошибка при запуске '{process_name}'. Подробности в логах сервера."
        success = False

    try:
        update_last_status(process_name, success, result_message)
        logger.info(f"Статус последнего запуска для '{process_name}' обновлен (Успех: {success}).")
    except Exception as status_e:
        logger.exception(f"Ошибка обновления статуса последнего запуска для '{process_name}'")

    # 3. Формируем и отправляем итоговое сообщение пользователю
    final_text = ""
    if success:
        # Если API клиент вернул success=True
        final_text = f"✅ Процесс '{process_name}' успешно завершен.\n\n{result_message}"
        logger.info(f"Ручной запуск '{process_name}' завершен успешно для {user_id}.")
    else:
        # Если API клиент вернул success=False или произошла ошибка выше
        # В result_message уже должно быть сообщение об ошибке
        final_text = f"❌ Ошибка при выполнении процесса '{process_name}'.\n\n{result_message}"
        logger.error(f"Ручной запуск '{process_name}' завершился ошибкой для {user_id}. Причина: {result_message}")

    # 4. Пытаемся обновить исходное сообщение результатом и вернуть клавиатуру
    try:
        await callback_query.message.edit_text(
            final_text,
            reply_markup=get_manual_start_keyboard() # Снова показываем клавиатуру выбора процесса
        )
    except Exception as e:
        logger.error(f"Ошибка редактирования сообщения после завершения '{process_name}' (user {user_id}): {e}")
        # Если редактирование не удалось (например, сообщение слишком старое),
        # отправляем результат новым сообщением.
        try:
            await callback_query.message.answer(
                final_text,
                reply_markup=get_manual_start_keyboard()
            )
        except Exception as e2:
            # Если и новое сообщение отправить не удалось
            logger.error(f"Не удалось отправить новое сообщение после завершения '{process_name}' (user {user_id}): {e2}")
            # Уведомляем пользователя через callback answer
            await callback_query.answer("Процесс завершен, но не удалось отобразить результат.", show_alert=True)