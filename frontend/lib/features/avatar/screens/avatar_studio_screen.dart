import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/api/api_models.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/theme/theme_provider.dart';
import '../../../features/avatar/providers/generate_provider.dart';
import '../../../features/avatar/providers/selections_provider.dart';
import '../../../features/config/providers/config_provider.dart';
import '../../../widgets/attribute_panel/attribute_panel.dart';
import '../../../widgets/avatar_preview/avatar_preview_pane.dart';
import '../../../widgets/traits_pane/traits_pane.dart';

const _kLeftMinWidth = 200.0;
const _kLeftMaxWidth = 560.0;
const _kLeftDefaultWidth = 368.0;

class AvatarStudioScreen extends ConsumerStatefulWidget {
  const AvatarStudioScreen({super.key});

  @override
  ConsumerState<AvatarStudioScreen> createState() => _AvatarStudioScreenState();
}

class _AvatarStudioScreenState extends ConsumerState<AvatarStudioScreen> {
  Timer? _debounceTimer;
  double _leftWidth = _kLeftDefaultWidth;
  bool _traitsCollapsed = false;

  @override
  void dispose() {
    _debounceTimer?.cancel();
    super.dispose();
  }

  void _scheduleGenerate() {
    _debounceTimer?.cancel();
    _debounceTimer = Timer(const Duration(milliseconds: 300), () {
      if (mounted) ref.read(generateProvider.notifier).generate();
    });
  }

  @override
  Widget build(BuildContext context) {
    final configAsync = ref.watch(configProvider);
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final borderColor = isDark ? StudioColors.surfaceBorder : StudioLightColors.surfaceBorder;
    final bgColor = isDark ? StudioColors.background : StudioLightColors.background;

    ref.listen<SelectionsState>(selectionsProvider, (_, _) => _scheduleGenerate());

    return Scaffold(
      backgroundColor: bgColor,
      appBar: AppBar(
        backgroundColor: bgColor,
        title: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 28,
              height: 28,
              decoration: BoxDecoration(
                gradient: const LinearGradient(
                  colors: [StudioColors.primary, StudioColors.secondary],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                ),
                borderRadius: BorderRadius.circular(7),
              ),
              child: const Icon(Icons.face_retouching_natural, size: 15, color: Colors.white),
            ),
            const SizedBox(width: 10),
            const Flexible(child: Text('Avatar Studio', overflow: TextOverflow.ellipsis)),
          ],
        ),
        actions: [
          // Traits pane toggle
          _AppBarButton(
            iconData: _traitsCollapsed ? Icons.view_sidebar_outlined : Icons.view_sidebar,
            label: 'Traits',
            onPressed: () => setState(() => _traitsCollapsed = !_traitsCollapsed),
            active: !_traitsCollapsed,
          ),
          const SizedBox(width: 6),
          _AppBarButton(
            icon: '🎲',
            label: 'Randomize',
            onPressed: () => _randomizeAll(context),
          ),
          const SizedBox(width: 6),
          _AppBarButton(
            iconData: Icons.refresh_rounded,
            label: 'Regenerate',
            onPressed: () => ref.read(generateProvider.notifier).generate(),
          ),
          const SizedBox(width: 6),
          // Theme toggle
          _ThemeToggleButton(),
          const SizedBox(width: 12),
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(1),
          child: Container(height: 1, color: borderColor),
        ),
      ),
      body: Row(
        children: [
          // ── Left: resizable attribute list ────────────────────────────────
          SizedBox(
            width: _leftWidth,
            child: Container(
              decoration: BoxDecoration(
                color: isDark ? StudioColors.surface : StudioLightColors.surface,
                border: Border(right: BorderSide(color: borderColor)),
              ),
              child: configAsync.when(
                data: (config) => _AttributePanelList(config: config),
                loading: () => const Center(
                  child: CircularProgressIndicator(color: StudioColors.primary, strokeWidth: 2),
                ),
                error: (err, _) => _ServerErrorState(error: err),
              ),
            ),
          ),

          // ── Drag handle ────────────────────────────────────────────────────
          _DragHandle(
            onDrag: (dx) => setState(() {
              _leftWidth = (_leftWidth + dx).clamp(_kLeftMinWidth, _kLeftMaxWidth);
            }),
            isDark: isDark,
          ),

          // ── Middle: optional traits pane ──────────────────────────────────
          if (!_traitsCollapsed)
            TraitsPane(collapsed: _traitsCollapsed),

          // ── Right: avatar preview ──────────────────────────────────────────
          const Expanded(child: AvatarPreviewPane()),
        ],
      ),
    );
  }

  Future<void> _randomizeAll(BuildContext context) async {
    final client = ref.read(apiClientProvider);
    try {
      final resp = await client.randomize(
        RandomizeRequest(
          constraints: ref.read(selectionsProvider.notifier).toRequestSelections(),
        ),
      );
      ref.read(selectionsProvider.notifier).applyRandomizeResult(resp.values);
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Randomize failed: $e'), backgroundColor: StudioColors.error),
        );
      }
    }
  }
}

// ── Drag handle ────────────────────────────────────────────────────────────────

class _DragHandle extends StatefulWidget {
  final ValueChanged<double> onDrag;
  final bool isDark;
  const _DragHandle({required this.onDrag, required this.isDark});

  @override
  State<_DragHandle> createState() => _DragHandleState();
}

