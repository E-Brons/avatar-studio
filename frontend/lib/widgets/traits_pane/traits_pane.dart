import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/theme/app_theme.dart';
import '../../features/avatar/providers/generate_provider.dart';
import '../../core/api/api_models.dart';

const double _kPaneWidth = 280.0;
const _kProgrammaticStyles = {'toon-head', 'avataaars', 'bottts', 'micah', 'opeeps'};

class TraitsPane extends ConsumerStatefulWidget {
  final bool collapsed;
  const TraitsPane({super.key, required this.collapsed});

  @override
  ConsumerState<TraitsPane> createState() => _TraitsPaneState();
}

class _TraitsPaneState extends ConsumerState<TraitsPane> with SingleTickerProviderStateMixin {
  late final AnimationController _botCtrl;
  late final Animation<double> _botPulse;

  int _revealedCount = 0;
  List<_TraitItem> _revealItems = [];
  bool _allDone = false;

  Timer? _revealTimer;

  @override
  void initState() {
    super.initState();
    _botCtrl = AnimationController(vsync: this, duration: const Duration(milliseconds: 900))
      ..repeat(reverse: true);
    _botPulse = CurvedAnimation(parent: _botCtrl, curve: Curves.easeInOut);
  }

  @override
  void dispose() {
    _botCtrl.dispose();
    _revealTimer?.cancel();
    super.dispose();
  }

  void _startReveal(List<_TraitItem> items) {
    _revealTimer?.cancel();
    setState(() {
      _revealedCount = 0;
      _allDone = false;
      _revealItems = items;
    });
    if (items.isEmpty) {
      setState(() => _allDone = true);
      return;
    }
    final intervalMs = (2400 ~/ items.length).clamp(60, 180);
    _revealTimer = Timer.periodic(Duration(milliseconds: intervalMs), (t) {
      if (!mounted) {
        t.cancel();
        return;
      }
      setState(() {
        if (_revealedCount < items.length) {
          _revealedCount++;
        } else {
          t.cancel();
          _allDone = true;
        }
      });
    });
  }

  // ── Flatten avatarPersona into displayable rows ──────────────────────────────

  List<_TraitItem> _buildPersonItems(Map<String, dynamic> persona) {
    final items = <_TraitItem>[];

    final personal = persona['personal'] as Map<String, dynamic>?;
    if (personal != null) {
      _add(items, 'Name', personal['name']);
      _add(items, 'Gender', personal['gender']);
      _add(items, 'Age', personal['age']);
    }

    final demographics = persona['demographics'] as Map<String, dynamic>?;
    if (demographics != null) {
      for (final entry in demographics.entries) {
        _add(items, _label(entry.key), entry.value);
      }
    }

    final personality = persona['personality'] as Map<String, dynamic>?;
    final traits = personality?['traits'];
    if (traits is List && traits.isNotEmpty) {
      _add(items, 'Personality', traits.take(6).join(', '));
    }

    final appearance = persona['appearance'] as Map<String, dynamic>?;
    if (appearance != null) {
      for (final entry in appearance.entries) {
        _add(items, _label(entry.key), entry.value);
      }
    }

    return items;
  }

  void _add(List<_TraitItem> items, String label, dynamic value) {
    if (value == null) return;
    String display;
    if (value is Map) {
      display = value.values.take(2).join(' / ');
    } else if (value is List) {
      display = value.take(4).join(', ');
    } else {
      display = value.toString();
    }
    display = display.trim();
    if (display.isEmpty) return;
    if (display.length > 52) display = '${display.substring(0, 52)}…';
    items.add(_TraitItem(label: label, value: display));
  }

  static String _label(String key) {
    // Convert snake_case / UPPER_CASE to Title Case
    return key
        .toLowerCase()
        .split('_')
        .map((w) => w.isEmpty ? w : '${w[0].toUpperCase()}${w.substring(1)}')
        .join(' ');
  }

