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

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }

    testOptions {
        unitTests.all {
            it.workingDir = rootProject.projectDir
            it.dependsOn("processDebugMainManifest")
        }
    }
}

dependencies {
    implementation(files("libs/jl_bt_ota_V1.11.0_11015-release.aar"))
    testImplementation("junit:junit:4.13.2")
}

tasks.withType<JavaCompile>().configureEach {
    options.compilerArgs.add("-Xlint:-options")
}
