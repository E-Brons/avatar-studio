import 'package:flutter/material.dart';
import '../../../../core/api/api_models.dart';

class ColorContent extends StatelessWidget {
  final AttributeDef attribute;
  final String? value;
  final ValueChanged<String> onChanged;

  const ColorContent({
    super.key,
    required this.attribute,
    required this.value,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: attribute.options.map((opt) {
          final hex = opt.id;
          final color = _hexToColor(hex);
          final isSelected = value == hex;
          return GestureDetector(
            onTap: () => onChanged(hex),
            child: Container(
              width: 28,
              height: 28,
              margin: const EdgeInsets.only(right: 4),
              decoration: BoxDecoration(
                color: color,
                shape: BoxShape.circle,
                border: isSelected
                    ? Border.all(
                        color: Theme.of(context).colorScheme.primary,
                        width: 2.5,
                      )
                    : Border.all(color: Colors.grey.shade300),
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
