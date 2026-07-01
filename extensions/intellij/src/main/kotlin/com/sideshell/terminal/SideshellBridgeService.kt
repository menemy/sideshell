package com.sideshell.terminal

import com.google.gson.GsonBuilder
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.Service
import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.ui.Messages
import java.io.BufferedReader
import java.io.File
import java.io.InputStreamReader
import java.io.PrintWriter
import java.net.StandardProtocolFamily
import java.net.UnixDomainSocketAddress
import java.nio.channels.Channels
import java.nio.channels.ServerSocketChannel
import java.nio.channels.SocketChannel
import java.security.SecureRandom

/**
 * Unix socket bridge service that exposes terminal control via JSON-RPC 2.0.
 * Newline-delimited JSON protocol over Unix domain socket.
 *
 * Security (two layers):
 *   1. Token auth - random token generated on start, written to port file (0600).
 *      Client must send {"type":"auth","token":"..."} as first message.
 *   2. User consent - on first connection, a dialog asks the user to approve.
 *      Until approved, all JSON-RPC requests return an auth error.
 */
@Service(Service.Level.APP)
class SideshellBridgeService {
    private val log = Logger.getInstance(SideshellBridgeService::class.java)
    private val gson = GsonBuilder().serializeNulls().create()
    private var serverChannel: ServerSocketChannel? = null
    private var serverThread: Thread? = null
    private val terminalManager = TerminalManagerService()

    private var token: String = ""
    @Volatile
    private var approvalPending = false
    @Volatile
    private var running = false

    private val socketPath: String
        get() = File(System.getProperty("user.home"), ".sideshell/intellij.sock").absolutePath

    val isRunning: Boolean
        get() = running

    fun start() {
        if (running) return

        token = generateToken()
        approvalPending = false

        try {
            val sockFile = File(socketPath)
            sockFile.parentFile?.mkdirs()
            sockFile.delete() // Clean up stale socket

            val address = UnixDomainSocketAddress.of(socketPath)
            serverChannel = ServerSocketChannel.open(StandardProtocolFamily.UNIX)
            serverChannel!!.bind(address)

            // Set socket file permissions to owner-only
            sockFile.setReadable(false, false)
            sockFile.setReadable(true, true)
            sockFile.setWritable(false, false)
            sockFile.setWritable(true, true)

            running = true
            writePortFile()

            // Accept connections in a background thread
            serverThread = Thread({
                while (running) {
                    try {
                        val client = serverChannel?.accept() ?: break
                        Thread { handleClient(client) }.start()
                    } catch (e: Exception) {
                        if (running) {
                            log.error("Accept error: ${e.message}", e)
                        }
                    }
                }
            }, "sideshell-accept")
            serverThread!!.isDaemon = true
            serverThread!!.start()

            log.info("sideshell bridge started on $socketPath")
        } catch (e: Exception) {
            log.error("Failed to start sideshell bridge: ${e.message}", e)
        }
    }

    private fun handleClient(channel: SocketChannel) {
        try {
            val reader = BufferedReader(InputStreamReader(Channels.newInputStream(channel)))
            val writer = PrintWriter(Channels.newOutputStream(channel), true)

            // First message must be auth handshake
            val authLine = reader.readLine() ?: return
            val authMsg = JsonParser.parseString(authLine).asJsonObject
            val msgType = authMsg.get("type")?.asString
            val msgToken = authMsg.get("token")?.asString

            if (msgType != "auth" || msgToken != token) {
                log.warn("sideshell: rejected connection — invalid token")
                writer.println(gson.toJson(mapOf("ok" to false, "error" to "invalid token")))
                channel.close()
                return
            }

            writer.println(gson.toJson(mapOf("ok" to true)))
            log.info("sideshell: client connected (token valid)")

            if (!SideshellSettings.getInstance().state.approved && !approvalPending) {
                requestApproval(channel)
            }

            // Read JSON-RPC requests (newline-delimited)
            while (running) {
                val line = reader.readLine() ?: break
                val response = handleRequest(line)
                writer.println(response)
            }
        } catch (e: Exception) {
            if (running) {
                log.debug("Client disconnected: ${e.message}")
            }
        } finally {
            try { channel.close() } catch (_: Exception) {}
            log.info("sideshell: client disconnected")
        }
    }

    fun stop() {
        try {
            running = false
            serverChannel?.close()
            serverChannel = null
            serverThread = null
            token = ""
            removePortFile()
            // Clean up socket file
            File(socketPath).delete()
            log.info("sideshell bridge stopped")
        } catch (e: Exception) {
            log.error("Failed to stop sideshell bridge: ${e.message}", e)
        }
    }

    private fun requestApproval(channel: SocketChannel) {
        approvalPending = true

        ApplicationManager.getApplication().invokeLater {
            val result = Messages.showYesNoDialog(
                "Sideshell wants to access your IDE terminals.\n\n" +
                        "This allows an MCP client to read terminal output, " +
                        "execute commands, and manage terminal sessions.\n\n" +
                        "Allow access?",
                "Sideshell Terminal Access",
                "Allow",
                "Deny",
                Messages.getWarningIcon(),
            )

            approvalPending = false

            if (result == Messages.YES) {
                SideshellSettings.getInstance().state.approved = true
                log.info("User approved sideshell terminal access (saved)")
            } else {
                log.info("User denied sideshell terminal access")
                token = generateToken()
                writePortFile()
                try { channel.close() } catch (_: Exception) {}
            }
        }
    }

