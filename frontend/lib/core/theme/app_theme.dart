import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

/// ── Dark palette ──────────────────────────────────────────────────────────────
class StudioColors {
  static const background = Color(0xFF0E0E16);
  static const surface = Color(0xFF151520);
  static const surfaceElevated = Color(0xFF1C1C2E);
  static const surfaceBorder = Color(0xFF2A2A3E);
  static const surfaceBorderSubtle = Color(0xFF222232);
  static const primary = Color(0xFF7C3AED);
  static const primaryLight = Color(0xFFA855F7);
  static const primaryGlow = Color(0x337C3AED);
  static const secondary = Color(0xFF22D3EE);
  static const amber = Color(0xFFF59E0B);
  static const error = Color(0xFFEF4444);
  static const success = Color(0xFF10B981);
  static const textPrimary = Color(0xFFF1F5F9);
  static const textSecondary = Color(0xFF94A3B8);
  static const textDisabled = Color(0xFF4B5563);
}

/// ── Light palette ─────────────────────────────────────────────────────────────
class StudioLightColors {
  static const background = Color(0xFFF8F9FB);
  static const surface = Color(0xFFFFFFFF);
  static const surfaceElevated = Color(0xFFF1F4F9);
  static const surfaceBorder = Color(0xFFE2E8F0);
  static const surfaceBorderSubtle = Color(0xFFEFF2F7);
  static const primary = Color(0xFF6D28D9);
  static const primaryLight = Color(0xFF7C3AED);
  static const secondary = Color(0xFF0891B2);
  static const error = Color(0xFFDC2626);
  static const success = Color(0xFF059669);
  static const textPrimary = Color(0xFF0F172A);
  static const textSecondary = Color(0xFF475569);
  static const textDisabled = Color(0xFF94A3B8);
}

class AppTheme {
  static ThemeData get dark => _build(
        brightness: Brightness.dark,
        bg: StudioColors.background,
        surface: StudioColors.surface,
        surfaceEl: StudioColors.surfaceElevated,
        border: StudioColors.surfaceBorder,
        primary: StudioColors.primary,
        onPrimary: Colors.white,
        secondary: StudioColors.secondary,
        error: StudioColors.error,
        textPrimary: StudioColors.textPrimary,
        textSecondary: StudioColors.textSecondary,
        textDisabled: StudioColors.textDisabled,
        primaryContainer: const Color(0xFF2D1B69),
        onPrimaryContainer: const Color(0xFFD8B4FE),
        cardColor: StudioColors.surfaceElevated,
        inputFill: StudioColors.surface,
      );

  static ThemeData get light => _build(
        brightness: Brightness.light,
        bg: StudioLightColors.background,
        surface: StudioLightColors.surface,
        surfaceEl: StudioLightColors.surfaceElevated,
        border: StudioLightColors.surfaceBorder,
        primary: StudioLightColors.primary,
        onPrimary: Colors.white,
        secondary: StudioLightColors.secondary,
        error: StudioLightColors.error,
        textPrimary: StudioLightColors.textPrimary,
        textSecondary: StudioLightColors.textSecondary,
        textDisabled: StudioLightColors.textDisabled,
        primaryContainer: const Color(0xFFEDE9FE),
        onPrimaryContainer: const Color(0xFF4C1D95),
        cardColor: StudioLightColors.surfaceElevated,
        inputFill: StudioLightColors.surface,
      );

