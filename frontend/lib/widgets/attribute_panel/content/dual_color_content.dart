import 'package:flutter/material.dart';
import '../../../../core/api/api_models.dart';

/// Displays dual-color options (hair color = base+shadow, eye = iris+pupil).
/// Each swatch shows both colors side by side.
class DualColorContent extends StatelessWidget {
  final AttributeDef attribute;
  final dynamic value; // String like "#BASE #SHADOW" or Map
  final ValueChanged<dynamic> onChanged;

  const DualColorContent({
    super.key,
    required this.attribute,
    required this.value,
    required this.onChanged,
  });

  String? _currentId() {
    if (value is String) return value as String;
    if (value is Map) {
      final m = value as Map;
      final fields = attribute.fieldNames ?? [];
      if (fields.length >= 2) {
        return '${m[fields[0]]} ${m[fields[1]]}';
      }
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final currentId = _currentId();
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: attribute.options.map((opt) {
          final isSelected = opt.id == currentId;
          final extra = opt.extra ?? {};
          final fields = attribute.fieldNames ?? ['hex_a', 'hex_b'];
          final color1 = _hexToColor(extra[fields[0]]?.toString() ?? '#888888');
          final color2 = _hexToColor(extra[fields[1]]?.toString() ?? '#444444');

          return GestureDetector(
            onTap: () => onChanged(opt.id),
            child: Container(
              width: 36,
              height: 28,
              margin: const EdgeInsets.only(right: 4),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(4),
                border: isSelected
                    ? Border.all(
                        color: Theme.of(context).colorScheme.primary,
                        width: 2.5,
                      )
                    : Border.all(color: Colors.grey.shade300),
              ),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(3),
                child: Row(
                  children: [
                    Expanded(child: ColoredBox(color: color1)),
                    Expanded(child: ColoredBox(color: color2)),
                  ],
                ),
              ),
            ),
          );
        }).toList(),
      ),
    );
  }

  Color _hexToColor(String hex) {
    final h = hex.replaceFirst('#', '');
    return Color(int.parse('FF$h', radix: 16));
  }
}
