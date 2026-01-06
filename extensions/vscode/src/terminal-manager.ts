import * as vscode from 'vscode';

/**
 * Manages terminal sessions and output buffering.
 *
 * VSCode terminal API limitations:
 * - sendText() works for writing
 * - Shell integration API needed for reading output
 * - No direct "read last N lines" API, so we buffer via shell integration events
 */
export class TerminalManager {
    private outputBuffers: Map<string, string[]> = new Map();
    private maxBufferSize: number;
    private disposables: vscode.Disposable[] = [];
    private terminalIds: Map<vscode.Terminal, string> = new Map();
    private nextId: number = 1;

    constructor(bufferSize: number = 10000) {
        this.maxBufferSize = bufferSize;
        this.setupListeners();
    }

    private assignId(terminal: vscode.Terminal): string {
        const existing = this.terminalIds.get(terminal);
        if (existing) { return existing; }
        const id = `term-${this.nextId++}`;
        this.terminalIds.set(terminal, id);
        return id;
    }

    private setupListeners() {
        // Track terminal creation/destruction
        this.disposables.push(
            vscode.window.onDidOpenTerminal((terminal) => {
                const id = this.assignId(terminal);
                this.outputBuffers.set(id, []);
                this.setupShellIntegration(terminal);
            }),
            vscode.window.onDidCloseTerminal((terminal) => {
                const id = this.getTerminalId(terminal);
                this.outputBuffers.delete(id);
                this.terminalIds.delete(terminal);
            })
        );

        // Initialize existing terminals
        for (const terminal of vscode.window.terminals) {
            const id = this.assignId(terminal);
            this.outputBuffers.set(id, []);
            this.setupShellIntegration(terminal);
        }

        // Shell integration for output capture
        this.disposables.push(
            vscode.window.onDidEndTerminalShellExecution((event) => {
                this.captureExecutionOutput(event);
            })
        );
    }

    private async setupShellIntegration(terminal: vscode.Terminal) {
        // Shell integration is auto-managed by VSCode
        // We capture output via onDidEndTerminalShellExecution
    }

