import 'package:flutter/material.dart';
import '../../../core/api/api_models.dart';

class ModeSelector extends StatelessWidget {
  final List<SelectionMode> modes;
  final String currentMode;
  final ValueChanged<String> onModeChanged;

  const ModeSelector({
    super.key,
    required this.modes,
    required this.currentMode,
    required this.onModeChanged,
  });

  @override
  Widget build(BuildContext context) {
    if (modes.length == 1) {
      return Text(
        modes.first.label,
        style: Theme.of(context).textTheme.labelSmall,
      );
    }
    return SegmentedButton<String>(
      showSelectedIcon: false,
      style: ButtonStyle(
        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
        visualDensity: VisualDensity.compact,
        padding: WidgetStateProperty.all(
          const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
        ),
      ),
      segments: modes
          .map((m) => ButtonSegment<String>(
                value: m.id,
                label: Text(
                  _modeIcon(m.id),
                  style: const TextStyle(fontSize: 14),
                ),
                tooltip: m.label,
              ))
          .toList(),
      selected: {currentMode},
      onSelectionChanged: (s) => onModeChanged(s.first),
    );
  }

  String _modeIcon(String modeId) {
    switch (modeId) {
      case 'random':
        return '🎲';
      case 'random_per_group':
        return '🎯';
      case 'inherited':
        return '🔗';
      case 'llm':
        return '🤖';
      case 'select':
        return '✏️';
      default:
        return modeId;
    }
  }
}
