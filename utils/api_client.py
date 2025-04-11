import logging
import asyncio
import urllib.parse
import json
from typing import Tuple, Dict, Any, Optional, List
import aiohttp

from config.settings import ApiConfig

# --- Вспомогательная функция для выполнения HTTP-запросов ---
async def _make_request(
    session: aiohttp.ClientSession,
    url: str,
    method: str = "GET",
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 60
) -> Tuple[bool, Dict | str]:
    """
    Отправляет асинхронный HTTP-запрос и обрабатывает базовые ответы/ошибки.

    Args:
        session: Экземпляр aiohttp.ClientSession.
        url: Полный URL эндпоинта.
        method: HTTP метод (GET, POST, etc.).
        params: Словарь GET-параметров (для GET запросов).
        timeout: Таймаут ожидания ответа.

    Returns:
        Кортеж (success: bool, result: dict | str), где result - это
        JSON-ответ в виде словаря при успехе, или строка с описанием ошибки
        при неудаче.
    """

    log_params_str = f" with params: {params}" if params else ""
    logging.info(f"Sending {method} request to: {url}{log_params_str}")

    try:
        # Выполняем асинхронный запрос с использованием сессии
        async with session.request(method, url, params=params, timeout=timeout) as response:
            logging.info(f"Received status {response.status} for {url}")

            # Проверяем успешность ответа (коды 2xx)
            if 200 <= response.status < 300:
                try:
                    # Пытаемся прочитать ответ как JSON
                    data = await response.json(content_type=None) # для большей гибкости
                    logging.debug(f"Response JSON for {url}: {data}")
                    if isinstance(data, dict) and 'status' not in data:
                        data['status'] = 'success'
                    return True, data
                except (aiohttp.ContentTypeError, ValueError, json.JSONDecodeError) as json_error:
                    logging.warning(f"Response for {url} is not valid JSON (status {response.status}): {json_error}")
                    text_data = await response.text()
                    logging.debug(f"Response Text for {url}: {text_data}")
                    return True, {"status": "success", "message": text_data or "OK"}
            else:
                # Если статус код указывает на ошибку (4xx, 5xx)
                error_text = await response.text()
                logging.error(f"API Error {response.status} from {url}: {error_text}")
                return False, f"API Error {response.status}: {error_text or 'Unknown API error'}"

    except asyncio.TimeoutError:
        logging.error(f"Request timeout ({timeout}s) for {url}")
        return False, f"Error: Request timed out after {timeout} seconds"
    except aiohttp.ClientConnectorError as e:
        logging.error(f"Connection error for {url}: {e}")
        return False, f"Error: Connection refused or DNS resolution failed for {url}"
    except aiohttp.ClientError as e:
        logging.error(f"Client error during request to {url}: {e}")
        return False, f"Error: Client error: {e}"
    except Exception as e:
        logging.exception(f"Unexpected error during request to {url}")
        return False, f"Error: An unexpected error occurred: {e}"

async def start_parser(
    session: aiohttp.ClientSession, api_config: ApiConfig, parser_name: str
) -> Tuple[bool, str]:
    """
    Запускает указанный парсер через API.
    Использует единый базовый URL из api_config.
    """
    base_url = api_config.base_url
    url = f"{base_url}/start_parser"
    params = {"parser": parser_name} # GET-параметр с именем парсера
    logging.info(f"Requesting parser start: {parser_name} using URL {base_url}")

    # Выполняем запрос через вспомогательную функцию
    success, result = await _make_request(session, url, params=params)

    # Формируем сообщение для бота на основе ответа
    message = result.get("message", str(result)) if isinstance(result, dict) else str(result)
    return success, f"Parser '{parser_name}': {message}"

async def start_table_process(
    session: aiohttp.ClientSession, api_config: ApiConfig, method_name: str, args: Optional[List[str]] = None
) -> Tuple[bool, str]:
    """
    Запускает указанный метод обработки таблицы через API.
    Использует единый базовый URL из api_config.
    При необходимости передает параметр 'args' как JSON-строку.
    """
    base_url = api_config.base_url
    url = f"{base_url}/start_table_process"
    params = {"method": method_name} # Обязательный GET-параметр с именем метода

    # Добавляем параметр 'args'
    if args:
        try:
            params["args"] = json.dumps(args)
            logging.info(f"Adding args parameter for method {method_name}: {params['args']}")
        except TypeError as e:
            logging.error(f"Failed to encode args {args} to JSON for method {method_name}: {e}")
            return False, f"Error encoding arguments for method '{method_name}'"

    # logging.info(f"{method_name} using URL {base_url}")
    success, result = await _make_request(session, url, params=params)

    # Формируем сообщение для бота на основе ответа
    message = result.get("message", str(result)) if isinstance(result, dict) else str(result)
    return success, f"Table process '{method_name}': {message}"

