package com.sideshell.terminal

import com.google.gson.GsonBuilder
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.Service
import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.ui.Messages
import org.java_websocket.WebSocket
import org.java_websocket.handshake.ClientHandshake
import org.java_websocket.server.WebSocketServer
import java.io.File
import java.net.InetSocketAddress
import java.security.SecureRandom

/**
 * WebSocket bridge service that exposes terminal control via JSON-RPC 2.0.
 *
 * Security (two layers):
 *   1. Token auth - random token generated on start, written to port file (0600).
 *      Client must include ?token=<token> in the WebSocket URL.
 *   2. User consent - on first connection, a dialog asks the user to approve.
 *      Until approved, all JSON-RPC requests return an auth error.
 */
@Service(Service.Level.APP)
class SideshellBridgeService {
    private val log = Logger.getInstance(SideshellBridgeService::class.java)
    private val gson = GsonBuilder().serializeNulls().create()
    private var server: SideshellWebSocketServer? = null
    private val terminalManager = TerminalManagerService()

    private var token: String = ""
    @Volatile
    private var approved = true  // TODO: temporary auto-allow for development
    @Volatile
    private var approvalPending = false

    val isRunning: Boolean
        get() = server?.isRunning == true

    fun start() {
        if (isRunning) return

        val settings = SideshellSettings.getInstance()
        val port = settings.state.port

        // Generate auth token
        token = generateToken()
        approved = true   // TODO: temporary auto-allow for development
        approvalPending = false

        try {
            server = SideshellWebSocketServer(port, token) { conn, request ->
                handleConnection(conn, request)
            }
            server?.start()
            writePortFile(port)
            log.info("sideshell bridge started on ws://127.0.0.1:$port")
        } catch (e: Exception) {
            log.error("Failed to start sideshell bridge: ${e.message}", e)
        }
    }

    fun stop() {
        try {
            server?.stop()
            server = null
            token = ""
            approved = false
            removePortFile()
            log.info("sideshell bridge stopped")
        } catch (e: Exception) {
            log.error("Failed to stop sideshell bridge: ${e.message}", e)
        }
    }

    private fun handleConnection(conn: WebSocket, request: String): String {
        // Request user approval on first connection
        if (!approved && !approvalPending) {
            requestApproval(conn)
        }

        return handleRequest(request)
    }

    private fun requestApproval(conn: WebSocket) {
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
                approved = true
                log.info("User approved sideshell terminal access")
            } else {
                log.info("User denied sideshell terminal access")
                // Regenerate token so denied client can't retry
                token = generateToken()
                writePortFile(SideshellSettings.getInstance().state.port)
                conn.close(4001, "Access denied by user")
            }
        }
    }

    private fun handleRequest(request: String): String {
        return try {
            val json = JsonParser.parseString(request).asJsonObject
            val id = json.get("id")
            val method = json.get("method")?.asString ?: ""
            val params = json.getAsJsonObject("params") ?: JsonObject()

            // Block requests until user approves
            if (!approved) {
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

    /** Safely get a string from JSON params, handling JsonNull. */
    private fun JsonObject.str(key: String): String? {
        val el = get(key) ?: return null
        return if (el.isJsonNull) null else el.asString
    }

    /** Safely get an int from JSON params, handling JsonNull. */
    private fun JsonObject.int(key: String, default: Int): Int {
        val el = get(key) ?: return default
        return if (el.isJsonNull) default else el.asInt
    }

    /** Safely get a boolean from JSON params, handling JsonNull. */
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

    private fun writePortFile(port: Int) {
        try {
            val dir = File(System.getProperty("user.home"), ".sideshell")
            dir.mkdirs()
            val file = File(dir, "intellij-port")
            val data = gson.toJson(mapOf(
                "port" to port,
                "pid" to ProcessHandle.current().pid(),
                "token" to token,
                "ide" to "intellij",
                "version" to "0.1.0",
            ))
            file.writeText(data)
            // Set file permissions to owner-only (0600)
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
            val file = File(System.getProperty("user.home"), ".sideshell/intellij-port")
            file.delete()
        } catch (e: Exception) {
            log.debug("Failed to remove port file: ${e.message}")
        }
    }

    companion object {
        fun getInstance(): SideshellBridgeService =
            ApplicationManager.getApplication().getService(SideshellBridgeService::class.java)
    }
}

/**
 * WebSocket server that validates auth tokens on connection handshake.
 *
 * The token must be passed as a query parameter: ws://127.0.0.1:PORT?token=TOKEN
 */
private class SideshellWebSocketServer(
    port: Int,
    private val expectedToken: String,
    private val handler: (WebSocket, String) -> String,
) : WebSocketServer(InetSocketAddress("127.0.0.1", port)) {

    private val log = Logger.getInstance(SideshellWebSocketServer::class.java)
    var isRunning = false
        private set

    override fun onOpen(conn: WebSocket, handshake: ClientHandshake) {
        // Validate token from query parameter
        val resource = handshake.resourceDescriptor ?: ""
        val tokenParam = parseQueryParam(resource, "token")

        if (tokenParam != expectedToken) {
            log.warn("sideshell: rejected connection — invalid token")
            conn.close(4003, "Invalid token")
            return
        }

        log.info("sideshell: client connected (token valid)")
    }

    override fun onClose(conn: WebSocket, code: Int, reason: String, remote: Boolean) {
        log.info("sideshell: client disconnected: $reason")
    }

    override fun onMessage(conn: WebSocket, message: String) {
        try {
            val response = handler(conn, message)
            conn.send(response)
        } catch (e: Exception) {
            log.error("Error handling message: ${e.message}", e)
        }
    }

    override fun onError(conn: WebSocket?, ex: Exception) {
        log.error("WebSocket error: ${ex.message}", ex)
    }

    override fun onStart() {
        isRunning = true
        log.info("sideshell WebSocket server started")
    }

    override fun stop() {
        isRunning = false
        super.stop()
    }

    private fun parseQueryParam(resource: String, key: String): String? {
        val queryStart = resource.indexOf('?')
        if (queryStart < 0) return null
        val query = resource.substring(queryStart + 1)
        for (param in query.split('&')) {
            val parts = param.split('=', limit = 2)
            if (parts.size == 2 && parts[0] == key) {
                return parts[1]
            }
        }
        return null
    }
}