class _DragHandleState extends State<_DragHandle> {
  bool _hovering = false;

  @override
  Widget build(BuildContext context) {
    final handleColor = _hovering
        ? StudioColors.primary
        : (widget.isDark ? StudioColors.surfaceBorder : StudioLightColors.surfaceBorder);

    return MouseRegion(
      cursor: SystemMouseCursors.resizeLeftRight,
      onEnter: (_) => setState(() => _hovering = true),
      onExit: (_) => setState(() => _hovering = false),
      child: GestureDetector(
        onHorizontalDragUpdate: (d) => widget.onDrag(d.delta.dx),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 150),
          width: 6,
          color: Colors.transparent,
          child: Center(
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 150),
              width: _hovering ? 3 : 1,
              color: handleColor,
            ),
          ),
        ),
      ),
    );
  }
}

// ── App-bar buttons ────────────────────────────────────────────────────────────

class _AppBarButton extends StatelessWidget {
  final String? icon;
  final IconData? iconData;
  final String label;
  final VoidCallback onPressed;
  final bool active;

  const _AppBarButton({
    this.icon,
    this.iconData,
    required this.label,
    required this.onPressed,
    this.active = false,
  });

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final borderColor = isDark ? StudioColors.surfaceBorder : StudioLightColors.surfaceBorder;
    final fgColor = active
        ? StudioColors.primaryLight
        : (isDark ? StudioColors.textSecondary : StudioLightColors.textSecondary);

    return OutlinedButton(
      onPressed: onPressed,
      style: OutlinedButton.styleFrom(
        foregroundColor: fgColor,
        backgroundColor:
            active ? StudioColors.primary.withAlpha(25) : Colors.transparent,
        side: BorderSide(
            color: active ? StudioColors.primary.withAlpha(100) : borderColor),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        minimumSize: Size.zero,
        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(7)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Text(icon!, style: const TextStyle(fontSize: 13)),
            const SizedBox(width: 5),
          ] else if (iconData != null) ...[
            Icon(iconData, size: 13),
            const SizedBox(width: 5),
          ],
          Text(label, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w500)),
        ],
      ),
    );
  }
}

class _ThemeToggleButton extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final mode = ref.watch(themeModeProvider);
    final isDark = mode == ThemeMode.dark;
    return _AppBarButton(
      iconData: isDark ? Icons.light_mode_rounded : Icons.dark_mode_rounded,
      label: isDark ? 'Light' : 'Dark',
      onPressed: () =>
          ref.read(themeModeProvider.notifier).set(isDark ? ThemeMode.light : ThemeMode.dark),
    );
  }
}

// ── Attribute list ────────────────────────────────────────────────────────────

class _AttributePanelList extends StatelessWidget {
  final ConfigResponse config;
  const _AttributePanelList({required this.config});

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final grouped = <String, List<AttributeDef>>{};
    for (final attr in config.attributes) {
      grouped.putIfAbsent(attr.category, () => []).add(attr);
    }
    const order = ['style', 'demographics', 'personal', 'phenotype', 'appearance', 'personality'];
    return ListView(
      padding: const EdgeInsets.only(bottom: 32),
      children: [
        for (final cat in order)
          if (grouped.containsKey(cat)) ...[
            _CategoryHeader(label: _label(cat), isDark: isDark),
            for (final attr in grouped[cat]!) AttributePanel(attribute: attr),
          ],
      ],
    );
  }

  static String _label(String cat) => switch (cat) {
        'style' => 'STYLE',
        'demographics' => 'DEMOGRAPHICS',
        'personal' => 'PERSONAL',
        'phenotype' => 'PHENOTYPE',
        'appearance' => 'APPEARANCE',
        'personality' => 'PERSONALITY',
        _ => cat.toUpperCase(),
      };
}

class _CategoryHeader extends StatelessWidget {
  final String label;
  final bool isDark;
  const _CategoryHeader({required this.label, required this.isDark});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(14, 22, 14, 5),
      child: Row(
        children: [
          Container(
            width: 3,
            height: 12,
            decoration: BoxDecoration(
              gradient: const LinearGradient(
                colors: [StudioColors.primary, StudioColors.secondary],
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
              ),
              borderRadius: BorderRadius.circular(2),
            ),
          ),
          const SizedBox(width: 8),
          Text(
            label,
            style: TextStyle(
              fontSize: 9.5,
              fontWeight: FontWeight.w700,
              color: isDark ? StudioColors.textDisabled : StudioLightColors.textDisabled,
              letterSpacing: 1.4,
            ),
          ),
        ],
      ),
    );
  }
}

// ── Server error ───────────────────────────────────────────────────────────────

class _ServerErrorState extends StatelessWidget {
  final Object error;
  const _ServerErrorState({required this.error});

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
                color: StudioColors.surfaceElevated,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: StudioColors.surfaceBorder),
              ),
              child: const Icon(Icons.wifi_off_rounded,
                  size: 36, color: StudioColors.textDisabled),
            ),
            const SizedBox(height: 16),
            Text('Server not reachable',
                style: Theme.of(context)
                    .textTheme
                    .titleSmall
                    ?.copyWith(color: StudioColors.textSecondary)),
            const SizedBox(height: 6),
            Text('Is the Avatar Studio server running?',
                style: Theme.of(context).textTheme.bodySmall,
                textAlign: TextAlign.center),
          ],
        ),
      ),
    );
  }
}
