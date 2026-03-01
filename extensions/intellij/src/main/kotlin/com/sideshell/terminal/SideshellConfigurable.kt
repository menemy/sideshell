package com.sideshell.terminal

import com.intellij.openapi.options.Configurable
import javax.swing.*

class SideshellConfigurable : Configurable {
    private var panel: JPanel? = null
    private var portField: JSpinner? = null
    private var autoStartCheckbox: JCheckBox? = null
    private var bufferSizeField: JSpinner? = null

    override fun getDisplayName(): String = "sideshell Terminal"

    override fun createComponent(): JComponent {
        val settings = SideshellSettings.getInstance()

        panel = JPanel().apply {
            layout = BoxLayout(this, BoxLayout.Y_AXIS)

            add(JPanel().apply {
                layout = BoxLayout(this, BoxLayout.X_AXIS)
                add(JLabel("WebSocket Port: "))
                portField = JSpinner(SpinnerNumberModel(settings.state.port, 1024, 65535, 1))
                add(portField)
            })

            add(Box.createVerticalStrut(8))

            autoStartCheckbox = JCheckBox("Auto-start on IDE launch", settings.state.autoStart)
            add(autoStartCheckbox)

            add(Box.createVerticalStrut(8))

            add(JPanel().apply {
                layout = BoxLayout(this, BoxLayout.X_AXIS)
                add(JLabel("Output buffer size (lines): "))
                bufferSizeField = JSpinner(SpinnerNumberModel(settings.state.outputBufferSize, 100, 100000, 100))
                add(bufferSizeField)
            })

            add(Box.createVerticalStrut(16))

            add(JLabel("Status: ${if (SideshellBridgeService.getInstance().isRunning) "Running" else "Stopped"}"))
        }

        return panel!!
    }

    override fun isModified(): Boolean {
        val settings = SideshellSettings.getInstance()
        return portField?.value != settings.state.port ||
                autoStartCheckbox?.isSelected != settings.state.autoStart ||
                bufferSizeField?.value != settings.state.outputBufferSize
    }

    override fun apply() {
        val settings = SideshellSettings.getInstance()
        settings.state.port = portField?.value as? Int ?: 46118
        settings.state.autoStart = autoStartCheckbox?.isSelected ?: true
        settings.state.outputBufferSize = bufferSizeField?.value as? Int ?: 10000
    }

    override fun reset() {
        val settings = SideshellSettings.getInstance()
        portField?.value = settings.state.port
        autoStartCheckbox?.isSelected = settings.state.autoStart
        bufferSizeField?.value = settings.state.outputBufferSize
    }
}
