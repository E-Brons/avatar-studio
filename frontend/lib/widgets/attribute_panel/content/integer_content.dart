import 'package:flutter/material.dart';
import '../../../../core/api/api_models.dart';

class IntegerContent extends StatelessWidget {
  final AttributeDef attribute;
  final int value;
  final ValueChanged<int> onChanged;

  const IntegerContent({
    super.key,
    required this.attribute,
    required this.value,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    final rangeList = attribute.range;
    final min = (rangeList != null && rangeList.isNotEmpty) ? rangeList[0].toDouble() : 0.0;
    final max = (rangeList != null && rangeList.length >= 2) ? rangeList[1].toDouble() : 110.0;

    return Row(
      children: [
        Text(value.toString(), style: Theme.of(context).textTheme.bodyLarge),
        Expanded(
          child: Slider(
            value: value.clamp(min.toInt(), max.toInt()).toDouble(),
            min: min,
            max: max,
            divisions: (max - min).toInt(),
            onChanged: (v) => onChanged(v.toInt()),
          ),
        ),
      ],
    );
  }
}
