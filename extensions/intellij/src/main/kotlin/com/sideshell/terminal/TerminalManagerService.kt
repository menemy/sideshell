package com.sideshell.terminal

import com.intellij.ide.DataManager
import com.intellij.openapi.actionSystem.ActionManager
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.DataContext
import com.intellij.openapi.actionSystem.PlatformDataKeys
import com.intellij.openapi.actionSystem.impl.SimpleDataContext
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.project.ProjectManager
import com.intellij.openapi.wm.IdeFocusManager
import com.intellij.openapi.wm.ToolWindowManager
import com.intellij.openapi.wm.WindowManager
import com.intellij.ui.content.Content
import com.intellij.util.ui.UIUtil
import org.jetbrains.plugins.terminal.ShellTerminalWidget
import org.jetbrains.plugins.terminal.TerminalToolWindowManager
import org.jetbrains.plugins.terminal.TerminalView
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * Manages terminal sessions in JetBrains IDE.
 *
 * Supports both classic (ShellTerminalWidget) and new (TerminalView) terminal
 * implementations. Uses TerminalToolWindowTabsManager as primary API for new
 * terminals, falls back to ContentManager for classic ones.
 */
class TerminalManagerService {
    private val log = Logger.getInstance(TerminalManagerService::class.java)
    private val outputBuffers = ConcurrentHashMap<String, MutableList<String>>()
    private val maxBufferSize = SideshellSettings.getInstance().state.outputBufferSize
    private val newApi = NewTerminalApiHelper()

    /**
     * Represents a terminal session with support for both APIs.
     */
    private data class TerminalInfo(
        val id: String,
        val name: String,
        val content: Content?,
        val widget: ShellTerminalWidget?,
        val newView: Any?,  // com.intellij.terminal.frontend.view.TerminalView
        val project: Project,
    ) {
        val type: String
            get() = when {
                widget != null -> "classic"
                newView != null -> "new"
                else -> "unknown"
            }
    }

    fun listSessions(): List<Map<String, Any?>> {
        val result = mutableListOf<Map<String, Any?>>()
        for (info in getAllTerminals()) {
            result.add(mapOf(
                "id" to info.id,
                "name" to info.name,
                "path" to (info.project.basePath ?: ""),
                "job" to info.name,
                "active" to (info.content?.isSelected == true),
                "at_prompt" to false,
                "project" to info.project.name,
                "type" to info.type,
            ))
        }
        return result
    }

    fun readOutput(sessionId: String?, lines: Int): String {
        val id = sessionId ?: getActiveSessionId() ?: return "No active terminal"
        val info = resolveTerminal(id)

        // Try new terminal API (direct output access)
        if (info?.newView != null) {
            val output = newApi.readOutput(info.newView, lines)
            if (output != null) return output
        }

        // Fall back to output buffer
        val buffer = outputBuffers[id]
        if (buffer == null || buffer.isEmpty()) {
            return "No output captured for terminal $id.\n" +
                    "Note: Output capture requires shell integration (Bash/Zsh/PowerShell)."
        }
        val lastLines = synchronized(buffer) {
            buffer.takeLast(lines)
        }
        return lastLines.joinToString("\n")
    }

    fun sendText(sessionId: String?, text: String): String {
        val info = resolveTerminal(sessionId) ?: return "Terminal not found: $sessionId"

        if (info.widget != null) {
            ApplicationManager.getApplication().invokeLater {
                try {
                    info.widget.executeCommand(text)
                } catch (e: Exception) {
                    log.warn("Failed to send text via classic API: ${e.message}")
                }
            }
            return "Sent text to terminal ${info.id}"
        }

        if (info.newView != null) {
            ApplicationManager.getApplication().invokeLater {
                try {
                    newApi.sendText(info.newView, text)
                } catch (e: Exception) {
                    log.warn("Failed to send text via new API: ${e.message}")
                }
            }
            return "Sent text to terminal ${info.id}"
        }

        return "Terminal does not support text input: ${info.id}"
    }

    fun executeCommand(
        sessionId: String?,
        command: String,
        wait: Boolean,
        timeout: Int,
        watchFor: String,
    ): String {
        val info = resolveTerminal(sessionId) ?: return "Terminal not found: $sessionId"
        val name = info.name.lowercase()

        // AI session check is informational only (is_ai_session method).
        // MCP clients can decide whether to allow execution in AI terminals.

        if (info.widget != null) {
            ApplicationManager.getApplication().invokeLater {
                try {
                    info.widget.executeCommand(command)
                } catch (e: Exception) {
                    log.warn("Failed to execute via classic API: ${e.message}")
                }
            }
        } else if (info.newView != null) {
            ApplicationManager.getApplication().invokeLater {
                try {
                    newApi.executeCommand(info.newView, command)
                } catch (e: Exception) {
                    log.warn("Failed to execute via new API: ${e.message}")
                }
            }
        } else {
            return "Terminal does not support commands: ${info.id}"
        }

        addToBuffer(info.id, "$ $command")

        if (wait) {
            Thread.sleep(minOf(timeout.toLong() * 1000, 30000))
            return readOutput(info.id, 50)
        }

        return "Executed in terminal ${info.id}: $command"
    }

    fun sendControl(sessionId: String?, key: String): String {
        val info = resolveTerminal(sessionId) ?: return "Terminal not found: $sessionId"

        val controlChars = mapOf(
            "c" to "\u0003", "d" to "\u0004", "z" to "\u001a",
            "a" to "\u0001", "e" to "\u0005", "k" to "\u000b",
            "l" to "\u000c", "u" to "\u0015", "w" to "\u0017",
            "enter" to "\r", "esc" to "\u001b", "tab" to "\t",
            "backspace" to "\u007f",
            "up" to "\u001b[A", "down" to "\u001b[B",
            "right" to "\u001b[C", "left" to "\u001b[D",
        )

        val char = controlChars[key] ?: return "Unknown control key: $key"

        if (info.widget != null) {
            ApplicationManager.getApplication().invokeLater {
                try {
                    info.widget.executeCommand(char)
                } catch (e: Exception) {
                    log.warn("Failed to send control via classic: ${e.message}")
                }
            }
        } else if (info.newView != null) {
            ApplicationManager.getApplication().invokeLater {
                try {
                    newApi.sendText(info.newView, char)
                } catch (e: Exception) {
                    log.warn("Failed to send control via new API: ${e.message}")
                }
            }
        } else {
            return "Terminal does not support control keys: ${info.id}"
        }

        return "Sent control key: $key"
    }

