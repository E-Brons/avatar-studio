import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/api/api_models.dart';
import '../../../features/config/providers/config_provider.dart';
import 'selections_provider.dart';

class GenerateNotifier extends AsyncNotifier<GenerateResult?> {
  @override
  Future<GenerateResult?> build() async => null;

  Future<void> generate() async {
    final client = ref.read(apiClientProvider);
    final selectionsNotifier = ref.read(selectionsProvider.notifier);

    state = const AsyncLoading();
    state = await AsyncValue.guard(() => client.generate(
          GenerateRequest(
            selections: selectionsNotifier.toRequestSelections(),
            expressions: const ['neutral'],
            width: 256,
            height: 256,
          ),
        ));
  }
}

final generateProvider = AsyncNotifierProvider<GenerateNotifier, GenerateResult?>(
  GenerateNotifier.new,
);
