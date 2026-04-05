import 'dart:convert';
import 'dart:math';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/api/api_models.dart';
import '../../core/theme/app_theme.dart';
import '../../features/avatar/providers/generate_provider.dart';
import '../../features/avatar/providers/selections_provider.dart';
import '../../widgets/traits_pane/traits_pane.dart';
import 'generation_progress.dart';

class AvatarPreviewPane extends ConsumerWidget {
  const AvatarPreviewPane({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final generateAsync = ref.watch(generateProvider);
    final sels = ref.watch(selectionsProvider);
    final currentStyle = sels.selections['style']?.value?.toString();
    final isProgrammatic = isStyleProgrammatic(currentStyle);

    return generateAsync.when(
      data: (result) {
        if (result == null) return _IdleState(isProgrammatic: isProgrammatic);
        return _ResultView(result: result);
      },
      loading: () => GenerationProgress(isProgrammatic: isProgrammatic),
      error: (err, _) => _ErrorState(error: err),
    );
  }
}

// ── Idle placeholder ──────────────────────────────────────────────────────────

class _IdleState extends StatelessWidget {
  final bool isProgrammatic;
  const _IdleState({required this.isProgrammatic});

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final bgColor = isDark ? StudioColors.surfaceElevated : StudioLightColors.surfaceElevated;
    final borderColor = isDark ? StudioColors.surfaceBorder : StudioLightColors.surfaceBorder;

    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 320,
            height: 320,
            decoration: BoxDecoration(
              color: bgColor,
              borderRadius: BorderRadius.circular(18),
              border: Border.all(color: borderColor),
            ),
            child: const Center(
              child: Icon(Icons.face_retouching_natural,
                  size: 72, color: StudioColors.textDisabled),
            ),
          ),
          const SizedBox(height: 20),
          Text(
            'Change any setting to generate',
            style: TextStyle(
              fontSize: 13,
              color: isDark ? StudioColors.textSecondary : StudioLightColors.textSecondary,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            'Regenerates automatically on selection changes',
            style: TextStyle(
              fontSize: 11,
              color: isDark ? StudioColors.textDisabled : StudioLightColors.textDisabled,
            ),
          ),
        ],
      ),
    );
  }
}

// ── Success result ────────────────────────────────────────────────────────────

class _ResultView extends StatelessWidget {
  final GenerateResult result;
  const _ResultView({required this.result});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Expanded(
          child: LayoutBuilder(
            builder: (ctx, constraints) {
              final size = (min(constraints.maxWidth, constraints.maxHeight) - 48)
                  .clamp(200.0, 1024.0);
              return Center(
                child: Container(
                  width: size,
                  height: size,
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(18),
                    boxShadow: [
                      BoxShadow(
                        color: StudioColors.primary.withAlpha(50),
                        blurRadius: 32,
                        spreadRadius: 4,
                      ),
                    ],
                  ),
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(18),
                    child: Image.memory(base64Decode(result.imageB64), fit: BoxFit.cover),
                  ),
                ),
              );
            },
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 10, 20, 16),
          child: _PersonaCard(persona: result.avatarPersona),
        ),
      ],
    );
  }
}

// ── Persona card ──────────────────────────────────────────────────────────────

class _PersonaCard extends StatefulWidget {
  final Map<String, dynamic> persona;
  const _PersonaCard({required this.persona});

  @override
  State<_PersonaCard> createState() => _PersonaCardState();
}

class _PersonaCardState extends State<_PersonaCard> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final personal = widget.persona['personal'] as Map<String, dynamic>? ?? {};
    final advisor = widget.persona['advisor'] as Map<String, dynamic>? ?? {};
    final traits = (advisor['traits'] as List?)?.cast<String>() ?? [];

    final bgColor = isDark ? StudioColors.surfaceElevated : StudioLightColors.surfaceElevated;
    final borderColor = isDark ? StudioColors.surfaceBorder : StudioLightColors.surfaceBorder;

    return Container(
      constraints: const BoxConstraints(maxWidth: 360),
      decoration: BoxDecoration(
        color: bgColor,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: borderColor),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InkWell(
            onTap: () => setState(() => _expanded = !_expanded),
            borderRadius: BorderRadius.circular(12),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 14, 12, 14),
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(personal['name']?.toString() ?? 'Avatar',
                            style: Theme.of(context).textTheme.titleMedium),
                        const SizedBox(height: 3),
                        Text(
                          [personal['gender'], personal['age']?.toString(), advisor['role']]
                              .where((v) => v != null && v.toString().isNotEmpty)
                              .join(' · '),
                          style: TextStyle(
                            fontSize: 12,
                            color: isDark
                                ? StudioColors.textSecondary
                                : StudioLightColors.textSecondary,
                          ),
                        ),
                      ],
                    ),
                  ),
                  Icon(
                    _expanded
                        ? Icons.keyboard_arrow_up_rounded
                        : Icons.keyboard_arrow_down_rounded,
                    color: isDark ? StudioColors.textDisabled : StudioLightColors.textDisabled,
                    size: 18,
                  ),
                ],
              ),
            ),
          ),
          if (_expanded && traits.isNotEmpty) ...[
            Container(height: 1, color: borderColor),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('TRAITS', style: TextStyle(
                    fontSize: 9,
                    fontWeight: FontWeight.w700,
                    color: isDark ? StudioColors.textDisabled : StudioLightColors.textDisabled,
                    letterSpacing: 1.2,
                  )),
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 6,
                    runSpacing: 6,
                    children: traits
                        .map((t) => Container(
                              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                              decoration: BoxDecoration(
                                color: StudioColors.primary.withAlpha(30),
                                borderRadius: BorderRadius.circular(5),
                                border: Border.all(color: StudioColors.primary.withAlpha(70)),
                              ),
                              child: Text(t,
                                  style: const TextStyle(
                                      fontSize: 11, color: StudioColors.primaryLight)),
                            ))
                        .toList(),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}

// ── Error state ───────────────────────────────────────────────────────────────

class _ErrorState extends StatelessWidget {
  final Object error;
  const _ErrorState({required this.error});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(28),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: StudioColors.error.withAlpha(20),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: StudioColors.error.withAlpha(80)),
              ),
              child: const Icon(Icons.error_outline_rounded, size: 36, color: StudioColors.error),
            ),
            const SizedBox(height: 14),
            Text('Generation failed',
                style: Theme.of(context)
                    .textTheme
                    .titleSmall
                    ?.copyWith(color: StudioColors.textSecondary)),
            const SizedBox(height: 6),
            Text(error.toString(),
                style: const TextStyle(fontSize: 11, color: StudioColors.textDisabled),
                textAlign: TextAlign.center,
                maxLines: 4,
                overflow: TextOverflow.ellipsis),
          ],
        ),
      ),
    );
  }
}