    fun splitPane(sessionId: String?, direction: String): Map<String, String> {
        val info = resolveTerminal(sessionId)
        val project = info?.project
            ?: ProjectManager.getInstance().openProjects.firstOrNull()
            ?: return mapOf("new_session_id" to "error", "error" to "No project open")

        val beforeCount = getAllTerminals().size
        // direction "h" = horizontal split (split down), "v" = vertical split (split right)
        val vertically = direction != "h"
        log.info("sideshell: splitPane direction=$direction vertically=$vertically beforeCount=$beforeCount")

        val isNewTerminal = info?.newView != null && info.widget == null
        val latch = CountDownLatch(1)

        ApplicationManager.getApplication().invokeLater {
            try {
                val toolWindow = ToolWindowManager.getInstance(project).getToolWindow("Terminal")
                if (toolWindow == null) {
                    log.warn("sideshell: Terminal tool window not found")
                    latch.countDown()
                    return@invokeLater
                }

                // === Strategy 1 (primary): TW.SplitRight/Down via activate() ===
                // Works for BOTH new and classic terminals. Creates a visual split
                // pane with a new terminal session tracked by the tab manager.
                // activate() ensures the tool window gets focus (required for TW.Split).
                // Select the target content before activating
                val cm = info?.content?.manager
                if (cm != null && info?.content != null) {
                    cm.setSelectedContent(info.content, true)
                }

                toolWindow.activate({
                    try {
                        val actionId = if (vertically) "TW.SplitRight" else "TW.SplitDown"
                        val action = ActionManager.getInstance().getAction(actionId)
                        if (action != null) {
                            val targetComponent = info?.content?.component ?: toolWindow.component
                            val dataContext = DataManager.getInstance().getDataContext(targetComponent)
                            val event = AnActionEvent.createFromAnAction(
                                action, null, "sideshell", dataContext
                            )
                            action.actionPerformed(event)
                            val fo = IdeFocusManager.getInstance(project).focusOwner
                            log.info("sideshell: executed $actionId via activate (focusOwner=${fo?.javaClass?.simpleName}, targetComponent=${targetComponent.javaClass.simpleName})")
                        } else {
                            log.warn("sideshell: action $actionId not found")
                        }
                    } catch (e: Exception) {
                        log.warn("sideshell: TW.Split action failed: ${e.message}", e)
                    }
                    latch.countDown()
                }, true) // autoFocusContents = true
            } catch (e: Exception) {
                log.warn("sideshell: split failed: ${e.message}", e)
                latch.countDown()
            }
        }

        latch.await(5, TimeUnit.SECONDS)

        // Poll for new terminal to appear (tab creation is async via coroutines).
        var after = listOf<TerminalInfo>()
        for (attempt in 1..10) {
            Thread.sleep(500)
            val ref = java.util.concurrent.atomic.AtomicReference<List<TerminalInfo>>()
            javax.swing.SwingUtilities.invokeAndWait {
                ref.set(getAllTerminals())
            }
            after = ref.get()
            log.info("sideshell: split poll attempt $attempt: count=${after.size} (need >${beforeCount})")
            if (after.size > beforeCount) break
        }

        // If TW.Split didn't create a new detectable terminal, fall back to createTab
        if (isNewTerminal && after.size <= beforeCount) {
            log.info("sideshell: TW.Split didn't increase count, falling back to createTab")
            val tabLatch = CountDownLatch(1)
            ApplicationManager.getApplication().invokeLater {
                try {
                    newApi.createTab(project, null, null)
                } catch (e: Exception) {
                    log.warn("sideshell: fallback createTab failed: ${e.message}", e)
                }
                tabLatch.countDown()
            }
            tabLatch.await(5, TimeUnit.SECONDS)

            // Poll again for the new tab
            for (attempt in 1..10) {
                Thread.sleep(500)
                val ref = java.util.concurrent.atomic.AtomicReference<List<TerminalInfo>>()
                javax.swing.SwingUtilities.invokeAndWait { ref.set(getAllTerminals()) }
                after = ref.get()
                log.info("sideshell: fallback poll attempt $attempt: count=${after.size} (need >${beforeCount})")
                if (after.size > beforeCount) break
            }
        }

        val newId = if (after.size > beforeCount) {
            after.last().id
        } else {
            after.lastOrNull()?.id ?: "unknown"
        }
        log.info("sideshell: split result: afterCount=${after.size} newId=$newId")
        return mapOf("new_session_id" to newId)
    }

    fun createTab(profile: String?, command: String?): Map<String, String> {
        val project = ProjectManager.getInstance().openProjects.firstOrNull()
            ?: return mapOf("new_session_id" to "error", "error" to "No project open")

        val beforeCount = getAllTerminals().size
        log.info("sideshell: createTab profile=$profile command=$command beforeCount=$beforeCount")

        val latch = CountDownLatch(1)

        ApplicationManager.getApplication().invokeLater {
            try {
                // Try new terminal API first (must run on EDT)
                if (newApi.available) {
                    try {
                        val result = newApi.createTab(project, profile, command)
                        if (result != null) {
                            log.info("sideshell: created tab via new API on EDT")
                            latch.countDown()
                            return@invokeLater
                        }
                        log.info("sideshell: new API createTab returned null, falling back")
                    } catch (e: Exception) {
                        log.info("sideshell: new API createTab on EDT failed: ${e.message}")
                    }
                }

                // Fall back to classic API
                val manager = TerminalToolWindowManager.getInstance(project)
                manager.createLocalShellWidget(
                    project.basePath ?: ".",
                    profile ?: "sideshell",
                )
                if (command != null) {
                    Thread.sleep(500)
                    val terminals = getAllTerminals()
                    terminals.lastOrNull()?.widget?.executeCommand(command)
                }
            } catch (e: Exception) {
                log.warn("sideshell: failed to create tab: ${e.message}", e)
            }
            latch.countDown()
        }

        latch.await(5, TimeUnit.SECONDS)
        Thread.sleep(500)

        val after = getAllTerminals()
        val newId = if (after.size > beforeCount) {
            after.last().id
        } else {
            after.lastOrNull()?.id ?: "unknown"
        }
        log.info("sideshell: createTab result: newId=$newId afterCount=${after.size}")
        return mapOf("new_session_id" to newId)
    }