async def get_parser_logs(
    session: aiohttp.ClientSession, api_config: ApiConfig, parser_name: str
) -> Tuple[bool, str]:
    """
    Запрашивает лог для указанного парсера через API.
    Использует единый базовый URL из api_config.
    Ожидает лог в поле 'message' ответа.
    """
    base_url = api_config.base_url
    safe_parser_name = urllib.parse.quote(parser_name)
    url = f"{base_url}/get_logs/parser={safe_parser_name}"
    logging.info(f"Requesting logs for parser: {parser_name} from URL: {url}")
    success, result = await _make_request(session, url, method="GET")

    if success:
        if isinstance(result, dict):
            log_message = result.get("message", None)
            if log_message is not None:
                logging.info(f"Successfully retrieved log for '{parser_name}'. Length: {len(str(log_message))}")
                return True, str(log_message) # Возвращаем содержимое 'message' как строку
            else:
                logging.warning(f"API response for logs '{parser_name}' is missing 'message' field: {result}")
                return True, f"Лог для '{parser_name}' не найден в ответе API."
        else:
            logging.warning(f"Received non-dictionary success response for logs '{parser_name}': {result}")
            return True, str(result)
    else:
        log_message = str(result)
        return False, f"Не удалось получить лог для '{parser_name}'.\nОшибка: {log_message}"


# --- Функции для запуска полных цепочек процессов ---
# Эти функции используют приведенные выше start_parser, start_table_process,
# поэтому им не нужно знать про конкретные URL, они просто передают api_config дальше.

async def run_process_chain(
    session: aiohttp.ClientSession,
    api_config: ApiConfig,
    parsers: List[str],
    sync_methods: List[Tuple[str, Optional[List[str]]]]
) -> Tuple[bool, str]:
    """
    Запускает последовательность парсеров и методов синхронизации.
    Останавливается при первой ошибке и возвращает лог выполнения.

    Args:
        session: Экземпляр aiohttp.ClientSession.
        api_config: Конфигурация API.
        parsers: Список имен парсеров для запуска.
        sync_methods: Список кортежей (method_name, args) для синхронизации.

    Returns:
        Кортеж (success: bool, message: str) с результатом выполнения цепочки.
    """
    results_log = [] # Список для записи результатов каждого шага

    # 1. Этап запуска парсеров
    logging.info(f"Starting process chain. Parsers: {parsers}")
    for parser_name in parsers:
        success, message = await start_parser(session, api_config, parser_name)
        results_log.append(message) # Добавляем результат шага в лог
        if not success:
            # Если парсер не запустился успешно, прерываем цепочку
            logging.warning(f"Chain stopped due to parser '{parser_name}' failure.")
            return False, "Ошибка на этапе запуска парсера:\n" + "\n".join(results_log)

    # 2. Этап запуска синхронизирующих функций
    logging.info(f"Parsers finished. Starting sync methods: {[m[0] for m in sync_methods]}")
    for method_name, args in sync_methods:
        success, message = await start_table_process(session, api_config, method_name, args)
        results_log.append(message) # Добавляем результат шага в лог
        if not success:
            # Если синхронизация не удалась, прерываем цепочку
            logging.warning(f"Chain stopped due to sync method '{method_name}' failure.")
            return False, "Ошибка на этапе синхронизации таблиц:\n" + "\n".join(results_log)

    # Если все шаги прошли успешно
    logging.info("Process chain completed successfully.")
    # Формируем итоговое сообщение об успехе с деталями
    final_message = "✅ Процесс успешно завершен.\n\n--- Детали выполнения ---\n" + "\n".join(results_log)
    return True, final_message

# --- Функции цепочек ---

async def run_sale_process(session: aiohttp.ClientSession, api_config: ApiConfig) -> Tuple[bool, str]:
    """ полная цепочка для процесса 'Sale'."""
    logging.info("Running 'Sale' process chain...")
    parsers = ["PackageIdSaleInfo", "BundleIdSaleInfo"]
    sync_methods = [
        ("set_final_price", None),
        ("set_delivery_region", None),
        ("set_shop_price", ["main"])
    ]
    return await run_process_chain(session, api_config, parsers, sync_methods)

async def run_currency_info_process(session: aiohttp.ClientSession, api_config: ApiConfig) -> Tuple[bool, str]:
    logging.info("Running 'CurrencyInfo' process chain...")
    parsers = ["CurrencyInfo"]
    sync_methods = [
        ("set_delivery_region", None),
        ("set_shop_price", ["main"])
    ]
    return await run_process_chain(session, api_config, parsers, sync_methods)

async def run_package_id_price_process(session: aiohttp.ClientSession, api_config: ApiConfig) -> Tuple[bool, str]:
    logging.info("Running 'PackageIdPrice' process chain...")
    parsers = ["PackageIdPrice"]
    sync_methods = [
        ("set_final_price", None),
        ("set_delivery_region", None),
        ("set_shop_price", ["main"])
    ]
    return await run_process_chain(session, api_config, parsers, sync_methods)