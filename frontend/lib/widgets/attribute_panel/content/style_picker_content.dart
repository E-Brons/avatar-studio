import 'dart:math';
import 'package:flutter/material.dart';
import '../../../../core/api/api_models.dart';
import '../../../../core/theme/app_theme.dart';

class StylePickerContent extends StatefulWidget {
  final AttributeDef attribute;
  final String mode;
  final String? value;
  final ValueChanged<String> onChanged;

  const StylePickerContent({
    super.key,
    required this.attribute,
    required this.mode,
    this.value,
    required this.onChanged,
  });

  @override
  State<StylePickerContent> createState() => _StylePickerContentState();
}

class _StylePickerContentState extends State<StylePickerContent> {
  bool _expanded = false;

  static IconData _iconFromName(String? name) => switch (name) {
        'face' => Icons.face,
        'emoji_emotions' => Icons.emoji_emotions_outlined,
        'smart_toy' => Icons.smart_toy_outlined,
        'account_circle' => Icons.account_circle_outlined,
        'people_alt' => Icons.people_alt_outlined,
        'view_in_ar' => Icons.view_in_ar,
        'brush' => Icons.brush_outlined,
        'photo_camera' => Icons.photo_camera_outlined,
        'draw' => Icons.draw_outlined,
        'texture' => Icons.texture,
        _ => Icons.image_outlined,
      };

  String get _effectiveValue {
    if (widget.value != null) return widget.value!;
    for (final opt in widget.attribute.options) {
      if ((opt.extra?['engine'] as String?) == 'programmatic') return opt.id;
    }
    return widget.attribute.options.isNotEmpty ? widget.attribute.options.first.id : '';
  }

  AttributeOption? get _currentOption =>
      widget.attribute.options.where((o) => o.id == _effectiveValue).firstOrNull;

  void _shuffle() {
    final opts = widget.attribute.options;
    if (opts.isEmpty) return;
    final picked = opts[Random().nextInt(opts.length)];
    widget.onChanged(picked.id);
    setState(() => _expanded = false);
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final current = _currentOption;

    final programmatic = widget.attribute.options
        .where((o) => (o.extra?['engine'] as String?) == 'programmatic')
        .toList();
    final llm = widget.attribute.options
        .where((o) => (o.extra?['engine'] as String?) != 'programmatic')
        .toList();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // ── Compact header (always visible) ───────────────────────────────────
        GestureDetector(
          onTap: () => setState(() => _expanded = !_expanded),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 120),
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 5),
            decoration: BoxDecoration(
              color: isDark
                  ? StudioColors.primary.withAlpha(22)
                  : StudioLightColors.primary.withAlpha(18),
              borderRadius: BorderRadius.circular(7),
              border: Border.all(
                color: isDark
                    ? StudioColors.primary.withAlpha(90)
                    : StudioLightColors.primary.withAlpha(80),
              ),
            ),
            child: Row(
              children: [
                Icon(Icons.circle, size: 8,
                    color: isDark ? StudioColors.primary : StudioLightColors.primary),
                const SizedBox(width: 7),
                Expanded(
                  child: Text(
                    current?.label ?? '—',
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      color: isDark ? StudioColors.textPrimary : const Color(0xFF0F172A),
                    ),
                  ),
                ),
                if ((current?.extra?['engine'] as String?) != 'programmatic')
                  Padding(
                    padding: const EdgeInsets.only(right: 4),
                    child: Icon(Icons.auto_awesome, size: 11,
                        color: isDark ? StudioColors.secondary : StudioLightColors.primary),
                  ),
                // 3 thumbnails for current
                _ThumbRow(option: current, iconFromName: _iconFromName, isDark: isDark),
                const SizedBox(width: 6),
                // Shuffle button
                GestureDetector(
                  onTap: _shuffle,
                  child: Tooltip(
                    message: 'Random style',
                    child: Icon(Icons.shuffle_rounded, size: 14,
                        color: isDark ? StudioColors.textSecondary : StudioLightColors.textSecondary),
                  ),
                ),
                const SizedBox(width: 4),
                Icon(
                  _expanded ? Icons.expand_less : Icons.expand_more,
                  size: 16,
                  color: isDark ? StudioColors.textDisabled : StudioLightColors.textDisabled,
                ),
              ],
            ),
          ),
        ),

        // ── Expanded list ─────────────────────────────────────────────────────
        if (_expanded) ...[
          const SizedBox(height: 8),
          if (programmatic.isNotEmpty) ...[
            _SectionLabel(label: 'INTERACTIVE', icon: Icons.widgets_outlined, isDark: isDark),
            const SizedBox(height: 4),
            for (final opt in programmatic)
              _StyleRow(
                option: opt,
                isSelected: _effectiveValue == opt.id,
                onTap: () { widget.onChanged(opt.id); setState(() => _expanded = false); },
                isDark: isDark,
                iconFromName: _iconFromName,
              ),
          ],
          if (llm.isNotEmpty) ...[
            if (programmatic.isNotEmpty) const SizedBox(height: 8),
            _SectionLabel(label: 'AI-GENERATED', icon: Icons.auto_awesome_outlined, isDark: isDark),
            const SizedBox(height: 4),
            for (final opt in llm)
              _StyleRow(
                option: opt,
                isSelected: _effectiveValue == opt.id,
                onTap: () { widget.onChanged(opt.id); setState(() => _expanded = false); },
                isDark: isDark,
                iconFromName: _iconFromName,
                isLlm: true,
              ),
          ],
        ],
      ],
    );
  }
}

