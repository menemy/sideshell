import * as crypto from 'crypto';
import * as net from 'net';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import * as vscode from 'vscode';
import { TerminalManager } from './terminal-manager';

/**
 * Unix socket bridge server that exposes terminal control via JSON-RPC 2.0.
 * Newline-delimited JSON protocol over Unix socket.
 *
 * Security (two layers):
 *   1. Token auth - random token generated on start, written to port file (0600).
 *      Client must send {"type":"auth","token":"..."} as first message.
 *   2. User consent - persisted in settings (sideshell.allowAccess).
 *      On first connection, a dialog asks the user to approve.
 */
export class SideshellBridge {
    private server: net.Server | null = null;
    private clients: Set<net.Socket> = new Set();
    private terminalManager: TerminalManager;
    private _isRunning = false;
    private _token: string = '';
    private _approvalPending: boolean = false;

    constructor() {
        this.terminalManager = new TerminalManager(10000);
    }

    private get _approved(): boolean {
        return vscode.workspace.getConfiguration('sideshell').get<boolean>('allowAccess', false);
    }

    private set _approved(value: boolean) {
        vscode.workspace.getConfiguration('sideshell').update('allowAccess', value, true);
    }

    get isRunning(): boolean {
        return this._isRunning;
    }

    get socketPath(): string {
        return path.join(os.homedir(), '.sideshell', 'vscode.sock');
    }

    private get portFilePath(): string {
        return path.join(os.homedir(), '.sideshell', 'vscode-port');
    }

    start() {
        if (this._isRunning) { return; }

        this._token = crypto.randomBytes(32).toString('hex');
        this._approvalPending = false;

        // Ensure ~/.sideshell exists BEFORE listen() — a Unix-domain socket
        // can only bind inside an existing directory. On a fresh machine the
        // directory is absent, so without this listen() fails with ENOENT/EACCES
        // and the bridge never starts (writePortFile, which also creates it,
        // only runs in the listen success callback — a chicken-and-egg).
        try {
            const dir = path.dirname(this.socketPath);
            if (!fs.existsSync(dir)) {
                fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
            }
        } catch (e) {
            console.error('sideshell: failed to create socket dir:', e);
        }

        // Clean up stale socket file
        try { fs.unlinkSync(this.socketPath); } catch { /* ok */ }

        this.server = net.createServer((socket: net.Socket) => {
            this.handleConnection(socket);
        });

        this.server.listen(this.socketPath, () => {
            this._isRunning = true;
            // Set socket file permissions to owner-only
            try { fs.chmodSync(this.socketPath, 0o600); } catch { /* ok */ }
            this.writePortFile();
            console.log(`sideshell bridge listening on ${this.socketPath}`);
        });

        this.server.on('error', (err: any) => {
            console.error('sideshell bridge error:', err);
        });
    }

    private handleConnection(socket: net.Socket) {
        let authenticated = false;
        let buffer = '';

        socket.on('data', async (data: Buffer) => {
            buffer += data.toString();
            const lines = buffer.split('\n');
            buffer = lines.pop() || ''; // Keep incomplete line in buffer

            for (const line of lines) {
                if (!line.trim()) { continue; }

                try {
                    const msg = JSON.parse(line);

                    // First message must be auth handshake
                    if (!authenticated) {
                        if (msg.type === 'auth' && msg.token === this._token) {
                            authenticated = true;
                            this.clients.add(socket);
                            console.log('sideshell: client connected (token valid)');
                            socket.write(JSON.stringify({ ok: true }) + '\n');

                            if (!this._approved) {
                                this.requestApproval(socket);
                            }
                        } else {
                            console.warn('sideshell: rejected connection — invalid token');
                            socket.write(JSON.stringify({ ok: false, error: 'invalid token' }) + '\n');
                            socket.destroy();
                        }
                        continue;
                    }

                    // Authenticated — handle JSON-RPC request
                    if (!this._approved) {
                        socket.write(JSON.stringify({
                            jsonrpc: '2.0',
                            id: msg.id,
                            error: {
                                code: -32001,
                                message: 'Waiting for user approval in IDE. '
                                    + 'Please click "Allow" in the notification.',
                            },
                        }) + '\n');
                        continue;
                    }

                    const response = await this.handleRequest(msg);
                    socket.write(JSON.stringify(response) + '\n');
                } catch (e: any) {
                    socket.write(JSON.stringify({
                        jsonrpc: '2.0',
                        id: null,
                        error: { code: -32700, message: `Parse error: ${e.message}` },
                    }) + '\n');
                }
            }
        });

        socket.on('close', () => {
            this.clients.delete(socket);
            console.log('sideshell: client disconnected');
        });

        socket.on('error', (err: Error) => {
            this.clients.delete(socket);
            console.error('sideshell: socket error:', err.message);
        });
    }

