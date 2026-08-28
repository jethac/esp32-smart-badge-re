plugins {
    id("com.android.application")
}

android {
    namespace = "net.jethachan.factory_badges"
    compileSdk = 34

    defaultConfig {
        applicationId = "net.jethachan.factory_badges"
        minSdk = 31
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        create("labQualified") {
            initWith(getByName("debug"))
            isDebuggable = true
            signingConfig = signingConfigs.getByName("debug")
            matchingFallbacks += listOf("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }

    testOptions {
        unitTests.all {
            it.workingDir = rootProject.projectDir
            it.dependsOn("processDebugManifest")
        }
    }
}

val e87FirmwareRelease = providers.gradleProperty("e87FirmwareRelease")
val e87Python = providers.gradleProperty("e87Python")
    .orElse(providers.environmentVariable("E87_PYTHON"))
    .orElse("/usr/bin/python3.11")
val e87GeneratedRoot = layout.buildDirectory.dir("generated/e87Firmware/labQualified")
val e87PrepareScript = rootProject.layout.projectDirectory.file("scripts/prepare-e87-firmware.py")
val e87EmbedModule = rootProject.layout.projectDirectory.file("scripts/e87_embed.py")
val e87EmbedSchema = rootProject.layout.projectDirectory.file("scripts/e87-android-embed-v1.schema.json")

android.sourceSets.getByName("labQualified").assets.srcDir(
    e87GeneratedRoot.map { it.dir("assets") }
)

val embedE87Firmware = tasks.register<Exec>("embedE87Firmware") {
    group = "build"
    description = "Validate and embed one explicitly lab-qualified E87 firmware handoff"

    inputs.files(e87PrepareScript, e87EmbedModule, e87EmbedSchema)
        .withPathSensitivity(PathSensitivity.RELATIVE)
    inputs.property("e87FirmwareRelease", e87FirmwareRelease.orElse("<absent>"))
    if (e87FirmwareRelease.isPresent) {
        inputs.dir(file(e87FirmwareRelease.get()))
            .withPathSensitivity(PathSensitivity.RELATIVE)
    }
    outputs.dir(e87GeneratedRoot)

    doFirst {
        val supplied = e87FirmwareRelease.orNull
            ?: throw GradleException(
                "labQualified firmware builds require " +
                    "-Pe87FirmwareRelease=<absolute validated handoff directory>"
            )
        val release = file(supplied)
        if (!release.isAbsolute) {
            throw GradleException("e87FirmwareRelease must be an absolute path")
        }
        commandLine(
            e87Python.get(),
            e87PrepareScript.asFile.absolutePath,
            "--release", release.absolutePath,
            "--output", e87GeneratedRoot.get().asFile.absolutePath,
        )
    }
}

tasks.configureEach {
    // Every task in the qualified variant must fail closed before it can inspect
    // or package its generated asset source set. This also covers AGP's internal
    // lint-model tasks, whose names are not part of the public variant API.
    if (name.contains("LabQualified")) {
        dependsOn(embedE87Firmware)
    }
    if (name == "embedE87Firmware") {
        mustRunAfter("clean")
    }
}

dependencies {
    testImplementation("junit:junit:4.13.2")
}

tasks.withType<JavaCompile>().configureEach {
    options.compilerArgs.add("-Xlint:-options")
}
