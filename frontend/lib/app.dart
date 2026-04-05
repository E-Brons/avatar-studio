import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'core/api/keepalive_service.dart';
import 'core/theme/app_theme.dart';
import 'core/theme/theme_provider.dart';
import 'features/avatar/screens/avatar_studio_screen.dart';

class AvatarStudioApp extends ConsumerStatefulWidget {
  const AvatarStudioApp({super.key});

  @override
  ConsumerState<AvatarStudioApp> createState() => _AvatarStudioAppState();
}

class _AvatarStudioAppState extends ConsumerState<AvatarStudioApp> {
  final _keepalive = KeepaliveService();

  @override
  void initState() {
    super.initState();
    _keepalive.start();
  }

  @override
  void dispose() {
    _keepalive.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final themeMode = ref.watch(themeModeProvider);
    return MaterialApp(
      title: 'Avatar Studio',
      theme: AppTheme.light,
      darkTheme: AppTheme.dark,
      themeMode: themeMode,
      home: const AvatarStudioScreen(),
      debugShowCheckedModeBanner: false,
    );
  }
}
