import * as crypto from 'crypto';
import * as http from 'http';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import * as url from 'url';
import * as vscode from 'vscode';
import { WebSocketServer, WebSocket } from 'ws';
import { TerminalManager } from './terminal-manager';

/**
 * WebSocket bridge server that exposes terminal control via JSON-RPC 2.0.
 *
 * Security (two layers):
 *   1. Token auth - random token generated on start, written to port file (0600).
 *      Client must connect with ?token=<token> query parameter.
 *   2. User consent - on first connection, a dialog asks the user to approve.
 *      Until approved, all JSON-RPC requests return an auth error.
 */
export class SideshellBridge {
    private wss: WebSocketServer | null = null;
    private server: http.Server | null = null;
    private terminalManager: TerminalManager;
    private _isRunning = false;
    private _token: string = '';
    private _approved: boolean = false;
    private _approvalPending: boolean = false;
    readonly port: number;

    constructor(port: number = 46117, bufferSize: number = 10000) {
        this.port = port;
        this.terminalManager = new TerminalManager(bufferSize);
    }

    get isRunning(): boolean {
        return this._isRunning;
    }

    start() {
        if (this._isRunning) { return; }

        this._token = crypto.randomBytes(32).toString('hex');
        this._approved = false;
        this._approvalPending = false;

        this.server = http.createServer();
        this.wss = new WebSocketServer({ noServer: true });

        // Verify token on HTTP upgrade (before WebSocket handshake)
        this.server.on('upgrade', (request, socket, head) => {
            const parsed = url.parse(request.url || '', true);
            const token = parsed.query.token as string | undefined;

            if (token !== this._token) {
                console.warn('sideshell: rejected connection — invalid token');
                socket.write('HTTP/1.1 401 Unauthorized\r\n\r\n');
                socket.destroy();
                return;
            }

            this.wss!.handleUpgrade(request, socket, head, (ws) => {
                this.wss!.emit('connection', ws, request);
            });
        });

        this.wss.on('connection', (ws: WebSocket) => {
            console.log('sideshell: client connected (token valid)');

            // Ask user for consent on first connection
            if (!this._approved) {
                this.requestApproval(ws);
            }

            ws.on('message', async (data: Buffer) => {
                try {
                    const request = JSON.parse(data.toString());

                    // Block requests until user approves
                    if (!this._approved) {
                        ws.send(JSON.stringify({
                            jsonrpc: '2.0',
                            id: request.id,
                            error: {
                                code: -32001,
                                message: 'Waiting for user approval in IDE. '
                                    + 'Please click "Allow" in the notification.',
                            },
                        }));
                        return;
                    }

                    const response = await this.handleRequest(request);
                    ws.send(JSON.stringify(response));
                } catch (e: any) {
                    ws.send(JSON.stringify({
                        jsonrpc: '2.0',
                        id: null,
                        error: { code: -32700, message: `Parse error: ${e.message}` },
                    }));
                }
            });

            ws.on('close', () => {
                console.log('sideshell: client disconnected');
            });

            ws.on('error', (err: Error) => {
                console.error('sideshell: WebSocket error:', err);
            });
        });

        this.server.listen(this.port, '127.0.0.1', () => {
            this._isRunning = true;
            this.writePortFile();
            console.log(`sideshell bridge listening on ws://127.0.0.1:${this.port}`);
        });

        this.server.on('error', (err: any) => {
            if (err.code === 'EADDRINUSE') {
                console.error(`Port ${this.port} already in use. Change sideshell.port in settings.`);
            } else {
                console.error('sideshell bridge error:', err);
            }
        });
    }

    private async requestApproval(ws: WebSocket) {
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
            // Regenerate token so the denied client can't retry
            this._token = crypto.randomBytes(32).toString('hex');
            this.writePortFile();
            ws.close(4001, 'Access denied by user');
        }
    }

    stop() {
        this._isRunning = false;
        this._token = '';
        this._approved = false;
        this.removePortFile();

        if (this.wss) {
            this.wss.close();
            this.wss = null;
        }
        if (this.server) {
            this.server.close();
            this.server = null;
        }
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

    private get portFilePath(): string {
        const dir = path.join(os.homedir(), '.sideshell');
        return path.join(dir, 'vscode-port');
    }

    private writePortFile() {
        try {
            const dir = path.dirname(this.portFilePath);
            if (!fs.existsSync(dir)) {
                fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
            }
            const data = JSON.stringify({
                port: this.port,
                pid: process.pid,
                token: this._token,
                ide: 'vscode',
                version: '0.1.0',
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
