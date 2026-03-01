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
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = __importStar(require("vscode"));
const bridge_1 = require("./bridge");
let bridge;
function activate(context) {
    console.log('sideshell terminal extension activating...');
    // Register commands
    context.subscriptions.push(vscode.commands.registerCommand('sideshell.start', () => {
        startBridge(context);
    }), vscode.commands.registerCommand('sideshell.stop', () => {
        stopBridge();
    }), vscode.commands.registerCommand('sideshell.status', () => {
        if (bridge?.isRunning) {
            vscode.window.showInformationMessage(`sideshell bridge running on port ${bridge.port}`);
        }
        else {
            vscode.window.showInformationMessage('sideshell bridge is not running');
        }
    }));
    // Auto-start if configured
    const config = vscode.workspace.getConfiguration('sideshell');
    if (config.get('autoStart', true)) {
        startBridge(context);
    }
}
function startBridge(context) {
    if (bridge?.isRunning) {
        vscode.window.showInformationMessage('sideshell bridge is already running');
        return;
    }
    const config = vscode.workspace.getConfiguration('sideshell');
    const port = config.get('port', 46117);
    const bufferSize = config.get('outputBufferSize', 10000);
    bridge = new bridge_1.SideshellBridge(port, bufferSize);
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
function deactivate() {
    bridge?.stop();
}
//# sourceMappingURL=extension.js.map