import java.io.File

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

// Releases pass -PversionName=0.7.3 -PversionCode=703 (versionCode = major*10000 + minor*100 + patch).
val shelfVersionName = (findProperty("versionName") as String?) ?: "0.7.3"
val shelfVersionCode = ((findProperty("versionCode") as String?) ?: "703").toInt()

// -Ppreview builds "Shelf Preview" (app.shelf.preview), which installs beside the released app for trying changes.
val preview = providers.gradleProperty("preview").isPresent

// The same signing key as the app it will replace (so it can update it in place).
val keystore = File(System.getenv("SHELF_KEYSTORE") ?: "${System.getProperty("user.home")}/.local/share/android-build/debug.keystore")

android {
    namespace = "app.shelf"
    compileSdk = 37

    defaultConfig {
        applicationId = if (preview) "app.shelf.preview" else "app.shelf" // app.shelf replaces the WebView app (same key)
        resValue("string", "app_name", if (preview) "Shelf Preview" else "Shelf")
        minSdk = 26
        targetSdk = 36
        versionCode = shelfVersionCode
        versionName = shelfVersionName
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    signingConfigs {
        create("shelf") {
            storeFile = keystore
            storePassword = "android"
            keyAlias = "shelf"
            keyPassword = "android"
        }
    }

    buildTypes {
        // Without the key (a fork, say) builds are signed with Android's own debug key instead.
        val signing = if (keystore.exists()) signingConfigs.getByName("shelf") else signingConfigs.getByName("debug")
        debug { signingConfig = signing }
        release {
            isMinifyEnabled = false
            signingConfig = signing
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
        resValues = true // the app name: "Shelf", or "Shelf Preview" with -Ppreview
    }

    testOptions {
        unitTests.isIncludeAndroidResources = true // fonts and strings for Robolectric
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.material3)
    implementation(libs.compose.ui.tooling.preview)
    debugImplementation(libs.compose.ui.tooling)
    implementation(libs.coil.compose)
    implementation(libs.coil.network.okhttp)
    implementation(libs.okhttp)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.media3.exoplayer)
    implementation(libs.media3.session)
    implementation(libs.media3.datasource.okhttp)

    testImplementation(libs.junit)
    testImplementation(libs.compose.ui)
    testImplementation(platform(libs.compose.bom))
    testImplementation(libs.compose.ui.test.junit4)
    testImplementation(libs.androidx.test.ext)
    testImplementation(libs.robolectric)
    testImplementation(libs.okhttp.mockwebserver)
    testImplementation(libs.kotlinx.coroutines.test)

    androidTestImplementation(platform(libs.compose.bom))
    androidTestImplementation(libs.compose.ui.test.junit4)
    androidTestImplementation(libs.androidx.test.ext)
    androidTestImplementation(libs.androidx.test.runner)
    debugImplementation(libs.compose.ui.test.manifest)
}
