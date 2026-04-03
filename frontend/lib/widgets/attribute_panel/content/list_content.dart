import 'package:flutter/material.dart';
import '../../../../core/api/api_models.dart';

/// Handles list and dict type attributes.
/// Shows a text area with the serialized value for manual editing.
class ListContent extends StatefulWidget {
  final AttributeDef attribute;
  final dynamic value;
  final ValueChanged<dynamic> onChanged;

  const ListContent({
    super.key,
    required this.attribute,
    required this.value,
    required this.onChanged,
  });

  @override
  State<ListContent> createState() => _ListContentState();
}

class _ListContentState extends State<ListContent> {
  late final TextEditingController _ctrl;

  @override
  void initState() {
    super.initState();
    _ctrl = TextEditingController(text: _displayText(widget.value));
  }

  String _displayText(dynamic v) {
    if (v == null) return '';
    if (v is List) return v.join('\n');
    if (v is Map) {
      return v.entries.map((e) => '${e.key}: ${e.value}').join('\n');
    }
    return v.toString();
  }

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: _ctrl,
      maxLines: 3,
      decoration: const InputDecoration(
        isDense: true,
        hintText: 'One item per line',
        border: OutlineInputBorder(),
        contentPadding: EdgeInsets.symmetric(horizontal: 8, vertical: 8),
      ),
      onChanged: (text) {
        final lines = text.split('\n').where((l) => l.trim().isNotEmpty).toList();
        widget.onChanged(lines);
      },
    );
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }
}
