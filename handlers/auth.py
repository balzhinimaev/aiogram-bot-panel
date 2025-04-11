# handlers/auth.py
import logging
from typing import Union # Добавим Union для аннотации

from aiogram import Router, F, types, Bot # Убедимся, что Bot импортирован, если нужен
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext

# Импортируем настройки и состояния
from config.settings import settings
from states.user_states import AuthState, UserState
# Импортируем клавиатуры
from keyboards.inline import get_main_menu_keyboard, get_cancel_keyboard

# Получаем логгер
logger = logging.getLogger(__name__)

# Создаем роутер для авторизации
auth_router = Router()

# --- Фильтр для проверки прав администратора ---
class AdminFilter:
    """
    Фильтр, который проверяет, присутствует ли ID пользователя
    в списке администраторов из настроек (settings.bot.admin_ids).
    """
    def __call__(self, event: Union[types.Message, types.CallbackQuery]) -> bool:
        user_id = event.from_user.id
        admin_list = settings.bot.admin_ids
        logger.debug(f"AdminFilter проверка: User ID={user_id}, Список админов={admin_list}")
        is_admin = user_id in admin_list
        if not is_admin:
             logger.warning(f"Доступ запрещен (не админ): User ID={user_id}")
        else:
             logger.debug(f"Доступ разрешен (админ): User ID={user_id}")
        return is_admin
# --- Конец фильтра ---

# --- Хэндлеры ---

# 1. Обработчик команды /start ДЛЯ АДМИНИСТРАТОРА
# Сначала проверяется команда, затем фильтр AdminFilter
@auth_router.message(Command("start"), AdminFilter()) # Применяем фильтр ЗДЕСЬ
async def admin_start(message: types.Message, state: FSMContext):
    """Обрабатывает /start от пользователя, который прошел AdminFilter."""
    user_id = message.from_user.id
    current_state = await state.get_state()
    user_data = await state.get_data()
    is_authenticated = user_data.get("is_authenticated", False)

    logger.info(f"Администратор {user_id} запустил /start. Состояние: {current_state}, Авторизован: {is_authenticated}")

    if is_authenticated and current_state == UserState.authorized:
        # Если уже авторизован, просто показываем меню
        await message.answer(
            "Вы уже авторизованы. Добро пожаловать!",
            reply_markup=get_main_menu_keyboard()
        )
    else:
        # Если не авторизован или состояние некорректно, запрашиваем пароль
        logger.info(f"Запрос пароля у администратора {user_id}.")
        await message.answer(
            "Добро пожаловать, Администратор! Пожалуйста, введите пароль для доступа:",
            reply_markup=get_cancel_keyboard() # Кнопка Отмена
        )
        # Устанавливаем состояние ожидания пароля
        await state.set_state(AuthState.waiting_for_password)
        # Сбрасываем флаг аутентификации на всякий случай
        await state.update_data(is_authenticated=False)

# 2. Обработчик ввода пароля
@auth_router.message(StateFilter(AuthState.waiting_for_password), F.text)
async def process_password(message: types.Message, state: FSMContext):
    """Обрабатывает ввод пароля в состоянии waiting_for_password."""
    user_id = message.from_user.id
    password = message.text
    # Важно: удаляем сообщение с паролем из чата для безопасности
    try: await message.delete()
    except Exception: logger.warning(f"Не удалось удалить сообщение с паролем от {user_id}")

    if password == settings.bot.password:
        # Пароль верный
        logger.info(f"Администратор {user_id}: Успешная авторизация по паролю.")
        await state.update_data(is_authenticated=True) # Сохраняем флаг авторизации
        await state.set_state(UserState.authorized) # Устанавливаем основное состояние админа
        await message.answer( # Отправляем подтверждение и меню (новым сообщением, т.к. старое удалено)
            "Авторизация прошла успешно! ✅\nГлавное меню:",
            reply_markup=get_main_menu_keyboard()
        )
    else:
        # Пароль неверный
        logger.warning(f"Администратор {user_id}: Введен неверный пароль.")
        # Отправляем сообщение об ошибке (тоже новым сообщением)
        await message.answer(
            "Неверный пароль. ❌ Попробуйте еще раз или нажмите 'Отмена'.",
            reply_markup=get_cancel_keyboard()
        )
        # Остаемся в состоянии AuthState.waiting_for_password

# 3. Обработчик кнопки "Отмена" при вводе пароля
@auth_router.callback_query(F.data == "cancel_fsm", StateFilter(AuthState.waiting_for_password))
async def cancel_password_input(callback_query: types.CallbackQuery, state: FSMContext):
    """Отменяет процесс ввода пароля."""
    user_id = callback_query.from_user.id
    logger.info(f"Администратор {user_id} отменил ввод пароля.")
    await state.clear() # Полностью сбрасываем состояние
    try:
        await callback_query.message.edit_text("Ввод пароля отменен. Для входа используйте /start.")
    except Exception: # Если не удалось отредактировать
        await callback_query.message.answer("Ввод пароля отменен. Для входа используйте /start.")
    await callback_query.answer()

# 4. Обработчик команды /start ДЛЯ НЕ-АДМИНИСТРАТОРОВ
# Он должен идти ПОСЛЕ хэндлера admin_start
# Фильтр Command("start") сработает только если НЕ прошел AdminFilter у предыдущего хэндлера
@auth_router.message(Command("start"))
async def non_admin_start(message: types.Message):
    """Обрабатывает /start от пользователей, не прошедших AdminFilter."""
    user_id = message.from_user.id
    # Логируем попытку доступа
    logger.warning(f"Пользователь {user_id} (не админ) попытался использовать /start.")
    # Отправляем сообщение об отказе
    await message.answer(f"Извините, доступ к этому боту ограничен. Ваш ID: {user_id}")