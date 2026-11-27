# Android setup
1. Install Flutter (stable channel) and Android Studio with Android SDK.
2. Generate the Android platform folder with `flutter create --platforms=android --org com.batates.editor .`.
3. Run `flutter pub get`.
4. Connect an Android device with USB debugging enabled and run `flutter run`.
5. Build a release APK with `flutter build apk --release`.

The current highlight radar ranks audio intensity only; it is not semantic AI and does not analyze live streams. Review FFmpeg fork licensing and Android package compatibility before public distribution.
