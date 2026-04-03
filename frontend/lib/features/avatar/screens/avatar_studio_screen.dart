import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/api/api_models.dart';
import '../../../core/api/avatar_api_client.dart';
import '../../../features/avatar/providers/generate_provider.dart';
import '../../../features/avatar/providers/selections_provider.dart';
import '../../../features/config/providers/config_provider.dart';
import '../../../widgets/attribute_panel/attribute_panel.dart';
import '../../../widgets/avatar_preview/avatar_preview_pane.dart';

class AvatarStudioScreen extends ConsumerWidget {
  const AvatarStudioScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final configAsync = ref.watch(configProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Avatar Studio'),
        actions: [
          // Randomize button
          IconButton(
            icon: const Text('🎲', style: TextStyle(fontSize: 20)),
            tooltip: 'Randomize all',
            onPressed: () => _randomizeAll(context, ref),
          ),
        ],
      ),
      body: Row(
        children: [
          // ── Left panel: attribute list ──────────────────────────────────
          SizedBox(
            width: 360,
            child: configAsync.when(
              data: (config) => _AttributePanelList(config: config),
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (err, _) => Center(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Text(
                    'Failed to load config:\n$err\n\nIs the server running?',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Theme.of(context).colorScheme.error),
                  ),
                ),
              ),
            ),
          ),

          const VerticalDivider(width: 1),

          // ── Right panel: avatar preview ──────────────────────────────────
          const Expanded(child: AvatarPreviewPane()),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => ref.read(generateProvider.notifier).generate(),
        icon: const Icon(Icons.auto_awesome),
        label: const Text('Generate Avatar'),
      ),
    );
  }

  Future<void> _randomizeAll(BuildContext context, WidgetRef ref) async {
    final client = ref.read(apiClientProvider);
    try {
      final resp = await client.randomize(
        RandomizeRequest(constraints: ref.read(selectionsProvider.notifier).toRequestSelections()),
      );
      ref.read(selectionsProvider.notifier).applyRandomizeResult(resp.values);
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Randomize failed: $e')),
        );
      }
    }
  }
}

class _AttributePanelList extends StatelessWidget {
  final ConfigResponse config;
  const _AttributePanelList({required this.config});

  @override
  Widget build(BuildContext context) {
    // Group attributes by category
    final grouped = <String, List<AttributeDef>>{};
    for (final attr in config.attributes) {
      grouped.putIfAbsent(attr.category, () => []).add(attr);
    }

    final categoryOrder = ['demographics', 'phenotype', 'appearance', 'advisor'];

    return ListView(
      children: [
        for (final category in categoryOrder)
          if (grouped.containsKey(category)) ...[
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
              child: Text(
                _categoryLabel(category),
                style: Theme.of(context).textTheme.labelLarge?.copyWith(
                      color: Theme.of(context).colorScheme.primary,
                      letterSpacing: 0.8,
                    ),
              ),
            ),
            for (final attr in grouped[category]!)
              AttributePanel(attribute: attr),
          ],
      ],
    );
  }

  String _categoryLabel(String cat) => switch (cat) {
        'demographics' => 'DEMOGRAPHICS',
        'phenotype' => 'PHENOTYPE',
        'appearance' => 'APPEARANCE',
        'advisor' => 'ADVISOR',
        _ => cat.toUpperCase(),
      };
}