    fun focusSession(sessionId: String): String {
        val info = resolveTerminal(sessionId) ?: return "Terminal not found: $sessionId"

        ApplicationManager.getApplication().invokeLater {
            try {
                val toolWindow = ToolWindowManager.getInstance(info.project)
                    .getToolWindow("Terminal")
                if (info.content != null) {
                    toolWindow?.contentManager?.setSelectedContent(info.content, true)
                }
                toolWindow?.show()
            } catch (e: Exception) {
                log.warn("sideshell: failed to focus: ${e.message}")
            }
        }

        return "Focused terminal $sessionId"
    }

    fun returnFocus(sessionId: String?): String {
        val info = if (sessionId != null) resolveTerminal(sessionId) else null
        val project = info?.project
            ?: ProjectManager.getInstance().openProjects.firstOrNull()
            ?: return "No project open"

        ApplicationManager.getApplication().invokeLater {
            try {
                val editor = FileEditorManager.getInstance(project).selectedTextEditor
                if (editor != null) {
                    IdeFocusManager.getInstance(project)
                        .requestFocus(editor.contentComponent, true)
                } else {
                    ToolWindowManager.getInstance(project)
                        .getToolWindow("Terminal")?.hide()
                }
            } catch (e: Exception) {
                log.warn("sideshell: failed to return focus: ${e.message}")
            }
        }

        return "Focus returned to editor"
    }

    fun closeSession(sessionId: String?): String {
        val info = resolveTerminal(sessionId) ?: return "Terminal not found: $sessionId"
        log.info("sideshell: closeSession ${info.id}: content=${info.content != null}, widget=${info.widget != null}, newView=${info.newView != null}")

        ApplicationManager.getApplication().invokeLater {
            try {
                var closed = false

                // Strategy 1: Remove content from its ContentManager
                if (info.content != null) {
                    val cm = info.content.manager
                    log.info("sideshell: close via content.manager: cm=${cm != null}, cm.class=${cm?.javaClass?.simpleName}")
                    if (cm != null) {
                        cm.removeContent(info.content, true)
                        closed = true
                        log.info("sideshell: removeContent succeeded")
                    }
                }

                // Strategy 2: Close via new terminal API (TabsManager.closeTab)
                if (!closed && info.content != null) {
                    closed = newApi.closeTabByContent(info.project, info.content)
                }

                // Strategy 3: Use widget's listener.onSessionClosed()
                if (!closed && info.widget != null) {
                    try {
                        val listener = info.widget.listener
                        if (listener != null) {
                            listener.onSessionClosed()
                            closed = true
                            log.info("sideshell: closed via listener.onSessionClosed()")
                        }
                    } catch (e: Exception) {
                        log.debug("sideshell: listener close failed: ${e.message}")
                    }
                    // Also close the process
                    try {
                        info.widget.terminalStarter?.close()
                    } catch (_: Exception) {}
                }

                if (!closed) {
                    log.warn("sideshell: could not close terminal ${info.id}")
                }
            } catch (e: Exception) {
                log.warn("sideshell: failed to close: ${e.message}", e)
            }
        }

        outputBuffers.remove(info.id)
        return "Closed terminal ${info.id}"
    }

    fun clearTerminal(sessionId: String?): String {
        val info = resolveTerminal(sessionId) ?: return "Terminal not found: $sessionId"

        if (info.widget != null) {
            ApplicationManager.getApplication().invokeLater {
                try { info.widget.executeCommand("clear") } catch (e: Exception) {
                    log.warn("sideshell: clear failed: ${e.message}")
                }
            }
        } else if (info.newView != null) {
            ApplicationManager.getApplication().invokeLater {
                try { newApi.executeCommand(info.newView, "clear") } catch (e: Exception) {
                    log.warn("sideshell: clear via new API failed: ${e.message}")
                }
            }
        } else {
            return "Terminal does not support clear: ${info.id}"
        }

        outputBuffers[info.id]?.clear()
        return "Cleared terminal ${info.id}"
    }

    fun getTerminalState(sessionId: String?): Map<String, Any?> {
        if (sessionId != null) {
            val info = resolveTerminal(sessionId)
            return mapOf(
                "id" to sessionId,
                "name" to (info?.name ?: "unknown"),
                "buffer_lines" to (outputBuffers[sessionId]?.size ?: 0),
                "type" to (info?.type ?: "unknown"),
            )
        }

        val sessions = listSessions()
        return mapOf(
            "terminals" to sessions,
            "total" to sessions.size,
            "active" to getActiveSessionId(),
        )
    }

    fun setAppearance(
        sessionId: String?,
        title: String?,
        color: String?,
        badge: String?,
    ): String {
        if (title != null) {
            val info = resolveTerminal(sessionId)
            if (info?.content != null) {
                ApplicationManager.getApplication().invokeLater {
                    try {
                        info.content.displayName = title
                    } catch (e: Exception) {
                        log.warn("sideshell: set title failed: ${e.message}")
                    }
                }
                return "Set terminal title: $title"
            }
        }
        return "Appearance settings limited in JetBrains IDE terminal API"
    }

    fun getActiveSessionId(): String? {
        val all = getAllTerminals()
        val active = all.find { it.content?.isSelected == true }
        return active?.id ?: all.firstOrNull()?.id
    }