  @override
  Widget build(BuildContext context) {
    final generateAsync = ref.watch(generateProvider);
    final isDark = Theme.of(context).brightness == Brightness.dark;

    ref.listen<AsyncValue<GenerateResult?>>(generateProvider, (prev, next) {
      if (next is AsyncLoading && prev is! AsyncLoading) {
        _revealTimer?.cancel();
        setState(() { _revealedCount = 0; _allDone = false; _revealItems = []; });
      } else if (next is AsyncData && prev is AsyncLoading) {
        final persona = next.value?.avatarPersona;
        _startReveal(persona != null ? _buildPersonItems(persona) : []);
      }
    });

    if (widget.collapsed) return const SizedBox.shrink();

    final bgColor = isDark ? StudioColors.surface : const Color(0xFFFAFAFA);
    final borderColor = isDark ? StudioColors.surfaceBorder : const Color(0xFFE2E8F0);

    return AnimatedContainer(
      duration: const Duration(milliseconds: 220),
      width: _kPaneWidth,
      decoration: BoxDecoration(
        color: bgColor,
        border: Border(right: BorderSide(color: borderColor)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // ── Header ──────────────────────────────────────────────────────────
          Container(
            padding: const EdgeInsets.fromLTRB(14, 12, 10, 12),
            decoration: BoxDecoration(border: Border(bottom: BorderSide(color: borderColor))),
            child: Row(
              children: [
                const Text('INFO', style: TextStyle(
                  fontSize: 9.5, fontWeight: FontWeight.w700,
                  color: StudioColors.textDisabled, letterSpacing: 1.4,
                )),
                const Spacer(),
                if (_allDone)
                  const Icon(Icons.check_circle_outline_rounded,
                      size: 14, color: StudioColors.success),
              ],
            ),
          ),

          // ── Content ─────────────────────────────────────────────────────────
          Expanded(
            child: _buildContent(context, generateAsync, isDark, borderColor),
          ),
        ],
      ),
    );
  }

