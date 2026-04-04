import 'package:flutter/material.dart';
import '../../../../core/api/api_models.dart';

class TextContent extends StatefulWidget {
  final AttributeDef attribute;
  final String value;
  final ValueChanged<String> onChanged;

  const TextContent({
    super.key,
    required this.attribute,
    required this.value,
    required this.onChanged,
  });

  @override
  State<TextContent> createState() => _TextContentState();
}

class _TextContentState extends State<TextContent> {
  late final TextEditingController _ctrl;

  @override
  void initState() {
    super.initState();
    _ctrl = TextEditingController(text: widget.value);
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final suggestions = widget.attribute.suggestions ?? [];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        TextField(
          controller: _ctrl,
          decoration: const InputDecoration(
            isDense: true,
            contentPadding: EdgeInsets.symmetric(horizontal: 8, vertical: 8),
            border: OutlineInputBorder(),
          ),
          onChanged: widget.onChanged,
        ),
        if (suggestions.isNotEmpty) ...[
          const SizedBox(height: 4),
          Wrap(
            spacing: 4,
            runSpacing: 2,
            children: suggestions
                .map((s) => ActionChip(
                      label: Text(s, style: const TextStyle(fontSize: 11)),
                      onPressed: () {
                        _ctrl.text = s;
                        widget.onChanged(s);
                      },
                    ))
                .toList(),
          ),
        ],
      ],
    );
  }
}