    fun debugComponentTree(sessionId: String?): Map<String, Any?> {
        val info = resolveTerminal(sessionId)
        val result = mutableMapOf<String, Any?>()
        result["session_id"] = info?.id
        result["type"] = info?.type
        result["has_content"] = info?.content != null
        result["has_widget"] = info?.widget != null
        result["has_newView"] = info?.newView != null

        val contentComponent = info?.content?.component
        if (contentComponent != null) {
            val tree = mutableListOf<String>()
            collectComponentTree(contentComponent, tree, 0, 8)
            result["component_tree"] = tree
        }

        // Also check all registered actions containing "split" or "terminal"
        val splitActions = mutableListOf<String>()
        val am = ActionManager.getInstance()
        for (id in am.getActionIdList("")) {
            val lower = id.lowercase()
            if (lower.contains("split") && (lower.contains("terminal") || lower.contains("tw."))) {
                splitActions.add(id)
            }
        }
        result["split_actions"] = splitActions

        return result
    }

    private fun collectComponentTree(
        component: java.awt.Component,
        tree: MutableList<String>,
        depth: Int,
        maxDepth: Int,
    ) {
        if (depth > maxDepth) return
        val indent = "  ".repeat(depth)
        val cls = component.javaClass.name
        val simpleCls = component.javaClass.simpleName
        val size = "${component.width}x${component.height}"

        // Check for interesting methods
        val methods = try {
            component.javaClass.methods
                .filter { m ->
                    m.parameterCount == 0 && (
                        m.name.contains("split", ignoreCase = true) ||
                        m.name.contains("terminal", ignoreCase = true) ||
                        m.name == "getView" || m.name == "getListener" ||
                        m.name == "getModel" || m.name == "getEditor"
                    )
                }
                .map { it.name }
                .take(5)
        } catch (_: Exception) { emptyList() }

        val methodsStr = if (methods.isNotEmpty()) " methods=${methods}" else ""
        tree.add("${indent}${cls} ($size)${methodsStr}")

        if (component is java.awt.Container) {
            for (child in component.components) {
                collectComponentTree(child, tree, depth + 1, maxDepth)
            }
        }
    }

    fun isAiSession(sessionId: String): Boolean {
        val info = resolveTerminal(sessionId) ?: return false
        val name = info.name.lowercase()
        return name.contains("claude") || name.contains("copilot") ||
                name.contains("cursor") || name.contains("cline") ||
                name.contains("aider")
    }

    private fun resolveTerminal(sessionId: String?): TerminalInfo? {
        if (sessionId != null) {
            return getAllTerminals().find { it.id == sessionId }
        }
        val all = getAllTerminals()
        return all.find { it.content?.isSelected == true } ?: all.firstOrNull()
    }

    private fun getAllTerminals(): List<TerminalInfo> {
        val result = mutableListOf<TerminalInfo>()
        for (project in ProjectManager.getInstance().openProjects) {
            result.addAll(getTerminalsForProject(project))
        }
        log.info("sideshell: getAllTerminals() -> ${result.size} terminals: ${result.map { "${it.id}(${it.type})" }}")
        return result
    }

    /**
     * Find all terminal views within a component tree, handling split panes.
     */
    private fun findTerminalViewsInComponent(
        component: java.awt.Component,
        depth: Int = 0,
    ): List<Any> {
        val views = mutableListOf<Any>()

        // Check if this component is a Splitter (split pane container)
        if (component is com.intellij.openapi.ui.Splitter) {
            component.firstComponent?.let { views.addAll(findTerminalViewsInComponent(it, depth + 1)) }
            component.secondComponent?.let { views.addAll(findTerminalViewsInComponent(it, depth + 1)) }
            return views
        }

        // Check if this component itself has a TerminalView (via reflection)
        val view = newApi.findViewInComponent(component)
        if (view != null) {
            views.add(view)
            return views
        }

        // Recurse into child components (only up to a reasonable depth)
        if (depth < 10 && component is java.awt.Container) {
            for (child in component.components) {
                views.addAll(findTerminalViewsInComponent(child, depth + 1))
            }
        }

        return views
    }

