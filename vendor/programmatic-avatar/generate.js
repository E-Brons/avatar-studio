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
  // The library always uses a 380×380 internal coordinate space regardless of `size`.
  // Generate at native 380×380 so the viewBox matches, then clip the avatar content
  // to the background circle so characters that extend beyond the circle are hidden.
  const { Avatar } = require("@opeepsfun/avatar-illustration-system");
  const OPEEPS_NATIVE = 380;
  const raw = Avatar({ size: OPEEPS_NATIVE, ...extraOptions });

  // Inject a <defs> block with a circle clip path matching the background circle,
  // then apply it to the avatar group so overflow is hidden.
  const clipDefs =
    '<defs><clipPath id="_opeeps_clip"><circle cx="190" cy="190" r="190"/></clipPath></defs>';
  const withDefs = raw.replace(/<svg([^>]*)>/, `<svg$1>${clipDefs}`);
  const withClip = withDefs.replace(
    '<g id="avatar">',
    '<g id="avatar" clip-path="url(#_opeeps_clip)">'
  );

  // Set width/height to the requested size while keeping the 380×380 viewBox so
  // the SVG renderer scales the content correctly.
  svg = withClip
    .replace(/width="\d+"/, `width="${size}"`)
    .replace(/height="\d+"/, `height="${size}"`);
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
