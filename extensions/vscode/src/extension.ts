import * as vscode from 'vscode';
import { SideshellBridge } from './bridge';

let bridge: SideshellBridge | undefined;

export function activate(context: vscode.ExtensionContext) {
    console.log('sideshell terminal extension activating...');

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
                    `sideshell bridge running on ${bridge.socketPath}`
                );
            } else {
                vscode.window.showInformationMessage('sideshell bridge is not running');
            }
        })
    );

    // Always auto-start
    startBridge(context);
}

function startBridge(context: vscode.ExtensionContext) {
    if (bridge?.isRunning) {
        vscode.window.showInformationMessage('sideshell bridge is already running');
        return;
    }

    bridge = new SideshellBridge();
    bridge.start();

    context.subscriptions.push({
        dispose: () => bridge?.stop()
    });
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
