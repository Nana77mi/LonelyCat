import { readFile } from "node:fs/promises";
import { test } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";

const indexPath = path.join(process.cwd(), "src", "index.ts");

test("qq connector exposes a health route in source", async () => {
  const content = await readFile(indexPath, "utf-8");
  assert.match(content, /createServer/);
  assert.ok(content.includes("/health"));
});
