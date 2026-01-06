"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.TerminalManager = void 0;
const vscode = __importStar(require("vscode"));
/**
 * Manages terminal sessions and output buffering.
 *
 * VSCode terminal API limitations:
 * - sendText() works for writing
 * - Shell integration API needed for reading output
 * - No direct "read last N lines" API, so we buffer via shell integration events
 */
class TerminalManager {
    outputBuffers = new Map();
    maxBufferSize;
    disposables = [];
    terminalIds = new Map();
    nextId = 1;
    constructor(bufferSize = 10000) {
        this.maxBufferSize = bufferSize;
        this.setupListeners();
    }
    assignId(terminal) {
        const existing = this.terminalIds.get(terminal);
        if (existing) {
            return existing;
        }
        const id = `term-${this.nextId++}`;
        this.terminalIds.set(terminal, id);
        return id;
    }
    setupListeners() {
        // Track terminal creation/destruction
        this.disposables.push(vscode.window.onDidOpenTerminal((terminal) => {
            const id = this.assignId(terminal);
            this.outputBuffers.set(id, []);
            this.setupShellIntegration(terminal);
        }), vscode.window.onDidCloseTerminal((terminal) => {
            const id = this.getTerminalId(terminal);
            this.outputBuffers.delete(id);
            this.terminalIds.delete(terminal);
        }));
        // Initialize existing terminals
        for (const terminal of vscode.window.terminals) {
            const id = this.assignId(terminal);
            this.outputBuffers.set(id, []);
            this.setupShellIntegration(terminal);
        }
        // Shell integration for output capture
        this.disposables.push(vscode.window.onDidEndTerminalShellExecution((event) => {
            this.captureExecutionOutput(event);
        }));
    }
    async setupShellIntegration(terminal) {
        // Shell integration is auto-managed by VSCode
        // We capture output via onDidEndTerminalShellExecution
    }
    async captureExecutionOutput(event) {
        const terminal = event.terminal;
        const id = this.getTerminalId(terminal);
        const execution = event.shellIntegration?.executeCommand?.toString() || '';
        try {
            const stream = event.execution.read();
            let output = '';
            for await (const chunk of stream) {
                output += chunk;
            }
            const buffer = this.outputBuffers.get(id) || [];
            const lines = output.split('\n');
            buffer.push(...lines);
            // Trim buffer to max size
            while (buffer.length > this.maxBufferSize) {
                buffer.shift();
            }
            this.outputBuffers.set(id, buffer);
        }
        catch (e) {
            // Shell integration may not be available
            console.debug(`Cannot read output for terminal ${id}: ${e}`);
        }
    }
    getTerminalId(terminal) {
        return this.assignId(terminal);
    }
    getTerminalById(id) {
        return vscode.window.terminals.find(t => this.getTerminalId(t) === id);
    }
    listSessions() {
        const activeTerminal = vscode.window.activeTerminal;
        return vscode.window.terminals.map(terminal => {
            const id = this.getTerminalId(terminal);
            return {
                id,
                name: terminal.name,
                path: terminal.creationOptions?.cwd?.toString() || '',
                job: terminal.name,
                active: terminal === activeTerminal,
                at_prompt: false, // Can't reliably detect this without shell integration
            };
        });
    }
    readOutput(terminalId, lines) {
        let id = terminalId;
        if (!id) {
            const active = vscode.window.activeTerminal;
            if (!active) {
                return 'No active terminal';
            }
            id = this.getTerminalId(active);
        }
        const buffer = this.outputBuffers.get(id);
        if (!buffer || buffer.length === 0) {
            return `No output captured for terminal ${id}.\nNote: Output capture requires VS Code shell integration to be active.`;
        }
        const lastLines = buffer.slice(-lines);
        return lastLines.join('\n');
    }
    sendText(terminalId, text) {
        const terminal = this.resolveTerminal(terminalId);
        if (!terminal) {
            return `Terminal not found: ${terminalId}`;
        }
        terminal.sendText(text, false);
        return `Sent text to terminal ${terminalId || this.getTerminalId(terminal)}`;
    }
    executeCommand(terminalId, command, _wait, _timeout, _watchFor) {
        const terminal = this.resolveTerminal(terminalId);
        if (!terminal) {
            return `Terminal not found: ${terminalId}`;
        }
        // Check if this is an AI session to prevent recursion
        const name = terminal.name.toLowerCase();
        if (name.includes('claude') || name.includes('copilot') || name.includes('cursor')) {
            return 'Cannot execute commands in AI terminal. Use \'split\' to create a new pane.';
        }
        terminal.sendText(command);
        terminal.show();
        const id = this.getTerminalId(terminal);
        // If wait is requested, we'd need shell integration to know when command finishes
        // For now, return immediately with the command sent confirmation
        if (_wait) {
            return `Command sent to terminal ${id}. Note: wait/timeout requires shell integration.`;
        }
        return `Executed in terminal ${id}: ${command}`;
    }
    sendControl(terminalId, key) {
        const terminal = this.resolveTerminal(terminalId);
        if (!terminal) {
            return `Terminal not found: ${terminalId}`;
        }
        const controlChars = {
            'c': '\x03',
            'd': '\x04',
            'z': '\x1a',
            'a': '\x01',
            'e': '\x05',
            'k': '\x0b',
            'l': '\x0c',
            'u': '\x15',
            'w': '\x17',
            'enter': '\r',
            'esc': '\x1b',
            'tab': '\t',
            'backspace': '\x7f',
            'up': '\x1b[A',
            'down': '\x1b[B',
            'right': '\x1b[C',
            'left': '\x1b[D',
        };
        const char = controlChars[key];
        if (!char) {
            return `Unknown control key: ${key}`;
        }
        terminal.sendText(char, false);
        return `Sent control key: ${key}`;
    }
    async splitPane(terminalId, direction) {
        const parent = this.resolveTerminal(terminalId);
        if (!parent) {
            throw new Error(`Terminal not found: ${terminalId}`);
        }
        // Strategy: use workbench.action.terminal.split for panel-level splits.
        // This creates a new terminal in the same group as the parent.
        // Note: Cursor renders grouped terminals as tabs within the group,
        // not as visual side-by-side panes. This is a Cursor limitation.
        // 1. Focus the parent terminal so the split targets it
        parent.show(false);
        await new Promise(resolve => setTimeout(resolve, 300));
        const terminalsBefore = new Set(vscode.window.terminals);
        // 2. Split via command (works in both VSCode and Cursor)
        await vscode.commands.executeCommand('workbench.action.terminal.split');
        await new Promise(resolve => setTimeout(resolve, 500));
        // 3. Detect the newly created terminal
        const newTerminal = vscode.window.terminals.find(t => !terminalsBefore.has(t));
        if (!newTerminal) {
            throw new Error('Split command executed but no new terminal detected');
        }
        const newId = this.getTerminalId(newTerminal);
        console.log(`sideshell: split created "${newTerminal.name}" (${newId}), direction=${direction}`);
        return { new_session_id: newId };
    }
    async createTab(profile, command) {
        const options = {};
        if (profile) {
            options.name = profile;
        }
        const terminal = vscode.window.createTerminal(options);
        terminal.show();
        if (command) {
            await new Promise(resolve => setTimeout(resolve, 500));
            terminal.sendText(command);
        }
        return { new_session_id: this.getTerminalId(terminal) };
    }
    async createWindow(profile, command) {
        // VSCode doesn't have separate windows for terminals
        // Create a terminal in the editor area instead
        const terminal = vscode.window.createTerminal({
            name: profile || undefined,
            location: vscode.TerminalLocation.Editor,
        });
        terminal.show();
        if (command) {
            await new Promise(resolve => setTimeout(resolve, 500));
            terminal.sendText(command);
        }
        return { new_session_id: this.getTerminalId(terminal) };
    }
    focusSession(terminalId) {
        const terminal = this.getTerminalById(terminalId);
        if (!terminal) {
            return `Terminal not found: ${terminalId}`;
        }
        terminal.show();
        return `Focused terminal ${terminalId}`;
    }
    closeSession(terminalId) {
        const terminal = this.resolveTerminal(terminalId);
        if (!terminal) {
            return `Terminal not found: ${terminalId}`;
        }
        terminal.dispose();
        return `Closed terminal ${terminalId || 'active'}`;
    }
    clearTerminal(terminalId) {
        const terminal = this.resolveTerminal(terminalId);
        if (!terminal) {
            return `Terminal not found: ${terminalId}`;
        }
        // Send clear command
        terminal.sendText('clear');
        // Also clear our buffer
        const id = this.getTerminalId(terminal);
        this.outputBuffers.set(id, []);
        return `Cleared terminal ${id}`;
    }
    getTerminalState(terminalId) {
        if (terminalId) {
            const terminal = this.getTerminalById(terminalId);
            if (!terminal) {
                return { error: `Terminal not found: ${terminalId}` };
            }
            return {
                id: terminalId,
                name: terminal.name,
                path: terminal.creationOptions?.cwd?.toString() || '',
                active: terminal === vscode.window.activeTerminal,
                buffer_lines: this.outputBuffers.get(terminalId)?.length || 0,
            };
        }
        return {
            terminals: this.listSessions(),
            total: vscode.window.terminals.length,
            active: vscode.window.activeTerminal
                ? this.getTerminalId(vscode.window.activeTerminal) : null,
        };
    }
    setAppearance(terminalId, title, color, badge) {
        // VSCode doesn't support changing terminal title/color/badge programmatically
        // for existing terminals. We can only rename via extension API in limited ways.
        if (title) {
            // Can rename by creating a new terminal with the name
            return `Terminal renaming is limited in VSCode. Title: ${title}`;
        }
        return 'Appearance settings limited in VS Code terminal API';
    }
    getActiveSessionId() {
        const active = vscode.window.activeTerminal;
        if (!active) {
            return null;
        }
        return this.getTerminalId(active);
    }
    isAiSession(terminalId) {
        const terminal = this.getTerminalById(terminalId);
        if (!terminal) {
            return false;
        }
        const name = terminal.name.toLowerCase();
        return name.includes('claude') || name.includes('copilot') ||
            name.includes('cursor') || name.includes('cline') ||
            name.includes('aider');
    }
    resolveTerminal(terminalId) {
        if (terminalId) {
            return this.getTerminalById(terminalId);
        }
        return vscode.window.activeTerminal || vscode.window.terminals[0];
    }
    dispose() {
        for (const d of this.disposables) {
            d.dispose();
        }
        this.disposables = [];
        this.outputBuffers.clear();
        this.terminalIds.clear();
    }
}
exports.TerminalManager = TerminalManager;
//# sourceMappingURL=terminal-manager.js.map