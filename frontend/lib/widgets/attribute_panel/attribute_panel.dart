import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/api/api_models.dart';
import '../../../features/avatar/providers/selections_provider.dart';
import 'mode_selector.dart';
import 'content/choice_content.dart';
import 'content/color_content.dart';
import 'content/dual_color_content.dart';
import 'content/integer_content.dart';
import 'content/text_content.dart';
import 'content/list_content.dart';

class AttributePanel extends ConsumerWidget {
  final AttributeDef attribute;
  const AttributePanel({super.key, required this.attribute});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final selectionsState = ref.watch(selectionsProvider);
    final notifier = ref.read(selectionsProvider.notifier);
    final currentMode = notifier.getModeFor(attribute.id);
    final currentValue = notifier.getValueFor(attribute.id);

    final isRandomMode = currentMode == 'random' || currentMode == 'inherited';

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    attribute.label,
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                ),
                ModeSelector(
                  modes: attribute.selectionModes,
                  currentMode: currentMode,
                  onModeChanged: (newMode) =>
                      notifier.setSelection(attribute.id, newMode, null),
                ),
              ],
            ),
            if (!isRandomMode) ...[
              const SizedBox(height: 8),
              _buildContent(context, ref, currentMode, currentValue, notifier),
            ] else ...[
              const SizedBox(height: 4),
              _buildRandomPreview(context, currentValue),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildRandomPreview(BuildContext context, dynamic value) {
    if (value == null) return const SizedBox.shrink();
    String displayText = value is Map ? value.toString() : value.toString();
    if (displayText.length > 40) displayText = '${displayText.substring(0, 40)}…';
    return Text(
      displayText,
      style: Theme.of(context).textTheme.bodySmall?.copyWith(
            color: Theme.of(context).colorScheme.outline,
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
        return Text('Unknown type: ${attribute.type}');
    }
  }
}
