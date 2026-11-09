import java.io.File

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

// Releases pass -PversionName=0.7.0 -PversionCode=700 (versionCode = major*10000 + minor*100 + patch).
val shelfVersionName = (findProperty("versionName") as String?) ?: "0.7.0"
val shelfVersionCode = ((findProperty("versionCode") as String?) ?: "700").toInt()

// The same signing key as the app it will replace (so it can update it in place).
val keystore = File(System.getenv("SHELF_KEYSTORE") ?: "${System.getProperty("user.home")}/.local/share/android-build/debug.keystore")

android {
    namespace = "app.shelf"
    compileSdk = 37

    defaultConfig {
        applicationId = "app.shelf.preview" // beside the WebView app until the switch-over (then "app.shelf")
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
