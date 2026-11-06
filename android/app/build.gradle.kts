import java.util.Properties

plugins {
    id("com.android.application")
}

val appUrl = providers.gradleProperty("APP_URL")
    .orElse("https://drawtogetherxixi-ggm028ng.b4a.run")
    .get()

val keystoreProperties = Properties()
val keystorePropertiesFile = rootProject.file("keystore.properties")
if (keystorePropertiesFile.exists()) {
    keystorePropertiesFile.inputStream().use(keystoreProperties::load)
}

android {
    namespace = "com.xixizd.drawtogether"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.xixizd.drawtogether"
        minSdk = 24
        targetSdk = 36
        versionCode = 1
        versionName = "1.0.0"

        buildConfigField("String", "APP_URL", "\"$appUrl\"")
        manifestPlaceholders["usesCleartextTraffic"] = "false"
    }

    signingConfigs {
        if (keystorePropertiesFile.exists()) {
            create("release") {
                storeFile = rootProject.file(keystoreProperties.getProperty("storeFile"))
                storePassword = keystoreProperties.getProperty("storePassword")
                keyAlias = keystoreProperties.getProperty("keyAlias")
                keyPassword = keystoreProperties.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        debug {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
        }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            if (keystorePropertiesFile.exists()) {
                signingConfig = signingConfigs.getByName("release")
            }
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