    private fun getTerminalsForProject(project: Project): List<TerminalInfo> {
        val result = mutableListOf<TerminalInfo>()

        // === 1. Try new terminal API (TerminalToolWindowTabsManager) ===
        try {
            val tabs = newApi.getTabs(project)
            log.info("sideshell: new API tabs for ${project.name}: ${tabs.size}")

            var globalIndex = 0
            for ((tabIndex, tab) in tabs.withIndex()) {
                try {
                    val tabView = newApi.getTabView(tab)
                    val content = newApi.getTabContent(tab)
                    val tabName = content?.displayName
                        ?: newApi.getTabName(tab)
                        ?: "Terminal"

                    // Check if this tab has split panes by examining the content component
                    val contentComponent = content?.component
                    val hasSplitter = contentComponent != null &&
                            containsSplitter(contentComponent)

                    if (hasSplitter && contentComponent != null) {
                        log.info("sideshell: tab[$tabIndex] '$tabName' has splits, traversing component tree")
                        val splitViews = findTerminalViewsInComponent(contentComponent)
                        log.info("sideshell: found ${splitViews.size} views in split tab[$tabIndex]")

                        if (splitViews.isNotEmpty()) {
                            for ((splitIdx, splitView) in splitViews.withIndex()) {
                                val id = "term-${project.name}-$globalIndex"
                                val name = if (splitIdx == 0) tabName else "$tabName (split ${splitIdx + 1})"
                                result.add(TerminalInfo(id, name, content, null, splitView, project))
                                globalIndex++
                            }
                        } else {
                            val id = "term-${project.name}-$globalIndex"
                            result.add(TerminalInfo(id, tabName, content, null, tabView, project))
                            globalIndex++
                        }
                    } else {
                        val id = "term-${project.name}-$globalIndex"
                        // Try to extract ShellTerminalWidget from the content component
                        val widget = if (contentComponent is javax.swing.JComponent) {
                            UIUtil.findComponentsOfType(
                                contentComponent, ShellTerminalWidget::class.java
                            ).firstOrNull()
                        } else null
                        log.info("sideshell: tab[$tabIndex]: name=$tabName, view=${tabView != null}, content=${content != null}, widget=${widget != null}")
                        result.add(TerminalInfo(id, tabName, content, widget, tabView, project))
                        globalIndex++
                    }
                } catch (e: Exception) {
                    log.warn("sideshell: error reading tab $tabIndex: ${e.message}")
                }
            }

            // Also scan for split panes via nested ContentManagers
            // TW.SplitRight/Down creates nested ContentManagers that hold
            // additional terminal Content objects not tracked by getTabs()
            try {
                val toolWindow = ToolWindowManager.getInstance(project)
                    .getToolWindow("Terminal")
                if (toolWindow != null) {
                    val allContents = newApi.findAllContentsRecursive(toolWindow)
                    val trackedContents = result.mapNotNull { it.content }
                        .map { System.identityHashCode(it) }.toSet()

                    val untrackedContents = allContents.filter {
                        System.identityHashCode(it) !in trackedContents
                    }

                    if (untrackedContents.isNotEmpty()) {
                        log.info("sideshell: found ${untrackedContents.size} untracked contents in nested ContentManagers")
                        for (content in untrackedContents) {
                            val contentComponent = content.component
                            log.info("sideshell: untracked content '${content.displayName}': component=${contentComponent?.javaClass?.name}")

                            // Dump the content's component tree for debugging
                            if (contentComponent != null) {
                                log.info("sideshell: content '${content.displayName}' component tree:")
                                dumpComponentTree(contentComponent, 0, 5)
                            }

                            // Strategy A: Look for ShellTerminalWidget in content's component tree
                            var added = false
                            if (contentComponent is javax.swing.JComponent) {
                                val widgets = UIUtil.findComponentsOfType(
                                    contentComponent,
                                    ShellTerminalWidget::class.java,
                                )
                                if (widgets.isNotEmpty()) {
                                    val widget = widgets.first()
                                    val id = "term-${project.name}-$globalIndex"
                                    val name = content.displayName ?: "Terminal (split ${globalIndex + 1})"
                                    log.info("sideshell: adding split pane via ShellTerminalWidget: id=$id name=$name")
                                    result.add(TerminalInfo(id, name, content, widget, null, project))
                                    globalIndex++
                                    added = true
                                }
                            }

                            // Strategy B: Look for TerminalView via DataProvider/reflection
                            if (!added) {
                                val view = newApi.findTerminalViewInContent(content)
                                if (view != null) {
                                    val id = "term-${project.name}-$globalIndex"
                                    val name = content.displayName ?: "Terminal (split ${globalIndex + 1})"
                                    log.info("sideshell: adding split pane via TerminalView: id=$id name=$name")
                                    result.add(TerminalInfo(id, name, content, null, view, project))
                                    globalIndex++
                                    added = true
                                }
                            }

                            if (!added) {
                                log.info("sideshell: untracked content '${content.displayName}' has no terminal widget, skipping")
                            }
                        }
                    }
                }
            } catch (e: Exception) {
                log.debug("sideshell: nested ContentManager scan error: ${e.message}")
            }

            // Also check if there are additional classic ShellTerminalWidgets
            // (split panes created via listener.split coexist with new terminal)
            val frame = WindowManager.getInstance().getFrame(project)
            if (frame != null) {
                val classicWidgets = UIUtil.findComponentsOfType(
                    frame.rootPane as javax.swing.JComponent,
                    ShellTerminalWidget::class.java,
                )
                // If UIUtil finds MORE widgets than the new API tabs, add the extras
                if (classicWidgets.size > result.size) {
                    log.info("sideshell: new API found ${result.size} but UIUtil found ${classicWidgets.size} classic widgets — adding extras")
                    for (idx in result.size until classicWidgets.size) {
                        val widget = classicWidgets[idx]
                        val id = "term-${project.name}-${globalIndex}"
                        val rawTitle = widget.terminalTitle?.toString() ?: ""
                        val name = if (rawTitle.contains("default=")) {
                            Regex("default=(.+?)(?:,\\s|$)").find(rawTitle)?.groupValues?.get(1)
                                ?: "Terminal ${idx + 1}"
                        } else if (rawTitle.isNotBlank()) {
                            rawTitle
                        } else {
                            "Terminal ${idx + 1}"
                        }
                        result.add(TerminalInfo(id, name, null, widget, null, project))
                        globalIndex++
                    }
                }
            }

            if (result.isNotEmpty()) {
                log.info("sideshell: using new API, found ${result.size} terminals (from ${tabs.size} tabs + nested scan)")
                return result
            }
        } catch (e: Exception) {
            log.info("sideshell: new API not available: ${e.message}")
        }

        // === 2. Fall back: traverse tool window component tree directly ===
        try {
            val toolWindow = ToolWindowManager.getInstance(project)
                .getToolWindow("Terminal")

            if (toolWindow == null) {
                log.info("sideshell: no Terminal tool window for ${project.name}")
                return emptyList()
            }

            val contents = toolWindow.contentManager.contents
            log.info("sideshell: classic API: ${contents.size} root contents for ${project.name}")

            if (contents.isNotEmpty()) {
                var index = 0
                for (content in contents) {
                    try {
                        val contentComponent = content.component
                        if (containsSplitter(contentComponent)) {
                            log.info("sideshell: content '${content.displayName}' has splits, scanning...")
                            val widgets = findClassicWidgetsInComponent(contentComponent)
                            log.info("sideshell: found ${widgets.size} widgets in split content")
                            for ((splitIdx, widget) in widgets.withIndex()) {
                                val id = "term-${project.name}-$index"
                                val name = if (splitIdx == 0) {
                                    content.displayName ?: "Terminal"
                                } else {
                                    "${content.displayName ?: "Terminal"} (split ${splitIdx + 1})"
                                }
                                result.add(TerminalInfo(id, name, content, widget, null, project))
                                index++
                            }
                        } else {
                            val widget = try {
                                TerminalView.getWidgetByContent(content) as? ShellTerminalWidget
                            } catch (e: Exception) { null }
                            val id = "term-${project.name}-$index"
                            val name = content.displayName ?: "Terminal"
                            log.info("sideshell: content[$index]: name=$name, widget=${widget != null}")
                            result.add(TerminalInfo(id, name, content, widget, null, project))
                            index++
                        }
                    } catch (e: Exception) {
                        log.debug("sideshell: error at content: ${e.message}")
                    }
                }
            }

            // If ContentManager is empty (split moved content to nested managers),
            // scan the entire project frame for terminal widgets using UIUtil
            if (result.isEmpty()) {
                log.info("sideshell: root ContentManager empty, scanning entire project frame")

                val frame = WindowManager.getInstance().getFrame(project)
                if (frame != null) {
                    val widgets = UIUtil.findComponentsOfType(
                        frame.rootPane as javax.swing.JComponent,
                        ShellTerminalWidget::class.java,
                    )
                    log.info("sideshell: UIUtil found ${widgets.size} ShellTerminalWidget(s) in frame")

                    for ((idx, widget) in widgets.withIndex()) {
                        val id = "term-${project.name}-$idx"
                        val rawTitle = widget.terminalTitle?.toString() ?: ""
                        val name = if (rawTitle.contains("default=")) {
                            Regex("default=(.+?)(?:,\\s|$)").find(rawTitle)?.groupValues?.get(1)
                                ?: "Terminal ${idx + 1}"
                        } else if (rawTitle.isNotBlank()) {
                            rawTitle
                        } else {
                            "Terminal ${idx + 1}"
                        }
                        log.info("sideshell: widget[$idx]: title=$name, class=${widget.javaClass.simpleName}")
                        result.add(TerminalInfo(id, name, null, widget, null, project))
                    }
                } else {
                    log.warn("sideshell: no frame for project ${project.name}")
                }
            }
        } catch (e: Exception) {
            log.debug("sideshell: classic API failed for ${project.name}: ${e.message}")
        }

        log.info("sideshell: total for ${project.name}: ${result.size} terminals")
        return result
    }

