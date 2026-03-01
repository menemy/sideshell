# Native iTerm2 MCP Server - Запуск через uv

## Установка uv

Если uv еще не установлен:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

или через Homebrew:
```bash
brew install uv
```

## Быстрый запуск (без установки)

### 1. Создайте виртуальное окружение и установите зависимости:
```bash
cd native-iterm-mcp
uv venv
source .venv/bin/activate  # На macOS/Linux
uv pip install -e .
```

### 2. Запустите сервер напрямую через uv run:
```bash
uv run python -m native_iterm_mcp.server
```

## Настройка в Claude Desktop

### Вариант 1: Через uv run (рекомендуется)

Добавьте в `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "native-iterm": {
      "command": "uv",
      "args": [
        "run",
        "--python",
        "3.11",
        "--with",
        "iterm2>=2.7",
        "--with",
        "mcp>=1.14.0",
        "python",
        "-m",
        "native_iterm_mcp.server"
      ],
      "cwd": "/Users/YOUR_USERNAME/Projects/enhanced-iterm-mcp-server/native-iterm-mcp"
    }
  }
}
```

### Вариант 2: С установкой в виртуальное окружение

1. Создайте и активируйте окружение:
```bash
cd native-iterm-mcp
uv venv
uv pip install -e .
```

2. Настройте Claude Desktop:
```json
{
  "mcpServers": {
    "native-iterm": {
      "command": "/Users/YOUR_USERNAME/Projects/enhanced-iterm-mcp-server/native-iterm-mcp/.venv/bin/python",
      "args": ["-m", "native_iterm_mcp.server"],
      "cwd": "/Users/YOUR_USERNAME/Projects/enhanced-iterm-mcp-server/native-iterm-mcp"
    }
  }
}
```

### Вариант 3: Установка через uv tool

Для глобальной установки как инструмента:
```bash
uv tool install /Users/YOUR_USERNAME/Projects/enhanced-iterm-mcp-server/native-iterm-mcp
```

Затем в Claude Desktop:
```json
{
  "mcpServers": {
    "native-iterm": {
      "command": "native-iterm-mcp"
    }
  }
}
```

## Важные замечания

1. **iTerm2 Python API должен быть включен**:
   - Откройте iTerm2
   - Preferences → General → Magic
   - Включите "Enable Python API"
   - Перезапустите iTerm2

2. **Замените YOUR_USERNAME** на ваше имя пользователя

3. **После изменения конфигурации**:
   - Полностью закройте Claude Desktop (Cmd+Q)
   - Откройте заново

## Проверка работы

1. Откройте Claude Desktop
2. В новом чате введите команду для проверки MCP сервера
3. Claude должен иметь доступ к инструментам iTerm2

## Разработка

Для разработки с автоматической перезагрузкой:
```bash
uv run --reload python -m native_iterm_mcp.server
```

Запуск тестов:
```bash
uv run pytest
```

Проверка типов:
```bash
uv run mypy native_iterm_mcp
```

Линтинг:
```bash
uv run ruff check native_iterm_mcp
```

## Отладка

Если сервер не запускается:

1. Проверьте, что iTerm2 Python API включен
2. Проверьте логи Claude Desktop:
   ```bash
   tail -f ~/Library/Logs/Claude/mcp*.log
   ```
3. Тестовый запуск сервера:
   ```bash
   uv run python -m native_iterm_mcp.server
   ```
   Должен вывести JSON-RPC сообщения

## Преимущества uv

- **Быстрая установка** - uv значительно быстрее pip
- **Изоляция зависимостей** - автоматическое управление виртуальными окружениями
- **Кэширование** - переиспользование установленных пакетов между проектами
- **Совместимость** - полная совместимость с pip и PyPI
- **uv run** - запуск без явной активации окружения