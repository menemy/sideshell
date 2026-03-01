#!/bin/bash

echo "🚀 Native iTerm MCP Server - Setup"
echo "===================================="

# Check if iTerm2 is running
if ! pgrep -f "iTerm" > /dev/null; then
    echo "❌ iTerm2 is not running. Please start iTerm2 first."
    exit 1
fi

echo "✅ iTerm2 is running"

# Check Python version
python_version=$(python3 --version 2>/dev/null)
if [ $? -ne 0 ]; then
    echo "❌ Python3 not found. Please install Python 3.11+ first."
    exit 1
fi

# Check Python version is 3.11 or higher
python_major_minor=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if (( $(echo "$python_major_minor < 3.11" | bc -l) )); then
    echo "❌ Python 3.11+ required, found: $python_version"
    exit 1
fi

echo "✅ Python version: $python_version"

# Install package in development mode
echo "📦 Installing native-iterm-mcp in development mode..."
pip install -e .
if [ $? -ne 0 ]; then
    echo "❌ Failed to install package"
    exit 1
fi

echo "✅ Package installed successfully"

# Install development dependencies
echo "📦 Installing development dependencies..."
pip install -e ".[dev]"
if [ $? -ne 0 ]; then
    echo "⚠️  Failed to install development dependencies (optional)"
fi

# Check iTerm2 Python API status
echo "🔍 Checking iTerm2 Python API configuration..."

# Use AppleScript to check if Python API is enabled
api_enabled=$(osascript -e '
tell application "System Events"
    tell process "iTerm2"
        try
            click menu item "Preferences…" of menu "iTerm2" of menu bar 1
            delay 1
            click button "General" of toolbar 1 of window "Preferences"
            delay 0.5
            click button "Magic" of group 1 of window "Preferences"
            delay 0.5
            set api_status to value of checkbox "Enable Python API" of group 1 of window "Preferences"
            click button 1 of window "Preferences"
            return api_status
        on error
            return false
        end try
    end tell
end tell' 2>/dev/null)

if [ "$api_enabled" = "true" ] || [ "$api_enabled" = "1" ]; then
    echo "✅ Python API is enabled in iTerm2"
else
    echo "⚠️  Python API might not be enabled in iTerm2"
    echo ""
    echo "🔧 To enable Python API manually:"
    echo "   1. Open iTerm2 → Preferences (⌘,)"
    echo "   2. Go to General → Magic"
    echo "   3. Check 'Enable Python API'"
    echo "   4. Restart iTerm2"
    echo ""

    # Try to enable it automatically
    echo "🔄 Attempting to enable Python API automatically..."
    osascript -e '
    tell application "System Events"
        tell process "iTerm2"
            try
                click menu item "Preferences…" of menu "iTerm2" of menu bar 1
                delay 1
                click button "General" of toolbar 1 of window "Preferences"
                delay 0.5
                click button "Magic" of group 1 of window "Preferences"
                delay 0.5
                set checkbox_value to value of checkbox "Enable Python API" of group 1 of window "Preferences"
                if checkbox_value is false then
                    click checkbox "Enable Python API" of group 1 of window "Preferences"
                    delay 0.5
                    display notification "Python API enabled! Please restart iTerm2." with title "Native iTerm MCP"
                end if
                click button 1 of window "Preferences"
            end try
        end tell
    end tell' 2>/dev/null

    if [ $? -eq 0 ]; then
        echo "✅ Python API enabled automatically"
        echo "⚠️  Please restart iTerm2 for changes to take effect"
    else
        echo "⚠️  Could not enable automatically. Please enable manually."
    fi
fi

# Test the connection
echo ""
echo "🧪 Testing iTerm2 connection..."
python3 -c "
import asyncio
import iterm2

async def test_connection():
    try:
        connection = await iterm2.Connection.async_create()
        app = await iterm2.async_get_app(connection)
        print('✅ Successfully connected to iTerm2 API')
        return True
    except Exception as e:
        print(f'❌ Failed to connect: {e}')
        return False

asyncio.run(test_connection())
" 2>/dev/null

if [ $? -ne 0 ]; then
    echo "⚠️  Could not connect to iTerm2 API. Make sure:"
    echo "   1. Python API is enabled in iTerm2"
    echo "   2. iTerm2 has been restarted after enabling API"
fi

echo ""
echo "🎉 Setup Complete!"
echo ""
echo "📋 Next steps:"
echo "   1. If not done automatically, enable Python API in iTerm2 preferences"
echo "   2. Restart iTerm2 if you just enabled the Python API"
echo "   3. Add to your Claude Desktop configuration:"
echo "      {"
echo "        \"mcpServers\": {"
echo "          \"native-iterm\": {"
echo "            \"command\": \"python\","
echo "            \"args\": [\"-m\", \"native_iterm_mcp.server\"],"
echo "            \"cwd\": \"$(pwd)\""
echo "          }"
echo "        }"
echo "      }"
echo ""
echo "🧪 Run tests:"
echo "   pytest tests/"
echo ""
echo "📚 View documentation:"
echo "   cat README.md"