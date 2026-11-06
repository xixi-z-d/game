# Keep JavaScript bridge behavior predictable for WebView.
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}
