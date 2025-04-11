from aiogram.fsm.state import State, StatesGroup

class AuthState(StatesGroup):
    waiting_for_password = State() # Состояние ожидания ввода пароля

class UserState(StatesGroup):
    authorized = State()      # Состояние после успешной авторизации
    unauthorized = State()    # Начальное состояние или после выхода

class ScheduleSettingsState(StatesGroup):
    choosing_schedule = State()
    waiting_for_time = State()