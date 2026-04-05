import 'dart:async';
import 'package:flutter/material.dart';
import '../../core/theme/app_theme.dart';

class GenerationProgress extends StatefulWidget {
  /// True when the selected style is programmatic (no LLM involved).
  final bool isProgrammatic;
  const GenerationProgress({super.key, this.isProgrammatic = false});

  @override
  State<GenerationProgress> createState() => _GenerationProgressState();
}

class _GenerationProgressState extends State<GenerationProgress>
    with SingleTickerProviderStateMixin {
  late final AnimationController _pulseController;
  late final Animation<double> _pulse;
  late final Timer _timer;
  int _seconds = 0;

  @override
  void initState() {
    super.initState();
    _pulseController =
        AnimationController(vsync: this, duration: const Duration(milliseconds: 1800))
          ..repeat(reverse: true);
    _pulse = CurvedAnimation(parent: _pulseController, curve: Curves.easeInOut);
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() => _seconds++);
    });
  }

  @override
  void dispose() {
    _pulseController.dispose();
    _timer.cancel();
    super.dispose();
  }

  String get _elapsed {
    if (_seconds < 60) return '${_seconds}s';
    return '${_seconds ~/ 60}m ${_seconds % 60}s';
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final dimColor = isDark ? StudioColors.textDisabled : StudioLightColors.textDisabled;

    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // ── Pulsing placeholder ────────────────────────────────────────────
          AnimatedBuilder(
            animation: _pulse,
            builder: (_, _) => Container(
              width: 320,
              height: 320,
              decoration: BoxDecoration(
                color: isDark ? StudioColors.surfaceElevated : StudioLightColors.surfaceElevated,
                borderRadius: BorderRadius.circular(18),
                border: Border.all(
                  color: StudioColors.primary.withAlpha((60 + (_pulse.value * 100).toInt())),
                  width: 1.5,
                ),
                boxShadow: [
                  BoxShadow(
                    color: StudioColors.primary.withAlpha((20 + (_pulse.value * 50).toInt())),
                    blurRadius: 24 + _pulse.value * 24,
                    spreadRadius: 2,
                  ),
                ],
              ),
              child: Center(
                child: Icon(
                  widget.isProgrammatic ? Icons.widgets_rounded : Icons.face_retouching_natural,
                  size: 72,
                  color:
                      StudioColors.primary.withAlpha((70 + (_pulse.value * 100).toInt())),
                ),
              ),
            ),
          ),

          const SizedBox(height: 28),

          // ── Status row ─────────────────────────────────────────────────────
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              SizedBox(
                width: 14,
                height: 14,
                child: CircularProgressIndicator(
                    strokeWidth: 1.8, color: StudioColors.primary),
              ),
              const SizedBox(width: 10),
              Text(
                widget.isProgrammatic ? 'Rendering avatar…' : 'AI is generating your avatar',
                style: Theme.of(context).textTheme.titleSmall,
              ),
            ],
          ),

          const SizedBox(height: 10),

          // ── Elapsed + hint ─────────────────────────────────────────────────
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: isDark ? StudioColors.surfaceElevated : StudioLightColors.surfaceElevated,
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(
                    color: isDark ? StudioColors.surfaceBorder : StudioLightColors.surfaceBorder,
                  ),
                ),
                child: Text(
                  _elapsed,
                  style: const TextStyle(
                    fontFamily: 'monospace',
                    fontSize: 12,
                    color: StudioColors.secondary,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Text(
                widget.isProgrammatic
                    ? 'Programmatic render — typically instant'
                    : 'LLM pipeline — typically 30–60s',
                style: TextStyle(fontSize: 11, color: dimColor),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
