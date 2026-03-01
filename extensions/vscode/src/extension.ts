import * as vscode from 'vscode';
import { SideshellBridge } from './bridge';

let bridge: SideshellBridge | undefined;

export function activate(context: vscode.ExtensionContext) {
    console.log('sideshell terminal extension activating...');

    // Register commands
    context.subscriptions.push(
        vscode.commands.registerCommand('sideshell.start', () => {
            startBridge(context);
        }),
        vscode.commands.registerCommand('sideshell.stop', () => {
            stopBridge();
        }),
        vscode.commands.registerCommand('sideshell.status', () => {
            if (bridge?.isRunning) {
                vscode.window.showInformationMessage(
                    `sideshell bridge running on port ${bridge.port}`
                );
            } else {
                vscode.window.showInformationMessage('sideshell bridge is not running');
            }
        })
    );

    // Auto-start if configured
    const config = vscode.workspace.getConfiguration('sideshell');
    if (config.get<boolean>('autoStart', true)) {
        startBridge(context);
    }
}

function startBridge(context: vscode.ExtensionContext) {
    if (bridge?.isRunning) {
        vscode.window.showInformationMessage('sideshell bridge is already running');
        return;
    }

    const config = vscode.workspace.getConfiguration('sideshell');
    const port = config.get<number>('port', 46117);
    const bufferSize = config.get<number>('outputBufferSize', 10000);

    bridge = new SideshellBridge(port, bufferSize);
    bridge.start();

    context.subscriptions.push({
        dispose: () => bridge?.stop()
    });

    console.log(`sideshell bridge started on port ${port}`);
}

function stopBridge() {
    if (bridge) {
        bridge.stop();
        bridge = undefined;
        vscode.window.showInformationMessage('sideshell bridge stopped');
    }
}

export function deactivate() {
    bridge?.stop();
}
