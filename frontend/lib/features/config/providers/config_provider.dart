import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/api/avatar_api_client.dart';
import '../../../core/api/api_models.dart';

/// Singleton API client provider.
final apiClientProvider = Provider<AvatarApiClient>((_) => AvatarApiClient());

/// Fetches /api/config on app start — all panels render from this.
final configProvider = FutureProvider<ConfigResponse>((ref) async {
  final client = ref.watch(apiClientProvider);
  return client.getConfig();
});