    /**
     * Find all ShellTerminalWidget instances in a component tree.
     */
    private fun findClassicWidgetsInComponent(component: java.awt.Component): List<ShellTerminalWidget> {
        val widgets = mutableListOf<ShellTerminalWidget>()
        findWidgetsRecursive(component, widgets, 0)
        return widgets
    }

    private fun findWidgetsRecursive(
        component: java.awt.Component,
        widgets: MutableList<ShellTerminalWidget>,
        depth: Int,
    ) {
        if (depth > 20) return

        if (component is ShellTerminalWidget) {
            widgets.add(component)
            return
        }

        if (component is com.intellij.openapi.ui.Splitter) {
            component.firstComponent?.let { findWidgetsRecursive(it, widgets, depth + 1) }
            component.secondComponent?.let { findWidgetsRecursive(it, widgets, depth + 1) }
            return
        }

        if (component is java.awt.Container) {
            for (child in component.components) {
                findWidgetsRecursive(child, widgets, depth + 1)
            }
        }
    }

    private fun dumpComponentTree(component: java.awt.Component, depth: Int, maxDepth: Int) {
        if (depth > maxDepth) return
        val indent = "  ".repeat(depth)
        val cls = component.javaClass.simpleName
        val size = "${component.width}x${component.height}"
        log.info("sideshell: ${indent}$cls ($size)")

        if (component is java.awt.Container) {
            for (child in component.components) {
                dumpComponentTree(child, depth + 1, maxDepth)
            }
        }
    }

    private fun containsSplitter(component: java.awt.Component): Boolean {
        if (component is com.intellij.openapi.ui.Splitter) return true
        if (component is java.awt.Container) {
            for (child in component.components) {
                if (containsSplitter(child)) return true
            }
        }
        return false
    }

    private fun addToBuffer(sessionId: String, line: String) {
        val buffer = outputBuffers.getOrPut(sessionId) { mutableListOf() }
        synchronized(buffer) {
            buffer.add(line)
            while (buffer.size > maxBufferSize) {
                buffer.removeAt(0)
            }
        }
    }
}

/**
 * Helper for new terminal API (2025.3+) via reflection.
 * All methods fail gracefully if API not available.
 */
class NewTerminalApiHelper {
    private val log = Logger.getInstance(NewTerminalApiHelper::class.java)

    val available: Boolean
    private val tabsManagerClass: Class<*>?
    private val tabClass: Class<*>?

    init {
        var avail = false
        var tmClass: Class<*>? = null
        var tClass: Class<*>? = null
        try {
            tmClass = Class.forName("com.intellij.terminal.frontend.toolwindow.TerminalToolWindowTabsManager")
            tClass = Class.forName("com.intellij.terminal.frontend.toolwindow.TerminalToolWindowTab")
            avail = true
            log.info("sideshell: new terminal API available")
        } catch (e: ClassNotFoundException) {
            log.info("sideshell: new terminal API NOT available: ${e.message}")
        }
        available = avail
        tabsManagerClass = tmClass
        tabClass = tClass
    }

    fun getTabs(project: Project): List<Any> {
        if (!available || tabsManagerClass == null) return emptyList()
        return try {
            val getInstanceMethod = tabsManagerClass.getMethod("getInstance", Project::class.java)
            val instance = getInstanceMethod.invoke(null, project) ?: run {
                log.info("sideshell: TabsManager.getInstance returned null")
                return emptyList()
            }

            val getTabsMethod = instance.javaClass.getMethod("getTabs")
            val tabs = getTabsMethod.invoke(instance) as? List<*> ?: run {
                log.info("sideshell: getTabs returned null")
                return emptyList()
            }

            log.info("sideshell: getTabs returned ${tabs.size} tabs")
            tabs.filterNotNull()
        } catch (e: Exception) {
            log.warn("sideshell: getTabs failed: ${e.message}", e)
            emptyList()
        }
    }

    fun getTabView(tab: Any): Any? {
        return try {
            val m = tab.javaClass.getMethod("getView")
            m.invoke(tab)
        } catch (e: Exception) {
            log.debug("sideshell: getView failed: ${e.message}")
            null
        }
    }

    fun findViewInComponent(component: java.awt.Component): Any? {
        val className = component.javaClass.name
        if (className.contains("TerminalPanel") ||
            className.contains("TerminalView") ||
            className.contains("TerminalWidget")) {
            return tryExtractView(component)
        }

        try {
            val dataProviderClass = Class.forName("com.intellij.openapi.actionSystem.DataProvider")
            if (dataProviderClass.isInstance(component)) {
                val getDataMethod = dataProviderClass.getMethod("getData", String::class.java)
                for (key in listOf("TerminalView", "terminal.view", "TERMINAL_VIEW")) {
                    val data = getDataMethod.invoke(component, key)
                    if (data != null) return data
                }
            }
        } catch (_: Exception) {}

        return null
    }

