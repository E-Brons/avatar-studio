import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/api/api_models.dart';
import '../../../core/theme/app_theme.dart';
import '../../../features/avatar/providers/selections_provider.dart';
import 'mode_selector.dart';
import 'content/choice_content.dart';
import 'content/color_content.dart';
import 'content/dual_color_content.dart';
import 'content/integer_content.dart';
import 'content/text_content.dart';
import 'content/list_content.dart';
import 'content/style_picker_content.dart';

class AttributePanel extends ConsumerWidget {
  final AttributeDef attribute;
  const AttributePanel({super.key, required this.attribute});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final notifier = ref.read(selectionsProvider.notifier);
    // ignore: unused_local_variable — watch ensures rebuild when selections change
    ref.watch(selectionsProvider);
    final currentMode = notifier.getModeFor(attribute.id, fallback: attribute.defaultMode);
    final currentValue = notifier.getValueFor(attribute.id);

    final isStyleAttr = attribute.id == 'style';
    final isRandomMode = !isStyleAttr && (currentMode == 'random' || currentMode == 'inherited');

    final isDark = Theme.of(context).brightness == Brightness.dark;
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: isDark ? StudioColors.surfaceElevated : StudioLightColors.surfaceElevated,
        borderRadius: BorderRadius.circular(9),
        border: Border.all(
          color: isDark ? StudioColors.surfaceBorderSubtle : StudioLightColors.surfaceBorder,
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 10, 10, 10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // ── Label + mode selector row ───────────────────────────────────
            Row(
              children: [
                Expanded(
                  child: Text(
                    attribute.label,
                    style: const TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      color: StudioColors.textPrimary,
                    ),
                  ),
                ),
                ModeSelector(
                  modes: attribute.selectionModes,
                  currentMode: currentMode,
                  onModeChanged: (m) => notifier.setSelection(attribute.id, m, null),
                ),
              ],
            ),

            // ── Content ─────────────────────────────────────────────────────
            if (isStyleAttr) ...[
              const SizedBox(height: 8),
              StylePickerContent(
                attribute: attribute,
                mode: currentMode,
                value: currentValue?.toString(),
                onChanged: (v) => notifier.setSelection(attribute.id, currentMode, v),
              ),
            ] else if (!isRandomMode) ...[
              const SizedBox(height: 7),
              _buildContent(context, ref, currentMode, currentValue, notifier),
            ] else ...[
              const SizedBox(height: 4),
              _buildRandomPreview(currentValue),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildRandomPreview(dynamic value) {
    if (value == null) return const SizedBox.shrink();
    var text = value is Map ? value.toString() : value.toString();
    if (text.length > 48) text = '${text.substring(0, 48)}…';
    return Text(
      text,
      style: const TextStyle(
        fontSize: 11,
        color: StudioColors.textDisabled,
        fontStyle: FontStyle.italic,
      ),
    );
  }

  Widget _buildContent(
    BuildContext context,
    WidgetRef ref,
    String mode,
    dynamic value,
    SelectionsNotifier notifier,
  ) {
    switch (attribute.type) {
      case 'choice':
        return ChoiceContent(
          attribute: attribute,
          value: value?.toString(),
          onChanged: (v) => notifier.setSelection(attribute.id, mode, v),
        );
      case 'color':
        return ColorContent(
          attribute: attribute,
          value: value?.toString(),
          onChanged: (v) => notifier.setSelection(attribute.id, mode, v),
        );
      case 'dual_color':
        return DualColorContent(
          attribute: attribute,
          value: value,
          onChanged: (v) => notifier.setSelection(attribute.id, mode, v),
        );
      case 'integer':
        return IntegerContent(
          attribute: attribute,
          value: value is int ? value : (int.tryParse(value?.toString() ?? '') ?? 30),
          onChanged: (v) => notifier.setSelection(attribute.id, mode, v),
        );
      case 'text':
        return TextContent(
          attribute: attribute,
          value: value?.toString() ?? '',
          onChanged: (v) => notifier.setSelection(attribute.id, mode, v),
        );
      case 'list':
      case 'dict':
        return ListContent(
          attribute: attribute,
          value: value,
          onChanged: (v) => notifier.setSelection(attribute.id, mode, v),
        );
      default:
        return Text('Unknown type: ${attribute.type}',
            style: const TextStyle(fontSize: 11, color: StudioColors.textDisabled));
    }
  }
}
