package com.sideshell.terminal

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.*

@Service(Service.Level.APP)
@State(
    name = "SideshellSettings",
    storages = [Storage("sideshell.xml")]
)
class SideshellSettings : PersistentStateComponent<SideshellSettings.State> {
    data class State(
        var port: Int = 46118,
        var autoStart: Boolean = true,
        var outputBufferSize: Int = 10000,
    )

    private var myState = State()

    override fun getState(): State = myState

    override fun loadState(state: State) {
        myState = state
    }

    companion object {
        fun getInstance(): SideshellSettings =
            ApplicationManager.getApplication().getService(SideshellSettings::class.java)
    }
}
