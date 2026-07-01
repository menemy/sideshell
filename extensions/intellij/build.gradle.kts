plugins {
    id("java")
    id("org.jetbrains.kotlin.jvm") version "2.1.0"
    id("org.jetbrains.intellij.platform") version "2.11.0"
}

group = "com.sideshell"
version = "1.0.0"

repositories {
    mavenCentral()
    intellijPlatform {
        defaultRepositories()
    }
}

dependencies {
    intellijPlatform {
        intellijIdeaUltimate("2025.3.2")
        bundledPlugin("org.jetbrains.plugins.terminal")
    }

    implementation("com.google.code.gson:gson:2.11.0")
}

intellijPlatform {
    pluginConfiguration {
        id = "com.sideshell.terminal"
        name = "sideshell Terminal Control"
        version = project.version.toString()
        description = """
            Exposes JetBrains IDE terminal control for AI agents via sideshell MCP server.

            Provides a Unix socket bridge that lets sideshell (or any MCP client) control
            IDE terminals: read output, execute commands, create tabs/splits, and more.

            Works with: IntelliJ IDEA, PyCharm, WebStorm, GoLand, RustRover, PhpStorm,
            Android Studio, and all other JetBrains IDEs.
        """.trimIndent()
        vendor {
            name = "sideshell"
            url = "https://github.com/menemy/sideshell"
        }
        ideaVersion {
            sinceBuild = "253"
            untilBuild = "261.*"
        }
    }
}

kotlin {
    jvmToolchain(21)
}

tasks {
    buildSearchableOptions {
        enabled = false
    }
}
