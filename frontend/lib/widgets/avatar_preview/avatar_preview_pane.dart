import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../features/avatar/providers/generate_provider.dart';
import 'generation_progress.dart';

class AvatarPreviewPane extends ConsumerWidget {
  const AvatarPreviewPane({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final generateAsync = ref.watch(generateProvider);

    return generateAsync.when(
      data: (result) {
        if (result == null) {
          return Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  Icons.person_outline,
                  size: 96,
                  color: Theme.of(context).colorScheme.outlineVariant,
                ),
                const SizedBox(height: 12),
                Text(
                  'Press Generate to create an avatar',
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: Theme.of(context).colorScheme.outline,
                      ),
                ),
              ],
            ),
          );
        }

        return SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Column(
            children: [
              Container(
                constraints: const BoxConstraints(maxWidth: 400, maxHeight: 400),
                child: Image.memory(
                  base64Decode(result.imageB64),
                  fit: BoxFit.contain,
                ),
              ),
              const SizedBox(height: 16),
              _PersonaSummary(persona: result.avatarPersona),
            ],
          ),
        );
      },
      loading: () => const GenerationProgress(),
      error: (err, _) => Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(
            'Generation failed:\n$err',
            style: TextStyle(color: Theme.of(context).colorScheme.error),
            textAlign: TextAlign.center,
          ),
        ),
      ),
    );
  }
}

class _PersonaSummary extends StatefulWidget {
  final Map<String, dynamic> persona;
  const _PersonaSummary({required this.persona});

  @override
  State<_PersonaSummary> createState() => _PersonaSummaryState();
}

class _PersonaSummaryState extends State<_PersonaSummary> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final personal = widget.persona['personal'] as Map<String, dynamic>? ?? {};
    final advisor = widget.persona['advisor'] as Map<String, dynamic>? ?? {};

    return Card(
      child: Column(
        children: [
          ListTile(
            title: Text(
              personal['name']?.toString() ?? 'Avatar',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            subtitle: Text(
              '${personal['gender'] ?? ''} · ${personal['age'] ?? ''} · ${advisor['role'] ?? ''}',
            ),
            trailing: IconButton(
              icon: Icon(_expanded ? Icons.expand_less : Icons.expand_more),
              onPressed: () => setState(() => _expanded = !_expanded),
            ),
          ),
          if (_expanded)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if ((advisor['traits'] as List?)?.isNotEmpty ?? false) ...[
                    Text('Traits', style: Theme.of(context).textTheme.labelMedium),
                    Text((advisor['traits'] as List).join(', ')),
                  ],
                ],
              ),
            ),
        ],
      ),
    );
  }
}
