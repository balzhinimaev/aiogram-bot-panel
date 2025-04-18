import logging
import asyncio
import urllib.parse
import json
from typing import Tuple, Dict, Any, Optional, List
import aiohttp

from config.settings import ApiConfig

logger = logging.getLogger(__name__)

async def _make_request(
    session: aiohttp.ClientSession,
    url: str,
    method: str = "GET",
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 120
) -> Tuple[bool, Dict | str, Optional[int]]:

    log_params_str = f" with params: {params}" if params else ""
    logger.info(f"Sending {method} request to: {url}{log_params_str}")
    status_code = None

    try:
        async with session.request(method, url, params=params, timeout=timeout) as response:
            status_code = response.status
            logger.info(f"Received status {status_code} for {url}")

            if 200 <= status_code < 300:
                try:
                    data = await response.json(content_type=None)
                    logger.debug(f"Response JSON for {url}: {data}")
                    if isinstance(data, dict) and 'status' not in data:
                        data['status'] = 'success'
                    if isinstance(data, dict) and data.get('status') == 'error':
                         logger.warning(f"API returned status 'error' inside 2xx response for {url}: {data}")
                         return False, data.get('message', 'API indicated an error in the response body.'), status_code
                    return True, data, status_code
                except (aiohttp.ContentTypeError, ValueError, json.JSONDecodeError):
                    text_data = await response.text()
                    logger.warning(f"Response for {url} (status {status_code}) is not valid JSON. Text: {text_data[:200]}")
                    return True, {"status": "success", "message": text_data or f"OK (Status {status_code})"}, status_code
            else:
                error_text = await response.text()
                logger.error(f"API Error {status_code} from {url}: {error_text}")
                try:
                    error_data = json.loads(error_text)
                    error_message = error_data.get('message', error_text)
                except json.JSONDecodeError:
                    error_message = error_text
                return False, f"API Error {status_code}: {error_message or 'Unknown API error'}", status_code

    except asyncio.TimeoutError:
        logger.error(f"Request timeout ({timeout}s) for {url}")
        return False, f"Error: Request timed out after {timeout} seconds", None
    except aiohttp.ClientConnectorError as e:
        logger.error(f"Connection error for {url}: {e}")
        return False, f"Error: Connection refused or DNS resolution failed for {url}", None
    except aiohttp.ClientError as e:
        logger.error(f"Client error during request to {url}: {e}")
        return False, f"Error: Client error: {e}", None
    except Exception as e:
        logger.exception(f"Unexpected error during request to {url}")
        return False, f"Error: An unexpected error occurred: {e}", None

async def start_parser(
    session: aiohttp.ClientSession, api_config: ApiConfig, parser_name: str
) -> Tuple[bool, str, Optional[int]]:
    base_url = api_config.base_url
    url = f"{base_url}/start_parser"
    params = {"parser": parser_name}
    logger.info(f"Requesting parser start: {parser_name} using URL {url}")
    success, result, status_code = await _make_request(session, url, params=params)
    message = result.get("message", str(result)) if isinstance(result, dict) else str(result)
    return success, f"Parser '{parser_name}': {message}", status_code

async def start_table_process(
    session: aiohttp.ClientSession, api_config: ApiConfig, method_name: str, args: Optional[List[str]] = None
) -> Tuple[bool, str, Optional[int]]:
    base_url = api_config.base_url
    url = f"{base_url}/start_table_process"
    params = {"method": method_name}
    if args:
        try:
            params["args"] = json.dumps(args)
            logger.info(f"Adding args parameter for method {method_name}: {params['args']}")
        except TypeError as e:
            logger.error(f"Failed to encode args {args} to JSON for method {method_name}: {e}")
            return False, f"Error encoding arguments for method '{method_name}'", None

    logger.info(f"Requesting table process start: {method_name} using URL {url}")
    success, result, status_code = await _make_request(session, url, params=params)
    message = result.get("message", str(result)) if isinstance(result, dict) else str(result)
    return success, f"Table process '{method_name}': {message}", status_code