    private fun handleRequest(request: String): String {
        return try {
            val json = JsonParser.parseString(request).asJsonObject
            val id = json.get("id")
            val method = json.get("method")?.asString ?: ""
            val params = json.getAsJsonObject("params") ?: JsonObject()

            if (!SideshellSettings.getInstance().state.approved) {
                val response = JsonObject()
                response.addProperty("jsonrpc", "2.0")
                response.add("id", id)
                val error = JsonObject()
                error.addProperty("code", -32001)
                error.addProperty(
                    "message",
                    "Waiting for user approval in IDE. " +
                            "Please click 'Allow' in the dialog.",
                )
                response.add("error", error)
                return gson.toJson(response)
            }

            val result = dispatch(method, params)

            val response = JsonObject()
            response.addProperty("jsonrpc", "2.0")
            response.add("id", id)
            response.add("result", gson.toJsonTree(result))
            gson.toJson(response)
        } catch (e: Exception) {
            val response = JsonObject()
            response.addProperty("jsonrpc", "2.0")
            response.add("id", null)
            val error = JsonObject()
            error.addProperty("code", -32603)
            error.addProperty("message", e.message ?: "Internal error")
            response.add("error", error)
            gson.toJson(response)
        }
    }

    private fun JsonObject.str(key: String): String? {
        val el = get(key) ?: return null
        return if (el.isJsonNull) null else el.asString
    }

    private fun JsonObject.int(key: String, default: Int): Int {
        val el = get(key) ?: return default
        return if (el.isJsonNull) default else el.asInt
    }

    private fun JsonObject.bool(key: String, default: Boolean): Boolean {
        val el = get(key) ?: return default
        return if (el.isJsonNull) default else el.asBoolean
    }

    private fun dispatch(method: String, params: JsonObject): Any {
        val sessionId = params.str("session_id")

        return when (method) {
            "list_sessions" -> terminalManager.listSessions()
            "read_terminal" -> terminalManager.readOutput(
                sessionId,
                params.int("lines", 20),
            )
            "send_text" -> terminalManager.sendText(
                sessionId,
                params.str("text") ?: "",
            )
            "execute_command" -> terminalManager.executeCommand(
                sessionId,
                params.str("command") ?: "",
                params.bool("wait", false),
                params.int("timeout", 30),
                params.str("watch_for") ?: "prompt",
            )
            "send_control" -> terminalManager.sendControl(
                sessionId,
                params.str("key") ?: "",
            )
            "split_pane" -> terminalManager.splitPane(
                sessionId,
                params.str("direction") ?: "v",
            )
            "create_tab" -> terminalManager.createTab(
                params.str("profile"),
                params.str("command"),
            )
            "create_window" -> terminalManager.createTab(
                params.str("profile"),
                params.str("command"),
            )
            "focus_session" -> terminalManager.focusSession(sessionId ?: "")
            "close_session" -> terminalManager.closeSession(sessionId)
            "clear_terminal" -> terminalManager.clearTerminal(sessionId)
            "get_terminal_state" -> terminalManager.getTerminalState(sessionId)
            "set_appearance" -> terminalManager.setAppearance(
                sessionId,
                params.str("title"),
                params.str("color"),
                params.str("badge"),
            )
            "get_active_session" -> mapOf("session_id" to terminalManager.getActiveSessionId())
            "is_ai_session" -> terminalManager.isAiSession(sessionId ?: "")
            "return_focus" -> terminalManager.returnFocus(sessionId)
            "debug_component_tree" -> terminalManager.debugComponentTree(sessionId)
            else -> throw IllegalArgumentException("Unknown method: $method")
        }
    }

    private fun generateToken(): String {
        val bytes = ByteArray(32)
        SecureRandom().nextBytes(bytes)
        return bytes.joinToString("") { "%02x".format(it) }
    }

    private fun writePortFile() {
        try {
            val dir = File(System.getProperty("user.home"), ".sideshell")
            dir.mkdirs()
            val file = File(dir, "intellij-port")
            val data = gson.toJson(mapOf(
                "socket" to socketPath,
                "pid" to ProcessHandle.current().pid(),
                "token" to token,
                "ide" to "intellij",
                "version" to "1.0.0",
            ))
            file.writeText(data)
            file.setReadable(false, false)
            file.setReadable(true, true)
            file.setWritable(false, false)
            file.setWritable(true, true)
        } catch (e: Exception) {
            log.warn("Failed to write port file: ${e.message}")
        }
    }

    private fun removePortFile() {
        try {
            File(System.getProperty("user.home"), ".sideshell/intellij-port").delete()
        } catch (e: Exception) {
            log.debug("Failed to remove port file: ${e.message}")
        }
    }

    companion object {
        fun getInstance(): SideshellBridgeService =
            ApplicationManager.getApplication().getService(SideshellBridgeService::class.java)
    }
}