// ─── Section header ───────────────────────────────────────────────────────────

class _SectionLabel extends StatelessWidget {
  final String label;
  final IconData icon;
  final bool isDark;
  const _SectionLabel({required this.label, required this.icon, required this.isDark});

  @override
  Widget build(BuildContext context) {
    final color = isDark ? StudioColors.textDisabled : StudioLightColors.textDisabled;
    return Row(
      children: [
        Icon(icon, size: 11, color: color),
        const SizedBox(width: 4),
        Text(label, style: TextStyle(
          fontSize: 9, fontWeight: FontWeight.w700, color: color, letterSpacing: 0.8,
        )),
      ],
    );
  }
}

// ─── Single style row ─────────────────────────────────────────────────────────

class _StyleRow extends StatelessWidget {
  final AttributeOption option;
  final bool isSelected;
  final VoidCallback onTap;
  final bool isDark;
  final bool isLlm;
  final IconData Function(String?) iconFromName;

  const _StyleRow({
    required this.option,
    required this.isSelected,
    required this.onTap,
    required this.isDark,
    required this.iconFromName,
    this.isLlm = false,
  });

  @override
  Widget build(BuildContext context) {
    final active = isDark ? StudioColors.primary : StudioLightColors.primary;
    final textColor = isSelected
        ? active
        : (isDark ? StudioColors.textSecondary : StudioLightColors.textSecondary);

    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 120),
        margin: const EdgeInsets.only(bottom: 3),
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 5),
        decoration: BoxDecoration(
          color: isSelected
              ? (isDark ? StudioColors.primary.withAlpha(22) : StudioLightColors.primary.withAlpha(18))
              : Colors.transparent,
          borderRadius: BorderRadius.circular(7),
          border: Border.all(
            color: isSelected
                ? active.withAlpha(90)
                : (isDark ? StudioColors.surfaceBorderSubtle : StudioLightColors.surfaceBorder),
          ),
        ),
        child: Row(
          children: [
            Icon(
              isSelected ? Icons.circle : Icons.circle_outlined,
              size: 8,
              color: isSelected
                  ? active
                  : (isDark ? StudioColors.textDisabled : StudioLightColors.textDisabled),
            ),
            const SizedBox(width: 7),
            Expanded(
              child: Text(option.label, style: TextStyle(
                fontSize: 12,
                fontWeight: isSelected ? FontWeight.w600 : FontWeight.w400,
                color: textColor,
              )),
            ),
            if (isLlm) ...[
              Icon(Icons.auto_awesome, size: 11,
                  color: isDark ? StudioColors.secondary : StudioLightColors.primary),
              const SizedBox(width: 6),
            ],
            _ThumbRow(option: option, iconFromName: iconFromName, isDark: isDark),
          ],
        ),
      ),
    );
  }
}

// ─── 3 preview thumbnails in a row ───────────────────────────────────────────

class _ThumbRow extends StatelessWidget {
  final AttributeOption? option;
  final IconData Function(String?) iconFromName;
  final bool isDark;
  const _ThumbRow({required this.option, required this.iconFromName, required this.isDark});

  @override
  Widget build(BuildContext context) {
    final exampleImages = (option?.extra?['example_images'] as List?)
            ?.map((e) => e.toString())
            .where((p) => p.isNotEmpty)
            .toList() ??
        [];
    final icon = iconFromName(option?.extra?['icon'] as String?);

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        for (int i = 0; i < 3; i++)
          Padding(
            padding: const EdgeInsets.only(left: 2),
            child: _Thumb(
              path: i < exampleImages.length ? exampleImages[i] : null,
              icon: icon,
              isDark: isDark,
            ),
          ),
      ],
    );
  }
}

// ─── Single thumbnail ─────────────────────────────────────────────────────────

class _Thumb extends StatelessWidget {
  final String? path;
  final IconData icon;
  final bool isDark;
  const _Thumb({required this.path, required this.icon, required this.isDark});

  @override
  Widget build(BuildContext context) {
    final bg = isDark ? StudioColors.surfaceElevated : StudioLightColors.surfaceElevated;
    return ClipRRect(
      borderRadius: BorderRadius.circular(4),
      child: SizedBox(
        width: 44,
        height: 40,
        child: path != null
            ? Image.asset(
                path!,
                fit: BoxFit.cover,
                errorBuilder: (_, _, _) => Container(
                  color: bg,
                  child: Icon(icon, size: 18, color: StudioColors.textDisabled),
                ),
              )
            : Container(
                color: bg,
                child: Icon(icon, size: 18, color: StudioColors.textDisabled),
              ),
      ),
    );
  }
}
