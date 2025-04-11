const express = require('express');
const app = express();
const PORT = 8081; // Основной порт, на котором слушает этот mock-сервер
const HOST = '0.0.0.0';

app.use(express.json());

// Хранилище для имитации логов
const mockLogs = {
    Sale: [],
    CurrencyInfo: [],
    PackageIdPrice: [],
    // Добавим парсеры из цепочки Sale для полноты, если бот будет их запрашивать
    PackageIdSaleInfo: [],
    BundleIdSaleInfo: []
};

// Функция добавления лога
function addLog(parserName, message) {
    // Находим ключ, даже если он не совпадает по регистру (на всякий случай)
    const logKey = Object.keys(mockLogs).find(k => k.toLowerCase() === parserName.toLowerCase());
    if (logKey) {
        const timestamp = new Date().toISOString();
        mockLogs[logKey].push(`[${timestamp}] ${message}`);
        if (mockLogs[logKey].length > 20) { // Увеличим немного лимит
            mockLogs[logKey].shift();
        }
        console.log(`Log added for ${logKey}: ${message}`);
    } else {
        console.warn(`Attempted to add log for unknown parser: ${parserName}`);
    }
}

console.log('Initializing Mock API...');

// --- Эндпоинты ---

// 1. Запуск парсера (/start_parser)
app.get('/start_parser', (req, res) => {
    const parserName = req.query.parser;
    const remotePort = req.connection.remotePort; // Порт, с которого пришел запрос (для отладки)
    console.log(`\n[${new Date().toISOString()}] Received /start_parser request for: ${parserName} from port ${remotePort}`);

    if (!parserName) {
        console.error('Error: Missing parser name');
        return res.status(400).json({ status: 400, message: 'Query parameter "parser" is required' });
    }

    // Проверяем, есть ли такой парсер в наших логах (для имитации)
    const logKey = Object.keys(mockLogs).find(k => k.toLowerCase() === parserName.toLowerCase());
    if (!logKey) {
         console.warn(`Warning: Unknown parser name requested: ${parserName}. Proceeding anyway.`);
    }

    const effectiveParserName = logKey || parserName; // Используем найденный ключ или исходное имя
    addLog(effectiveParserName, `Parser start requested.`);

    // Имитация времени выполнения (1-4 секунды)
    const delay = Math.random() * 3000 + 1000;
    console.log(`Simulating work for ${parserName} for ${delay.toFixed(0)}ms...`);

    setTimeout(() => {
        const shouldFail = effectiveParserName === 'CurrencyInfo' && Math.random() < 0.2;

        if (shouldFail) {
             console.log(`Simulating FAILURE for parser: ${parserName}`);
             addLog(effectiveParserName, `Parser execution FAILED.`);
             res.status(500).json({
                 status: 500,
                 message: `Mock error during ${parserName} parsing`,
                 parser: parserName
             });
        } else {
            console.log(`Simulating SUCCESS for parser: ${parserName}`);
            addLog(effectiveParserName, `Parser execution finished successfully.`);
            res.status(200).json({
                status: 200,
                message: `Parser ${parserName} started and finished successfully (mock).`,
                parser: parserName
            });
        }
    }, delay);
});

// 2. Запуск синхронизирующей функции (/start_table_process)
app.get('/start_table_process', (req, res) => {
    const methodName = req.query.method;
    const args = req.query.args; // Читаем параметр args
    console.log(`\n[${new Date().toISOString()}] Received /start_table_process request for: ${methodName}, args: ${args}`);

    if (!methodName) {
        console.error('Error: Missing method name');
        return res.status(400).json({ status: 400, message: 'Query parameter "method" is required' });
    }

    // Проверяем наличие args для set_shop_price (для логирования)
    if (methodName === 'set_shop_price' && args !== '["main"]') {
        console.warn(`Warning: Expected args='["main"]' for set_shop_price, but received: ${args}`);
    }

    // Имитация времени выполнения (0.5 - 1.5 секунды)
    const delay = Math.random() * 1000 + 500;
    console.log(`Simulating work for ${methodName} for ${delay.toFixed(0)}ms...`);

    setTimeout(() => {
        console.log(`Simulating SUCCESS for table process: ${methodName}`);
        // Можно добавить логирование и для этих процессов
        res.status(200).json({
            status: 200,
            message: `Table process ${methodName} finished successfully (mock).`,
            method: methodName
        });
    }, delay);
});

// 3. Получение логов (/get_logs/parser=...)
app.get(/\/get_logs\/parser=(.+)/, (req, res) => {
    const parserName = req.params[0];
    console.log(`\n[${new Date().toISOString()}] Received /get_logs request for: ${parserName}`);

    const logKey = Object.keys(mockLogs).find(k => k.toLowerCase() === parserName.toLowerCase());

    if (!logKey) {
        console.error(`Error: Unknown parser name for logs: ${parserName}`);
        return res.status(404).json({ status: 404, message: `No logs found for unknown parser: ${parserName}` });
    }

    console.log(`Returning logs for ${logKey}`);
    let logsToSend = (mockLogs[logKey].length > 0
        ? mockLogs[logKey].join('\n')
        : `[${new Date().toISOString()}] No logs recorded yet for ${logKey}.`);

    // Генерируем длинный лог для 'Sale' для теста
    if (logKey === 'Sale' && mockLogs[logKey].length > 0) {
        logsToSend += "\n----- START LONG LOG -----\n";
        for (let i = 0; i < 500; i++) {
            logsToSend += `This is a very long log line number ${i + 1} to test the file sending feature. Count: ${Math.random().toString(36).substring(2)}.\n`;
        }
        logsToSend += "----- END LONG LOG -----";
         console.log(`Generated long log for ${logKey}. Total length: ${logsToSend.length}`);
    }

    // Возвращаем в ожидаемом формате {status: ..., message: ...}
    res.status(200).json({
        status: 200,
        message: logsToSend
    });
});

// Обработка ненайденных роутов
app.use((req, res) => {
    console.log(`\n[${new Date().toISOString()}] Received request for unknown route: ${req.method} ${req.originalUrl}`);
    res.status(404).json({ status: 404, message: 'Endpoint not found' });
});


// --- Запуск сервера ---
app.listen(PORT, HOST, () => {
    console.log(`Mock API server listening at ${HOST}:${PORT}`);
    console.log('Available endpoints:');
    console.log(`  GET /start_parser?parser={parserName}`);
    console.log(`  GET /start_table_process?method={methodName}&args={jsonStringArray}`);
    console.log(`  GET /get_logs/parser={parserName}`);
    console.log('\nKnown parser names for logs:', Object.keys(mockLogs).join(', '));
    console.log('Method names: PackageIdSaleInfo, BundleIdSaleInfo, set_final_price, set_delivery_region, set_shop_price, CurrencyInfo, PackageIdPrice');
    console.log('\nWaiting for requests...');
});