  static ThemeData _build({
    required Brightness brightness,
    required Color bg,
    required Color surface,
    required Color surfaceEl,
    required Color border,
    required Color primary,
    required Color onPrimary,
    required Color secondary,
    required Color error,
    required Color textPrimary,
    required Color textSecondary,
    required Color textDisabled,
    required Color primaryContainer,
    required Color onPrimaryContainer,
    required Color cardColor,
    required Color inputFill,
  }) =>
      ThemeData(
        brightness: brightness,
        colorScheme: ColorScheme(
          brightness: brightness,
          primary: primary,
          onPrimary: onPrimary,
          secondary: secondary,
          onSecondary: brightness == Brightness.dark ? Colors.black : Colors.white,
          surface: surface,
          onSurface: textPrimary,
          error: error,
          onError: Colors.white,
          outline: border,
          outlineVariant: border.withAlpha(100),
          surfaceContainerHighest: surfaceEl,
          onSurfaceVariant: textSecondary,
          primaryContainer: primaryContainer,
          onPrimaryContainer: onPrimaryContainer,
        ),
        scaffoldBackgroundColor: bg,
        useMaterial3: true,
        textTheme: _textTheme(textPrimary, textSecondary),
        appBarTheme: AppBarTheme(
          backgroundColor: bg,
          foregroundColor: textPrimary,
          elevation: 0,
          scrolledUnderElevation: 0,
          centerTitle: false,
          titleTextStyle: GoogleFonts.syne(
            fontSize: 17,
            fontWeight: FontWeight.w700,
            color: textPrimary,
            letterSpacing: 0.3,
          ),
        ),
        cardTheme: CardThemeData(
          color: cardColor,
          elevation: brightness == Brightness.light ? 0.5 : 0,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(10),
            side: BorderSide(color: border, width: 1),
          ),
          margin: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        ),
        segmentedButtonTheme: SegmentedButtonThemeData(
          style: ButtonStyle(
            backgroundColor: WidgetStateProperty.resolveWith((states) {
              if (states.contains(WidgetState.selected)) {
                return primary.withAlpha(brightness == Brightness.dark ? 55 : 30);
              }
              return surface;
            }),
            foregroundColor: WidgetStateProperty.resolveWith((states) {
              if (states.contains(WidgetState.selected)) return primary;
              return textSecondary;
            }),
            side: WidgetStateProperty.all(BorderSide(color: border)),
            padding: WidgetStateProperty.all(
                const EdgeInsets.symmetric(horizontal: 6, vertical: 2)),
          ),
        ),
        dividerTheme: DividerThemeData(color: border, thickness: 1),
        iconTheme: IconThemeData(color: textSecondary),
        sliderTheme: SliderThemeData(
          activeTrackColor: primary,
          inactiveTrackColor: border,
          thumbColor: primary,
          overlayColor: primary.withAlpha(40),
          trackHeight: 3,
        ),
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: inputFill,
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(8),
            borderSide: BorderSide(color: border),
          ),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(8),
            borderSide: BorderSide(color: border),
          ),
          focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(8),
            borderSide: BorderSide(color: primary),
          ),
          contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          hintStyle: TextStyle(color: textDisabled, fontSize: 13),
        ),
        snackBarTheme: SnackBarThemeData(
          backgroundColor: surfaceEl,
          contentTextStyle: GoogleFonts.dmSans(color: textPrimary, fontSize: 13),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(8),
            side: BorderSide(color: border),
          ),
          behavior: SnackBarBehavior.floating,
        ),
      );

  static TextTheme _textTheme(Color primary, Color secondary) => TextTheme(
        displayLarge: GoogleFonts.syne(
            fontSize: 32, fontWeight: FontWeight.w700, color: primary),
        displayMedium: GoogleFonts.syne(
            fontSize: 24, fontWeight: FontWeight.w600, color: primary),
        titleLarge: GoogleFonts.syne(
            fontSize: 18, fontWeight: FontWeight.w600, color: primary),
        titleMedium: GoogleFonts.syne(
            fontSize: 15, fontWeight: FontWeight.w600, color: primary),
        titleSmall: GoogleFonts.syne(
            fontSize: 13, fontWeight: FontWeight.w600, color: primary),
        bodyLarge: GoogleFonts.dmSans(
            fontSize: 15, fontWeight: FontWeight.w400, color: primary),
        bodyMedium: GoogleFonts.dmSans(
            fontSize: 13, fontWeight: FontWeight.w400, color: primary),
        bodySmall: GoogleFonts.dmSans(
            fontSize: 11, fontWeight: FontWeight.w400, color: secondary),
        labelLarge: GoogleFonts.dmSans(
            fontSize: 12,
            fontWeight: FontWeight.w600,
            color: primary,
            letterSpacing: 0.4),
        labelMedium: GoogleFonts.dmSans(
            fontSize: 11, fontWeight: FontWeight.w500, color: secondary),
        labelSmall: GoogleFonts.dmSans(
            fontSize: 10,
            fontWeight: FontWeight.w500,
            color: secondary,
            letterSpacing: 0.5),
      );
}
