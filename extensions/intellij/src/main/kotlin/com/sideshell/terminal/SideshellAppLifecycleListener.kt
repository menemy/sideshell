package com.sideshell.terminal

import com.intellij.ide.AppLifecycleListener

/**
 * Stops the sideshell bridge when the IDE shuts down.
 */
class SideshellAppLifecycleListener : AppLifecycleListener {
    override fun appWillBeClosed(isRestart: Boolean) {
        SideshellBridgeService.getInstance().stop()
    }
}
