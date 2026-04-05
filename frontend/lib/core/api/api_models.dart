/// Data models mirroring the FastAPI Pydantic models.
/// These are plain Dart classes (no code generation required).

// ─── Config response ──────────────────────────────────────────────────────────

class SelectionMode {
  final String id;
  final String label;
  const SelectionMode({required this.id, required this.label});

  factory SelectionMode.fromJson(Map<String, dynamic> j) =>
      SelectionMode(id: j['id'] as String, label: j['label'] as String);
}

class AttributeOption {
  final String id;
  final String label;
  final Map<String, dynamic>? extra;
  const AttributeOption({required this.id, required this.label, this.extra});

  factory AttributeOption.fromJson(Map<String, dynamic> j) => AttributeOption(
        id: j['id'] as String,
        label: j['label'] as String,
        extra: j['extra'] as Map<String, dynamic>?,
      );
}

class AttributeDef {
  final String id;
  final String label;
  final String category;
  final String type;
  final List<SelectionMode> selectionModes;
  final String defaultMode;
  final List<AttributeOption> options;
  final String? dependsOn;
  final bool llmGenerated;
  final List<int>? range;
  final List<String>? fieldNames;
  final String? formula;
  final List<String>? suggestions;

  const AttributeDef({
    required this.id,
    required this.label,
    required this.category,
    required this.type,
    required this.selectionModes,
    required this.defaultMode,
    required this.options,
    this.dependsOn,
    this.llmGenerated = false,
    this.range,
    this.fieldNames,
    this.formula,
    this.suggestions,
  });

  factory AttributeDef.fromJson(Map<String, dynamic> j) => AttributeDef(
        id: j['id'] as String,
        label: j['label'] as String,
        category: j['category'] as String,
        type: j['type'] as String,
        selectionModes: (j['selection_modes'] as List)
            .map((e) => SelectionMode.fromJson(e as Map<String, dynamic>))
            .toList(),
        defaultMode: j['default_mode'] as String,
        options: (j['options'] as List? ?? [])
            .map((e) => AttributeOption.fromJson(e as Map<String, dynamic>))
            .toList(),
        dependsOn: j['depends_on'] as String?,
        llmGenerated: j['llm_generated'] as bool? ?? false,
        range: (j['range'] as List?)?.map((e) => e as int).toList(),
        fieldNames: (j['field_names'] as List?)?.map((e) => e as String).toList(),
        formula: j['formula'] as String?,
        suggestions: (j['suggestions'] as List?)?.map((e) => e as String).toList(),
      );
}

class ConfigResponse {
  final List<AttributeDef> attributes;
  const ConfigResponse({required this.attributes});

  factory ConfigResponse.fromJson(Map<String, dynamic> j) => ConfigResponse(
        attributes: (j['attributes'] as List)
            .map((e) => AttributeDef.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}

// ─── Request / response models ────────────────────────────────────────────────

class AttributeSelection {
  final String id;
  final String mode;
  final dynamic value;
  const AttributeSelection({required this.id, required this.mode, this.value});

  Map<String, dynamic> toJson() => {'id': id, 'mode': mode, 'value': value};
}

class RandomizeRequest {
  final List<AttributeSelection> constraints;
  final int? seed;
  const RandomizeRequest({this.constraints = const [], this.seed});

  Map<String, dynamic> toJson() => {
        'constraints': constraints.map((c) => c.toJson()).toList(),
        if (seed != null) 'seed': seed,
      };
}

class RandomizeResponse {
  final Map<String, dynamic> values;
  const RandomizeResponse({required this.values});

  factory RandomizeResponse.fromJson(Map<String, dynamic> j) =>
      RandomizeResponse(values: j['values'] as Map<String, dynamic>);
}

class GenerateRequest {
  final List<AttributeSelection> selections;
  final List<String> expressions;
  final int width;
  final int height;
  final int? seed;

  const GenerateRequest({
    this.selections = const [],
    this.expressions = const ['neutral'],
    this.width = 256,
    this.height = 256,
    this.seed,
  });

  Map<String, dynamic> toJson() => {
        'selections': selections.map((s) => s.toJson()).toList(),
        'expressions': expressions,
        'width': width,
        'height': height,
        if (seed != null) 'seed': seed,
      };
}

class GenerateResult {
  final String imageB64;
  final Map<String, dynamic> avatarPersona;
  final Map<String, String> expressions;
  final String sessionId;

  const GenerateResult({
    required this.imageB64,
    required this.avatarPersona,
    required this.expressions,
    required this.sessionId,
  });

  factory GenerateResult.fromJson(Map<String, dynamic> j) => GenerateResult(
        imageB64: j['image_b64'] as String,
        avatarPersona: j['avatar_persona'] as Map<String, dynamic>,
        expressions: (j['expressions'] as Map<String, dynamic>)
            .map((k, v) => MapEntry(k, v as String)),
        sessionId: j['session_id'] as String,
      );
}
