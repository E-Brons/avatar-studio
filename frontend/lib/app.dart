import 'package:flutter/material.dart';
import 'core/api/keepalive_service.dart';
import 'core/theme/app_theme.dart';
import 'features/avatar/screens/avatar_studio_screen.dart';

class AvatarStudioApp extends StatefulWidget {
  const AvatarStudioApp({super.key});

  @override
  State<AvatarStudioApp> createState() => _AvatarStudioAppState();
}

class _AvatarStudioAppState extends State<AvatarStudioApp> {
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
    return MaterialApp(
      title: 'Avatar Studio',
      theme: AppTheme.light,
      darkTheme: AppTheme.dark,
      home: const AvatarStudioScreen(),
      debugShowCheckedModeBanner: false,
    );
  }
}