    private async requestApproval(socket: net.Socket) {
        if (this._approvalPending) { return; }
        this._approvalPending = true;

        const choice = await vscode.window.showWarningMessage(
            'Sideshell wants to access your IDE terminals. '
            + 'This allows an MCP client to read terminal output and execute commands.',
            { modal: false },
            'Allow',
            'Deny',
        );

        this._approvalPending = false;

        if (choice === 'Allow') {
            this._approved = true;
            console.log('sideshell: user approved terminal access');
            vscode.window.showInformationMessage('Sideshell terminal access granted.');
        } else {
            console.log('sideshell: user denied terminal access');
            this._token = crypto.randomBytes(32).toString('hex');
            this.writePortFile();
            socket.destroy();
        }
    }

    stop() {
        this._isRunning = false;
        this._token = '';

        for (const client of this.clients) {
            client.destroy();
        }
        this.clients.clear();

        if (this.server) {
            this.server.close();
            this.server = null;
        }
        this.removePortFile();
        // Clean up socket file
        try { fs.unlinkSync(this.socketPath); } catch { /* ok */ }
        this.terminalManager.dispose();
    }

    private async handleRequest(request: any): Promise<any> {
        const { id, method, params } = request;

        try {
            const result = await this.dispatch(method, params || {});
            return { jsonrpc: '2.0', id, result };
        } catch (e: any) {
            return {
                jsonrpc: '2.0',
                id,
                error: { code: -32603, message: e.message || 'Internal error' },
            };
        }
    }

    private async dispatch(method: string, params: any): Promise<any> {
        switch (method) {
            case 'list_sessions':
                return this.terminalManager.listSessions();

            case 'read_terminal':
                return this.terminalManager.readOutput(
                    params.session_id || null,
                    params.lines || 20,
                );

            case 'send_text':
                return this.terminalManager.sendText(
                    params.session_id || null,
                    params.text || '',
                );

            case 'execute_command':
                return this.terminalManager.executeCommand(
                    params.session_id || null,
                    params.command || '',
                    params.wait || false,
                    params.timeout || 30,
                    params.watch_for || 'prompt',
                );

            case 'send_control':
                return this.terminalManager.sendControl(
                    params.session_id || null,
                    params.key || '',
                );

            case 'split_pane':
                return await this.terminalManager.splitPane(
                    params.session_id || null,
                    params.direction || 'v',
                );

            case 'create_tab':
                return await this.terminalManager.createTab(
                    params.profile,
                    params.command,
                );

            case 'create_window':
                return await this.terminalManager.createWindow(
                    params.profile,
                    params.command,
                );

            case 'focus_session':
                return this.terminalManager.focusSession(params.session_id);

            case 'close_session':
                return this.terminalManager.closeSession(params.session_id || null);

            case 'clear_terminal':
                return this.terminalManager.clearTerminal(params.session_id || null);

            case 'get_terminal_state':
                return this.terminalManager.getTerminalState(params.session_id || null);

            case 'set_appearance':
                return this.terminalManager.setAppearance(
                    params.session_id || null,
                    params.title,
                    params.color,
                    params.badge,
                );

            case 'get_active_session':
                return { session_id: this.terminalManager.getActiveSessionId() };

            case 'is_ai_session':
                return this.terminalManager.isAiSession(params.session_id);

            default:
                throw new Error(`Unknown method: ${method}`);
        }
    }

    private writePortFile() {
        try {
            const dir = path.dirname(this.portFilePath);
            if (!fs.existsSync(dir)) {
                fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
            }
            const data = JSON.stringify({
                socket: this.socketPath,
                pid: process.pid,
                token: this._token,
                ide: 'vscode',
                version: '0.3.0',
            });
            fs.writeFileSync(this.portFilePath, data, { mode: 0o600 });
        } catch (e) {
            console.error('Failed to write port file:', e);
        }
    }

    private removePortFile() {
        try {
            if (fs.existsSync(this.portFilePath)) {
                fs.unlinkSync(this.portFilePath);
            }
        } catch (e) {
            console.debug('Failed to remove port file:', e);
        }
    }
}