    private async captureExecutionOutput(event: vscode.TerminalShellExecutionEndEvent) {
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
        } catch (e) {
            // Shell integration may not be available
            console.debug(`Cannot read output for terminal ${id}: ${e}`);
        }
    }

    getTerminalId(terminal: vscode.Terminal): string {
        return this.assignId(terminal);
    }

    getTerminalById(id: string): vscode.Terminal | undefined {
        return vscode.window.terminals.find(t => this.getTerminalId(t) === id);
    }

    listSessions(): SessionInfo[] {
        const activeTerminal = vscode.window.activeTerminal;
        return vscode.window.terminals.map(terminal => {
            const id = this.getTerminalId(terminal);
            return {
                id,
                name: terminal.name,
                path: (terminal.creationOptions as vscode.TerminalOptions)?.cwd?.toString() || '',
                job: terminal.name,
                active: terminal === activeTerminal,
                at_prompt: false, // Can't reliably detect this without shell integration
            };
        });
    }

    readOutput(terminalId: string | null, lines: number): string {
        let id = terminalId;
        if (!id) {
            const active = vscode.window.activeTerminal;
            if (!active) { return 'No active terminal'; }
            id = this.getTerminalId(active);
        }

        const buffer = this.outputBuffers.get(id);
        if (!buffer || buffer.length === 0) {
            return `No output captured for terminal ${id}.\nNote: Output capture requires VS Code shell integration to be active.`;
        }

        const lastLines = buffer.slice(-lines);
        return lastLines.join('\n');
    }

    sendText(terminalId: string | null, text: string): string {
        const terminal = this.resolveTerminal(terminalId);
        if (!terminal) { return `Terminal not found: ${terminalId}`; }

        terminal.sendText(text, false);
        return `Sent text to terminal ${terminalId || this.getTerminalId(terminal)}`;
    }

    executeCommand(
        terminalId: string | null,
        command: string,
        _wait: boolean,
        _timeout: number,
        _watchFor: string,
    ): string {
        const terminal = this.resolveTerminal(terminalId);
        if (!terminal) { return `Terminal not found: ${terminalId}`; }

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

    sendControl(terminalId: string | null, key: string): string {
        const terminal = this.resolveTerminal(terminalId);
        if (!terminal) { return `Terminal not found: ${terminalId}`; }

        const controlChars: Record<string, string> = {
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
        if (!char) { return `Unknown control key: ${key}`; }

        terminal.sendText(char, false);
        return `Sent control key: ${key}`;
    }

    async splitPane(terminalId: string | null, direction: string): Promise<{ new_session_id: string }> {
        const parent = this.resolveTerminal(terminalId);
        if (!parent) { throw new Error(`Terminal not found: ${terminalId}`); }

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

    async createTab(profile?: string, command?: string): Promise<{ new_session_id: string }> {
        const options: vscode.TerminalOptions = {};
        if (profile) { options.name = profile; }

        const terminal = vscode.window.createTerminal(options);
        terminal.show();

        if (command) {
            await new Promise(resolve => setTimeout(resolve, 500));
            terminal.sendText(command);
        }

        return { new_session_id: this.getTerminalId(terminal) };
    }

    async createWindow(profile?: string, command?: string): Promise<{ new_session_id: string }> {
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

    focusSession(terminalId: string): string {
        const terminal = this.getTerminalById(terminalId);
        if (!terminal) { return `Terminal not found: ${terminalId}`; }

        terminal.show();
        return `Focused terminal ${terminalId}`;
    }

    closeSession(terminalId: string | null): string {
        const terminal = this.resolveTerminal(terminalId);
        if (!terminal) { return `Terminal not found: ${terminalId}`; }

        terminal.dispose();
        return `Closed terminal ${terminalId || 'active'}`;
    }

    clearTerminal(terminalId: string | null): string {
        const terminal = this.resolveTerminal(terminalId);
        if (!terminal) { return `Terminal not found: ${terminalId}`; }

        // Send clear command
        terminal.sendText('clear');
        // Also clear our buffer
        const id = this.getTerminalId(terminal);
        this.outputBuffers.set(id, []);
        return `Cleared terminal ${id}`;
    }

    getTerminalState(terminalId: string | null): object {
        if (terminalId) {
            const terminal = this.getTerminalById(terminalId);
            if (!terminal) { return { error: `Terminal not found: ${terminalId}` }; }
            return {
                id: terminalId,
                name: terminal.name,
                path: (terminal.creationOptions as vscode.TerminalOptions)?.cwd?.toString() || '',
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

    setAppearance(
        terminalId: string | null,
        title?: string,
        color?: string,
        badge?: string,
    ): string {
        // VSCode doesn't support changing terminal title/color/badge programmatically
        // for existing terminals. We can only rename via extension API in limited ways.
        if (title) {
            // Can rename by creating a new terminal with the name
            return `Terminal renaming is limited in VSCode. Title: ${title}`;
        }
        return 'Appearance settings limited in VS Code terminal API';
    }

    getActiveSessionId(): string | null {
        const active = vscode.window.activeTerminal;
        if (!active) { return null; }
        return this.getTerminalId(active);
    }

    isAiSession(terminalId: string): boolean {
        const terminal = this.getTerminalById(terminalId);
        if (!terminal) { return false; }
        const name = terminal.name.toLowerCase();
        return name.includes('claude') || name.includes('copilot') ||
               name.includes('cursor') || name.includes('cline') ||
               name.includes('aider');
    }

    private resolveTerminal(terminalId: string | null): vscode.Terminal | undefined {
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

export interface SessionInfo {
    id: string;
    name: string;
    path: string;
    job: string;
    active: boolean;
    at_prompt: boolean;
}
