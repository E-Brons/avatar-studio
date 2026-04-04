import 'dart:async';
import 'package:web_socket_channel/web_socket_channel.dart';
import '../config/app_config.dart';

/// Holds a WebSocket connection to /api/ws/keepalive for the lifetime of the
/// app.  When this connection drops (browser window closed), the server's
/// shutdown watcher detects it and terminates the uvicorn process.
class KeepaliveService {
  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _sub;
  Timer? _reconnectTimer;

  void start() {
    _connect();
  }

  void _connect() {
    try {
      final wsUrl = kApiBaseUrl
          .replaceFirst('http://', 'ws://')
          .replaceFirst('https://', 'wss://');
      _channel = WebSocketChannel.connect(Uri.parse('$wsUrl/api/ws/keepalive'));
      _sub = _channel!.stream.listen(
        (_) {}, // server pings — no action needed
        onDone: _onDisconnect,
        onError: (_) => _onDisconnect(),
      );
    } catch (_) {
      // Keepalive is best-effort; never crash the app if it fails.
    }
  }

  void _onDisconnect() {
    _sub?.cancel();
    _channel?.sink.close();
    // Retry after 3 s (handles server restarts during development).
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(const Duration(seconds: 3), _connect);
  }

  void dispose() {
    _reconnectTimer?.cancel();
    _sub?.cancel();
    _channel?.sink.close();
  }
}
