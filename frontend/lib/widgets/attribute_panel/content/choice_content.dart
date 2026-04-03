import 'package:flutter/material.dart';
import '../../../../core/api/api_models.dart';

class ChoiceContent extends StatelessWidget {
  final AttributeDef attribute;
  final String? value;
  final ValueChanged<String> onChanged;

  const ChoiceContent({
    super.key,
    required this.attribute,
    required this.value,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return DropdownButtonFormField<String>(
      value: value,
      isDense: true,
      decoration: const InputDecoration(
        isDense: true,
        contentPadding: EdgeInsets.symmetric(horizontal: 8, vertical: 6),
        border: OutlineInputBorder(),
      ),
      items: attribute.options
          .map((opt) => DropdownMenuItem(
                value: opt.id,
                child: Text(opt.label),
              ))
          .toList(),
      onChanged: (v) {
        if (v != null) onChanged(v);
      },
    );
  }
}
