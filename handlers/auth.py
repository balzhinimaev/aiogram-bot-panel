import logging

from aiogram import Router, F, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext

from config.settings import settings
from states.user_states import AuthState, UserState
from keyboards.inline import get_main_menu_keyboard, get_cancel_keyboard

auth_router = Router()

# Этот фильтр будет проверять, является ли пользователь админом
# Его можно использовать для защиты всех админских хэндлеров
class AdminFilter:
    def __call__(self, message: types.Message) -> bool:
        return message.from_user.id == settings.bot.admin_id

# Обработчик команды /start для администратора
@auth_router.message(Command("start"), AdminFilter())
async def admin_start(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    user_data = await state.get_data() # Получаем данные из FSM Storage
    is_authenticated = user_data.get("is_authenticated", False) # Проверяем флаг

    logging.info(f"Admin {message.from_user.id} started. Current state: {current_state}, Authenticated: {is_authenticated}")

    if is_authenticated and current_state == UserState.authorized:
        await message.answer(
            "Вы уже авторизованы. Добро пожаловать!",
            reply_markup=get_main_menu_keyboard()
        )
    else:
        # Если не авторизован или состояние не установлено/сброшено, запрашиваем пароль
        await message.answer(
            "Добро пожаловать, Администратор! Пожалуйста, введите пароль для доступа:",
            reply_markup=get_cancel_keyboard() # Добавим кнопку отмены
        )
        await state.set_state(AuthState.waiting_for_password)
        # Сбрасываем флаг аутентификации на всякий случай
        await state.update_data(is_authenticated=False)

# Обработчик для ввода пароля
@auth_router.message(StateFilter(AuthState.waiting_for_password), F.text)
async def process_password(message: types.Message, state: FSMContext):
    password = message.text
    # удалить сообщение с паролем из чата
    await message.delete()

    if password == settings.bot.password:
        logging.info(f"Admin {message.from_user.id} entered correct password.")

        await state.update_data(is_authenticated=True)
        await state.set_state(UserState.authorized)
        await message.answer(
            "Авторизация прошла успешно! ✅\nГлавное меню:",
            reply_markup=get_main_menu_keyboard()
        )
    else:
        logging.warning(f"Admin {message.from_user.id} entered incorrect password.")
        await message.answer(
            "Неверный пароль. ❌ Попробуйте еще раз или нажмите 'Отмена'.",
            reply_markup=get_cancel_keyboard()
        )

# Обработчик кнопки/команды отмены ввода пароля
@auth_router.callback_query(StateFilter(AuthState.waiting_for_password), F.data == "cancel_fsm")
async def cancel_password_input(callback_query: types.CallbackQuery, state: FSMContext):
    logging.info(f"Admin {callback_query.from_user.id} cancelled password input.")
    await state.clear() # Сбрасываем состояние и данные
    await callback_query.message.edit_text("Ввод пароля отменен.")
    await callback_query.answer()

# Обработчик для не-администраторов
@auth_router.message(Command("start"))
async def non_admin_start(message: types.Message):
    user_id = message.from_user.id
    logging.warning(f"Non-admin user {user_id} tried to use /start.")
    await message.answer(f"Извините, доступ к этому боту ограничен. Ваш ID: {user_id}")