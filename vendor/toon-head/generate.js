#!/usr/bin/env node
/**
 * Avatar Studio — ToonHead generator (DiceBear big-smile style)
 *
 * Usage:
 *   node generate.js --seed <name> [--size <N>] [--options <json>] [--out <path>]
 *
 * Writes SVG to stdout when --out is omitted, otherwise saves to the given path.
 *
 * Options JSON keys (all optional):
 *   skinColor, hairColor, backgroundColor — hex strings without the leading '#'
 *   Any other option accepted by @dicebear/big-smile
 *
 * Exit codes:
 *   0  success
 *   1  bad arguments / runtime error
 */

"use strict";

const { createAvatar } = require("@dicebear/core");
const bigSmile = require("@dicebear/big-smile");
const fs = require("fs");
const path = require("path");

// ── Argument parsing ──────────────────────────────────────────────────────────

const args = process.argv.slice(2);

let seed = "";
let size = 256;
let extraOptions = {};
let outPath = null;

for (let i = 0; i < args.length; i++) {
  switch (args[i]) {
    case "--seed":
      seed = args[++i] ?? "";
      break;
    case "--size":
      size = parseInt(args[++i], 10);
      if (isNaN(size) || size <= 0) {
        console.error("--size must be a positive integer");
        process.exit(1);
      }
      break;
    case "--options":
      try {
        extraOptions = JSON.parse(args[++i] ?? "{}");
      } catch (e) {
        console.error(`--options must be valid JSON: ${e.message}`);
        process.exit(1);
      }
      break;
    case "--out":
      outPath = args[++i] ?? null;
      break;
    default:
      console.error(`Unknown argument: ${args[i]}`);
      process.exit(1);
  }
}

if (!seed) {
  console.error("--seed is required");
  process.exit(1);
}

// ── Avatar generation ─────────────────────────────────────────────────────────

const options = {
  seed,
  size,
  ...extraOptions,
};

const avatar = createAvatar(bigSmile, options);
const svg = avatar.toString();

// ── Output ────────────────────────────────────────────────────────────────────

if (outPath) {
  const dir = path.dirname(outPath);
  if (dir && dir !== ".") {
    fs.mkdirSync(dir, { recursive: true });
  }
  fs.writeFileSync(outPath, svg, "utf8");
} else {
  process.stdout.write(svg);
}