    fun tryExtractViewPublic(component: java.awt.Component): Any? = tryExtractView(component)

    private fun tryExtractView(component: java.awt.Component): Any? {
        try {
            val m = component.javaClass.getMethod("getView")
            val view = m.invoke(component)
            if (view != null) return view
        } catch (_: Exception) {}

        try {
            val m = component.javaClass.getMethod("getTerminalView")
            val view = m.invoke(component)
            if (view != null) return view
        } catch (_: Exception) {}

        try {
            component.javaClass.getMethod("sendText", String::class.java)
            return component
        } catch (_: Exception) {}

        return null
    }

    fun getTabContent(tab: Any): Content? {
        return try {
            val m = tab.javaClass.getMethod("getContent")
            m.invoke(tab) as? Content
        } catch (e: Exception) {
            log.debug("sideshell: getContent failed: ${e.message}")
            null
        }
    }

    fun getTabName(tab: Any): String? {
        return try {
            val view = getTabView(tab) ?: return null
            val getTitleMethod = view.javaClass.getMethod("getTitle")
            val title = getTitleMethod.invoke(view)
            title?.toString()
        } catch (e: Exception) {
            null
        }
    }

    fun sendText(view: Any, text: String) {
        val m = view.javaClass.getMethod("sendText", String::class.java)
        m.invoke(view, text)
    }

    fun executeCommand(view: Any, command: String) {
        try {
            val builderMethod = view.javaClass.getMethod("createSendTextBuilder")
            val builder = builderMethod.invoke(view)
            val shouldExec = builder.javaClass.getMethod("shouldExecute")
            val b2 = shouldExec.invoke(builder)
            val sendMethod = b2.javaClass.getMethod("send", String::class.java)
            sendMethod.invoke(b2, command)
        } catch (e: Exception) {
            log.debug("sideshell: sendTextBuilder fallback: ${e.message}")
            sendText(view, command + "\n")
        }
    }

    fun readOutput(view: Any, lines: Int): String? {
        return try {
            val getOutputModels = view.javaClass.getMethod("getOutputModels")
            val models = getOutputModels.invoke(view)
            val getActive = models.javaClass.getMethod("getActive")
            val activeFlow = getActive.invoke(models)
            val getValue = activeFlow.javaClass.getMethod("getValue")
            val model = getValue.invoke(activeFlow)

            val getStart = model.javaClass.getMethod("getStartOffset")
            val getEnd = model.javaClass.getMethod("getEndOffset")
            val startOffset = getStart.invoke(model)
            val endOffset = getEnd.invoke(model)

            val getTextMethod = model.javaClass.methods.find { m ->
                m.name == "getText" && m.parameterCount == 2
            } ?: return null

            val text = getTextMethod.invoke(model, startOffset, endOffset) as? CharSequence
            text?.toString()?.lines()?.takeLast(lines)?.joinToString("\n")
        } catch (e: Exception) {
            log.debug("sideshell: readOutput failed: ${e.message}")
            null
        }
    }

    /**
     * Find all Content objects in a tool window, including those in nested
     * ContentManagers created by TW.SplitRight/Down splits.
     */
    fun findAllContentsRecursive(toolWindow: com.intellij.openapi.wm.ToolWindow): List<Content> {
        val allContents = mutableListOf<Content>()
        val visited = mutableSetOf<Int>()

        fun collectFromManager(manager: com.intellij.ui.content.ContentManager) {
            val id = System.identityHashCode(manager)
            if (!visited.add(id)) return
            for (content in manager.contents) {
                allContents.add(content)
            }
        }

        // Start with root ContentManager
        collectFromManager(toolWindow.contentManager)

        // Also scan for nested ContentManagers in the component tree
        // (created by InternalDecoratorImpl splits)
        val toolWindowComponent = toolWindow.component
        if (toolWindowComponent != null) {
            findNestedContentManagers(toolWindowComponent, visited).forEach { cm ->
                for (content in cm.contents) {
                    allContents.add(content)
                }
            }
        }

        return allContents.distinctBy { System.identityHashCode(it) }
    }

    /**
     * Scan component tree for ContentManager instances in nested decorators.
     */
    private fun findNestedContentManagers(
        component: java.awt.Component,
        visited: MutableSet<Int>,
        depth: Int = 0,
    ): List<com.intellij.ui.content.ContentManager> {
        if (depth > 15) return emptyList()
        val result = mutableListOf<com.intellij.ui.content.ContentManager>()

        // Check if this component is an InternalDecoratorImpl (has getContentManager)
        try {
            val getContentManager = component.javaClass.getMethod("getContentManager")
            val cm = getContentManager.invoke(component) as? com.intellij.ui.content.ContentManager
            if (cm != null) {
                val id = System.identityHashCode(cm)
                if (visited.add(id)) {
                    result.add(cm)
                }
            }
        } catch (_: Exception) {}

        // Recurse into children
        if (component is java.awt.Container) {
            for (child in component.components) {
                result.addAll(findNestedContentManagers(child, visited, depth + 1))
            }
        }

        return result
    }

    /**
     * Try to extract a TerminalView from a Content's component using DataKey.
     */
    fun findTerminalViewInContent(content: Content): Any? {
        val component = content.component ?: return null

        // Method 1: Check if the component implements DataProvider with TerminalView key
        try {
            val dataProviderClass = Class.forName("com.intellij.openapi.actionSystem.DataProvider")
            if (dataProviderClass.isInstance(component)) {
                val getDataMethod = dataProviderClass.getMethod("getData", String::class.java)
                for (key in listOf("TerminalView", "terminal.view")) {
                    val data = getDataMethod.invoke(component, key)
                    if (data != null) {
                        log.info("sideshell: found TerminalView via DataProvider key '$key'")
                        return data
                    }
                }
            }
        } catch (_: Exception) {}

        // Method 2: Recurse into component tree looking for TerminalView components
        return findTerminalViewRecursive(component, 0)
    }

