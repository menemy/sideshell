package com.sideshell.terminal

import com.intellij.openapi.project.Project
import com.intellij.openapi.startup.ProjectActivity

/**
 * Starts the sideshell WebSocket bridge when a project opens.
 */
class SideshellStartupActivity : ProjectActivity {
    override suspend fun execute(project: Project) {
        val settings = SideshellSettings.getInstance()
        if (settings.state.autoStart) {
            SideshellBridgeService.getInstance().start()
        }
    }
}
