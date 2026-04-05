import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/api/api_models.dart';
import '../../config/providers/config_provider.dart';

/// Current selection state for all attributes.
class SelectionsState {
  /// Map of attributeId → AttributeSelection
  final Map<String, AttributeSelection> selections;
  const SelectionsState({this.selections = const {}});

  SelectionsState copyWith({Map<String, AttributeSelection>? selections}) =>
      SelectionsState(selections: selections ?? this.selections);
}

class SelectionsNotifier extends Notifier<SelectionsState> {
  @override
  SelectionsState build() => SelectionsState(
        selections: const {
          // Style defaults to 'photorealistic' so the AI style is pre-selected
          // on first load and the picker shows a clear selection.
          'style': AttributeSelection(id: 'style', mode: 'select', value: 'photorealistic'),
        },
      );

  void setSelection(String id, String mode, dynamic value) {
    final updated = Map<String, AttributeSelection>.from(state.selections);
    updated[id] = AttributeSelection(id: id, mode: mode, value: value);
    state = state.copyWith(selections: updated);

    // If gender changed, reset all depends_on: gender attributes to their default mode.
    if (id == 'gender') {
      _resetGenderDependentAttributes();
    }
  }

  void applyRandomizeResult(Map<String, dynamic> values) {
    final updated = Map<String, AttributeSelection>.from(state.selections);
    values.forEach((attrId, value) {
      // Only update attributes whose current mode is non-pinned (random or llm).
      final current = updated[attrId];
      if (current == null || current.mode == 'random' || current.mode == 'llm') {
        updated[attrId] = AttributeSelection(
          id: attrId,
          mode: current?.mode ?? 'random',
          value: value,
        );
      }
    });
    state = state.copyWith(selections: updated);
  }

  void _resetGenderDependentAttributes() {
    final configAsync = ref.read(configProvider);
    configAsync.whenData((config) {
      final attrDefaults = {for (final a in config.attributes) a.id: a.defaultMode};
      final updated = Map<String, AttributeSelection>.from(state.selections);
      for (final attr in config.attributes) {
        if (attr.dependsOn == 'gender') {
          final current = updated[attr.id];
          final defaultMode = attrDefaults[attr.id] ?? 'random';
          if (current != null && current.mode != defaultMode) {
            updated[attr.id] = AttributeSelection(id: attr.id, mode: defaultMode, value: null);
          }
        }
      }
      state = state.copyWith(selections: updated);
    });
  }

  List<AttributeSelection> toRequestSelections() {
    return state.selections.values.toList();
  }

  String getModeFor(String attrId, {String fallback = 'random'}) =>
      state.selections[attrId]?.mode ?? fallback;

  dynamic getValueFor(String attrId) => state.selections[attrId]?.value;
}

final selectionsProvider = NotifierProvider<SelectionsNotifier, SelectionsState>(
  SelectionsNotifier.new,
);
