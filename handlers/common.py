import logging

from aiogram import Router, F, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext

from states.user_states import UserState
from handlers.auth import AdminFilter # Импортируем фильтр админа

common_router = Router()

common_router.message.filter(AdminFilter())
common_router.callback_query.filter(AdminFilter())

# Обработчик команды /logout и кнопки "Выход"
@common_router.message(Command("logout"))
@common_router.callback_query(F.data == "logout")
async def handle_logout(event: types.Message | types.CallbackQuery, state: FSMContext):
    user_id = event.from_user.id
    logging.info(f"Admin {user_id} initiated logout.")

    await state.clear()

    message_text = "Вы вышли из системы. Для повторного входа используйте /start."

    if isinstance(event, types.Message):
        await event.answer(message_text)
    elif isinstance(event, types.CallbackQuery):

        await event.message.edit_text(message_text, reply_markup=None)
        await event.answer()

# Обработчик для неизвестных команд/сообщений от админа в авторизованном состоянии
@common_router.message(StateFilter(UserState.authorized))
async def handle_unknown_authorized(message: types.Message):
    logging.debug(f"Received unknown message from admin {message.from_user.id} in authorized state: {message.text}")
    await message.reply("Неизвестная команда. Используйте кнопки главного меню.")

# Обработчик "блуждающих" колбэков (если пользователь нажмет старую кнопку)
@common_router.callback_query()
async def handle_unknown_callback(callback_query: types.CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    logging.warning(f"Received unknown callback '{callback_query.data}' from admin {callback_query.from_user.id} in state {current_state}")
    await callback_query.answer("Эта кнопка больше не активна или команда неизвестна.", show_alert=True)