  Widget _buildContent(
    BuildContext context,
    AsyncValue<GenerateResult?> generateAsync,
    bool isDark,
    Color borderColor,
  ) {
    final isLoading = generateAsync is AsyncLoading;
    final result = generateAsync.asData?.value;

    // ── Loading: bot animation ────────────────────────────────────────────────
    if (isLoading) {
      return _BotPhase(pulse: _botPulse, isDark: isDark);
    }

    // ── No result yet ─────────────────────────────────────────────────────────
    if (result == null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Text(
            'Generate an avatar to see info here',
            style: TextStyle(
              fontSize: 11,
              color: isDark ? StudioColors.textDisabled : const Color(0xFF94A3B8),
            ),
            textAlign: TextAlign.center,
          ),
        ),
      );
    }

    // ── Result: style section + person traits ─────────────────────────────────
    final styleSection = result.avatarPersona['style'] as Map<String, dynamic>?;
    final styleName = styleSection?['name']?.toString() ?? '';
    final styleDesc = styleSection?['description']?.toString() ?? '';
    final styleCredit = styleSection?['credit']?.toString() ?? '';

    // Items to display — use reveal animation while in progress, else full list
    final allItems = _allDone || _revealItems.isEmpty
        ? _buildPersonItems(result.avatarPersona)
        : _revealItems;

    return SingleChildScrollView(
      padding: const EdgeInsets.only(bottom: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // ── Style block ────────────────────────────────────────────────────
          if (styleName.isNotEmpty) ...[
            Padding(
              padding: const EdgeInsets.fromLTRB(14, 12, 14, 4),
              child: Text('STYLE', style: TextStyle(
                fontSize: 9, fontWeight: FontWeight.w700,
                color: isDark ? StudioColors.textDisabled : const Color(0xFF94A3B8),
                letterSpacing: 1.2,
              )),
            ),
            Container(
              margin: const EdgeInsets.symmetric(horizontal: 10),
              padding: const EdgeInsets.fromLTRB(10, 8, 10, 10),
              decoration: BoxDecoration(
                color: isDark ? StudioColors.surfaceElevated : const Color(0xFFF1F5F9),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: borderColor),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(styleName, style: TextStyle(
                    fontSize: 13, fontWeight: FontWeight.w700,
                    color: isDark ? StudioColors.textPrimary : const Color(0xFF0F172A),
                  )),
                  if (styleDesc.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(styleDesc, style: TextStyle(
                      fontSize: 10.5,
                      color: isDark ? StudioColors.textSecondary : const Color(0xFF475569),
                      height: 1.4,
                    )),
                  ],
                  if (styleCredit.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(styleCredit, style: TextStyle(
                      fontSize: 9.5,
                      fontStyle: FontStyle.italic,
                      color: isDark ? StudioColors.textDisabled : const Color(0xFF94A3B8),
                    )),
                  ],
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(14, 12, 14, 4),
              child: Text('PERSON', style: TextStyle(
                fontSize: 9, fontWeight: FontWeight.w700,
                color: isDark ? StudioColors.textDisabled : const Color(0xFF94A3B8),
                letterSpacing: 1.2,
              )),
            ),
          ],

          // ── Person traits ──────────────────────────────────────────────────
          for (int i = 0; i < allItems.length; i++) ...[
            AnimatedOpacity(
              duration: const Duration(milliseconds: 280),
              opacity: (_allDone || _revealItems.isEmpty || i < _revealedCount) ? 1.0 : 0.15,
              child: _TraitRow(
                item: allItems[i],
                isCurrent: !_allDone && _revealItems.isNotEmpty && i == _revealedCount,
                isDark: isDark,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

// ── Bot working phase ──────────────────────────────────────────────────────────

class _BotPhase extends StatelessWidget {
  final Animation<double> pulse;
  final bool isDark;
  const _BotPhase({required this.pulse, required this.isDark});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: AnimatedBuilder(
        animation: pulse,
        builder: (_, _) => Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 56,
              height: 56,
              decoration: BoxDecoration(
                color: StudioColors.primary.withAlpha((30 + (pulse.value * 20).toInt())),
                shape: BoxShape.circle,
                border: Border.all(
                  color: StudioColors.primary.withAlpha((80 + (pulse.value * 80).toInt())),
                ),
              ),
              child: Icon(
                Icons.smart_toy_rounded,
                size: 28,
                color: StudioColors.primary.withAlpha((180 + (pulse.value * 75).toInt())),
              ),
            ),
            const SizedBox(height: 12),
            Text(
              'Thinking…',
              style: TextStyle(
                fontSize: 12,
                color: isDark ? StudioColors.textSecondary : const Color(0xFF64748B),
              ),
            ),
            const SizedBox(height: 4),
            SizedBox(
              width: 100,
              child: LinearProgressIndicator(
                value: null,
                backgroundColor: StudioColors.surfaceBorder,
                color: StudioColors.primary,
                minHeight: 2,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ── Single trait row ───────────────────────────────────────────────────────────

class _TraitRow extends StatelessWidget {
  final _TraitItem item;
  final bool isCurrent;
  final bool isDark;

  const _TraitRow({required this.item, required this.isCurrent, required this.isDark});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 3),
            child: isCurrent
                ? SizedBox(
                    width: 11,
                    height: 11,
                    child: CircularProgressIndicator(strokeWidth: 1.4, color: StudioColors.primary),
                  )
                : Icon(Icons.check_circle_outline_rounded, size: 11, color: StudioColors.success),
          ),
          const SizedBox(width: 7),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  item.label,
                  style: TextStyle(
                    fontSize: 9.5,
                    fontWeight: FontWeight.w600,
                    color: isDark ? StudioColors.textDisabled : const Color(0xFF94A3B8),
                    letterSpacing: 0.3,
                  ),
                ),
                const SizedBox(height: 1),
                Text(
                  item.value,
                  style: TextStyle(
                    fontSize: 11.5,
                    color: isDark ? StudioColors.textPrimary : const Color(0xFF1E293B),
                  ),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ── Data ───────────────────────────────────────────────────────────────────────

class _TraitItem {
  final String label;
  final String value;
  const _TraitItem({required this.label, required this.value});
}

// ── Public helper ──────────────────────────────────────────────────────────────

bool isStyleProgrammatic(String? styleId) => _kProgrammaticStyles.contains(styleId);
