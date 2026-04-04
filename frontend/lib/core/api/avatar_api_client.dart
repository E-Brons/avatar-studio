import 'package:dio/dio.dart';
import '../config/app_config.dart';
import 'api_models.dart';

class AvatarApiClient {
  AvatarApiClient({String? baseUrl})
      : _dio = Dio(BaseOptions(
          baseUrl: baseUrl ?? kApiBaseUrl,
          connectTimeout: const Duration(seconds: 10),
          receiveTimeout: const Duration(seconds: 120),
          headers: {'Content-Type': 'application/json'},
        ));

  final Dio _dio;

  Future<ConfigResponse> getConfig() async {
    final resp = await _dio.get<Map<String, dynamic>>('/api/config');
    return ConfigResponse.fromJson(resp.data!);
  }

  Future<RandomizeResponse> randomize(RandomizeRequest request) async {
    final resp = await _dio.post<Map<String, dynamic>>(
      '/api/avatar/randomize',
      data: request.toJson(),
    );
    return RandomizeResponse.fromJson(resp.data!);
  }

  Future<GenerateResult> generate(GenerateRequest request) async {
    final resp = await _dio.post<Map<String, dynamic>>(
      '/api/avatar/generate',
      data: request.toJson(),
    );
    return GenerateResult.fromJson(resp.data!);
  }

  Future<bool> healthCheck() async {
    try {
      final resp = await _dio.get<Map<String, dynamic>>('/health');
      return resp.data?['status'] == 'ok';
    } catch (_) {
      return false;
    }
  }
}
