package com.sideshell.terminal

import com.intellij.openapi.options.Configurable
import javax.swing.*

class SideshellConfigurable : Configurable {
    private var panel: JPanel? = null
    private var approvedCheckbox: JCheckBox? = null

    override fun getDisplayName(): String = "sideshell"

    override fun createComponent(): JComponent {
        val settings = SideshellSettings.getInstance()
        val bridge = SideshellBridgeService.getInstance()

        panel = JPanel().apply {
            layout = BoxLayout(this, BoxLayout.Y_AXIS)

            approvedCheckbox = JCheckBox("Allow terminal access", settings.state.approved)
            add(approvedCheckbox)

            add(Box.createVerticalStrut(12))

            val status = if (bridge.isRunning) "Running" else "Stopped"
            add(JLabel("Status: $status"))
        }

        return panel!!
    }

    override fun isModified(): Boolean {
        val settings = SideshellSettings.getInstance()
        return approvedCheckbox?.isSelected != settings.state.approved
    }

    override fun apply() {
        val settings = SideshellSettings.getInstance()
        settings.state.approved = approvedCheckbox?.isSelected ?: false
    }

    override fun reset() {
        val settings = SideshellSettings.getInstance()
        approvedCheckbox?.isSelected = settings.state.approved
    }
}
