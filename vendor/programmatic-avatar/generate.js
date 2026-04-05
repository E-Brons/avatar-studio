#!/usr/bin/env node
/**
 * Avatar Studio — Programmatic Avatar (PA) multi-style generator
 *
 * Usage:
 *   node generate.js --seed <name> [--style <style>] [--size <N>] [--options <json>] [--out <path>]
 *
 * Styles:
 *   toon-head   (default) @dicebear/toon-head
 *   avataaars             @dicebear/avataaars
 *   bottts                @dicebear/bottts
 *   micah                 @dicebear/micah
 *   opeeps                @opeepsfun/avatar-illustration-system
 *
 * Writes SVG to stdout when --out is omitted, otherwise saves to the given path.
 *
 * Exit codes:
 *   0  success
 *   1  bad arguments / runtime error
 */

"use strict";

const { createAvatar } = require("@dicebear/core");
const fs = require("fs");
const path = require("path");

// ── Argument parsing ──────────────────────────────────────────────────────────

const args = process.argv.slice(2);

let seed = "";
let size = 256;
let style = "toon-head";
let extraOptions = {};
let outPath = null;

for (let i = 0; i < args.length; i++) {
  switch (args[i]) {
    case "--seed":
      seed = args[++i] ?? "";
      break;
    case "--style":
      style = args[++i] ?? "toon-head";
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

let svg;

if (style === "opeeps") {
  // @opeepsfun/avatar-illustration-system — not DiceBear, different API
  const { Avatar } = require("@opeepsfun/avatar-illustration-system");
  svg = Avatar({ size, ...extraOptions });
} else {
  // DiceBear styles
  let dicebearStyle;
  if (style === "toon-head") {
    dicebearStyle = require("@dicebear/toon-head");
  } else if (style === "avataaars") {
    dicebearStyle = require("@dicebear/avataaars");
  } else if (style === "bottts") {
    dicebearStyle = require("@dicebear/bottts");
  } else if (style === "micah") {
    dicebearStyle = require("@dicebear/micah");
  } else {
    console.error(`Unknown style: ${style}. Valid: toon-head, avataaars, bottts, micah, opeeps`);
    process.exit(1);
  }

  const avatar = createAvatar(dicebearStyle, { seed, size, ...extraOptions });
  svg = avatar.toString();
}

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
