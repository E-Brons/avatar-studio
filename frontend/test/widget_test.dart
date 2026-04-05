import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:avatar_studio_app/core/api/api_models.dart';
import 'package:avatar_studio_app/core/api/avatar_api_client.dart';
import 'package:avatar_studio_app/features/avatar/screens/avatar_studio_screen.dart';
import 'package:avatar_studio_app/features/config/providers/config_provider.dart';
import 'package:avatar_studio_app/core/theme/app_theme.dart';

/// Fake client — returns an empty config immediately, no Dio/network/timers.
class _FakeApiClient extends AvatarApiClient {
  _FakeApiClient() : super(baseUrl: 'http://localhost');

  @override
  Future<ConfigResponse> getConfig() async =>
      const ConfigResponse(attributes: []);
}

void main() {
  testWidgets('app renders without crashing', (WidgetTester tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          apiClientProvider.overrideWithValue(_FakeApiClient()),
        ],
        child: MaterialApp(
          title: 'Avatar Studio',
          theme: AppTheme.light,
          darkTheme: AppTheme.dark,
          home: const AvatarStudioScreen(),
          debugShowCheckedModeBanner: false,
        ),
      ),
    );

    expect(find.byType(MaterialApp), findsOneWidget);
  });
}