    private fun findTerminalViewRecursive(component: java.awt.Component, depth: Int): Any? {
        if (depth > 15) return null

        // Check class name for terminal-related components
        val className = component.javaClass.name
        if (className.contains("TerminalPanel") ||
            className.contains("TerminalView") ||
            className.contains("TerminalWidget")) {
            val view = tryExtractViewPublic(component)
            if (view != null) return view
        }

        // Check DataProvider interface
        try {
            val dataProviderClass = Class.forName("com.intellij.openapi.actionSystem.DataProvider")
            if (dataProviderClass.isInstance(component)) {
                val getDataMethod = dataProviderClass.getMethod("getData", String::class.java)
                for (key in listOf("TerminalView", "terminal.view")) {
                    val data = getDataMethod.invoke(component, key)
                    if (data != null) return data
                }
            }
        } catch (_: Exception) {}

        // Recurse into children
        if (component is java.awt.Container) {
            for (child in component.components) {
                val found = findTerminalViewRecursive(child, depth + 1)
                if (found != null) return found
            }
        }

        return null
    }

    /**
     * Call a method on the builder, handling access restrictions on private inner classes.
     * Returns the result of the method call, or null if the method doesn't exist.
     */
    private fun callBuilderMethod(builder: Any, methodName: String, vararg args: Any?): Any? {
        // Try declared methods first (handles private inner class)
        for (m in builder.javaClass.declaredMethods) {
            if (m.name == methodName && m.parameterCount == args.size) {
                m.isAccessible = true
                return m.invoke(builder, *args)
            }
        }
        // Try interfaces
        for (iface in builder.javaClass.interfaces) {
            for (m in iface.methods) {
                if (m.name == methodName && m.parameterCount == args.size) {
                    val dm = builder.javaClass.getDeclaredMethod(m.name, *m.parameterTypes)
                    dm.isAccessible = true
                    return dm.invoke(builder, *args)
                }
            }
        }
        return null
    }

    fun createTab(project: Project, profile: String?, command: String?): Map<String, String>? {
        if (!available || tabsManagerClass == null) return null
        return try {
            val getInstanceMethod = tabsManagerClass.getMethod("getInstance", Project::class.java)
            val instance = getInstanceMethod.invoke(null, project) ?: return null

            val createBuilderMethod = instance.javaClass.getMethod("createTabBuilder")
            createBuilderMethod.isAccessible = true
            val builder = createBuilderMethod.invoke(instance) ?: return null
            log.info("sideshell: builder class: ${builder.javaClass.name}")

            // Set working directory
            val basePath = project.basePath
            if (basePath != null) {
                try { callBuilderMethod(builder, "workingDirectory", basePath) } catch (_: Exception) {}
            }

            // Set tab name
            if (profile != null) {
                try { callBuilderMethod(builder, "tabName", profile) } catch (_: Exception) {}
            }

            // Request focus
            try { callBuilderMethod(builder, "requestFocus", true) } catch (_: Exception) {}

            // Start session immediately
            try { callBuilderMethod(builder, "deferSessionStartUntilUiShown", false) } catch (_: Exception) {}

            log.info("sideshell: creating tab via new API builder")
            val tab = callBuilderMethod(builder, "createTab")
            log.info("sideshell: createTab returned: ${tab?.javaClass?.simpleName}")

            Thread.sleep(500)

            // Find the new session by scanning all terminals
            // (getTabs may not include it immediately, use full scan)
            val allTerminals = getTerminalsForProject(project)
            val newId = allTerminals.lastOrNull()?.let { "term-${project.name}-${allTerminals.size - 1}" } ?: "unknown"
            log.info("sideshell: createTab result: newId=$newId, total=${allTerminals.size}")

            if (command != null) {
                // Find and execute in the new tab
                val newView = if (tab != null) getTabView(tab) else null
                if (newView != null) {
                    Thread.sleep(500)
                    executeCommand(newView, command)
                }
            }

            mapOf("new_session_id" to newId)
        } catch (e: Exception) {
            log.warn("sideshell: createTab via new API failed: ${e.message}", e)
            null
        }
    }

    /**
     * Get all terminals for a project (delegates to TerminalManagerService logic).
     * Used internally to find terminals after creation.
     */
    private fun getTerminalsForProject(project: Project): List<Any> {
        if (!available || tabsManagerClass == null) return emptyList()
        return try {
            val tabs = getTabs(project)
            tabs
        } catch (e: Exception) {
            emptyList()
        }
    }

    /**
     * Close a tab by its Content. Finds the matching tab and calls closeTab() on the manager.
     * Returns true if the tab was closed successfully.
     */
    fun closeTabByContent(project: Project, content: Content): Boolean {
        if (!available || tabsManagerClass == null) return false
        return try {
            val getInstanceMethod = tabsManagerClass.getMethod("getInstance", Project::class.java)
            val instance = getInstanceMethod.invoke(null, project) ?: return false

            val tabs = getTabs(project)
            for (tab in tabs) {
                val tabContent = getTabContent(tab)
                if (tabContent != null && System.identityHashCode(tabContent) == System.identityHashCode(content)) {
                    // Try closeTab(tab)
                    try {
                        val closeMethod = instance.javaClass.getMethod("closeTab", tabClass)
                        closeMethod.invoke(instance, tab)
                        log.info("sideshell: closed tab via closeTab()")
                        return true
                    } catch (_: Exception) {}

                    // Try removeTab(tab)
                    try {
                        val removeMethod = instance.javaClass.getMethod("removeTab", tabClass)
                        removeMethod.invoke(instance, tab)
                        log.info("sideshell: closed tab via removeTab()")
                        return true
                    } catch (_: Exception) {}

                    // Try tab.close()
                    try {
                        val closeMethod = tab.javaClass.getMethod("close")
                        closeMethod.invoke(tab)
                        log.info("sideshell: closed tab via tab.close()")
                        return true
                    } catch (_: Exception) {}

                    // Try dispose()
                    try {
                        val disposeMethod = tab.javaClass.getMethod("dispose")
                        disposeMethod.invoke(tab)
                        log.info("sideshell: closed tab via tab.dispose()")
                        return true
                    } catch (_: Exception) {}

                    log.warn("sideshell: found matching tab but no close method worked")
                    break
                }
            }
            false
        } catch (e: Exception) {
            log.warn("sideshell: closeTabByContent failed: ${e.message}")
            false
        }
    }
}