async def get_parser_logs(
    session: aiohttp.ClientSession, api_config: ApiConfig, parser_name: str
) -> Tuple[bool, str]:
    base_url = api_config.base_url
    safe_parser_name = urllib.parse.quote(parser_name)
    url = f"{base_url}/get_logs/parser={safe_parser_name}"

    logger.info(f"Requesting logs for parser: {parser_name} from URL: {url}")
    success, result, _ = await _make_request(session, url, method="GET")

    if success:
        if isinstance(result, dict):
            log_message = result.get("message", None)
            if log_message is not None:
                logger.info(f"Successfully retrieved log for '{parser_name}'. Length: {len(str(log_message))}")
                return True, str(log_message)
            else:
                logger.warning(f"API response for logs '{parser_name}' is missing 'message' field: {result}")
                return True, f"Лог для '{parser_name}' не найден в ответе API (но запрос успешен)."
        else:
            logger.info(f"Received non-dictionary success response for logs '{parser_name}', returning as string.")
            return True, str(result)
    else:
        return False, f"Не удалось получить лог для '{parser_name}'.\nОшибка: {result}"

async def run_process_chain(
    session: aiohttp.ClientSession,
    api_config: ApiConfig,
    process_id: str,
    parsers: List[str],
    sync_methods: List[Tuple[str, Optional[List[str]]]]
) -> Tuple[bool, str, Optional[int]]:
    results_log = []
    last_status_code = None

    logger.info(f"[{process_id}] Starting process chain. Parsers: {parsers}")
    for parser_name in parsers:
        success, message, status_code = await start_parser(session, api_config, parser_name)
        last_status_code = status_code
        results_log.append(f"[{status_code or 'N/A'}] {message}")
        if not success:
            logger.warning(f"[{process_id}] Chain stopped due to parser '{parser_name}' failure (Status: {status_code}).")
            return False, "❌ Ошибка на этапе запуска парсера:\n" + "\n".join(results_log), status_code

    logger.info(f"[{process_id}] Parsers finished. Starting sync methods: {[m[0] for m in sync_methods]}")
    for method_name, args in sync_methods:
        success, message, status_code = await start_table_process(session, api_config, method_name, args)
        last_status_code = status_code
        results_log.append(f"[{status_code or 'N/A'}] {message}")
        if not success:
            logger.warning(f"[{process_id}] Chain stopped due to sync method '{method_name}' failure (Status: {status_code}).")
            return False, "❌ Ошибка на этапе синхронизации таблиц:\n" + "\n".join(results_log), status_code

    logger.info(f"[{process_id}] Process chain completed successfully.")
    final_message = "✅ Процесс успешно завершен.\n\n--- Детали выполнения ---\n" + "\n".join(results_log)
    return True, final_message, last_status_code

async def run_sale_process(session: aiohttp.ClientSession, api_config: ApiConfig) -> Tuple[bool, str, Optional[int]]:
    logging.info("Running 'Sale' process chain...")
    parsers = ["PackageIdSaleInfo", "BundleIdSaleInfo"]
    sync_methods = [
        ("set_final_price", None),
        ("set_delivery_region", None),
        ("set_shop_price", ["main"])
    ]
    return await run_process_chain(session, api_config, "Sale", parsers, sync_methods)

async def run_currency_info_process(session: aiohttp.ClientSession, api_config: ApiConfig) -> Tuple[bool, str, Optional[int]]:
    logging.info("Running 'CurrencyInfo' process chain...")
    parsers = ["CurrencyInfo"]
    sync_methods = [
        ("set_delivery_region", None),
        ("set_shop_price", ["main"])
    ]
    return await run_process_chain(session, api_config, "CurrencyInfo", parsers, sync_methods)

async def run_package_id_price_process(session: aiohttp.ClientSession, api_config: ApiConfig) -> Tuple[bool, str, Optional[int]]:
    logging.info("Running 'PackageIdPrice' process chain...")
    parsers = ["PackageIdPrice"]
    sync_methods = [
        ("set_final_price", None),
        ("set_delivery_region", None),
        ("set_shop_price", ["main"])
    ]
    return await run_process_chain(session, api_config, "PackageIdPrice", parsers, sync_methods)