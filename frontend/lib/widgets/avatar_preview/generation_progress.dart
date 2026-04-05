import 'package:flutter/material.dart';
import 'package:shimmer/shimmer.dart';

class GenerationProgress extends StatelessWidget {
  const GenerationProgress({super.key});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Shimmer.fromColors(
            baseColor: Theme.of(context).colorScheme.surfaceContainerHighest,
            highlightColor: Theme.of(context).colorScheme.surface,
            child: Container(
              width: 256,
              height: 256,
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(12),
              ),
            ),
          ),
          const SizedBox(height: 16),
          const Text('Generating avatar…'),
          const SizedBox(height: 8),
          const LinearProgressIndicator(
            backgroundColor: Colors.transparent,
          ),
        ],
      ),
    );
  }
}
